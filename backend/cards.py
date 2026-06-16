"""Turn cards into rendered HTML.

Live deck cards: AnkiConnect's cardsInfo already returns fully rendered
question/answer plus the note's css, so we use that directly (most faithful).

Provisional inbox cards: no card exists in Anki yet, so we template it
ourselves. If Anki is running we borrow the real note type's template and css so
it looks like the real thing; if Anki is closed we fall back to a plain
front/back render so the inbox still works offline.
"""
from . import rendering
from .ankiconnect import AnkiConnectError


class CardRenderer:
    def __init__(self, anki, cfg):
        self.anki = anki
        self.cfg = cfg
        self._model_cache = {}

    def _model(self, model_name):
        if model_name in self._model_cache:
            return self._model_cache[model_name]
        templates = css = field_order = None
        try:
            templates = self.anki.model_templates(model_name)
            styling = self.anki.model_styling(model_name)
            css = styling.get("css") if isinstance(styling, dict) else None
            field_order = self.anki.model_field_names(model_name)
        except AnkiConnectError:
            pass
        result = (templates, css, field_order)
        self._model_cache[model_name] = result
        return result

    def render_provisional(self, card):
        fields = card.get("fields", {})
        model_name = card.get("note_type", "Basic")
        templates, css, field_order = self._model(model_name)
        field_order = field_order or list(fields.keys())

        if templates:
            first = next(iter(templates.values()))
            qfmt = first.get("Front", "")
            afmt = first.get("Back", "")
        else:
            cloze_name = rendering.cloze_field_name(fields)
            if cloze_name:
                qfmt, afmt = rendering.cloze_templates(field_order, cloze_name)
            else:
                qfmt, afmt = rendering.basic_templates(field_order)
        if not css:
            css = rendering.DEFAULT_CSS

        rendered = rendering.render(fields, qfmt, afmt)
        rendered["css"] = css
        rendered["field_order"] = field_order
        return rendered

    @staticmethod
    def from_card_info(info):
        """Shape a cardsInfo result into the same payload the frontend expects
        for any rendered card."""
        fields = info.get("fields", {})
        ordered = sorted(fields.items(), key=lambda kv: kv[1].get("order", 0))
        field_order = [name for name, _ in ordered]
        return {
            "card_id": info.get("cardId"),
            "note_id": info.get("note"),
            "model": info.get("modelName"),
            "deck": info.get("deckName"),
            "flag": info.get("flags", 0),
            "fields": {name: val.get("value", "") for name, val in fields.items()},
            "field_order": field_order,
            "question": rendering.convert_latex(info.get("question", "")),
            "answer": rendering.convert_latex(info.get("answer", "")),
            "css": info.get("css", rendering.DEFAULT_CSS),
        }
