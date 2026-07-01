# TODO / backlog

Running list of things noted but not (all) done. Roughly priority-ordered within
each area.

## Queue (inbox)
- [x] **Filter the queue by deck** — done 2026-07-01. Deck dropdown in the inbox
  surface; `/api/inbox?deck=` filters; counts shown per deck.
- [ ] **Survey the cards currently in the queue** — a grid once-over of a freshly
  created batch to spot glaring issues before reviewing one-by-one. *(moderate-high
  priority; above better browser search)*

## Stats
- [x] **Calendar heatmap** (GitHub-style, trailing year) + **reviews-per-day
  stacked bar chart** (30 days, by action type) — done 2026-07-01, from the
  existing `events.jsonl` (`stats.summary().daily`). No new data needed.
- [ ] **Cards added per day.** Needs a new "added" event logged when a card
  enters the inbox (e.g. from `add_card.py`); no historical data, forward-only.
- [ ] **Queue size per day** (to see if the backlog is growing/shrinking). Needs
  a daily snapshot of inbox count; no historical data, forward-only.
- [x] Time-range toggles (1mo / 3mo / 1yr), cumulative line, and Anki-style
  hover tooltips on both charts — done 2026-07-01.
- [ ] Year navigation on the heatmap — polish, later.

## Exemplars
- [x] **Comment / "why" when marking an exemplar** — done 2026-07-01. Pressing
  `g` then `g`/`b` reveals a "why" box; Ctrl+Enter saves it into the exemplar.
- [x] **Own surface + see / delete / render-as-card** — done 2026-07-01.
  Exemplars are their own tab (`6`), listed compactly (verdict · front · deck ·
  delete); clicking a row opens it rendered **as a real card** (flippable), with
  media inlined. Same click-to-render added to the graveyard.
- [ ] **Search** over exemplars (will matter once there are many).
- [ ] **Edit** an exemplar in place (vs. delete + re-add).
- [ ] Consider folding a send-back comment into an exemplar — several send-back
  comments were really "this is a good/bad example because…".

## Browser / survey
- [ ] **Real search + more filters in survey.** Currently only deck / tag / added /
  lapses / due, no free-text search; the survey isn't very useful as-is.
  *(lower priority)*

## Card-making agent docs
- [ ] The `~/Desktop/claudes/anki/CLAUDE.md` (where card-making Claudes are
  launched) does **not** mention the send-back / `comment_history` revision loop,
  so an agent there won't know to read the user's comments and revise cards.
  Decide whether to wire this up (add a "revising sent-back cards" section that
  points at `data/inbox/<id>.json` → `comment_history`).
