#!/usr/bin/env python3
"""Add a provisional card to the workbench inbox, validated against your live
Anki note types.

The inbox is just JSON files in ``data/inbox/`` (see the README "Inbox file
format" section). This helper builds a well-formed file and -- crucially --
checks the note type, field names, and deck against your *running* Anki first,
so a generator (you, or a Claude Code instance) can't silently write a card
whose fields get dropped on approve.

It writes files directly and talks to AnkiConnect directly, so the workbench
server does not need to be running; new cards show up the next time the inbox
loads.

Examples
--------
  # one Basic card from flags
  ./add-card -t Basic -d "Z::Deletable" \
      -f Front="What port does AnkiConnect use?" -f Back="8765" --tag ai

  # programmatic: a card (or a JSON array of cards) on stdin
  echo '{"note_type":"Cloze","deck":"Z::Deletable",
         "fields":{"Text":"The capital of {{c1::France}} is {{c2::Paris}}."}}' \
      | ./add-card --json -

  # give it a stable id so re-running updates the same inbox file
  ./add-card --id photosynthesis-1 -t Basic -d Biology \
      -f Front="Where does photosynthesis occur?" -f Back="Chloroplasts"

  # skip validation when Anki is closed
  ./add-card --no-validate -t Basic -d MyDeck -f Front=Q -f Back=A
"""
import argparse
import json
import os
import re
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend import inbox as inbox_mod  # noqa: E402
from backend import models as models_mod  # noqa: E402
from backend.ankiconnect import AnkiConnect, AnkiConnectError, AnkiUnavailable  # noqa: E402
from backend.config import load_config  # noqa: E402


def _slug(card):
    fields = card.get("fields", {})
    first = next((v for v in fields.values() if str(v or "").strip()), "card")
    text = re.sub(r"<[^>]+>", "", str(first))
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]
    return "%s-%s" % (slug or "card", uuid.uuid4().hex[:8])


def _safe_stem(stem):
    return re.sub(r"[^A-Za-z0-9._-]", "-", str(stem))


def validate(anki, card):
    """Check a card against the live collection. Returns (errors, warnings);
    errors block the write, warnings are advisory."""
    errors, warnings = [], []
    model = card.get("note_type", "Basic")
    models = anki.model_names()
    if model not in models:
        errors.append(
            "note type %r not found. Available: %s" % (model, ", ".join(sorted(models)))
        )
        return errors, warnings  # nothing else is checkable without the model

    valid_fields = anki.model_field_names(model)
    card_fields = card.get("fields", {})
    unknown = [f for f in card_fields if f not in valid_fields]
    if unknown:
        errors.append(
            "unknown field(s) for %r: %s. Valid fields: %s"
            % (model, ", ".join(unknown), ", ".join(valid_fields))
        )
    missing = [f for f in valid_fields if f not in card_fields]
    if missing:
        warnings.append("fields left empty: %s" % ", ".join(missing))
    if valid_fields and not str(card_fields.get(valid_fields[0], "")).strip():
        warnings.append("first field %r is empty; this card may not generate" % valid_fields[0])

    is_cloze = "cloze" in model.lower()
    has_markers = any(re.search(r"\{\{c\d+::", str(v or "")) for v in card_fields.values())
    if is_cloze and not has_markers:
        warnings.append("cloze note type but no {{c1::...}} markers found")
    if has_markers and not is_cloze:
        warnings.append("{{c...}} markers present but note type isn't a cloze type")

    deck = card.get("deck")
    if deck and deck not in anki.deck_names():
        warnings.append("deck %r doesn't exist yet; it'll be created on approve" % deck)
    return errors, warnings


def _card_from_flags(args, default_deck):
    fields = {}
    for item in args.field or []:
        if "=" not in item:
            sys.exit("--field must be NAME=VALUE, got %r" % item)
        name, value = item.split("=", 1)
        fields[name.strip()] = value
    return {
        "note_type": args.type,
        "deck": args.deck or default_deck,
        "fields": fields,
        "tags": args.tag or [],
        "source": args.source,
    }


def _load_json_cards(raw):
    if raw == "-":
        raw = sys.stdin.read()
    data = json.loads(raw)
    return data if isinstance(data, list) else [data]


def main():
    p = argparse.ArgumentParser(
        description="Add a validated provisional card to the workbench inbox.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("-t", "--type", default="Basic", help="note type (default: Basic)")
    p.add_argument("-d", "--deck", help="target deck (default: config default_deck)")
    p.add_argument("-f", "--field", action="append", metavar="NAME=VALUE",
                   help="a field value; repeatable")
    p.add_argument("--tag", action="append", help="a tag; repeatable")
    p.add_argument("--source", default="ai", help='value for the "source" field (default: ai)')
    p.add_argument("--id", help="filename stem / inbox id (default: slug of first field + hash)")
    p.add_argument("--json", metavar="JSON",
                   help="a card object or JSON array of objects; use - to read stdin")
    p.add_argument("--no-validate", action="store_true",
                   help="skip AnkiConnect validation (use when Anki is closed)")
    p.add_argument("--schema", action="store_true",
                   help="print note types, their fields, and decks as JSON, then exit")
    p.add_argument("--config", help="path to config.json")
    args = p.parse_args()

    cfg = load_config(args.config)
    inbox_dir = cfg["paths"]["inbox"]

    if args.schema:
        anki = AnkiConnect(cfg["ankiconnect_url"], cfg["ankiconnect_version"])
        if not anki.reachable():
            sys.exit("Anki not reachable at %s; open Anki to read the schema." % cfg["ankiconnect_url"])
        print(json.dumps(models_mod.snapshot(anki), indent=2, ensure_ascii=False))
        return

    if args.json:
        cards = _load_json_cards(args.json)
        if args.id and len(cards) > 1:
            sys.exit("--id can't be combined with multiple cards")
    else:
        cards = [_card_from_flags(args, cfg["default_deck"])]

    anki = None
    if not args.no_validate:
        anki = AnkiConnect(cfg["ankiconnect_url"], cfg["ankiconnect_version"])
        if not anki.reachable():
            sys.exit(
                "Anki/AnkiConnect not reachable at %s. Open Anki, or pass "
                "--no-validate to write without checking." % cfg["ankiconnect_url"]
            )

    written, failed = 0, 0
    for card in cards:
        card.setdefault("note_type", "Basic")
        card.setdefault("deck", cfg["default_deck"])
        card.setdefault("fields", {})
        card["fields"] = {k: ("" if v is None else str(v)) for k, v in card["fields"].items()}
        label = re.sub(r"<[^>]+>", "", next(iter(card["fields"].values()), ""))[:50]

        if anki is not None:
            try:
                errors, warnings = validate(anki, card)
            except (AnkiConnectError, AnkiUnavailable) as exc:
                errors, warnings = ["AnkiConnect error: %s" % exc], []
            for w in warnings:
                print("  warn: %s" % w, file=sys.stderr)
            if errors:
                failed += 1
                for e in errors:
                    print("SKIP (%s): %s" % (label or "?", e), file=sys.stderr)
                continue

        card["id"] = _safe_stem(args.id or card.get("id") or _slug(card))
        saved = inbox_mod.save_card(inbox_dir, card)
        written += 1
        print("wrote %s.json  [%s] -> %s" % (saved["id"], saved["note_type"], saved["deck"]))

    if failed:
        print("\n%d written, %d skipped (see validation errors above)." % (written, failed),
              file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
