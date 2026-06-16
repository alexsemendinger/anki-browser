"""Flask app: the API surface and static file serving.

Surfaces (see README): inbox, repair queue, survey grid, stats. AnkiConnect is
the only write path to the live deck; provisional cards live on disk until
approved; nothing is hard-deleted.
"""
import json
import os

from flask import Flask, jsonify, request, send_from_directory

from . import (
    actions,
    beeminder,
    config as config_mod,
    exemplars,
    graveyard,
    inbox,
    stats,
)
from .ankiconnect import AnkiConnect, AnkiConnectError, AnkiUnavailable
from .cards import CardRenderer

FRONTEND = os.path.join(config_mod.ROOT, "frontend")


# --- session (one sitting; optional "tell me when done" target) ----------
def _load_session(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {"active": False, "target": None, "count": 0, "started": None}


def _save_session(path, sess):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(sess, fh, indent=2)
    return sess


def _session_view(path):
    sess = _load_session(path)
    target = sess.get("target")
    sess["target_hit"] = bool(
        sess.get("active") and target and sess.get("count", 0) >= target
    )
    return sess


def _bump_session(path, delta):
    sess = _load_session(path)
    sess["count"] = max(0, sess.get("count", 0) + delta)
    return _save_session(path, sess)


def create_app(cfg=None):
    cfg = cfg or config_mod.load_config()
    paths = cfg["paths"]
    anki = AnkiConnect(cfg["ankiconnect_url"], cfg["ankiconnect_version"])
    renderer = CardRenderer(anki, cfg)

    app = Flask(__name__, static_folder=FRONTEND, static_url_path="")

    def maybe_push_beeminder():
        """Best-effort. A Beeminder hiccup must never block a judgment."""
        bm = cfg["beeminder"]
        if not bm["enabled"] or bm["push_on"] != "each_action":
            return
        try:
            value = stats.count_today(paths["stats"], beeminder.counted_types(cfg))
            beeminder.push_today(cfg, value)
        except Exception:
            pass

    # --- shell -----------------------------------------------------------
    @app.route("/")
    def index():
        return send_from_directory(FRONTEND, "index.html")

    @app.get("/api/config")
    def get_config():
        return jsonify(config_mod.public_config(cfg))

    @app.get("/api/status")
    def status():
        try:
            version = anki.invoke("version")
            return jsonify({"anki": True, "version": version})
        except AnkiConnectError:
            return jsonify({"anki": False, "version": None})

    # --- inbox -----------------------------------------------------------
    @app.get("/api/inbox")
    def inbox_list():
        cards = inbox.list_cards(paths["inbox"])
        out = []
        for card in cards:
            out.append({"card": card, "rendered": renderer.render_provisional(card)})
        return jsonify({"cards": out, "count": len(out)})

    @app.post("/api/inbox/<card_id>/approve")
    def inbox_approve(card_id):
        """Approve one of a note's cards. The note is only sent to Anki once
        EVERY card it generates has been approved (addNote is atomic -- you
        can't add c1's card without c2's). A partial approval is just persisted
        on the inbox file; the final one commits the whole note."""
        card = inbox.get_card(paths["inbox"], card_id)
        if card is None:
            return jsonify({"error": "not found"}), 404
        # the renderer is the authority on which cards this note generates
        ordinals = [c["ordinal"] for c in renderer.render_provisional(card)["cards"]]
        approved = list(card.get("approved_cards", []))
        body = request.get_json(silent=True) or {}
        ordinal = body.get("ordinal")
        if ordinal is None:
            pending = [o for o in ordinals if o not in approved]
            ordinal = pending[0] if pending else ordinals[-1]
        ordinal = int(ordinal)
        new_approved = sorted(set(approved) | {ordinal})

        if set(new_approved) < set(ordinals):
            # not all cards approved yet -- persist and stay in the inbox
            inbox.set_approved(paths["inbox"], card_id, new_approved)
            actions.push(
                paths["actions"],
                "approve_card",
                {"card_id": card_id, "ordinal": ordinal},
                "approve card",
            )
            return jsonify(
                {"ok": True, "committed": False, "ordinals": ordinals, "approved_cards": new_approved}
            )

        # every card approved -> send the whole note to Anki
        try:
            note_id = anki.add_note(
                card.get("deck") or cfg["default_deck"],
                card.get("note_type", "Basic"),
                card.get("fields", {}),
                card.get("tags", []),
            )
        except AnkiUnavailable as exc:
            return jsonify({"error": "anki unavailable", "detail": str(exc)}), 503
        except AnkiConnectError as exc:
            return jsonify({"error": "add failed", "detail": str(exc)}), 409
        inbox.remove_card(paths["inbox"], card_id)
        stats.record(paths["stats"], "approve")
        # `card` still carries the pre-commit approvals, so undo restores the
        # inbox file to "one card left" rather than a fully-fresh note.
        actions.push(
            paths["actions"],
            "approve",
            {"card": card, "note_id": note_id},
            "approve",
        )
        _bump_session(paths["session"], 1)
        maybe_push_beeminder()
        return jsonify(
            {"ok": True, "committed": True, "note_id": note_id, "remaining": inbox.count(paths["inbox"])}
        )

    @app.post("/api/inbox/<card_id>/delete")
    def inbox_delete(card_id):
        card = inbox.remove_card(paths["inbox"], card_id)
        if card is None:
            return jsonify({"error": "not found"}), 404
        graveyard.bury(paths["graveyard"], card, origin="inbox")
        stats.record(paths["stats"], "delete")
        actions.push(paths["actions"], "delete", {"card_id": card_id}, "delete")
        _bump_session(paths["session"], 1)
        maybe_push_beeminder()
        return jsonify({"ok": True, "remaining": inbox.count(paths["inbox"])})

    @app.post("/api/inbox/<card_id>/comment")
    def inbox_comment(card_id):
        text = (request.json or {}).get("text", "").strip()
        if cfg["send_back_requires_comment"] and not text:
            return jsonify({"error": "comment required"}), 400
        card = inbox.add_comment(paths["inbox"], card_id, text)
        if card is None:
            return jsonify({"error": "not found"}), 404
        stats.record(paths["stats"], "send_back")
        actions.push(paths["actions"], "send_back", {"card_id": card_id}, "send back")
        _bump_session(paths["session"], 1)
        maybe_push_beeminder()
        return jsonify({"ok": True, "card": card})

    @app.put("/api/inbox/<card_id>")
    def inbox_edit(card_id):
        fields = (request.json or {}).get("fields", {})
        card = inbox.get_card(paths["inbox"], card_id)
        if card is None:
            return jsonify({"error": "not found"}), 404
        old_fields = card.get("fields", {})
        old_approved = list(card.get("approved_cards", []))
        inbox.update_fields(paths["inbox"], card_id, fields)
        # content changed -> prior per-card approvals are stale, re-review
        card = inbox.set_approved(paths["inbox"], card_id, [])
        actions.push(
            paths["actions"],
            "edit_inbox",
            {"card_id": card_id, "old_fields": old_fields, "old_approved": old_approved},
            "edit",
        )
        return jsonify({"ok": True, "card": card, "rendered": renderer.render_provisional(card)})

    # --- repair queue ----------------------------------------------------
    @app.get("/api/repair")
    def repair_list():
        flags = cfg["repair_flags"]
        query = " OR ".join("flag:%d" % f for f in flags)
        try:
            card_ids = anki.find_cards("(%s)" % query)
            infos = anki.cards_info(card_ids)
        except AnkiUnavailable as exc:
            return jsonify({"error": "anki unavailable", "detail": str(exc)}), 503
        cards = [CardRenderer.from_card_info(i) for i in infos]
        cards.sort(key=lambda c: (c["flag"] != 1, c["flag"]))  # red first
        return jsonify({"cards": cards, "count": len(cards)})

    @app.put("/api/repair/<int:note_id>")
    def repair_save(note_id):
        body = request.json or {}
        fields = body.get("fields", {})
        card_id = body.get("card_id")
        try:
            old_flag = 0
            old_fields = {}
            if card_id:
                info = anki.cards_info([int(card_id)])
                if info:
                    shaped = CardRenderer.from_card_info(info[0])
                    old_fields = shaped["fields"]
                    old_flag = shaped["flag"]
            anki.update_note_fields(note_id, fields)
            flag_cleared = True
            if card_id:
                try:
                    anki.set_flag(card_id, 0)
                except AnkiConnectError:
                    flag_cleared = False
        except AnkiUnavailable as exc:
            return jsonify({"error": "anki unavailable", "detail": str(exc)}), 503
        except AnkiConnectError as exc:
            return jsonify({"error": "save failed", "detail": str(exc)}), 409
        stats.record(paths["stats"], "repair")
        actions.push(
            paths["actions"],
            "repair",
            {
                "note_id": note_id,
                "card_id": card_id,
                "old_fields": old_fields,
                "old_flag": old_flag,
            },
            "repair",
        )
        _bump_session(paths["session"], 1)
        maybe_push_beeminder()
        return jsonify({"ok": True, "flag_cleared": flag_cleared})

    # --- survey grid -----------------------------------------------------
    @app.get("/api/survey")
    def survey():
        parts = []
        if request.args.get("deck"):
            parts.append('deck:"%s"' % request.args["deck"])
        if request.args.get("tag"):
            parts.append("tag:%s" % request.args["tag"])
        if request.args.get("added"):
            parts.append("added:%s" % request.args["added"])
        if request.args.get("due"):
            parts.append("is:due")
        if request.args.get("lapses"):
            parts.append("prop:lapses>=%s" % request.args["lapses"])
        query = " ".join(parts) if parts else "deck:*"
        offset = int(request.args.get("offset", 0))
        limit = int(request.args.get("limit", 20))
        try:
            card_ids = anki.find_cards(query)
            page = card_ids[offset : offset + limit]
            infos = anki.cards_info(page)
        except AnkiUnavailable as exc:
            return jsonify({"error": "anki unavailable", "detail": str(exc)}), 503
        cards = [CardRenderer.from_card_info(i) for i in infos]
        return jsonify(
            {"cards": cards, "total": len(card_ids), "offset": offset, "limit": limit}
        )

    @app.get("/api/decks")
    def decks():
        try:
            return jsonify({"decks": sorted(anki.deck_names())})
        except AnkiConnectError:
            return jsonify({"decks": []})

    # --- exemplar archive ------------------------------------------------
    @app.post("/api/exemplar")
    def exemplar_add():
        body = request.json or {}
        verdict = body.get("verdict")
        if verdict not in ("good", "bad"):
            return jsonify({"error": "verdict must be good or bad"}), 400
        exemplars.add(
            paths["exemplars"],
            verdict=verdict,
            fields=body.get("fields", {}),
            rendered=body.get("rendered", {}),
            note_type=body.get("note_type", ""),
            note_id=body.get("note_id"),
            comment=body.get("comment", ""),
            deck=body.get("deck"),
        )
        stats.record(paths["stats"], "exemplar_%s" % verdict)
        actions.push(paths["actions"], "exemplar", {}, "exemplar %s" % verdict)
        maybe_push_beeminder()
        return jsonify({"ok": True})

    @app.get("/api/exemplars")
    def exemplar_list():
        rows = exemplars.list_all(paths["exemplars"])
        rows.reverse()
        return jsonify({"exemplars": rows, "count": len(rows)})

    # --- undo ------------------------------------------------------------
    @app.post("/api/undo")
    def undo():
        record = actions.peek(paths["actions"])
        if record is None:
            return jsonify({"undone": None})
        kind = record["kind"]
        payload = record["payload"]
        try:
            if kind == "approve":
                anki.delete_notes([payload["note_id"]])
                inbox.save_card(paths["inbox"], payload["card"])
                stats.pop_last(paths["stats"])
                _bump_session(paths["session"], -1)
            elif kind == "delete":
                card = graveyard.exhume(paths["graveyard"], payload["card_id"])
                if card:
                    inbox.save_card(paths["inbox"], card)
                stats.pop_last(paths["stats"])
                _bump_session(paths["session"], -1)
            elif kind == "send_back":
                inbox.pop_comment(paths["inbox"], payload["card_id"])
                stats.pop_last(paths["stats"])
                _bump_session(paths["session"], -1)
            elif kind == "approve_card":
                c = inbox.get_card(paths["inbox"], payload["card_id"])
                if c is not None:
                    inbox.set_approved(
                        paths["inbox"],
                        payload["card_id"],
                        [o for o in c.get("approved_cards", []) if o != payload["ordinal"]],
                    )
            elif kind == "edit_inbox":
                inbox.update_fields(paths["inbox"], payload["card_id"], payload["old_fields"])
                inbox.set_approved(paths["inbox"], payload["card_id"], payload.get("old_approved", []))
            elif kind == "repair":
                anki.update_note_fields(payload["note_id"], payload["old_fields"])
                if payload.get("card_id"):
                    try:
                        anki.set_flag(payload["card_id"], payload["old_flag"])
                    except AnkiConnectError:
                        pass
                stats.pop_last(paths["stats"])
                _bump_session(paths["session"], -1)
            elif kind == "exemplar":
                exemplars.pop_last(paths["exemplars"])
                stats.pop_last(paths["stats"])
        except AnkiUnavailable as exc:
            return jsonify({"error": "anki unavailable", "detail": str(exc)}), 503
        actions.pop(paths["actions"])
        return jsonify({"undone": record["label"], "remaining_undo": actions.depth(paths["actions"])})

    # --- stats / session / beeminder ------------------------------------
    @app.get("/api/stats")
    def get_stats():
        summary = stats.summary(paths["stats"])
        summary["inbox_count"] = inbox.count(paths["inbox"])
        summary["graveyard_count"] = len(graveyard.list_buried(paths["graveyard"]))
        summary["undo_depth"] = actions.depth(paths["actions"])
        return jsonify(summary)

    @app.get("/api/session")
    def session_get():
        return jsonify(_session_view(paths["session"]))

    @app.post("/api/session/start")
    def session_start():
        body = request.json or {}
        target = body.get("target")
        from datetime import datetime, timezone

        _save_session(
            paths["session"],
            {
                "active": True,
                "target": int(target) if target else None,
                "count": 0,
                "started": datetime.now(timezone.utc).isoformat(),
            },
        )
        return jsonify(_session_view(paths["session"]))

    @app.post("/api/session/stop")
    def session_stop():
        sess = _load_session(paths["session"])
        sess["active"] = False
        _save_session(paths["session"], sess)
        result = {"pushed": False}
        bm = cfg["beeminder"]
        if bm["enabled"] and bm["push_on"] == "session_end":
            try:
                value = stats.count_today(paths["stats"], beeminder.counted_types(cfg))
                result = beeminder.push_today(cfg, value)
            except Exception as exc:  # noqa: BLE001
                result = {"pushed": False, "error": str(exc)}
        return jsonify({"session": _session_view(paths["session"]), "beeminder": result})

    @app.post("/api/beeminder/push")
    def beeminder_push():
        try:
            value = stats.count_today(paths["stats"], beeminder.counted_types(cfg))
            return jsonify(beeminder.push_today(cfg, value))
        except Exception as exc:  # noqa: BLE001
            return jsonify({"pushed": False, "error": str(exc)}), 502

    return app
