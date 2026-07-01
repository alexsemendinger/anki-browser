# Handoff / working context

For the next Claude picking this up. `DESIGN_NOTES.md` is the original v1
architecture; `SPEC.md` is the original spec; `TODO.md` is the live backlog;
`README.md` is usage. **This file is the "who, why, and how Alex thinks"** —
read it before doing design work, because a lot of the value here is matching
Alex's taste, not just shipping features.

## Who Alex is / how to work with him

- **He uses the app for real and reports friction as he hits it.** "I'll update
  as I notice flaws." Expect iterative, hands-on feedback grounded in actual use,
  not abstract specs. Build the thing, let him live with it, adjust.
- **"Don't have copy" rule.** He dislikes explanatory prose / microcopy in the
  UI. Keep text terse and functional; labels and keybinding references are fine,
  sentences that narrate are not. He *will* call out copy that creeps in. (Also
  saved to memory.)
- **Effortless is a hard requirement, not a nice-to-have.** He hates venv/startup
  friction — "if I have to do some nonsense like `venv activate…` every time I'm
  going to lose my mind." Hence `./start.sh` (self-bootstrapping, opens the
  browser, no activation). Apply the same instinct elsewhere: remove ritual.
- **Do the standard, obvious thing.** He got visibly frustrated when the app
  showed stripped text instead of just rendering a card the normal way: "there's
  a standard way to display a card and you keep doing anything except letting me
  do that." When there's a conventional UX, use it.
- **Don't overcomplicate explanations.** He pushed back hard when a simple thing
  (a settings form that writes a config file) got wrapped in security-sounding
  caveats. Explain plainly; if you're hedging a non-problem, stop.
- **Commit and push regularly.** He says "commit" / "push" and expects it. Work
  is committed in logical chunks with descriptive messages; tests kept green.
- **Verify against real Anki when you can.** He keeps Anki open and expects the
  live round-trip to be checked, not assumed.

## What the app is *for* (the core philosophy)

The workbench is a **review-and-approval gate between AI-generated cards and
Anki.** The through-line, in Alex's words and choices:

- **AI generates cards *outside* Anki; nothing enters Anki until Alex has
  reviewed it.** "For now I think I prefer AIs creating cards completely outside
  of Anki and not importing them at all until I've reviewed them." The inbox is
  that holding pen.
- **The inbox is plain JSON files on disk** (`data/inbox/<id>.json`), which is
  the deliberate, stable **seam for AI generation** — a generator just writes
  files. Keep the format stable and additive.
- **Per-card approval is real and non-negotiable.** A note that generates several
  cards (cloze ordinals, or templates like Basic-and-reversed) is only sent to
  Anki once *every* one of its cards is approved. On template cards specifically:
  "template cards are a very important case, support for them isn't optional."
- **Send-back = a revision request to the AI.** Commenting on a card appends to
  its `comment_history`; the card stays in the queue for the generator to read
  and rewrite. Important open gap: the card-making agent's instructions don't yet
  tell it this loop exists, so comments are currently write-only. (See TODO.)
- **Exemplars are frozen good/bad reference snapshots with reasons** — content
  captured at a moment, *not* a live note reference (so a later-fixed card still
  reads as it was judged). The intent is that an AI could later read them.
- **Nothing is hard-deleted; everything is inspectable.** Deletes go to the
  graveyard (restorable); undo is LIFO and persisted. Alex repeatedly wanted to
  *see* things — the graveyard, exemplars, comments — rendered as real cards.

## Specific things Alex has said he's looking for / is still deciding

- **The monolithic one-by-one queue.** "There's a virtue to this but as I'm
  using it, I'm realizing how limiting it is." → added a deck filter; a
  *survey-the-queue* view (grid once-over of a fresh batch) is high on the TODO.
- **Send-back behavior is unsettled.** He's "still torn." He first liked that
  comments pile up and "force you to do more than nothing" when you keep skipping
  a card; then found re-seeing a just-commented card annoying. Current compromise:
  sent-back cards **sink to the bottom** of the queue (don't leave). The
  "leave until an AI revises it" option is a small change away if he wants it.
- **Stats should feel like Anki's.** He wants the motivating ones — the
  GitHub-style calendar heatmap and reviews-per-day. Built. Cards-added-per-day
  and queue-size-over-time need new forward-only logging (TODO).
- **Billing (set aside).** He'd prefer AI generation to run on his Anthropic
  account (Max / Claude Code) rather than separate API billing. Flagged as tricky;
  not being pursued yet.
- **"WORKBENCH deck" idea (set aside).** He mused about treating a real Anki deck
  as entirely-provisional cards, as an alternative/complement to the file-based
  inbox. Possibly better for AIs in some ways. Not being built; "we'll see."

## How card generation actually happens (the two-repo split)

- **Card-making Claudes are launched from `~/Desktop/claudes/anki/`** (outside
  this repo). That directory has its own `CLAUDE.md` (points at this workbench's
  `add-card` by absolute path) plus Alex's card-quality style guides
  (`anki_style_guide_v2.md`, `anki_math_style_guide.md`). A card Claude reads the
  style guide for *quality* and uses `add-card` for *mechanics*.
- **This repo (`anki-browser`) is for working on the app itself.** Its root
  `CLAUDE.md` is a dev guide (invariants + run/test), deliberately *not* about
  card-making.
- **`./add-card`** is the validated entry point: `--schema` prints note
  types/fields/decks (live from Anki); `--json -` adds a card/batch from stdin
  and validates note type + field names + deck against the running Anki before
  writing. See README "Adding cards".

## Where things are now (architecture at a glance)

Flask + vanilla JS, no build step; `./start.sh` to run,
`.venv/bin/python -m pytest` to test (113 tests, hermetic — no real Anki needed).

Surfaces: **1 inbox** (deck-filterable, per-card approval gating, send-back sinks
to bottom), **2 repair** (flagged live cards; edit clears the native flag via
`setSpecificValueOfCard`), **3 survey** (whole-deck grid, lazy-rendered),
**4 stats** (heatmap + reviews chart + tiles), **5 graveyard** (restore /
click-to-render), **6 exemplars** (comments, delete, click-to-render). Settings
(Beeminder) behind ⚙ / `,`.

Cross-cutting since v1:
- Card iframes are sandboxed and **forward keystrokes to the app via
  postMessage**, so shortcuts work even when a card is focused/clicked.
- **Images render** by inlining `<img>` sources as data URIs via AnkiConnect
  `retrieveMediaFile` (cached) — no file syncing. Applies to inbox/repair/survey
  and to exemplar/graveyard previews.
- **Settings** persist to `config.json` (live cfg updated in place too); the
  Beeminder auth token is write-only from the frontend.
- **UI is a warm light "paper & ink" theme** (2026-07-01 redesign): white cards
  sit on warm paper instead of glaring against dark chrome; serif numerals on
  stats tiles; a bottom key/status bar shows the current surface's bindings
  (edit `KEYHINTS` in `app.js`). Stats are inline SVG charts with Anki-style
  hover tooltips and a 1mo/3mo/1yr range toggle.
- **Deleting an exemplar appends it to `data/exemplars.jsonl.trash`** — the
  delete button is not undoable via `u`, so the trash file is the recovery
  path (keeps the nothing-hard-deleted invariant true).

Invariants that must not break (also in the dev `CLAUDE.md`): AnkiConnect is the
only write path to the live deck; nothing is hard-deleted; the undo stack ↔ stats
are LIFO lockstep; live deck cards are rendered by Anki (`cardsInfo`), provisional
inbox cards by `rendering.py`; the inbox filename stem is the canonical id; the
inbox JSON format is the generation seam (additive changes only).

Known-unproven: the **Beeminder push has never hit the real API** (mock-tested
only). The settings panel's "push now" button is how to verify it.

## Suggested first moves for a new Claude

1. `./start.sh`, open the app, click around all six surfaces to get the feel.
2. Read `TODO.md` — the highest-value next item is **survey-the-queue**, and the
   most important loose thread is **wiring the send-back revision loop into the
   card-making `CLAUDE.md`** (so comments stop being write-only).
3. Match Alex's taste (above) before adding anything: terse, standard, effortless.
