# Anki Deck Workbench

A local, keyboard-first tool for curating your own Anki cards: judge provisional
cards one at a time, repair flagged cards in the live deck, and survey what you
have. The native browser is for managing a collection; this is for rendering
per-card judgment fast and pleasant so only good cards make it in.

AnkiConnect is the only write path to your live deck. Provisional cards live as
plain files until you approve them. Nothing is hard-deleted.

Docs: `docs/SPEC.md` (original build spec, source of truth for intent) and
`docs/DESIGN_NOTES.md` (design rationale, nonobvious choices, known risks,
verification status, next steps). Read `DESIGN_NOTES.md` before changing the
Anki write path.

## Requirements

- Python 3.11+
- Anki running with the [AnkiConnect](https://ankiweb.net/shared/info/2055492159)
  add-on (default `127.0.0.1:8765`), for any live-deck operation
- A browser (the UI uses MathJax from a CDN by default; see config to change)

The inbox surface works without Anki. Approve, repair, and survey need Anki open.

## Run

```
./start.sh
```

That's it. The first run sets up a hidden virtualenv and installs dependencies;
every run after just starts the server and opens http://127.0.0.1:5151 in your
browser. Press Ctrl+C to stop. On macOS you can also double-click
**`Anki Workbench.command`** in Finder (or keep it in the Dock).

You never activate or manage a venv. If you ever want a clean slate, delete the
`.venv` folder and run `./start.sh` again.

<details><summary>Manual / no-script alternative</summary>

```
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python run.py            # then open http://127.0.0.1:5151
```
</details>

Optional: copy `config.example.json` to `config.json` and edit it.

To try the inbox with no setup, drop the sample cards in:

```
mkdir -p data/inbox && cp sample_inbox/*.json data/inbox/
```

## Surfaces

- **1 inbox** — provisional cards, one at a time. Approve into the deck, send
  back with a comment, or delete to the graveyard. The count drains to zero.
- **2 repair** — live deck cards carrying a red or orange Anki flag. Edit
  inline; saving writes the fields back and clears the native flag.
- **3 survey** — a grid for scanning and filtering. Orienting, not the workspace.
- **4 stats** — lifetime processed, approval rate, judgments, queue sizes.

## Keys

Modal, vim-style. A quiet indicator in the top right shows NORMAL or INSERT.

| key | action |
| --- | --- |
| `1`-`4` | switch surface |
| `j` / `k` (or arrows) | previous / next card |
| `space` | flip |
| `a` | approve (inbox to deck) |
| `d` | delete (inbox to graveyard) |
| `c` | comment and send back (inbox) |
| `e` | edit fields (inbox / repair) |
| `g` | mark exemplar, then `g` good or `b` bad |
| `u` | undo |
| `s` | start session / set target |
| `?` | help |

In edit and comment overlays: `Ctrl+Enter` commits, `Esc` cancels. In the survey
grid, arrows move the selection, `space` flips one card, and the flip-all button
flips the grid (defaults to backs).

## Inbox file format

One card per JSON file in `data/inbox/`. **The filename stem is the card's id**,
so a generator can write `data/inbox/whatever.json` and the tool addresses it as
`whatever` (any internal `"id"` field is ignored for addressing). The directory
is read live, so a new file appears the next time the inbox loads — no restart.

```json
{
  "note_type": "Basic",
  "deck": "Biology",
  "fields": { "Front": "...", "Back": "..." },
  "tags": ["ai"],
  "source": "ai",
  "created": "<iso8601>",
  "comment_history": [
    { "date": "<iso8601>", "author": "me", "text": "too vague, add an example" }
  ],
  "approved_cards": []
}
```

Only `fields` is strictly required; everything else has a default (`note_type` →
`Basic`, `deck` → config `default_deck`, the rest empty). Two things that bite:

- **`deck` must be a real deck** in your collection, or approving creates a stray one.
- **Field names must match the note type exactly** (`Basic` → `Front`/`Back`,
  `Cloze` → `Text`/`Extra`); unknown fields are silently dropped on approve.

`comment_history` accumulates send-back comments so a regenerating agent sees the
whole conversation, not just the latest state. `approved_cards` holds the per-card
approvals (cloze ordinals / template indices) and is managed by the app — a
generator should leave it out (it defaults to `[]`).

## Adding cards (the `add-card` helper)

Writing that JSON by hand is no fun and it's easy to get a field name wrong.
`./add-card` builds a well-formed file for you and validates the note type, field
names, and deck against your **running Anki** first, so mistakes are caught before
they reach the inbox. It writes files directly (the workbench server need not be
running) and is the intended entry point for scripted / AI card creation.

```
# one Basic card from flags
./add-card -t Basic -d "Biology" \
    -f Front="Where does photosynthesis occur?" -f Back="Chloroplasts" --tag ai

# a card (or a JSON array of cards) on stdin -- the programmatic path
echo '{"note_type":"Cloze","deck":"Biology",
       "fields":{"Text":"ATP is made in the {{c1::mitochondria}}."}}' \
    | ./add-card --json -

# stable id so re-running updates the same inbox file (the revision loop)
./add-card --id photosynthesis-1 -t Basic -d Biology -f Front="..." -f Back="..."

# Anki closed? skip validation (you lose the safety check)
./add-card --no-validate -t Basic -d Biology -f Front=Q -f Back=A
```

Validation **errors** (unknown note type, unknown field) block the write;
**warnings** (deck doesn't exist yet, empty first field, cloze with no
`{{c1::...}}` markers) are printed but don't. See `./add-card --help` for all flags.

**For a Claude Code instance:** generate your notes, then for each call
`./add-card --json -` with the card JSON on stdin. Match `note_type` to a real
Anki model and use that model's exact field names (see the schema reference
below). After a card is sent back with a comment it lands in that file's
`comment_history` — read it, revise, and write the same `id` to update the card
in place.

## Note type / field reference

Every time the app is opened it snapshots your collection's schema to:

- `data/note_types.json` — `{ "models": { "Basic": ["Front","Back"], ... },
  "decks": [...] }`, for programmatic use
- `data/note_types.md` — the same, human-readable

This is the authoritative list of note types, their exact field names, and your
real deck names — read `data/note_types.json` before generating cards. It's also
available live at `GET /api/models` (which regenerates the files), and
`add-card` validates against the same data. Cheap to produce (one `modelNames`
call plus one `modelFieldNames` per model), so it always reflects the current
collection.

## Data

Everything lives under `data/` (gitignored):

- `inbox/` — provisional cards
- `graveyard/` — deleted cards, kept so undo and restore are trivial
- `exemplars.jsonl` — append-only frozen snapshots. Marking a card good or bad
  stores its content at that moment (fields plus rendered HTML), not a pointer
  to the note. The live note can later change or vanish; the snapshot stays
  true. Re-judging the same note appends a new snapshot; both coexist on purpose.
- `events.jsonl` — one event per judgment, for stats
- `actions.json` — the undo stack
- `session.json` — current sitting

## Sessions

Press `s` to start a session and optionally set a target count. The top right
shows progress and tells you when you hit the target. The target never locks
anything; keep going if you want. Off by default.

## Beeminder

Off by default. Configure under `beeminder` in `config.json`: `username`,
`auth_token`, `goal`. The tool pushes one aggregated datapoint per day (keyed by
daystamp, so repeats update that day's point rather than piling up), which keeps
the number measured rather than self-reported.

Configurable and unsettled on purpose:

- `count` — which actions count toward the value (`approve`, `delete`, `repair`,
  `send_back`, `exemplar`). Send-back is off by default.
- `push_on` — `session_end` (default) or `each_action`.

Queue size is never the committed metric; generating cards would punish you for
making work. It stays a display statistic only.

## Config

See `config.example.json`. Notable keys: `ankiconnect_url`, `default_deck`,
`repair_flags` (default `[1, 2]` = red, orange), `grid_show_backs`,
`grid_mathjax`, `mathjax_url`, `send_back_requires_comment`.

## Rendering notes

Live deck cards (repair, survey) are rendered by Anki itself via cardsInfo, so
they look exactly like your real cards. Provisional inbox cards are templated
here; if Anki is open the real note type's template and CSS are borrowed, and if
Anki is closed there is a plain front/back (and cloze-aware) fallback so the
inbox still works offline. LaTeX delimiters (`\(..\)`, `[$]..[$]`,
`[latex]..[/latex]`) are normalized to MathJax form.

## Clearing native flags on repair

Repair clears a card's flag with AnkiConnect's `setSpecificValueOfCard`, which
some builds gate behind a confirmation. If your build refuses it the repair save
still succeeds; the flag just stays, and the UI says so. The flag-setting call
is isolated in `backend/ankiconnect.py` if you need to adjust it.

## Tests

```
. .venv/bin/activate && python -m pytest -q
```

Disk and logic paths (rendering, inbox, graveyard, undo, exemplars, stats) and
the full Anki write path (approve, repair, undo) run against an in-memory Anki
stand-in, so the suite passes with no Anki present. The live round-trip against
a real running Anki should be confirmed on your machine.
