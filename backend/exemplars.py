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
    removed row, or None if the index is out of range. The removed row is
    appended to `<file>.trash` -- nothing the tool touches is hard-deleted."""
    rows = list_all(exemplar_file)
    if index < 0 or index >= len(rows):
        return None
    removed = rows.pop(index)
    _rewrite(exemplar_file, rows)
    with open(exemplar_file + ".trash", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"deleted": _now(), "exemplar": removed}, ensure_ascii=False) + "\n")
    return removed


def set_comment(exemplar_file, index, text):
    """Replace the comment on the snapshot at `index` (file position).
    Returns the old comment, or None if the index is out of range. Only the
    comment is mutable -- the snapshot content stays frozen."""
    rows = list_all(exemplar_file)
    if index < 0 or index >= len(rows):
        return None
    old = rows[index].get("comment", "")
    rows[index]["comment"] = text
    _rewrite(exemplar_file, rows)
    return old


def set_comment_by_date(exemplar_file, date, text):
    """Same, addressed by the snapshot's `date` stamp (stable across deletes,
    unlike a file index). Used by undo. No-op if the row is gone."""
    rows = list_all(exemplar_file)
    for row in rows:
        if row.get("date") == date:
            row["comment"] = text
            _rewrite(exemplar_file, rows)
            return True
    return False


def _rewrite(exemplar_file, rows):
    with open(exemplar_file, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
