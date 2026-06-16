import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import app as app_mod  # noqa: E402
from backend import config as config_mod  # noqa: E402
from backend.ankiconnect import AnkiConnectError  # noqa: E402


class FakeAnki:
    """In-memory stand-in for AnkiConnect so the write path can be tested
    without a running Anki."""

    def __init__(self, *_, **__):
        self.notes = {}
        self.cards = {}
        self._next = 1000

    def invoke(self, action, **params):
        if action == "version":
            return 6
        raise AnkiConnectError("unhandled " + action)

    def reachable(self):
        return True

    def add_note(self, deck, model, fields, tags=None, allow_duplicate=False):
        nid = self._next
        self._next += 1
        self.notes[nid] = {"fields": dict(fields), "model": model, "deck": deck, "tags": tags or []}
        return nid

    def update_note_fields(self, note_id, fields):
        self.notes.setdefault(int(note_id), {"fields": {}})["fields"] = dict(fields)

    def delete_notes(self, note_ids):
        for n in note_ids:
            self.notes.pop(int(n), None)

    def find_cards(self, query):
        return list(self.cards.keys())

    def cards_info(self, card_ids):
        out = []
        for cid in card_ids:
            c = self.cards[int(cid)]
            out.append(
                {
                    "cardId": int(cid),
                    "note": c["note_id"],
                    "modelName": c["model"],
                    "deckName": c["deck"],
                    "flags": c["flag"],
                    "fields": c["fields"],
                    "question": "Q",
                    "answer": "A",
                    "css": ".card{}",
                }
            )
        return out

    def set_flag(self, card_id, flag):
        self.cards[int(card_id)]["flag"] = flag

    def deck_names(self):
        return ["Default"]

    def model_templates(self, model):
        if model == "Basic (and reversed card)":
            return {
                "Card 1": {"Front": "{{Front}}", "Back": "{{FrontSide}}<hr>{{Back}}"},
                "Card 2": {"Front": "{{Back}}", "Back": "{{FrontSide}}<hr>{{Front}}"},
            }
        if model == "Basic (optional reversed card)":
            return {
                "Card 1": {"Front": "{{Front}}", "Back": "{{FrontSide}}<hr>{{Back}}"},
                "Card 2": {"Front": "{{#Add Reverse}}{{Back}}{{/Add Reverse}}", "Back": "{{Front}}"},
            }
        return {"Card 1": {"Front": "{{Front}}", "Back": "{{FrontSide}}<hr>{{Back}}"}}

    def model_styling(self, model):
        return {"css": ".card{color:red}"}

    def model_field_names(self, model):
        return ["Front", "Back"]


@pytest.fixture
def cfg(tmp_path):
    conf = {"data_dir": str(tmp_path / "data")}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(conf))
    return config_mod.load_config(str(path))


@pytest.fixture
def client(cfg, monkeypatch):
    fake = FakeAnki()
    monkeypatch.setattr(app_mod, "AnkiConnect", lambda *a, **k: fake)
    application = app_mod.create_app(cfg)
    application.testing = True
    c = application.test_client()
    c.fake = fake
    c.cfg = cfg
    return c
