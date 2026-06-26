import argparse
import io
import json
import sys

import pytest

import add_card
from add_card import validate
from tests.conftest import FakeAnki


def _anki():
    a = FakeAnki()
    a.deck_names = lambda: ["Default", "Z::Deletable"]
    return a


def test_valid_basic_card_has_no_errors():
    errors, _ = validate(_anki(), {
        "note_type": "Basic", "deck": "Default",
        "fields": {"Front": "Q", "Back": "A"},
    })
    assert errors == []


def test_unknown_note_type_errors():
    errors, _ = validate(_anki(), {"note_type": "Nope", "fields": {"Front": "Q"}})
    assert errors and "not found" in errors[0]


def test_unknown_field_errors():
    errors, _ = validate(_anki(), {
        "note_type": "Basic", "fields": {"Frnt": "typo", "Back": "A"},
    })
    assert errors and "Frnt" in errors[0]


def test_missing_deck_is_a_warning_not_error():
    errors, warnings = validate(_anki(), {
        "note_type": "Basic", "deck": "NoSuchDeck", "fields": {"Front": "Q", "Back": "A"},
    })
    assert errors == []
    assert any("doesn't exist" in w for w in warnings)


def test_cloze_without_markers_warns():
    errors, warnings = validate(_anki(), {
        "note_type": "Cloze", "deck": "Default", "fields": {"Text": "no clozes here"},
    })
    assert errors == []
    assert any("marker" in w for w in warnings)


# --- pure helpers ---------------------------------------------------------

def test_slug_and_safe_stem():
    assert add_card._safe_stem("a/b c!..") == "a-b-c-.."
    assert add_card._slug({"fields": {"Front": "Hello, World!"}}).startswith("hello-world")


def test_card_from_flags_and_json_loading():
    args = argparse.Namespace(type="Basic", deck=None, field=["Front=Q", "Back=A"], tag=["x"], source="ai")
    card = add_card._card_from_flags(args, "Def")
    assert card["deck"] == "Def" and card["fields"] == {"Front": "Q", "Back": "A"} and card["tags"] == ["x"]
    assert add_card._load_json_cards('{"a":1}') == [{"a": 1}]
    assert add_card._load_json_cards('[{"a":1},{"b":2}]') == [{"a": 1}, {"b": 2}]


# --- main() end to end ----------------------------------------------------

def _wire(monkeypatch, tmp_path, argv, anki=None):
    cfg = {"paths": {"inbox": str(tmp_path)}, "default_deck": "Default",
           "ankiconnect_url": "x", "ankiconnect_version": 6}
    monkeypatch.setattr(add_card, "load_config", lambda path=None: cfg)
    fake = anki if anki is not None else FakeAnki()
    fake.deck_names = lambda: ["Default", "Z::Deletable"]
    monkeypatch.setattr(add_card, "AnkiConnect", lambda *a, **k: fake)
    monkeypatch.setattr(sys, "argv", ["add-card"] + argv)


def test_main_writes_valid_card(monkeypatch, tmp_path, capsys):
    _wire(monkeypatch, tmp_path, ["-t", "Basic", "-d", "Default", "-f", "Front=Q", "-f", "Back=A", "--id", "c1"])
    add_card.main()
    assert "wrote c1.json" in capsys.readouterr().out
    data = json.loads((tmp_path / "c1.json").read_text())
    assert data["fields"] == {"Front": "Q", "Back": "A"} and data["note_type"] == "Basic"


def test_main_unknown_field_skips_and_exits_1(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, ["-t", "Basic", "-d", "Default", "-f", "Frnt=oops", "--id", "bad"])
    with pytest.raises(SystemExit) as ei:
        add_card.main()
    assert ei.value.code == 1
    assert not (tmp_path / "bad.json").exists()


def test_main_anki_down_without_no_validate_exits(monkeypatch, tmp_path):
    class Down(FakeAnki):
        def reachable(self):
            return False
    _wire(monkeypatch, tmp_path, ["-t", "Basic", "-d", "D", "-f", "Front=Q"], anki=Down())
    with pytest.raises(SystemExit):
        add_card.main()


def test_main_no_validate_writes_without_anki(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, ["--no-validate", "-t", "Basic", "-d", "D", "-f", "Front=Q", "--id", "nv"])
    add_card.main()
    assert (tmp_path / "nv.json").exists()


def test_main_bad_field_format_exits(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, ["--no-validate", "-f", "noequals"])
    with pytest.raises(SystemExit):
        add_card.main()


def test_main_batch_json_stdin(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, ["--no-validate", "--json", "-"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps([
        {"id": "b1", "note_type": "Basic", "deck": "D", "fields": {"Front": "1", "Back": "x"}},
        {"id": "b2", "note_type": "Basic", "deck": "D", "fields": {"Front": "2", "Back": "y"}},
    ])))
    add_card.main()
    assert (tmp_path / "b1.json").exists() and (tmp_path / "b2.json").exists()


def test_main_id_with_multiple_cards_errors(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, ["--no-validate", "--id", "x", "--json", "-"])
    monkeypatch.setattr(sys, "stdin", io.StringIO('[{"fields":{"Front":"a"}},{"fields":{"Front":"b"}}]'))
    with pytest.raises(SystemExit):
        add_card.main()
