"""The thin AnkiConnect HTTP client: payload shape and error mapping, with
``requests`` mocked so no real Anki is needed."""
import pytest
import requests

from backend.ankiconnect import AnkiConnect, AnkiConnectError, AnkiUnavailable


class FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _client():
    return AnkiConnect("http://x:8765", version=6, timeout=3)


def test_invoke_success_returns_result(monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResp({"result": 42, "error": None})

    monkeypatch.setattr(requests, "post", fake_post)
    assert _client().invoke("version", foo="bar") == 42
    assert captured["url"] == "http://x:8765"
    assert captured["json"] == {"action": "version", "version": 6, "params": {"foo": "bar"}}
    assert captured["timeout"] == 3


def test_invoke_error_field_raises_ankiconnecterror(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp({"result": None, "error": "boom"}))
    with pytest.raises(AnkiConnectError) as ei:
        _client().invoke("addNote")
    assert "boom" in str(ei.value)


def test_invoke_connection_error_raises_unavailable(monkeypatch):
    def boom(*a, **k):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(requests, "post", boom)
    with pytest.raises(AnkiUnavailable):
        _client().invoke("version")


def test_unavailable_is_an_ankiconnecterror():
    # callers catch AnkiConnectError broadly; AnkiUnavailable must be caught too
    assert issubclass(AnkiUnavailable, AnkiConnectError)


def test_reachable_true_and_false(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp({"result": 6, "error": None}))
    assert _client().reachable() is True

    def boom(*a, **k):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(requests, "post", boom)
    assert _client().reachable() is False


def test_add_note_payload_shape(monkeypatch):
    captured = {}
    monkeypatch.setattr(requests, "post",
                        lambda url, json=None, timeout=None: captured.update(json=json) or FakeResp({"result": 99, "error": None}))
    nid = _client().add_note("DeckA", "Basic", {"Front": "F", "Back": "B"}, tags=["x"], allow_duplicate=True)
    assert nid == 99
    note = captured["json"]["params"]["note"]
    assert note["deckName"] == "DeckA"
    assert note["modelName"] == "Basic"
    assert note["fields"] == {"Front": "F", "Back": "B"}
    assert note["tags"] == ["x"]
    assert note["options"]["allowDuplicate"] is True


def test_set_flag_uses_setspecificvalueofcard(monkeypatch):
    captured = {}
    monkeypatch.setattr(requests, "post",
                        lambda url, json=None, timeout=None: captured.update(json=json) or FakeResp({"result": [True], "error": None}))
    _client().set_flag(123, 0)
    p = captured["json"]
    assert p["action"] == "setSpecificValueOfCard"
    assert p["params"]["card"] == 123
    assert p["params"]["keys"] == ["flags"]
    assert p["params"]["newValues"] == [0]
    assert p["params"]["warning_check"] is True


def test_notes_and_cards_info_short_circuit_on_empty(monkeypatch):
    # must not even call the network for an empty id list
    def explode(*a, **k):
        raise AssertionError("should not hit the network")

    monkeypatch.setattr(requests, "post", explode)
    c = _client()
    assert c.notes_info([]) == []
    assert c.cards_info([]) == []


def test_method_wrappers_send_right_actions(monkeypatch):
    seen = []

    def fake_post(url, json=None, timeout=None):
        seen.append((json["action"], json["params"]))
        return FakeResp({"result": [], "error": None})

    monkeypatch.setattr(requests, "post", fake_post)
    c = _client()
    c.deck_names(); c.model_names()
    c.find_notes("q"); c.find_cards("q")
    c.notes_info([1]); c.cards_info([2])
    c.model_templates("M"); c.model_styling("M"); c.model_field_names("M")
    c.update_note_fields(7, {"Front": "x"}); c.delete_notes([3, 4])

    assert [a for a, _ in seen] == [
        "deckNames", "modelNames", "findNotes", "findCards", "notesInfo", "cardsInfo",
        "modelTemplates", "modelStyling", "modelFieldNames", "updateNoteFields", "deleteNotes",
    ]
    params = dict(seen)
    assert params["updateNoteFields"]["note"] == {"id": 7, "fields": {"Front": "x"}}
    assert params["deleteNotes"]["notes"] == [3, 4]
