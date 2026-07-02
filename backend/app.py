"""Flask app: the API surface and static file serving.

Surfaces (see README): inbox, repair queue, survey grid, stats. AnkiConnect is
the only write path to the live deck; provisional cards live on disk until
approved; nothing is hard-deleted.
"""
import json
import os
from datetime import datetime, timezone

from flask import Flask, jsonify, request, send_from_directory

from . import (
    actions,
    beeminder,
    config as config_mod,
    exemplars,
    graveyard,
    inbox,
    models,
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

    @app.get("/api/settings")
    def get_settings():
        return jsonify(config_mod.settings_view(cfg))

    @app.post("/api/config")
    def set_config():
        updates = request.get_json(silent=True) or {}
        bm = updates.get("beeminder")
        if isinstance(bm, dict):
            if not bm.get("auth_token"):
                bm.pop("auth_token", None)  # blank field -> keep the existing token
            if bm.get("push_on") not in (None, "session_end", "each_action"):
                return jsonify({"error": "invalid push_on"}), 400
        config_mod.save_user_config(cfg, updates)
        return jsonify({"ok": True, "settings": config_mod.settings_view(cfg)})

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
        decks = {}
        for c in cards:
            d = c.get("deck", "")
            decks[d] = decks.get(d, 0) + 1
        wanted = request.args.get("deck")
        if wanted:
            cards = [c for c in cards if c.get("deck") == wanted]
        out = [{"card": c, "rendered": renderer.render_provisional(c)} for c in cards]
        return jsonify({"cards": out, "count": len(out), "total": sum(decks.values()), "decks": decks})

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
        if ordinal not in ordinals:
            return jsonify({"error": "unknown card ordinal", "ordinals": ordinals}), 400
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
        body = request.json or {}
        card = inbox.get_card(paths["inbox"], card_id)
        if card is None:
            return jsonify({"error": "not found"}), 404
        old = {
            "old_fields": card.get("fields", {}),
            "old_approved": list(card.get("approved_cards", [])),
            "old_deck": card.get("deck"),
            "old_tags": list(card.get("tags", [])),
        }
        updates = {}
        fields = body.get("fields")
        if fields is not None:
            updates["fields"] = fields
            if fields != old["old_fields"]:
                # content changed -> prior per-card approvals are stale, re-review
                updates["approved_cards"] = []
        if isinstance(body.get("deck"), str) and body["deck"]:
            updates["deck"] = body["deck"]
        if isinstance(body.get("tags"), list):
            updates["tags"] = [str(t) for t in body["tags"]]
        card = inbox.update_card(paths["inbox"], card_id, updates)
        actions.push(paths["actions"], "edit_inbox", {"card_id": card_id, **old}, "edit")
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
        cards = [renderer.shape_live(i) for i in infos]
        decks = {}
        for c in cards:
            d = c.get("deck", "")
            decks[d] = decks.get(d, 0) + 1
        wanted = request.args.get("deck")
        if wanted:
            cards = [c for c in cards if c.get("deck") == wanted]
        cards.sort(key=lambda c: (c["flag"] != 1, c["flag"]))  # red first
        return jsonify({"cards": cards, "count": len(cards), "decks": decks})

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
            parts.append('deck:"%s"' % request.args["deck"].replace('"', '\\"'))
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
        cards = [renderer.shape_live(i) for i in infos]
        return jsonify(
            {"cards": cards, "total": len(card_ids), "offset": offset, "limit": limit}
        )

    @app.get("/api/decks")
    def decks():
        try:
            return jsonify({"decks": sorted(anki.deck_names())})
        except AnkiConnectError:
            return jsonify({"decks": []})

    @app.get("/api/models")
    def models_list():
        """Every note type with its field names, plus decks. Also (re)writes
        data/note_types.{json,md} so a generator has the schema on disk."""
        snap = models.write_snapshot(anki, paths["data"])
        if snap is None:
            return jsonify({"error": "anki unavailable", "models": {}, "decks": []})
        return jsonify(snap)

    # --- graveyard -------------------------------------------------------
    @app.get("/api/graveyard")
    def graveyard_list():
        rows = graveyard.list_buried(paths["graveyard"])
        for e in rows:
            e["rendered"] = renderer.render_provisional(e.get("card", {}))
        return jsonify({"cards": rows, "count": len(rows)})

    @app.post("/api/graveyard/<card_id>/restore")
    def graveyard_restore(card_id):
        card = graveyard.exhume(paths["graveyard"], card_id)
        if card is None:
            return jsonify({"error": "not found"}), 404
        inbox.save_card(paths["inbox"], card)
        return jsonify({"ok": True, "remaining": len(graveyard.list_buried(paths["graveyard"]))})

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
        # one judgment, one record: the "why" of an inbox exemplar is also a
        # comment on the card itself, so the generator sees it on send-back
        card_id = body.get("card_id")
        comment = (body.get("comment") or "").strip()
        commented = False
        if card_id and comment:
            commented = (
                inbox.add_comment(
                    paths["inbox"], card_id, comment, author="me · exemplar %s" % verdict
                )
                is not None
            )
        stats.record(paths["stats"], "exemplar_%s" % verdict)
        actions.push(
            paths["actions"],
            "exemplar",
            {"card_id": card_id, "commented": commented},
            "exemplar %s" % verdict,
        )
        maybe_push_beeminder()
        return jsonify({"ok": True})

    @app.get("/api/exemplars")
    def exemplar_list():
        rows = exemplars.list_all(paths["exemplars"])
        for i, row in enumerate(rows):
            row["_idx"] = i  # file position, so the UI can delete a specific one
            r = row.get("rendered") or {}
            if r:  # re-resolve media so the frozen snapshot can render as a card
                r["question"] = renderer.inline_media(r.get("question", ""))
                r["answer"] = renderer.inline_media(r.get("answer", ""))
        rows.reverse()  # newest first
        return jsonify({"exemplars": rows, "count": len(rows)})

    @app.post("/api/exemplars/<int:idx>/delete")
    def exemplar_delete(idx):
        removed = exemplars.delete_at(paths["exemplars"], idx)
        if removed is None:
            return jsonify({"error": "not found"}), 404
        return jsonify({"ok": True})

    @app.post("/api/exemplars/<int:idx>/comment")
    def exemplar_comment(idx):
        text = ((request.json or {}).get("text") or "").strip()
        rows = exemplars.list_all(paths["exemplars"])
        if idx < 0 or idx >= len(rows):
            return jsonify({"error": "not found"}), 404
        old = exemplars.set_comment(paths["exemplars"], idx, text)
        if old == text:
            return jsonify({"ok": True})  # no change, nothing to undo
        actions.push(
            paths["actions"],
            "edit_exemplar",
            {"date": rows[idx].get("date"), "old": old, "new": text},
            "exemplar comment",
        )
        return jsonify({"ok": True})

    # --- undo / history ---------------------------------------------------
    # Kinds that recorded a stat when they happened. The undo stack and
    # events.jsonl are order-aligned: the k-th stat-recording action in the
    # stack corresponds to the k-th event row, so undoing any action (not
    # just the top) removes its own stat.
    STAT_KINDS = {"approve", "delete", "send_back", "repair", "exemplar"}

    def _delete_exemplar_near(ts):
        """Exemplar action payloads are empty, so find the snapshot written at
        (about) the action's timestamp. Does nothing rather than delete the
        wrong row (e.g. if it was already deleted from the exemplars surface)."""
        target = datetime.fromisoformat(ts)
        best, best_dt = None, None
        for i, row in enumerate(exemplars.list_all(paths["exemplars"])):
            try:
                dt = abs((datetime.fromisoformat(row.get("date", "")) - target).total_seconds())
            except ValueError:
                continue
            if best_dt is None or dt < best_dt:
                best, best_dt = i, dt
        if best is not None and best_dt <= 10:
            exemplars.delete_at(paths["exemplars"], best)

    def _reverse(record):
        """Reverse a record's effects (stats/session bookkeeping is separate).
        May raise AnkiUnavailable, in which case nothing has been removed."""
        kind = record["kind"]
        payload = record["payload"]
        if kind == "approve":
            anki.delete_notes([payload["note_id"]])
            inbox.save_card(paths["inbox"], payload["card"])
        elif kind == "delete":
            card = graveyard.exhume(paths["graveyard"], payload["card_id"])
            if card:
                inbox.save_card(paths["inbox"], card)
        elif kind == "send_back":
            inbox.pop_comment(paths["inbox"], payload["card_id"])
        elif kind == "approve_card":
            c = inbox.get_card(paths["inbox"], payload["card_id"])
            if c is not None:
                inbox.set_approved(
                    paths["inbox"],
                    payload["card_id"],
                    [o for o in c.get("approved_cards", []) if o != payload["ordinal"]],
                )
        elif kind == "edit_inbox":
            restore = {
                "fields": payload["old_fields"],
                "approved_cards": payload.get("old_approved", []),
            }
            if payload.get("old_deck"):
                restore["deck"] = payload["old_deck"]
            if payload.get("old_tags") is not None:
                restore["tags"] = payload["old_tags"]
            inbox.update_card(paths["inbox"], payload["card_id"], restore)
        elif kind == "repair":
            anki.update_note_fields(payload["note_id"], payload["old_fields"])
            if payload.get("card_id"):
                try:
                    anki.set_flag(payload["card_id"], payload["old_flag"])
                except AnkiConnectError:
                    pass
        elif kind == "exemplar":
            _delete_exemplar_near(record["ts"])
            if payload.get("commented"):
                inbox.pop_comment(paths["inbox"], payload["card_id"])
        elif kind == "edit_exemplar":
            exemplars.set_comment_by_date(paths["exemplars"], payload["date"], payload["old"])

    def _undo_at(index):
        stack = actions.list_all(paths["actions"])
        record = stack[index]
        _reverse(record)
        if record["kind"] in STAT_KINDS:
            stat_idx = sum(1 for r in stack[:index] if r["kind"] in STAT_KINDS)
            stats.pop_at(paths["stats"], stat_idx)
            if record["kind"] != "exemplar":
                _bump_session(paths["session"], -1)
        actions.remove_at(paths["actions"], index)
        return record

    @app.post("/api/undo")
    def undo():
        depth = actions.depth(paths["actions"])
        if not depth:
            return jsonify({"undone": None})
        try:
            record = _undo_at(depth - 1)
        except AnkiUnavailable as exc:
            return jsonify({"error": "anki unavailable", "detail": str(exc)}), 503
        return jsonify({"undone": record["label"], "remaining_undo": actions.depth(paths["actions"])})

    @app.get("/api/history")
    def history():
        stack = actions.list_all(paths["actions"])
        return jsonify({"actions": stack, "count": len(stack)})

    @app.post("/api/history/<int:index>/undo")
    def history_undo(index):
        stack = actions.list_all(paths["actions"])
        if index < 0 or index >= len(stack):
            return jsonify({"error": "not found"}), 404
        ts = (request.json or {}).get("ts")
        if ts and stack[index]["ts"] != ts:
            return jsonify({"error": "history changed, reloaded"}), 409
        try:
            record = _undo_at(index)
        except AnkiUnavailable as exc:
            return jsonify({"error": "anki unavailable", "detail": str(exc)}), 503
        return jsonify({"undone": record["label"]})

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
