"""Graveyard: deleted provisional cards land here instead of vanishing, so undo
and restore are trivial. Nothing is ever hard-deleted by the tool."""
import json
import os
from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).isoformat()


def _path(graveyard_dir, card_id):
    return os.path.join(graveyard_dir, "%s.json" % card_id)


def bury(graveyard_dir, card, origin="inbox"):
    entry = {"buried": _now(), "origin": origin, "card": card}
    with open(_path(graveyard_dir, card["id"]), "w", encoding="utf-8") as fh:
        json.dump(entry, fh, indent=2, ensure_ascii=False)
    return entry


def exhume(graveyard_dir, card_id):
    """Pull a card back out and remove its grave. Returns the card data."""
    path = _path(graveyard_dir, card_id)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        entry = json.load(fh)
    os.remove(path)
    return entry["card"]


def list_buried(graveyard_dir):
    out = []
    for name in os.listdir(graveyard_dir):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(graveyard_dir, name), "r", encoding="utf-8") as fh:
            out.append(json.load(fh))
    out.sort(key=lambda e: e.get("buried", ""), reverse=True)
    return out
