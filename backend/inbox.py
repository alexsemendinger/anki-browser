"""Inbox: provisional cards as one JSON file each. Never touches Anki until
approved. This is also the file format a v2 generation agent writes into and
reads back from, so keep it stable and obvious.

The filename stem is the canonical id. An agent (or you) drops
`data/inbox/<anything>.json` in and the tool addresses it as `<anything>`. Any
internal "id" field is optional and ignored for addressing.

File shape:
{
  "note_type": "Basic",
  "deck": "Default",
  "fields": {"Front": "...", "Back": "..."},
  "tags": ["ai"],
  "source": "ai" | "manual",
  "created": "<iso8601>",
  "comment_history": [{"date": "<iso>", "author": "...", "text": "..."}],
  "approved_cards": [1, 2]   # ordinals approved so far; note is sent to Anki
                             # only once every card it generates is approved.
                             # Additive/optional -- old files and generators
                             # that omit it default to [] (nothing approved).
}
"""
import json
import os
import uuid
from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).isoformat()


def _path(inbox_dir, card_id):
    return os.path.join(inbox_dir, "%s.json" % card_id)


def _normalize(card, card_id):
    card["id"] = card_id
    card.setdefault("note_type", "Basic")
    card.setdefault("deck", "Default")
    card.setdefault("fields", {})
    card.setdefault("tags", [])
    card.setdefault("source", "manual")
    card.setdefault("created", _now())
    card.setdefault("comment_history", [])
    card.setdefault("approved_cards", [])  # ordinals approved so far (gate to send)
    return card


def _last_activity(card):
    """Sort key for the review queue: the newest of `created` and any comment
    date. A just-sent-back card (fresh comment) therefore sinks to the bottom,
    so you don't immediately re-review the card you just commented on."""
    ts = card.get("created", "")
    for c in card.get("comment_history", []):
        ts = max(ts, c.get("date", ""))
    return ts


def list_cards(inbox_dir):
    cards = []
    for name in os.listdir(inbox_dir):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(inbox_dir, name), "r", encoding="utf-8") as fh:
                cards.append(_normalize(json.load(fh), name[:-5]))
        except (json.JSONDecodeError, OSError):
            continue
    cards.sort(key=_last_activity)
    return cards


def get_card(inbox_dir, card_id):
    path = _path(inbox_dir, card_id)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return _normalize(json.load(fh), card_id)


def save_card(inbox_dir, card):
    card_id = card.get("id") or uuid.uuid4().hex
    card = _normalize(card, card_id)
    with open(_path(inbox_dir, card_id), "w", encoding="utf-8") as fh:
        json.dump(card, fh, indent=2, ensure_ascii=False)
    return card


def update_fields(inbox_dir, card_id, fields):
    card = get_card(inbox_dir, card_id)
    if card is None:
        return None
    card["fields"] = fields
    return save_card(inbox_dir, card)


def set_approved(inbox_dir, card_id, ordinals):
    """Set the list of per-card approvals (cloze ordinals) on a provisional
    note. The note is sent to Anki only once every card is approved."""
    card = get_card(inbox_dir, card_id)
    if card is None:
        return None
    card["approved_cards"] = sorted({int(o) for o in ordinals})
    return save_card(inbox_dir, card)


def add_comment(inbox_dir, card_id, text, author="me"):
    card = get_card(inbox_dir, card_id)
    if card is None:
        return None
    card["comment_history"].append({"date": _now(), "author": author, "text": text})
    return save_card(inbox_dir, card)


def pop_comment(inbox_dir, card_id):
    card = get_card(inbox_dir, card_id)
    if card and card["comment_history"]:
        card["comment_history"].pop()
        save_card(inbox_dir, card)
    return card


def remove_card(inbox_dir, card_id):
    """Read the card out and delete its file. Returns the card data."""
    card = get_card(inbox_dir, card_id)
    if card is None:
        return None
    os.remove(_path(inbox_dir, card_id))
    return card


def count(inbox_dir):
    return sum(1 for n in os.listdir(inbox_dir) if n.endswith(".json"))
