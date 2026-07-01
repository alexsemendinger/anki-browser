# TODO / backlog

Running list of things noted but not (all) done. Roughly priority-ordered within
each area.

## Queue (inbox)
- [x] **Filter the queue by deck** — done 2026-07-01. Deck dropdown in the inbox
  surface; `/api/inbox?deck=` filters; counts shown per deck.
- [ ] **Survey the cards currently in the queue** — a grid once-over of a freshly
  created batch to spot glaring issues before reviewing one-by-one. *(moderate-high
  priority; above better browser search)*

## Exemplars
- [ ] **Prompt for a reason/comment when marking an exemplar.** Backend already
  stores a `comment` field (`exemplars.add(..., comment=...)`); the UI just sends
  `comment: ""`. So this is a small frontend add.
- [ ] **A view to see / edit / delete the exemplar list** (none exists yet).
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
