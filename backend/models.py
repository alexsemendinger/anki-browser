"""Snapshot of the collection's note types (with their fields) and decks.

This is the exact schema a card generator -- you, or a Claude Code instance --
needs to write valid inbox cards: which note types exist, the precise field
names of each, and which decks are real. It's cheap to produce (modelNames plus
one modelFieldNames per model), so the app regenerates it on every open and
drops it in data/ for anything to read.
"""
import json
import os
from datetime import datetime, timezone

from .ankiconnect import AnkiConnectError


def snapshot(anki):
    """{'models': {name: [field, ...]}, 'decks': [...], 'generated': iso}."""
    models = {name: anki.model_field_names(name) for name in anki.model_names()}
    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "models": models,
        "decks": sorted(anki.deck_names()),
    }


def to_markdown(snap):
    lines = [
        "# Note types & decks",
        "",
        "Auto-generated from your live Anki collection, refreshed each time the",
        "workbench is opened. Use these *exact* note-type and field names when",
        "writing inbox cards.",
        "",
        "_Generated: %s_" % snap["generated"],
        "",
        "## Note types (field names)",
        "",
    ]
    for name in sorted(snap["models"]):
        fields = ", ".join("`%s`" % f for f in snap["models"][name]) or "(no fields)"
        lines.append("- **%s** — %s" % (name, fields))
    lines += ["", "## Decks", ""]
    lines += ["- `%s`" % d for d in snap["decks"]]
    lines.append("")
    return "\n".join(lines)


def write_snapshot(anki, data_dir):
    """Best-effort: write JSON + Markdown snapshots into data_dir. Returns the
    snapshot dict, or None if Anki was unreachable (nothing is written then)."""
    try:
        snap = snapshot(anki)
    except AnkiConnectError:
        return None
    try:
        with open(os.path.join(data_dir, "note_types.json"), "w", encoding="utf-8") as fh:
            json.dump(snap, fh, indent=2, ensure_ascii=False)
        with open(os.path.join(data_dir, "note_types.md"), "w", encoding="utf-8") as fh:
            fh.write(to_markdown(snap))
    except OSError:
        pass
    return snap
