"""Turn cards into rendered HTML.

Live deck cards: AnkiConnect's cardsInfo already returns fully rendered
question/answer plus the note's css, so we use that directly (most faithful).

Provisional inbox cards: no card exists in Anki yet, so we template it
ourselves. If Anki is running we borrow the real note type's template and css so
it looks like the real thing; if Anki is closed we fall back to a plain
front/back render so the inbox still works offline.
"""
import re
from urllib.parse import unquote

from . import rendering
from .ankiconnect import AnkiConnectError

_IMG_SRC_RE = re.compile(r'(<img\b[^>]*?\bsrc=")([^"]+)(")', re.I)
_MEDIA_MIME = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif",
    "svg": "image/svg+xml", "webp": "image/webp", "bmp": "image/bmp", "ico": "image/x-icon",
}


class CardRenderer:
    def __init__(self, anki, cfg):
        self.anki = anki
        self.cfg = cfg
        self._model_cache = {}
        self._media_cache = {}

    # --- media -----------------------------------------------------------
    def inline_media(self, html):
        """Replace <img src="file.png"> with a data: URI fetched from Anki's
        media folder, so images render in our sandboxed iframe without copying
        or syncing any files. Already-inlined / remote srcs are left alone."""
        if not html or "<img" not in html.lower():
            return html

        def repl(m):
            src = m.group(2)
            if src.startswith(("data:", "http:", "https:", "//")):
                return m.group(0)
            uri = self._media_data_uri(unquote(src))
            return m.group(1) + (uri or src) + m.group(3)

        return _IMG_SRC_RE.sub(repl, html)

    def _media_data_uri(self, filename):
        if filename in self._media_cache:
            return self._media_cache[filename]
        uri = None
        try:
            b64 = self.anki.retrieve_media_file(filename)
            if b64:
                ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
                mime = _MEDIA_MIME.get(ext, "application/octet-stream")
                uri = "data:%s;base64,%s" % (mime, b64)
        except AnkiConnectError:
            uri = None
        self._media_cache[filename] = uri
        return uri

    def shape_live(self, info):
        """from_card_info plus media inlining, for live deck cards."""
        shaped = self.from_card_info(info)
        shaped["question"] = self.inline_media(shaped["question"])
        shaped["answer"] = self.inline_media(shaped["answer"])
        return shaped

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
        if not css:
            css = rendering.DEFAULT_CSS

        # Enumerate EVERY card the note will generate so the inbox can page
        # through and approve each one. addNote is atomic, so the note is only
        # sent once all its cards are approved. Cloze -> one card per ordinal;
        # any other note type -> one card per template that generates.
        if rendering.cloze_field_name(fields):
            cards = self._cloze_cards(fields, field_order, templates)
        else:
            cards = self._template_cards(fields, field_order, templates)

        for c in cards:
            c["question"] = self.inline_media(c["question"])
            c["answer"] = self.inline_media(c["answer"])

        return {
            "question": cards[0]["question"],
            "answer": cards[0]["answer"],
            "cards": cards,
            "css": css,
            "field_order": field_order,
        }

    def _cloze_cards(self, fields, field_order, templates):
        """One card per cloze ordinal (c1, c2, ...); ordinal = the cloze number."""
        qfmt = afmt = None
        if templates:
            first = next(iter(templates.values()))
            if "{{cloze:" in (first.get("Front", "") or ""):
                qfmt, afmt = first.get("Front", ""), first.get("Back", "")
        if qfmt is None:  # Anki closed or non-cloze template: synthesize one
            cloze_name = rendering.cloze_field_name(fields)
            qfmt, afmt = rendering.cloze_templates(field_order, cloze_name)
        cards = []
        for ordinal in rendering.cloze_ordinals(fields):
            r = rendering.render(fields, qfmt, afmt, ordinal=ordinal)
            cards.append(
                {"ordinal": ordinal, "name": "cloze %d" % ordinal,
                 "question": r["question"], "answer": r["answer"]}
            )
        return cards

    def _template_cards(self, fields, field_order, templates):
        """One card per card template that actually generates for these fields.
        A template whose front renders empty (e.g. an optional reverse with its
        field unset) produces no card, matching Anki. Ordinal = template index,
        which is Anki's card ord."""
        items = list(templates.items()) if templates else []
        if not items:  # Anki closed: fall back to a single basic template
            qfmt, afmt = rendering.basic_templates(field_order)
            items = [("Card 1", {"Front": qfmt, "Back": afmt})]
        cards = []
        for ordinal, (name, tmpl) in enumerate(items):
            r = rendering.render(fields, tmpl.get("Front", ""), tmpl.get("Back", ""))
            if not rendering.strip_tags(r["question"]).strip():
                continue  # empty front -> Anki generates no card for this template
            cards.append(
                {"ordinal": ordinal, "name": name,
                 "question": r["question"], "answer": r["answer"]}
            )
        if not cards:  # every template empty: still show one so the inbox isn't blank
            name, tmpl = items[0]
            r = rendering.render(fields, tmpl.get("Front", ""), tmpl.get("Back", ""))
            cards.append(
                {"ordinal": 0, "name": name, "question": r["question"], "answer": r["answer"]}
            )
        return cards

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
