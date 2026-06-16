from backend import inbox


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


def test_survey_query(client):
    fake = client.fake
    fake.cards[1] = {"note_id": 1, "flag": 0, "model": "Basic", "deck": "Default", "fields": {"Front": {"value": "x", "order": 0}}}
    data = client.get("/api/survey?deck=Default&limit=10").get_json()
    assert data["total"] == 1
    assert data["cards"][0]["deck"] == "Default"
