"""The note-type/deck schema snapshot."""
import json

from backend import models
from backend.ankiconnect import AnkiConnectError


class Anki:
    def model_names(self):
        return ["Basic", "Cloze"]

    def model_field_names(self, m):
        return ["Text", "Extra"] if m == "Cloze" else ["Front", "Back"]

    def deck_names(self):
        return ["B", "A"]


class DownAnki:
    def model_names(self):
        raise AnkiConnectError("down")

    def model_field_names(self, m):
        raise AnkiConnectError("down")

    def deck_names(self):
        raise AnkiConnectError("down")


def test_snapshot_structure():
    snap = models.snapshot(Anki())
    assert snap["models"] == {"Basic": ["Front", "Back"], "Cloze": ["Text", "Extra"]}
    assert snap["decks"] == ["A", "B"]  # sorted
    assert snap["generated"]


def test_to_markdown_lists_types_and_decks():
    md = models.to_markdown(models.snapshot(Anki()))
    assert "**Basic** — `Front`, `Back`" in md
    assert "- `A`" in md and "- `B`" in md


def test_write_snapshot_creates_both_files(tmp_path):
    snap = models.write_snapshot(Anki(), str(tmp_path))
    assert snap is not None
    assert (tmp_path / "note_types.json").exists()
    assert (tmp_path / "note_types.md").exists()
    data = json.loads((tmp_path / "note_types.json").read_text())
    assert data["models"]["Cloze"] == ["Text", "Extra"]


def test_write_snapshot_returns_none_when_anki_down(tmp_path):
    assert models.write_snapshot(DownAnki(), str(tmp_path)) is None
    assert not (tmp_path / "note_types.json").exists()
