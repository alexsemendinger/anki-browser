"""Undo stack, persisted to disk so undo survives a restart where the data
allows. Each entry carries the inverse information its undo needs. The stack
stores records; app.py owns the interpreter that reverses them, since it holds
the wired-up services (Anki, inbox, graveyard, ...).
"""
import json
import os
from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).isoformat()


def _read(actions_file):
    if not os.path.exists(actions_file):
        return []
    with open(actions_file, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _write(actions_file, stack):
    with open(actions_file, "w", encoding="utf-8") as fh:
        json.dump(stack, fh, indent=2, ensure_ascii=False)


def push(actions_file, kind, payload, label):
    stack = _read(actions_file)
    stack.append({"ts": _now(), "kind": kind, "payload": payload, "label": label})
    _write(actions_file, stack)


def peek(actions_file):
    stack = _read(actions_file)
    return stack[-1] if stack else None


def pop(actions_file):
    stack = _read(actions_file)
    if not stack:
        return None
    last = stack.pop()
    _write(actions_file, stack)
    return last


def depth(actions_file):
    return len(_read(actions_file))
