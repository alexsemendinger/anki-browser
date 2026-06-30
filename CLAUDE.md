# Anki Deck Workbench — working on this app

Local single-user tool for reviewing and approving AI-generated Anki cards.
Flask + vanilla JS, no build step.

**Read `docs/DESIGN_NOTES.md` first** — it's the architecture map, the rationale
for the non-obvious choices, and the known risks. `docs/SPEC.md` is the original
spec; `README.md` is usage.

## Run & test
- `./start.sh` — start the server (creates a hidden venv on first run, opens the browser).
- `.venv/bin/python -m pytest` — the test suite (hermetic; mocks Anki, no real collection needed).

## Invariants — don't break these
- **AnkiConnect is the only write path to the live deck.** No direct collection writes.
- **Nothing is hard-deleted** by the tool (inbox delete → graveyard).
- **Undo stack ↔ stats are LIFO lockstep.** A new action either records a stat AND its undo pops one, or neither.
- **Live deck cards are rendered by Anki** (`cardsInfo` HTML+CSS), not by `rendering.py`; that engine is only for provisional inbox cards.
- **Filename stem is the canonical inbox id** (`inbox._normalize` overwrites `id`).
- **The inbox JSON format is the card-generation seam** — keep it stable, additive changes only.

## Note on card generation
Generating cards is done by separate agents launched elsewhere, not from this
repo. Their job is to write valid files into the inbox via `add_card.py` /
`/api/models`; this repo's job is to keep those, the inbox format, and the
review/approve flow working.
