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
