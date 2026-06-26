"""CardRenderer: cardsInfo shaping and the provisional render paths, including
the Anki-closed fallback and template generation rules."""
from backend.ankiconnect import AnkiConnectError
from backend.cards import CardRenderer


class ClosedAnki:
    """Anki unreachable: every model lookup raises, exercising the fallback."""

    def model_templates(self, m):
        raise AnkiConnectError("down")

    def model_styling(self, m):
        raise AnkiConnectError("down")

    def model_field_names(self, m):
        raise AnkiConnectError("down")


class TemplateAnki:
    def __init__(self, templates, fields, css=".card{}"):
        self._t, self._f, self._css = templates, fields, css

    def model_templates(self, m):
        return self._t

    def model_styling(self, m):
        return {"css": self._css}

    def model_field_names(self, m):
        return self._f


def test_from_card_info_shapes_payload():
    info = {
        "cardId": 5, "note": 9, "modelName": "Basic", "deckName": "D", "flags": 2,
        "fields": {"Back": {"value": "B", "order": 1}, "Front": {"value": "F", "order": 0}},
        "question": "[$]x[$]", "answer": "A", "css": ".c{}",
    }
    out = CardRenderer.from_card_info(info)
    assert out["card_id"] == 5 and out["note_id"] == 9 and out["flag"] == 2
    assert out["field_order"] == ["Front", "Back"]  # sorted by 'order'
    assert out["fields"] == {"Front": "F", "Back": "B"}
    assert out["question"] == r"\(x\)"  # latex normalized
    assert out["css"] == ".c{}"


def test_render_provisional_basic_anki_closed():
    out = CardRenderer(ClosedAnki(), {}).render_provisional(
        {"note_type": "Basic", "fields": {"Front": "Q", "Back": "A"}}
    )
    assert len(out["cards"]) == 1
    assert out["cards"][0]["question"] == "Q"
    assert out["css"]  # DEFAULT_CSS fallback


def test_render_provisional_cloze_anki_closed_renders_all_ordinals():
    out = CardRenderer(ClosedAnki(), {}).render_provisional(
        {"note_type": "Cloze", "fields": {"Text": "{{c1::a}} {{c2::b}}"}}
    )
    assert [c["ordinal"] for c in out["cards"]] == [1, 2]


def test_template_card_omitted_when_front_empty():
    templates = {
        "Forward": {"Front": "{{Front}}", "Back": "{{Back}}"},
        "Reverse": {"Front": "{{#Add Reverse}}{{Back}}{{/Add Reverse}}", "Back": "{{Front}}"},
    }
    two = CardRenderer(TemplateAnki(templates, ["Front", "Back", "Add Reverse"]), {}).render_provisional(
        {"note_type": "X", "fields": {"Front": "F", "Back": "B", "Add Reverse": "y"}}
    )
    one = CardRenderer(TemplateAnki(templates, ["Front", "Back", "Add Reverse"]), {}).render_provisional(
        {"note_type": "X", "fields": {"Front": "F", "Back": "B", "Add Reverse": ""}}
    )
    assert [c["ordinal"] for c in two["cards"]] == [0, 1]
    assert two["cards"][1]["name"] == "Reverse"
    assert [c["ordinal"] for c in one["cards"]] == [0]


def test_all_templates_empty_still_shows_one():
    templates = {"Only": {"Front": "{{Front}}", "Back": "{{Back}}"}}
    out = CardRenderer(TemplateAnki(templates, ["Front", "Back"]), {}).render_provisional(
        {"note_type": "X", "fields": {"Front": "", "Back": "B"}}
    )
    assert len(out["cards"]) == 1  # safety: inbox is never blank
