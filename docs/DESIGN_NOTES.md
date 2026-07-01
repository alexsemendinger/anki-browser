# Design Notes & Handoff

> **This documents the original v1.** The app has evolved a lot since (per-card
> approval, extra surfaces, media, settings, stats, etc.). For the current state
> and — importantly — how Alex thinks about the app, read **`docs/HANDOFF.md`**
> first. `docs/TODO.md` is the live backlog.

Context for whoever picks this up next. The original spec is in `docs/SPEC.md`;
user-facing usage is in `README.md`. This file is the "why," the things you
might question when you read the code, and what is and isn't proven.

## Build environment caveat (read first)

v1 was built in a remote container with **no Anki running and AnkiConnect
unreachable** (localhost:8765 refused). Consequences:

- Everything that touches disk or pure logic (inbox, graveyard, undo,
  exemplars, stats, rendering) was tested live and works.
- The AnkiConnect write path (approve, repair, survey, decks) was tested only
  against an in-memory stand-in (`tests/conftest.py::FakeAnki`). It has **never
  run against a real Anki.** The first job with Anki up is to confirm the live
  round-trip and the specific calls flagged under "Known risks" below.

## Status vs. build order

All 8 components are implemented at the "crude working" bar the spec asked for.

| # | Component | State |
|---|-----------|-------|
| 1 | AnkiConnect + render w/ real CSS/LaTeX | code complete, live round-trip UNVERIFIED |
| 2 | Inbox: file format, full-screen, 3 exits, keys | done, verified offline |
| 3 | Modal system + undo + graveyard | done, verified offline |
| 4 | Beeminder push | code complete, never hit the real API |
| 5 | Repair queue | code complete, UNVERIFIED against Anki |
| 6 | Exemplar archive (snapshots) | done, verified offline |
| 7 | Survey grid | code complete, UNVERIFIED against Anki |
| 8 | Stats | done, verified offline |

25 tests pass: `. .venv/bin/activate && python -m pytest -q`.

## Architecture map

```
run.py                  entry point; python run.py -> http://127.0.0.1:5151
backend/
  config.py             defaults + config.json merge; computes data/ paths
  ankiconnect.py        thin client; the ONLY write path to the live deck
  cards.py              CardRenderer: live cards via cardsInfo, provisional via templating
  rendering.py          Anki templating subset (fields, sections, cloze, latex)
  inbox.py              provisional cards as files; filename stem is the id
  graveyard.py          soft-delete store
  exemplars.py          append-only jsonl of frozen snapshots
  actions.py            persisted undo stack (records only)
  stats.py              one event per judgment; derive summaries
  beeminder.py          aggregated per-day datapoint
  app.py                Flask routes + undo interpreter + session
frontend/
  index.html            shell + overlays
  app.js                modal keyboard SPA, iframe card rendering
  style.css             dark, terse
data/                   gitignored runtime state (inbox/ graveyard/ *.jsonl ...)
sample_inbox/           three example cards (Basic, LaTeX, Cloze)
```

## Decisions you might question, and why

**Flask, not FastAPI.** Spec left it my call. Flask = two deps (Flask, requests),
built-in dev server, no build step. FastAPI would add pydantic/uvicorn/starlette
for no benefit at single-user scale. Easy to swap; routes are plain.

**Vanilla JS frontend, no build step.** Per the spec's "lightest thing that
renders cards well." No framework, no bundler. If this grows a lot it may want
one; it doesn't yet.

**Cards render in `<iframe srcdoc sandbox="allow-scripts">`.** Needed to isolate
each note's CSS from the app UI and to run MathJax per card. Alternative
considered: Shadow DOM, but MathJax v3 shadow support is flaky. Cost: the survey
grid is N iframes, each loading MathJax from the CDN. Made that toggleable via
`grid_mathjax` (default on). If the grid feels heavy with many cards, that's the
first knob. The single-card surfaces (inbox, repair) are one iframe at a time,
so no concern there.

**Live deck cards are NOT rendered by our templating engine.** `cardsInfo`
returns fully rendered `question` / `answer` HTML plus the note's `css`, so
repair and survey use Anki's own output (most faithful). `rendering.py` is used
**only** for provisional inbox cards, where no card exists in Anki yet. Don't
"unify" these by routing deck cards through `rendering.py`; that would be
strictly worse. This split is the single most important thing to understand.

**`rendering.py` is a deliberate subset, not a full Anki renderer.** It handles
`{{Field}}`, `{{FrontSide}}`, `{{#Field}}`/`{{^Field}}` sections, `{{cloze:...}}`,
and normalizes LaTeX delimiters (`[$]..[$]` -> `\(..\)`, `[$$]` -> `\[..\]`,
`[latex]..[/latex]` -> `\[..\]`) to MathJax form. It does not implement every
filter or special field. It only has to make a *provisional* card look right
enough to judge. When Anki is open it borrows the real template + CSS anyway, so
the engine is mostly the offline fallback.

**Filename stem is the canonical inbox id, not any internal `id` field.** This
was a corrected bug: the sample files had filenames that differed from their
internal `id`, so delete/edit/approve couldn't find them. Now `data/inbox/foo.json`
is addressed as `foo`; `_normalize` overwrites `card["id"]` with the stem on
load. Rationale: robust to files dropped in by anything (incl. a v2 generator),
matches "plain files on disk." Alternative (scan files matching an internal id)
is O(n) per op and risks orphaning a file on save when filename != id. If you
see `card["id"]` being set to the stem and wonder why, this is it.

**Approve uses `addNote` (singular), spec says `addNotes`.** The inbox is
strictly one card at a time, so singular is the natural call and gives back the
new note id directly (needed for undo). Functionally identical for the flow.
Batch `addNotes` would only matter if you add a bulk-approve, which the
"one at a time" principle argues against anyway.

**Approve sets `allowDuplicate: false`.** A duplicate returns 409 and the card
stays in the inbox with a toast. Conservative default; make it configurable if
it gets annoying.

**Session counts approve / delete / send-back / repair; not exemplar or
inbox-edit.** The target is "how many cards did I deal with." Sending back is
dealing with a card, so it counts here even though it does NOT count toward
Beeminder by default (those are deliberately separate knobs). Marking an
exemplar is a side annotation, not processing, so it doesn't bump the session.
Undo decrements for the four that incremented.

**Beeminder: one datapoint/day, `requestid` keyed to the daystamp.** Idempotent
(repeat pushes update the day's point, never pile up). Default counts
approve/delete/repair, pushes on `session_end`. Send-back off by default (matches
the spec's lean). Queue size is never a metric, only a display stat. All of this
is in `config.beeminder` and easy to change.

**Native flag cleared on repair via `setSpecificValueOfCard(keys=["flags"],
newValues=[0], warning_check=True)`.** See "Known risks" — this is the call I'm
least sure of and could not test.

## Invariants to preserve

- **AnkiConnect is the only write path to the live deck.** No direct
  `collection.anki2` writes, ever. Reads via SQLite only if AnkiConnect truly
  can't (not currently needed).
- **Nothing is hard-deleted by the tool.** Inbox delete moves the file to the
  graveyard. Exemplar/stat/undo "pops" only ever remove the most recent entry
  for an immediate undo.
- **Exemplar snapshots are frozen content, not note references.** Never resolve
  an exemplar back through a live note id at display time; that reintroduces the
  exact bug the spec calls out (a now-good card reading as bad).
- **Undo stack <-> stats alignment.** Both are append-ordered. Every action that
  records a stat (approve, delete, send_back, repair, exemplar) pops that stat on
  undo; `edit_inbox` records no stat and pops none. Because undo is strictly LIFO
  and these stay in lockstep, popping the top action and the top stat is always
  aligned. If you add a new action: either it records a stat AND its undo pops
  one, or neither. Don't half-do it.

## Known risks / verify with Anki up

1. **Flag clearing (`setSpecificValueOfCard`).** Standard AnkiConnect has no
   clean `setFlag`. This is the community workaround and some builds gate it
   behind `warning_check`. It's isolated in `ankiconnect.py::set_flag` and
   wrapped best-effort: if it throws, the repair save still succeeds and the UI
   says "saved (flag not cleared)". **Verify it actually clears the flag.** If
   not, options: check your AnkiConnect version's supported actions, or fall
   back to leaving the flag (and document that).
2. **`cardsInfo` keys.** We rely on `question`, `answer`, `css`, `flags`,
   `note`, `modelName`, `deckName`, `fields` (as `{name: {value, order}}`).
   These match AnkiConnect docs but confirm against your version, especially
   `flags` (plural) and that `question`/`answer` are the rendered HTML.
3. **`addNote` field/model names** must match your real note types exactly
   (e.g. "Basic", "Cloze", field "Front"/"Back"/"Text"). The sample cards assume
   defaults; your collection may differ.
4. **Cloze offline fallback renders ordinal 1 only.** With Anki closed, a
   multi-cloze note shows only the card-1 view in the inbox preview. With Anki
   open the real template is used, so this only affects offline preview.
5. **`[latex]..[/latex]`** is treated as raw MathJax. Real Anki renders legacy
   `[latex]` to images server-side; those notes won't match exactly. Modern
   `\(..\)` / `\[..\]` MathJax notes are fine.
6. **MathJax from CDN.** Default `mathjax_url` is jsDelivr. If the machine is
   offline or behind a strict network, math won't typeset. Vendoring MathJax
   locally is the fix if that matters.

## Open questions (spec) and where they landed

| Question | Current default | How to change |
|----------|-----------------|---------------|
| Grid backs vs fronts | backs | `grid_show_backs` |
| Repair one-keys exemplar? | yes, `g` works in repair (and survey) | n/a |
| Send-back requires comment? | no | `send_back_requires_comment` |
| Beeminder counts what? | approve/delete/repair | `beeminder.count.*` |
| Beeminder push when? | session_end | `beeminder.push_on` |
| v2 generation surface | out of scope; inbox file format is the seam | see below |

## v2 seam (don't break it)

The inbox file format is the clean target for AI generation. A generator should
be able to write `data/inbox/<name>.json` with `fields` + `note_type` +
`comment_history` and have the tool pick it up with no other coordination.
Send-back appends to `comment_history` so the generator sees the whole
conversation. Keep that format stable; if you must change it, version it.

## Suggested next steps (with Anki running)

1. Smoke test connection: `GET /api/status` should show `anki: true`.
2. Inbox: copy `sample_inbox/*.json` into `data/inbox/`, approve one, confirm it
   lands in the deck; undo and confirm the note is deleted and the file restored.
3. Repair: flag a couple of real cards red/orange, open surface 2, edit one,
   save, confirm fields updated AND flag cleared (this is risk #1).
4. Survey: filter by a real deck, confirm rendering matches the real card.
5. Beeminder: set real creds in `config.json`, run a session, stop it, confirm a
   single datapoint appears.
6. Then iterate on feel: keybindings, grid mathjax perf, whether send-back
   should require a comment, target defaults.
