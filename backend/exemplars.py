"""Exemplar archive: append-only log of frozen snapshots.

Marking a card good or bad stores its content *as it was at that moment* (fields
plus rendered HTML), not a pointer to the note. The live note may later be
fixed, mangled, or deleted; the snapshot stays true. Re-judging the same note in
a new state appends a new snapshot, and both coexist on purpose.
"""
import json
import os
from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).isoformat()


def add(exemplar_file, *, verdict, fields, rendered, note_type,
        note_id=None, comment="", deck=None):
    snapshot = {
        "date": _now(),
        "verdict": verdict,  # "good" | "bad"
        "note_id": note_id,
        "note_type": note_type,
        "deck": deck,
        "fields": fields,
        "rendered": rendered,  # {"question": ..., "answer": ..., "css": ...}
        "comment": comment,
    }
    with open(exemplar_file, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
    return snapshot


def list_all(exemplar_file):
    if not os.path.exists(exemplar_file):
        return []
    out = []
    with open(exemplar_file, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def pop_last(exemplar_file):
    """Remove the most recent snapshot. Used only for immediate undo."""
    rows = list_all(exemplar_file)
    if not rows:
        return None
    last = rows.pop()
    _rewrite(exemplar_file, rows)
    return last


def delete_at(exemplar_file, index):
    """Delete the snapshot at `index` (its position in the file). Returns the
    removed row, or None if the index is out of range."""
    rows = list_all(exemplar_file)
    if index < 0 or index >= len(rows):
        return None
    removed = rows.pop(index)
    _rewrite(exemplar_file, rows)
    return removed


def _rewrite(exemplar_file, rows):
    with open(exemplar_file, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
