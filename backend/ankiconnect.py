"""Thin client over AnkiConnect. The only write path to the live deck.

Anki must be running with the AnkiConnect add-on listening (default
127.0.0.1:8765). Everything here maps one-to-one onto an AnkiConnect action so
the surface stays easy to reason about and to mock in tests.
"""
import requests


class AnkiConnectError(Exception):
    pass


class AnkiUnavailable(AnkiConnectError):
    """Anki not running / port not reachable."""


class AnkiConnect:
    def __init__(self, url, version=6, timeout=8):
        self.url = url
        self.version = version
        self.timeout = timeout

    def invoke(self, action, **params):
        payload = {"action": action, "version": self.version, "params": params}
        try:
            resp = requests.post(self.url, json=payload, timeout=self.timeout)
        except requests.exceptions.RequestException as exc:
            raise AnkiUnavailable(str(exc)) from exc
        data = resp.json()
        if data.get("error") is not None:
            raise AnkiConnectError(data["error"])
        return data.get("result")

    # --- connection -----------------------------------------------------
    def reachable(self):
        try:
            self.invoke("version")
            return True
        except AnkiConnectError:
            return False

    def deck_names(self):
        return self.invoke("deckNames")

    def model_names(self):
        return self.invoke("modelNames")

    # --- reading --------------------------------------------------------
    def find_notes(self, query):
        return self.invoke("findNotes", query=query)

    def find_cards(self, query):
        return self.invoke("findCards", query=query)

    def notes_info(self, note_ids):
        if not note_ids:
            return []
        return self.invoke("notesInfo", notes=note_ids)

    def cards_info(self, card_ids):
        if not card_ids:
            return []
        return self.invoke("cardsInfo", cards=card_ids)

    def model_templates(self, model_name):
        return self.invoke("modelTemplates", modelName=model_name)

    def model_styling(self, model_name):
        return self.invoke("modelStyling", modelName=model_name)

    def model_field_names(self, model_name):
        return self.invoke("modelFieldNames", modelName=model_name)

    # --- writing --------------------------------------------------------
    def add_note(self, deck, model, fields, tags=None, allow_duplicate=False):
        note = {
            "deckName": deck,
            "modelName": model,
            "fields": fields,
            "tags": tags or [],
            "options": {"allowDuplicate": allow_duplicate},
        }
        return self.invoke("addNote", note=note)

    def update_note_fields(self, note_id, fields):
        return self.invoke(
            "updateNoteFields", note={"id": int(note_id), "fields": fields}
        )

    def delete_notes(self, note_ids):
        return self.invoke("deleteNotes", notes=[int(n) for n in note_ids])

    def set_flag(self, card_id, flag):
        """Set/clear a card's native flag (0 = none). Uses
        setSpecificValueOfCard, which is gated behind warning_check. If your
        AnkiConnect build refuses it the repair save still succeeds; the flag
        just stays. See README."""
        return self.invoke(
            "setSpecificValueOfCard",
            card=int(card_id),
            keys=["flags"],
            newValues=[int(flag)],
            warning_check=True,
        )
