import json

import pytest

from backend import inbox
from backend.ankiconnect import AnkiConnectError, AnkiUnavailable


def _raiser(exc):
    def f(*a, **k):
        raise exc
    return f


def _seed_inbox(cfg, **over):
    card = {"note_type": "Basic", "deck": "Default", "fields": {"Front": "Q", "Back": "A"}}
    card.update(over)
    return inbox.save_card(cfg["paths"]["inbox"], card)


def test_status_and_config(client):
    assert client.get("/api/status").get_json()["anki"] is True
    cfg = client.get("/api/config").get_json()
    assert "auth_token" not in cfg["beeminder"]
    assert cfg["default_deck"] == "Default"


def test_inbox_list_renders(client):
    _seed_inbox(client.cfg)
    data = client.get("/api/inbox").get_json()
    assert data["count"] == 1
    assert data["cards"][0]["rendered"]["question"] == "Q"


def test_approve_pushes_to_anki_and_undo(client):
    card = _seed_inbox(client.cfg)
    res = client.post(f"/api/inbox/{card['id']}/approve").get_json()
    assert res["ok"] is True
    nid = res["note_id"]
    assert nid in client.fake.notes
    assert inbox.count(client.cfg["paths"]["inbox"]) == 0
    # undo deletes the note and restores the inbox file
    undo = client.post("/api/undo").get_json()
    assert undo["undone"] == "approve"
    assert nid not in client.fake.notes
    assert inbox.count(client.cfg["paths"]["inbox"]) == 1


def test_cloze_per_card_approval_gates_send(client):
    # a 2-cloze note -> two cards; the note must NOT reach Anki until both are approved
    card = _seed_inbox(
        client.cfg, note_type="Cloze", fields={"Text": "{{c1::a}} and {{c2::b}}"}
    )
    cid = card["id"]

    r1 = client.post(f"/api/inbox/{cid}/approve", json={"ordinal": 1}).get_json()
    assert r1["committed"] is False and r1["approved_cards"] == [1]
    assert client.fake.notes == {}  # nothing sent yet
    assert inbox.count(client.cfg["paths"]["inbox"]) == 1
    assert inbox.get_card(client.cfg["paths"]["inbox"], cid)["approved_cards"] == [1]

    r2 = client.post(f"/api/inbox/{cid}/approve", json={"ordinal": 2}).get_json()
    assert r2["committed"] is True
    assert r2["note_id"] in client.fake.notes  # whole note now sent
    assert inbox.count(client.cfg["paths"]["inbox"]) == 0

    # undo the commit -> note removed, file back with one card still pending
    client.post("/api/undo")
    assert r2["note_id"] not in client.fake.notes
    assert inbox.get_card(client.cfg["paths"]["inbox"], cid)["approved_cards"] == [1]
    # undo the first approval -> back to nothing approved
    client.post("/api/undo")
    assert inbox.get_card(client.cfg["paths"]["inbox"], cid)["approved_cards"] == []


def test_template_note_per_card_approval_gates_send(client):
    # a 2-template note (forward + reverse) -> two cards, both must be approved
    card = _seed_inbox(
        client.cfg, note_type="Basic (and reversed card)", fields={"Front": "F", "Back": "B"}
    )
    cid = card["id"]
    listing = client.get("/api/inbox").get_json()
    t = [c for c in listing["cards"] if c["card"]["id"] == cid][0]
    assert [s["ordinal"] for s in t["rendered"]["cards"]] == [0, 1]

    r1 = client.post(f"/api/inbox/{cid}/approve", json={"ordinal": 0}).get_json()
    assert r1["committed"] is False and client.fake.notes == {}
    r2 = client.post(f"/api/inbox/{cid}/approve", json={"ordinal": 1}).get_json()
    assert r2["committed"] is True and r2["note_id"] in client.fake.notes


def test_optional_reverse_card_count_follows_field(client):
    # the reverse card only exists when its field is set
    two = _seed_inbox(
        client.cfg, note_type="Basic (optional reversed card)",
        fields={"Front": "F", "Back": "B", "Add Reverse": "y"},
    )
    one = _seed_inbox(
        client.cfg, note_type="Basic (optional reversed card)",
        fields={"Front": "F", "Back": "B", "Add Reverse": ""},
    )
    listing = client.get("/api/inbox").get_json()["cards"]
    by_id = {c["card"]["id"]: c for c in listing}
    assert [s["ordinal"] for s in by_id[two["id"]]["rendered"]["cards"]] == [0, 1]
    assert [s["ordinal"] for s in by_id[one["id"]]["rendered"]["cards"]] == [0]


def test_inbox_edit_clears_approvals(client):
    card = _seed_inbox(
        client.cfg, note_type="Cloze", fields={"Text": "{{c1::a}} {{c2::b}}"}, approved_cards=[1]
    )
    cid = card["id"]
    client.put(f"/api/inbox/{cid}", json={"fields": {"Text": "{{c1::x}} {{c2::y}}"}})
    assert inbox.get_card(client.cfg["paths"]["inbox"], cid)["approved_cards"] == []
    client.post("/api/undo")
    assert inbox.get_card(client.cfg["paths"]["inbox"], cid)["approved_cards"] == [1]


def test_delete_to_graveyard_and_undo(client):
    card = _seed_inbox(client.cfg)
    client.post(f"/api/inbox/{card['id']}/delete")
    assert inbox.count(client.cfg["paths"]["inbox"]) == 0
    assert client.get("/api/stats").get_json()["graveyard_count"] == 1
    client.post("/api/undo")
    assert inbox.count(client.cfg["paths"]["inbox"]) == 1


def test_send_back_appends_comment_and_undo(client):
    card = _seed_inbox(client.cfg)
    client.post(f"/api/inbox/{card['id']}/comment", json={"text": "too vague"})
    got = inbox.get_card(client.cfg["paths"]["inbox"], card["id"])
    assert got["comment_history"][-1]["text"] == "too vague"
    client.post("/api/undo")
    got = inbox.get_card(client.cfg["paths"]["inbox"], card["id"])
    assert got["comment_history"] == []


def test_send_back_requires_comment_when_configured(client):
    client.cfg["send_back_requires_comment"] = True
    card = _seed_inbox(client.cfg)
    res = client.post(f"/api/inbox/{card['id']}/comment", json={"text": "  "})
    assert res.status_code == 400


def test_inbox_edit_and_undo(client):
    card = _seed_inbox(client.cfg)
    client.put(f"/api/inbox/{card['id']}", json={"fields": {"Front": "Q2", "Back": "A2"}})
    assert inbox.get_card(client.cfg["paths"]["inbox"], card["id"])["fields"]["Front"] == "Q2"
    client.post("/api/undo")
    assert inbox.get_card(client.cfg["paths"]["inbox"], card["id"])["fields"]["Front"] == "Q"


def test_repair_flow_and_undo(client):
    fake = client.fake
    fake.notes[5001] = {"fields": {"Front": "old", "Back": "b"}, "model": "Basic", "deck": "Default"}
    fake.cards[9001] = {
        "note_id": 5001,
        "flag": 1,
        "model": "Basic",
        "deck": "Default",
        "fields": {"Front": {"value": "old", "order": 0}, "Back": {"value": "b", "order": 1}},
    }
    listing = client.get("/api/repair").get_json()
    assert listing["count"] == 1
    assert listing["cards"][0]["flag"] == 1

    res = client.put("/api/repair/5001", json={"fields": {"Front": "new", "Back": "b"}, "card_id": 9001})
    body = res.get_json()
    assert body["ok"] is True and body["flag_cleared"] is True
    assert fake.notes[5001]["fields"]["Front"] == "new"
    assert fake.cards[9001]["flag"] == 0

    client.post("/api/undo")
    assert fake.notes[5001]["fields"]["Front"] == "old"
    assert fake.cards[9001]["flag"] == 1


def test_inbox_exemplar_comment_attaches_to_card_and_undo(client):
    card = _seed_inbox(client.cfg)
    payload = {
        "verdict": "bad",
        "card_id": card["id"],
        "note_type": "Basic",
        "fields": {"Front": "Q"},
        "rendered": {"question": "Q", "answer": "A", "css": ""},
        "comment": "too vague",
    }
    client.post("/api/exemplar", json=payload)
    got = inbox.get_card(client.cfg["paths"]["inbox"], card["id"])
    assert got["comment_history"] == [
        {"date": got["comment_history"][0]["date"], "author": "me · exemplar bad", "text": "too vague"}
    ]
    assert client.get("/api/exemplars").get_json()["count"] == 1

    # undoing the exemplar removes the snapshot AND the attached comment
    client.post("/api/undo")
    assert client.get("/api/exemplars").get_json()["count"] == 0
    assert inbox.get_card(client.cfg["paths"]["inbox"], card["id"])["comment_history"] == []


def test_inbox_exemplar_without_comment_leaves_card_alone(client):
    card = _seed_inbox(client.cfg)
    payload = {
        "verdict": "good",
        "card_id": card["id"],
        "note_type": "Basic",
        "fields": {"Front": "Q"},
        "rendered": {"question": "Q", "answer": "A", "css": ""},
        "comment": "",
    }
    client.post("/api/exemplar", json=payload)
    assert inbox.get_card(client.cfg["paths"]["inbox"], card["id"])["comment_history"] == []
    client.post("/api/undo")
    assert client.get("/api/exemplars").get_json()["count"] == 0


def test_repair_deck_filter(client):
    fake = client.fake
    fake.notes[5001] = {"fields": {"Front": "a", "Back": "b"}, "model": "Basic", "deck": "Default"}
    fake.notes[5002] = {"fields": {"Front": "c", "Back": "d"}, "model": "Basic", "deck": "Math"}
    fake.cards[9001] = {
        "note_id": 5001,
        "flag": 1,
        "model": "Basic",
        "deck": "Default",
        "fields": {"Front": {"value": "a", "order": 0}, "Back": {"value": "b", "order": 1}},
    }
    fake.cards[9002] = {
        "note_id": 5002,
        "flag": 2,
        "model": "Basic",
        "deck": "Math",
        "fields": {"Front": {"value": "c", "order": 0}, "Back": {"value": "d", "order": 1}},
    }
    listing = client.get("/api/repair").get_json()
    assert listing["count"] == 2
    assert listing["decks"] == {"Default": 1, "Math": 1}

    filtered = client.get("/api/repair?deck=Math").get_json()
    assert filtered["count"] == 1
    assert filtered["cards"][0]["deck"] == "Math"
    # deck tallies stay global so the dropdown keeps every option
    assert filtered["decks"] == {"Default": 1, "Math": 1}


def test_exemplar_snapshot_and_undo(client):
    payload = {
        "verdict": "good",
        "note_type": "Basic",
        "fields": {"Front": "Q"},
        "rendered": {"question": "Q", "answer": "A", "css": ""},
    }
    client.post("/api/exemplar", json=payload)
    ex = client.get("/api/exemplars").get_json()
    assert ex["count"] == 1
    assert ex["exemplars"][0]["verdict"] == "good"
    client.post("/api/undo")
    assert client.get("/api/exemplars").get_json()["count"] == 0


def test_session_target(client):
    client.post("/api/session/start", json={"target": 2})
    _seed_inbox(client.cfg)
    c2 = _seed_inbox(client.cfg)
    s = client.get("/api/session").get_json()
    assert s["active"] and s["target"] == 2 and s["count"] == 0
    client.post(f"/api/inbox/{c2['id']}/approve")
    s = client.get("/api/session").get_json()
    assert s["count"] == 1 and s["target_hit"] is False


def test_models_endpoint_lists_types_and_writes_snapshot(client):
    import os
    data = client.get("/api/models").get_json()
    assert data["models"]["Basic"] == ["Front", "Back"]
    assert data["models"]["Cloze"] == ["Text", "Extra"]
    assert "Default" in data["decks"]
    data_dir = client.cfg["paths"]["data"]
    assert os.path.exists(os.path.join(data_dir, "note_types.json"))
    assert os.path.exists(os.path.join(data_dir, "note_types.md"))


def test_survey_query(client):
    fake = client.fake
    fake.cards[1] = {"note_id": 1, "flag": 0, "model": "Basic", "deck": "Default", "fields": {"Front": {"value": "x", "order": 0}}}
    data = client.get("/api/survey?deck=Default&limit=10").get_json()
    assert data["total"] == 1
    assert data["cards"][0]["deck"] == "Default"


# --- error / edge branches ------------------------------------------------

def test_status_reports_anki_down(client):
    client.fake.invoke = _raiser(AnkiConnectError("down"))
    assert client.get("/api/status").get_json() == {"anki": False, "version": None}


def test_approve_anki_unavailable_503_keeps_card(client):
    card = _seed_inbox(client.cfg)
    client.fake.add_note = _raiser(AnkiUnavailable("down"))
    res = client.post(f"/api/inbox/{card['id']}/approve")
    assert res.status_code == 503
    assert inbox.count(client.cfg["paths"]["inbox"]) == 1  # not lost


def test_approve_duplicate_409_keeps_card(client):
    card = _seed_inbox(client.cfg)
    client.fake.add_note = _raiser(AnkiConnectError("cannot create note because it is a duplicate"))
    res = client.post(f"/api/inbox/{card['id']}/approve")
    assert res.status_code == 409
    assert inbox.count(client.cfg["paths"]["inbox"]) == 1


def test_approve_unknown_ordinal_400(client):
    card = _seed_inbox(client.cfg, note_type="Cloze", fields={"Text": "{{c1::a}} {{c2::b}}"})
    res = client.post(f"/api/inbox/{card['id']}/approve", json={"ordinal": 99})
    assert res.status_code == 400
    assert client.fake.notes == {}  # nothing sent


def test_inbox_actions_missing_card_404(client):
    assert client.post("/api/inbox/nope/approve").status_code == 404
    assert client.post("/api/inbox/nope/delete").status_code == 404
    assert client.post("/api/inbox/nope/comment", json={"text": "x"}).status_code == 404
    assert client.put("/api/inbox/nope", json={"fields": {}}).status_code == 404


def test_undo_with_empty_stack(client):
    assert client.post("/api/undo").get_json()["undone"] is None


def test_exemplar_rejects_bad_verdict(client):
    assert client.post("/api/exemplar", json={"verdict": "meh"}).status_code == 400


def test_repair_anki_unavailable_503(client):
    client.fake.find_cards = _raiser(AnkiUnavailable("down"))
    res = client.get("/api/repair")
    assert res.status_code == 503


def test_repair_save_reports_flag_not_cleared(client):
    fake = client.fake
    fake.notes[5001] = {"fields": {"Front": "old", "Back": "b"}, "model": "Basic", "deck": "Default"}
    fake.cards[9001] = {"note_id": 5001, "flag": 1, "model": "Basic", "deck": "Default",
                        "fields": {"Front": {"value": "old", "order": 0}, "Back": {"value": "b", "order": 1}}}
    fake.set_flag = _raiser(AnkiConnectError("no setFlag support"))
    res = client.put("/api/repair/5001", json={"fields": {"Front": "new", "Back": "b"}, "card_id": 9001})
    body = res.get_json()
    assert body["ok"] is True and body["flag_cleared"] is False  # save succeeds, flag stays
    assert fake.notes[5001]["fields"]["Front"] == "new"


def test_survey_builds_query_from_filters(client):
    captured = {}

    def cap(q):
        captured["q"] = q
        return []

    client.fake.find_cards = cap
    client.get("/api/survey?deck=MyDeck&tag=foo&due=1&lapses=3&added=7")
    q = captured["q"]
    for part in ('deck:"MyDeck"', "tag:foo", "is:due", "prop:lapses>=3", "added:7"):
        assert part in q


def test_models_endpoint_anki_down(client):
    client.fake.model_names = _raiser(AnkiConnectError("down"))
    data = client.get("/api/models").get_json()
    assert data["error"] == "anki unavailable" and data["models"] == {}


def test_beeminder_push_endpoint_disabled(client):
    out = client.post("/api/beeminder/push").get_json()
    assert out == {"pushed": False, "reason": "disabled"}


def test_session_start_stop(client):
    client.post("/api/session/start", json={"target": 3})
    s = client.get("/api/session").get_json()
    assert s["active"] is True and s["target"] == 3
    stopped = client.post("/api/session/stop").get_json()
    assert stopped["session"]["active"] is False


def test_survey_anki_unavailable_503(client):
    client.fake.find_cards = _raiser(AnkiUnavailable("down"))
    assert client.get("/api/survey?deck=X").status_code == 503


def test_each_action_beeminder_push(client, monkeypatch):
    from backend import beeminder
    calls = []
    monkeypatch.setattr(beeminder, "push_today", lambda cfg, value: calls.append(value) or {"pushed": True})
    client.cfg["beeminder"].update(enabled=True, username="u", auth_token="t", goal="g", push_on="each_action")
    card = _seed_inbox(client.cfg)
    client.post(f"/api/inbox/{card['id']}/approve")
    assert calls == [1]


def test_session_stop_pushes_on_session_end(client, monkeypatch):
    from backend import beeminder
    calls = {}

    def fake_push(cfg, value):
        calls["value"] = value
        return {"pushed": True, "value": value}

    monkeypatch.setattr(beeminder, "push_today", fake_push)
    client.cfg["beeminder"].update(enabled=True, username="u", auth_token="t", goal="g", push_on="session_end")
    card = _seed_inbox(client.cfg)
    client.post(f"/api/inbox/{card['id']}/approve")
    out = client.post("/api/session/stop").get_json()
    assert out["beeminder"]["pushed"] is True and calls["value"] == 1


def test_graveyard_list_and_restore(client):
    card = _seed_inbox(client.cfg)
    client.post(f"/api/inbox/{card['id']}/delete")
    assert client.get("/api/graveyard").get_json()["count"] == 1
    res = client.post(f"/api/graveyard/{card['id']}/restore").get_json()
    assert res["ok"] is True and res["remaining"] == 0
    assert inbox.count(client.cfg["paths"]["inbox"]) == 1


def test_graveyard_restore_missing_404(client):
    assert client.post("/api/graveyard/nope/restore").status_code == 404


def test_settings_view_hides_token_value(client):
    client.cfg["beeminder"]["auth_token"] = "SECRET"
    s = client.get("/api/settings").get_json()
    assert "auth_token" not in s["beeminder"]
    assert s["beeminder"]["auth_token_set"] is True


def test_save_config_updates_live_and_persists(client):
    import json
    res = client.post("/api/config", json={"beeminder": {"enabled": True, "goal": "g", "auth_token": "TOK"}})
    assert res.get_json()["ok"] is True
    assert client.cfg["beeminder"]["enabled"] is True
    assert client.cfg["beeminder"]["auth_token"] == "TOK"
    on_disk = json.load(open(client.cfg["_config_path"]))
    assert on_disk["beeminder"]["goal"] == "g"


def test_save_config_blank_token_keeps_existing(client):
    client.cfg["beeminder"]["auth_token"] = "KEEP"
    client.post("/api/config", json={"beeminder": {"auth_token": "", "goal": "g2"}})
    assert client.cfg["beeminder"]["auth_token"] == "KEEP"
    assert client.cfg["beeminder"]["goal"] == "g2"


def test_save_config_invalid_push_on_rejected(client):
    assert client.post("/api/config", json={"beeminder": {"push_on": "hourly"}}).status_code == 400


def test_inbox_filters_by_deck(client):
    _seed_inbox(client.cfg, deck="Programming", fields={"Front": "p1", "Back": "x"})
    _seed_inbox(client.cfg, deck="Programming", fields={"Front": "p2", "Back": "x"})
    _seed_inbox(client.cfg, deck="History", fields={"Front": "h1", "Back": "x"})
    allc = client.get("/api/inbox").get_json()
    assert allc["count"] == 3 and allc["total"] == 3
    assert allc["decks"] == {"Programming": 2, "History": 1}
    prog = client.get("/api/inbox?deck=Programming").get_json()
    assert prog["count"] == 2 and prog["total"] == 3  # count filtered, total is whole queue
    assert all(c["card"]["deck"] == "Programming" for c in prog["cards"])


def test_exemplar_list_has_idx_and_delete(client):
    client.post("/api/exemplar", json={"verdict": "good", "note_type": "Basic", "fields": {"Front": "Q"}, "rendered": {}})
    client.post("/api/exemplar", json={"verdict": "bad", "note_type": "Basic", "fields": {"Front": "R"}, "rendered": {}})
    lst = client.get("/api/exemplars").get_json()
    assert lst["count"] == 2
    assert sorted(e["_idx"] for e in lst["exemplars"]) == [0, 1]
    assert client.post("/api/exemplars/0/delete").get_json()["ok"] is True
    assert client.get("/api/exemplars").get_json()["count"] == 1


def test_exemplar_delete_out_of_range_404(client):
    assert client.post("/api/exemplars/9/delete").status_code == 404


def test_inbox_edit_deck_tags_and_undo(client):
    card = inbox.save_card(client.cfg["paths"]["inbox"], {
        "note_type": "Cloze", "deck": "Default",
        "fields": {"Text": "{{c1::x}} {{c2::y}}"}, "tags": ["old"],
    })
    cid = card["id"]
    client.post(f"/api/inbox/{cid}/approve", json={"ordinal": 1})
    # deck/tags-only edit: content unchanged, so the partial approval survives
    res = client.put(f"/api/inbox/{cid}", json={"fields": card["fields"], "deck": "Other", "tags": ["nyc", "claude"]})
    got = res.get_json()["card"]
    assert got["deck"] == "Other" and got["tags"] == ["nyc", "claude"]
    assert got["approved_cards"] == [1]
    # a field edit still resets approvals
    client.put(f"/api/inbox/{cid}", json={"fields": {"Text": "{{c1::z}} {{c2::y}}"}})
    assert inbox.get_card(client.cfg["paths"]["inbox"], cid)["approved_cards"] == []
    # undo the field edit, then the deck/tags edit
    client.post("/api/undo")
    client.post("/api/undo")
    back = inbox.get_card(client.cfg["paths"]["inbox"], cid)
    assert back["deck"] == "Default" and back["tags"] == ["old"]
    assert back["approved_cards"] == [1]


def test_history_lists_actions_and_undoes_arbitrary_one(client):
    a = inbox.save_card(client.cfg["paths"]["inbox"], {"note_type": "Basic", "deck": "Default", "fields": {"Front": "A", "Back": "1"}})
    b = inbox.save_card(client.cfg["paths"]["inbox"], {"note_type": "Basic", "deck": "Default", "fields": {"Front": "B", "Back": "2"}})
    client.post(f"/api/inbox/{a['id']}/approve")       # -> Anki
    client.post(f"/api/inbox/{b['id']}/delete")        # -> graveyard
    hist = client.get("/api/history").get_json()
    assert hist["count"] == 2
    assert [r["kind"] for r in hist["actions"]] == ["approve", "delete"]
    # undo the OLDER action (the approve) while the delete stays put
    res = client.post("/api/history/0/undo", json={"ts": hist["actions"][0]["ts"]})
    assert res.get_json()["undone"] == "approve"
    assert client.fake.notes == {}                     # note pulled back out of Anki
    assert inbox.get_card(client.cfg["paths"]["inbox"], a["id"]) is not None
    # the delete action, and only it, remains -- with its stat
    hist = client.get("/api/history").get_json()
    assert [r["kind"] for r in hist["actions"]] == ["delete"]
    totals = client.get("/api/stats").get_json()["totals"]
    assert totals.get("approve", 0) == 0 and totals["delete"] == 1
    # plain undo still works on what's left
    assert client.post("/api/undo").get_json()["undone"] == "delete"


def test_history_undo_stale_ts_409(client):
    card = inbox.save_card(client.cfg["paths"]["inbox"], {"note_type": "Basic", "deck": "Default", "fields": {"Front": "Q", "Back": "A"}})
    client.post(f"/api/inbox/{card['id']}/delete")
    assert client.post("/api/history/0/undo", json={"ts": "2000-01-01T00:00:00+00:00"}).status_code == 409
    assert client.post("/api/history/5/undo", json={}).status_code == 404


def test_exemplar_delete_lands_in_trash(client):
    client.post("/api/exemplar", json={"verdict": "bad", "note_type": "Basic", "fields": {"Front": "Q"}, "rendered": {}})
    client.post("/api/exemplars/0/delete")
    with open(client.cfg["paths"]["exemplars"] + ".trash", encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    assert len(rows) == 1
    assert rows[0]["exemplar"]["verdict"] == "bad"
    assert rows[0]["deleted"]
