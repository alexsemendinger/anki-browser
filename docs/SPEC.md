# Anki Deck Workbench — Build Spec v1

> This is the original build spec, reproduced verbatim. It is the source of
> truth for intent. Where the implementation made a choice the spec left open,
> see `docs/DESIGN_NOTES.md`.

## Intent (read this first)

Single-user local tool for one person curating their own Anki cards. The native Anki browser is clunky and creates friction; this replaces it for *curation* work, not studying.

The goal is to be able to generate cards with AI while maintaining high standards. I want AI-generated cards in my deck, I just want a process rigorous enough that only good ones make it in and weak ones get caught, repaired, or rejected first. The same rigor applies to cards I write myself and to existing cards already in the deck.

The core problem is rigor: the app can't supply it, that comes from me reading each card. What the app does is make per-card judgment the only available motion, and make it fast, keyboard-driven, and pleasant enough to get into flow. The UI's job is to get out of the way. Cards render with their real CSS and LaTeX so they look like my actual cards.

Principles: common actions are single keystrokes; I never repeat myself; nothing is ever unrecoverable; the design enforces looking at each card one at a time.

## UI copy standing order (hard constraint)

Read this before writing any user-visible text.

- No em dashes anywhere in user-visible copy. None.
- Almost nothing visible should be a full sentence, or even a full clause, except possibly a single "how to use" section. Labels and counts, not prose.
- Do not re-explain things. State a thing once. When I'm not looking at the "how to use" section, the app does not narrate itself, restate what a button does, or describe what just happened in words when a state change shows it.
- Default to terse. If you're unsure whether a piece of copy is needed, it isn't.

## Terminology (strict)

- **Flag** = Anki's native colored flags only (red, orange, etc.), set during phone review. Never use "flag" for anything else.
- **Verdict** = this tool's judgment on a card (approve / send-back / delete / mark-as-exemplar). Always "verdict," never "flag."

## Architecture

- Local web app. Python backend (Flask or FastAPI, your call). Single-page frontend, keyboard-first.
- **AnkiConnect is the only write path to the live deck.** Local HTTP API to the running Anki app (`findNotes`, `notesInfo`, `updateNoteFields`, `addNotes`, tag/flag operations). Anki must be open for live operations. Do not write to `collection.anki2` directly. Direct SQLite reads are acceptable only for something AnkiConnect genuinely can't do, never for writes.
- Provisional (not-yet-approved) cards live as plain files on disk, never touching Anki until approved.

## Storage / data model

- **Inbox** — provisional cards as plain files (one card = fields + card type + a `comment_history` array). Many will be AI-generated. This tool does not generate them in v1, it consumes whatever lands in the inbox directory.
- **Graveyard** — deleted cards move here, never hard-deleted. Makes undo trivial.
- **Exemplar archive** — append-only. Marking a card good or bad stores a **frozen snapshot of its content at that moment** (fields, rendered form, date, verdict, comment), not a reference to the note ID. The live card may later be fixed, mangled, or deleted; the archive entry stays true. Re-judging the same note later in a new state creates a new snapshot; both coexisting is intended (lets me see if my opinion changed). Must never produce the bug where a now-good card reads as bad because it once was.
- **Comments** on a sent-back card accumulate in that card's `comment_history` so a downstream regenerating agent sees the full conversation, not just the latest state.

## The three surfaces

**1. Inbox (Superhuman-style) — primary surface.**
Provisional cards, one at a time, full screen. The count drains to zero or it doesn't, no "deal with later." Exits:
- **approve** → pushed into the deck via `addNotes`
- **send back with comment** → stays in inbox, comment appended to history
- **delete** → moved to graveyard

**2. Repair queue.**
Existing deck cards carrying native Anki flags (red and orange prioritized; red = definitely fix, orange = probably fix), pulled via AnkiConnect. Full render, edited inline, written back with `updateNoteFields`, native flag cleared on save. One at a time.

**3. Survey grid — secondary, orienting only.**
Responsive grid (~4x5) of rendered cards, infinite scroll, filter by deck/tag/creation-date/due/lapse. A flip-all toggle; try defaulting to backs (usually where the info is), confirm in use. For scanning and filtering, not the main workspace.

## Sessions and the optional target

- A **session** is one sitting: from when I start working a queue until I stop or hit a target.
- Optionally I set a **target count** at the start (e.g. 5, 10). The app tracks progress against it and tells me when I've hit it, so I'm not counting in my head. This is off by default and configurable. It's a "tell me when I'm done" convenience, not an enforced cap.
- Hitting the target doesn't lock anything; I can keep going.

## Modal keyboard interface (vim-style)

Modal because single-keystroke destructive actions and free-text comment fields are otherwise incompatible.

- **Normal mode**: `j`/`k` (or arrows) navigate, `space` flip, `a` approve, `d` delete, `c` comment-and-send-back, `e` edit card, `g` mark as exemplar (then choose good/bad), `u` undo.
- **Insert mode**: entered by `c` or `e`; `Esc` returns to normal.
- Quiet mode indicator in a corner.
- **Undo** (`u`) covers at least the current session, backed by graveyard + an action stack. Soft deletes keep it safe.

(Keybindings above are a starting point, not load-bearing; expect to adjust them in use.)

## Beeminder integration (in v1)

The app pushes data to Beeminder. This matters because the data is auto-pushed by the tool, not self-entered, which removes the temptation to fudge it.

What's settled: the integration exists in v1; it's a small amount of code against an API I already know; it pushes an aggregated datapoint rather than one per card (don't hammer their servers or overflow the one-per-day convention).

What's **not** settled, leave configurable or easy to change, don't hardcode an opinion:
- What counts as the unit being pushed (e.g. whether "send back with comment" counts toward the number, or only approve/delete/repair). I lean no on send-back but won't know until I use it.
- The metric itself (per-day processed count vs. something else) and any target number.
- When exactly the push fires.

One thing I do want avoided: don't make queue size the committed metric, since it jumps when I generate cards and would punish me for creating work. Queue size can be a display statistic.

## Stats (lightweight)

Cheap because everything flows through the tool: lifetime processed count, approval rate over time, deck inflow vs. repair rate, judgments rendered. Small numbers on a screen, no prose.

## Explicitly out of scope for v1

- Card generation. v1's inbox only consumes generated files. AI card creation integrated into the app itself is a wanted **v2** feature (possibly an embedded terminal running Claude Code with custom instructions, possibly something else, open question). Build v1 so this can bolt on later: the inbox file format and `comment_history` should be a clean target for an agent to write into and read back from.
- Analytics beyond the stats above, re-entry/backlog triage, semantic search, near-duplicate detection.

The inbox + repair queue + AnkiConnect write path is the core; the rest bolts on later.

## Build order

1. AnkiConnect connection + render one card with real CSS/LaTeX. Prove the write path with a full round-trip (read a note, edit a field, write it back).
2. Inbox: file format, one-card full-screen view, the three exits, normal-mode keys.
3. Modal system + undo + graveyard.
4. Beeminder push.
5. Repair queue.
6. Exemplar archive (snapshots).
7. Survey grid.
8. Stats.

Get the crudest working version of 1–4 running in one session before any polish.

## Open questions, resolve by experiment

- Grid-of-backs vs. grid-of-fronts as survey default.
- Whether the repair queue also one-keys a card into the exemplar archive.
- Whether send-back should require a non-empty comment.
- Beeminder unit/metric/target and what counts as processed (see above).
- v2 AI generation: how cards get generated and how that surface integrates (embedded terminal vs. other).

## Environment

I'll tell Claude Code my OS, where Anki lives, and my Python version at the start of the build session. AnkiConnect needs Anki running and listening on its default port. Frontend framework isn't pinned; for a single-user local tool the lightest thing that renders cards well beats a heavy build step, but make your case if you disagree.
