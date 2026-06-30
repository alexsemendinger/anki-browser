"use strict";

const state = {
  surface: "inbox",
  mode: "normal",
  config: null,
  inbox: { cards: [], idx: 0, ord: 0, flipped: false },
  repair: { cards: [], idx: 0, flipped: false },
  survey: { cards: [], total: 0, offset: 0, limit: 200, sel: 0, flipAll: false, loading: false },
  exemplarCtx: null,
  targetAnnounced: false,
};

// --- api ------------------------------------------------------------------
const api = {
  get: (u) => fetch(u).then((r) => r.json()),
  send: (u, m, body) =>
    fetch(u, {
      method: m,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    }).then(async (r) => ({ ok: r.ok, status: r.status, data: await r.json() })),
};

const $ = (id) => document.getElementById(id);

function toast(msg, kind) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast" + (kind ? " " + kind : "");
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.hidden = true), 1800);
}

// --- card rendering into an isolated iframe -------------------------------
function cardDoc(html, css, withMath) {
  const mj =
    "window.MathJax={tex:{inlineMath:[['\\\\(','\\\\)']],displayMath:[['\\\\[','\\\\]']]},svg:{fontCache:'global'}};";
  const head = withMath
    ? `<script>${mj}</script><script src="${state.config.mathjax_url}"></script>`
    : "";
  // A sandboxed iframe traps focus, so a click on the card would otherwise
  // swallow keystrokes and the shortcuts stop working. Forward keydowns to the
  // app via postMessage (and stop the card from scrolling on the keys we use).
  const keyfwd =
    "<script>document.addEventListener('keydown',function(e){" +
    "parent.postMessage({source:'adw-card',type:'key',key:e.key,ctrlKey:e.ctrlKey," +
    "metaKey:e.metaKey,shiftKey:e.shiftKey,altKey:e.altKey},'*');" +
    "if(e.key===' '||e.key.indexOf('Arrow')===0){e.preventDefault();}});<\/script>";
  return `<!doctype html><html><head><meta charset=utf-8><style>html,body{margin:0;padding:14px}${css || ""}</style>${head}</head><body><div class="card">${html || ""}</div>${keyfwd}</body></html>`;
}

function frameInto(container, html, css, withMath) {
  const f = document.createElement("iframe");
  f.setAttribute("sandbox", "allow-scripts");
  f.srcdoc = cardDoc(html, css, withMath);
  container.replaceChildren(f);
}

// --- chrome ---------------------------------------------------------------
function setMode(mode) {
  state.mode = mode;
  const el = $("mode");
  el.textContent = mode.toUpperCase();
  el.classList.toggle("insert", mode === "insert");
}

function setSurface(name) {
  state.surface = name;
  document.querySelectorAll(".surface").forEach((s) => (s.hidden = true));
  $("surface-" + name).hidden = false;
  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.surface === name)
  );
  if (name === "inbox") loadInbox();
  if (name === "repair") loadRepair();
  if (name === "survey") loadSurvey(true);
  if (name === "stats") loadStats();
}

function updateBadges() {
  $("inbox-badge").textContent = state.inbox.cards.length || "";
  $("repair-badge").textContent = state.repair.cards.length || "";
}

async function refreshSession() {
  const s = await api.get("/api/session");
  const el = $("session");
  if (!s.active) {
    el.textContent = "";
  } else {
    el.textContent = s.target ? `${s.count}/${s.target}` : `${s.count}`;
    if (s.target_hit && !state.targetAnnounced) {
      state.targetAnnounced = true;
      toast("target hit");
    }
    if (!s.target_hit) state.targetAnnounced = false;
  }
}

async function pollStatus() {
  try {
    const s = await api.get("/api/status");
    $("anki-dot").className = "dot " + (s.anki ? "on" : "off");
    $("anki-dot").title = s.anki ? "Anki connected" : "Anki not reachable";
  } catch {
    $("anki-dot").className = "dot off";
  }
}

// --- inbox ----------------------------------------------------------------
async function loadInbox() {
  const data = await api.get("/api/inbox");
  state.inbox.cards = data.cards;
  if (state.inbox.idx >= data.cards.length) state.inbox.idx = Math.max(0, data.cards.length - 1);
  state.inbox.ord = 0;
  state.inbox.flipped = false;
  renderInbox();
  updateBadges();
}

function renderInbox() {
  const { cards, idx } = state.inbox;
  const single = document.querySelector("#surface-inbox .single");
  if (!cards.length) {
    single.style.display = "none";
    $("inbox-empty").hidden = false;
    return;
  }
  single.style.display = "flex";
  $("inbox-empty").hidden = true;
  const item = cards[idx];
  const c = item.card;
  const r = item.rendered;
  // a note may generate several cards (cloze c1, c2, ...); page through them
  const subcards = r.cards && r.cards.length ? r.cards : [{ ordinal: 1, question: r.question, answer: r.answer }];
  if (state.inbox.ord >= subcards.length) state.inbox.ord = subcards.length - 1;
  if (state.inbox.ord < 0) state.inbox.ord = 0;
  const sub = subcards[state.inbox.ord];
  const approvedSet = new Set(item.card.approved_cards || []);
  const pips =
    subcards.length > 1
      ? '<span class="pips">' +
        subcards
          .map(
            (sc, i) =>
              `<span class="pip${approvedSet.has(sc.ordinal) ? " ok" : ""}${i === state.inbox.ord ? " cur" : ""}"></span>`
          )
          .join("") +
        "</span>"
      : "";
  $("inbox-meta").innerHTML =
    `<span>${idx + 1} / ${cards.length}</span>` +
    `<span>${c.note_type}</span><span>${c.deck}</span>` +
    (subcards.length > 1
      ? `<span>card ${state.inbox.ord + 1} / ${subcards.length}</span>${pips}` +
        (sub.name ? `<span class="muted">${sub.name}</span>` : "")
      : "") +
    `<span class="muted">${c.source}</span>` +
    (c.tags && c.tags.length ? `<span class="muted">${c.tags.join(" ")}</span>` : "") +
    `<span class="muted">${state.inbox.flipped ? "back" : "front"}</span>`;
  frameInto($("inbox-frame"), state.inbox.flipped ? sub.answer : sub.question, r.css, true);
  const ch = c.comment_history || [];
  $("inbox-comments").innerHTML = ch
    .map(
      (e) =>
        `<div class="comment"><div class="when">${(e.date || "").slice(0, 16).replace("T", " ")} · ${e.author || ""}</div>${escapeHtml(e.text)}</div>`
    )
    .join("");
}

async function inboxAction(path, okMsg, kind) {
  const item = state.inbox.cards[state.inbox.idx];
  if (!item) return;
  const res = await api.send(`/api/inbox/${item.card.id}/${path}`, "POST", {});
  if (!res.ok) {
    toast(res.data.error || "failed");
    return;
  }
  await loadInbox();
  await refreshSession();
  if (okMsg) toast(okMsg, kind);
}

// Approve the CURRENT card. The note is only sent to Anki once every card it
// generates is approved; until then this just marks the card and moves on.
async function approveCard() {
  const item = state.inbox.cards[state.inbox.idx];
  if (!item) return;
  const r = item.rendered;
  const subcards = r.cards && r.cards.length ? r.cards : [{ ordinal: 1 }];
  const sub = subcards[state.inbox.ord] || subcards[0];
  const res = await api.send(`/api/inbox/${item.card.id}/approve`, "POST", { ordinal: sub.ordinal });
  if (!res.ok) {
    toast(res.data.error || "failed");
    return;
  }
  if (res.data.committed) {
    toast("approved → deck", "ok");
    await loadInbox();
    await refreshSession();
    return;
  }
  // partial: persist the approval and jump to the next still-pending card
  item.card.approved_cards = res.data.approved_cards;
  const approved = new Set(res.data.approved_cards);
  for (let step = 1; step <= subcards.length; step++) {
    const i = (state.inbox.ord + step) % subcards.length;
    if (!approved.has(subcards[i].ordinal)) { state.inbox.ord = i; break; }
  }
  state.inbox.flipped = false;
  renderInbox();
  toast("card approved", "ok");
}

// --- repair ---------------------------------------------------------------
async function loadRepair() {
  const data = await api.get("/api/repair");
  if (data.error) {
    state.repair.cards = [];
    $("repair-empty").textContent = "anki not reachable";
    $("repair-empty").hidden = false;
    document.querySelector("#surface-repair .single").style.display = "none";
    updateBadges();
    return;
  }
  state.repair.cards = data.cards;
  if (state.repair.idx >= data.cards.length) state.repair.idx = Math.max(0, data.cards.length - 1);
  state.repair.flipped = false;
  renderRepair();
  updateBadges();
}

function flagName(f) {
  return f === 1 ? "red" : f === 2 ? "orange" : "flag " + f;
}

function renderRepair() {
  const { cards, idx } = state.repair;
  const single = document.querySelector("#surface-repair .single");
  if (!cards.length) {
    single.style.display = "none";
    $("repair-empty").textContent = "no flagged cards";
    $("repair-empty").hidden = false;
    return;
  }
  single.style.display = "flex";
  $("repair-empty").hidden = true;
  const c = cards[idx];
  const pill = c.flag === 1 ? "flag-red" : c.flag === 2 ? "flag-orange" : "";
  $("repair-meta").innerHTML =
    `<span>${idx + 1} / ${cards.length}</span>` +
    `<span class="flagpill ${pill}">${flagName(c.flag)}</span>` +
    `<span>${c.model}</span><span>${c.deck}</span>` +
    `<span class="muted">${state.repair.flipped ? "back" : "front"}</span>`;
  frameInto($("repair-frame"), state.repair.flipped ? c.answer : c.question, c.css, true);
}

// --- survey ---------------------------------------------------------------
async function loadDecks() {
  const data = await api.get("/api/decks");
  const sel = $("f-deck");
  sel.innerHTML = '<option value="">deck</option>' + data.decks.map((d) => `<option>${d}</option>`).join("");
}

function hasSurveyScope() {
  return !!(
    $("f-deck").value || $("f-tag").value || $("f-added").value ||
    $("f-lapses").value || $("f-due").checked
  );
}

function surveyQuery() {
  const p = new URLSearchParams();
  if ($("f-deck").value) p.set("deck", $("f-deck").value);
  if ($("f-tag").value) p.set("tag", $("f-tag").value);
  if ($("f-added").value) p.set("added", $("f-added").value);
  if ($("f-lapses").value) p.set("lapses", $("f-lapses").value);
  if ($("f-due").checked) p.set("due", "1");
  p.set("offset", state.survey.offset);
  p.set("limit", state.survey.limit);
  return p.toString();
}

// Load the WHOLE selected scope (a deck can be hundreds of cards), one page at
// a time. Cards are placed immediately as fixed-size placeholders and their
// iframe is built lazily when scrolled near, so a big deck doesn't freeze.
async function loadSurvey(reset) {
  if (state.survey.loading) return;
  state.survey.loading = true;
  if (reset) {
    state.survey.offset = 0;
    state.survey.cards = [];
    state.survey.sel = 0;
    state.survey.flipAll = !!state.config.grid_show_backs;
    $("grid").innerHTML = "";
    ensureGridObserver();
  }
  // avoid pulling the entire collection; scan is per-deck/filter
  if (!hasSurveyScope()) {
    $("survey-count").textContent = "select a deck";
    state.survey.loading = false;
    return;
  }
  while (true) {
    const data = await api.get("/api/survey?" + surveyQuery());
    if (data.error) {
      $("survey-count").textContent = "anki not reachable";
      break;
    }
    state.survey.total = data.total;
    const start = state.survey.cards.length;
    state.survey.cards = state.survey.cards.concat(data.cards);
    renderGridAppend(data.cards, start);
    $("survey-count").textContent = `${state.survey.cards.length} / ${data.total}`;
    if (!data.cards.length || state.survey.cards.length >= data.total) break;
    state.survey.offset += state.survey.limit;
  }
  state.survey.loading = false;
}

let gridObserver = null;
function ensureGridObserver() {
  if (gridObserver) gridObserver.disconnect();
  gridObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((en) => {
        if (en.isIntersecting) {
          renderGridCard(en.target);
          gridObserver.unobserve(en.target);
        }
      });
    },
    { root: $("grid"), rootMargin: "400px" }
  );
}

function renderGridCard(div) {
  if (div.dataset.rendered) return;
  const c = state.survey.cards[+div.dataset.index];
  if (!c) return;
  const back = c._flipped == null ? state.survey.flipAll : c._flipped;
  const f = document.createElement("iframe");
  f.setAttribute("sandbox", "allow-scripts");
  f.srcdoc = cardDoc(back ? c.answer : c.question, c.css, state.config.grid_mathjax);
  div.replaceChildren(f);
  div.dataset.rendered = "1";
}

function renderGridAppend(cards, start) {
  const grid = $("grid");
  cards.forEach((c, j) => {
    const div = document.createElement("div");
    div.className = "gridcard";
    div.dataset.index = start + j;
    grid.appendChild(div);
    gridObserver.observe(div);
  });
  markSelection();
}

function markSelection() {
  const nodes = $("grid").querySelectorAll(".gridcard");
  nodes.forEach((n, i) => n.classList.toggle("sel", i === state.survey.sel));
  const cur = nodes[state.survey.sel];
  if (cur) cur.scrollIntoView({ block: "nearest" });
}

// --- stats ----------------------------------------------------------------
async function loadStats() {
  const s = await api.get("/api/stats");
  const tiles = [
    ["processed", s.processed_lifetime],
    ["approval rate", s.approval_rate == null ? "—" : Math.round(s.approval_rate * 100) + "%"],
    ["judgments", s.judgments],
    ["approved", (s.totals.approve || 0)],
    ["repaired", s.inflow_vs_repair.repairs],
    ["deleted", (s.totals.delete || 0)],
    ["sent back", (s.totals.send_back || 0)],
    ["inbox", s.inbox_count],
    ["graveyard", s.graveyard_count],
    ["undo depth", s.undo_depth],
  ];
  $("stats-grid").innerHTML = tiles
    .map(([k, n]) => `<div class="stat"><div class="n">${n}</div><div class="k">${k}</div></div>`)
    .join("");
  const ex = await api.get("/api/exemplars");
  $("exemplar-list").innerHTML = ex.exemplars
    .map((e) => {
      const first = Object.values(e.fields || {})[0] || "";
      const snip = escapeHtml(stripTags(first)).slice(0, 90);
      return `<div class="ex"><span class="v ${e.verdict}">${e.verdict}</span><span class="muted">${(e.date || "").slice(0, 10)}</span><span>${snip}</span></div>`;
    })
    .join("");
}

// --- exemplar -------------------------------------------------------------
function startExemplar() {
  let ctx = null;
  if (state.surface === "inbox") {
    const item = state.inbox.cards[state.inbox.idx];
    if (!item) return;
    ctx = {
      note_type: item.card.note_type,
      deck: item.card.deck,
      fields: item.card.fields,
      rendered: { question: item.rendered.question, answer: item.rendered.answer, css: item.rendered.css },
    };
  } else if (state.surface === "repair") {
    const c = state.repair.cards[state.repair.idx];
    if (!c) return;
    ctx = { note_type: c.model, deck: c.deck, note_id: c.note_id, fields: c.fields, rendered: { question: c.question, answer: c.answer, css: c.css } };
  } else if (state.surface === "survey") {
    const c = state.survey.cards[state.survey.sel];
    if (!c) return;
    ctx = { note_type: c.model, deck: c.deck, note_id: c.note_id, fields: c.fields, rendered: { question: c.question, answer: c.answer, css: c.css } };
  }
  if (!ctx) return;
  state.exemplarCtx = ctx;
  openOverlay("exemplar-prompt");
}

async function commitExemplar(verdict) {
  closeOverlays();
  const ctx = state.exemplarCtx;
  state.exemplarCtx = null;
  if (!ctx) return;
  const res = await api.send("/api/exemplar", "POST", { ...ctx, verdict, comment: "" });
  toast(res.ok ? "exemplar " + verdict : "failed");
}

// --- undo -----------------------------------------------------------------
async function doUndo() {
  const res = await api.send("/api/undo", "POST", {});
  if (!res.ok) {
    toast(res.data.error || "undo failed");
    return;
  }
  if (!res.data.undone) {
    toast("nothing to undo");
    return;
  }
  toast("undo: " + res.data.undone, "info");
  if (state.surface === "inbox") await loadInbox();
  if (state.surface === "repair") await loadRepair();
  if (state.surface === "stats") await loadStats();
  await refreshSession();
}

// --- overlays -------------------------------------------------------------
function anyOverlayOpen() {
  return [...document.querySelectorAll(".overlay")].some((o) => !o.hidden);
}
function openOverlay(id) {
  $(id).hidden = false;
  if (id === "editor" || id === "commenter" || id === "session-prompt") setMode("insert");
}
function closeOverlays() {
  document.querySelectorAll(".overlay").forEach((o) => (o.hidden = true));
  setMode("normal");
}

function openEditor() {
  let fields, order, title, onSave;
  if (state.surface === "inbox") {
    const item = state.inbox.cards[state.inbox.idx];
    if (!item) return;
    fields = item.card.fields;
    order = item.rendered.field_order;
    title = "edit (inbox)";
    onSave = async (vals) => {
      const res = await api.send(`/api/inbox/${item.card.id}`, "PUT", { fields: vals });
      if (res.ok) { await loadInbox(); toast("saved"); }
    };
  } else if (state.surface === "repair") {
    const c = state.repair.cards[state.repair.idx];
    if (!c) return;
    fields = c.fields;
    order = c.field_order;
    title = "edit (repair) · saving clears flag";
    onSave = async (vals) => {
      const res = await api.send(`/api/repair/${c.note_id}`, "PUT", { fields: vals, card_id: c.card_id });
      if (res.ok) {
        toast(res.data.flag_cleared ? "repaired" : "saved (flag not cleared)");
        await loadRepair();
        await refreshSession();
      } else {
        toast(res.data.error || "save failed");
      }
    };
  } else {
    return;
  }
  $("editor-title").textContent = title;
  $("editor-fields").innerHTML = order
    .map(
      (name, i) =>
        `<div class="field-row"><label>${name}</label><textarea data-field="${name}" rows="3">${escapeHtml(fields[name] || "")}</textarea></div>`
    )
    .join("");
  $("editor").dataset.surface = state.surface;
  editorSave = onSave;
  openOverlay("editor");
  const first = $("editor-fields").querySelector("textarea");
  if (first) { first.focus(); }
}
let editorSave = null;

function collectEditor() {
  const vals = {};
  $("editor-fields")
    .querySelectorAll("textarea")
    .forEach((t) => (vals[t.dataset.field] = t.value));
  return vals;
}

function openCommenter() {
  if (state.surface !== "inbox") return;
  if (!state.inbox.cards[state.inbox.idx]) return;
  $("comment-text").value = "";
  openOverlay("commenter");
  $("comment-text").focus();
}

async function submitComment() {
  const text = $("comment-text").value.trim();
  const item = state.inbox.cards[state.inbox.idx];
  closeOverlays();
  const res = await api.send(`/api/inbox/${item.card.id}/comment`, "POST", { text });
  if (!res.ok) {
    toast(res.data.error || "failed");
    openCommenter();
    $("comment-text").value = text;
    return;
  }
  // sent back: keep moving past it
  state.inbox.idx = Math.min(state.inbox.idx + 1, state.inbox.cards.length - 1);
  await loadInbox();
  await refreshSession();
  toast("sent back", "info");
}

function openSession() {
  $("session-target").value = state.config.session.target_enabled ? state.config.session.target_default || "" : "";
  openOverlay("session-prompt");
  $("session-target").focus();
}
async function startSession() {
  const v = $("session-target").value;
  closeOverlays();
  await api.send("/api/session/start", "POST", { target: v ? parseInt(v, 10) : null });
  state.targetAnnounced = false;
  await refreshSession();
  toast("session started");
}

// --- help -----------------------------------------------------------------
const HELP = [
  ["1-4", "switch surface (inbox, repair, survey, stats)"],
  ["j / k", "move down / up"],
  ["h / l", "move left / right"],
  ["space", "flip"],
  ["a", "approve card"],
  ["d", "delete (inbox -> graveyard)"],
  ["c", "comment + send back (inbox)"],
  ["e", "edit fields (inbox / repair)"],
  ["g", "exemplar, then g good / b bad"],
  ["u", "undo"],
  ["s", "start session / set target"],
  ["?", "this help"],
];
function buildHelp() {
  $("help-body").innerHTML =
    HELP.map(([k, v]) => `<div class="row"><span class="k"><code>${k}</code></span><span>${v}</span></div>`).join("");
}
function toggleHelp() {
  const h = $("help");
  if (h.hidden) { buildHelp(); h.hidden = false; }
  else h.hidden = true;
}

// --- keyboard -------------------------------------------------------------
function onKey(e) {
  const tag = e.target.tagName;
  const typing = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";

  // overlay-scoped handling
  if (!$("editor").hidden) {
    if (e.key === "Escape") { closeOverlays(); return; }
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      const vals = collectEditor();
      const save = editorSave;
      closeOverlays();
      if (save) save(vals);
    }
    return;
  }
  if (!$("commenter").hidden) {
    if (e.key === "Escape") { closeOverlays(); return; }
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); submitComment(); }
    return;
  }
  if (!$("session-prompt").hidden) {
    if (e.key === "Escape") closeOverlays();
    if (e.key === "Enter") { e.preventDefault(); startSession(); }
    return;
  }
  if (!$("exemplar-prompt").hidden) {
    if (e.key === "Escape") closeOverlays();
    if (e.key === "g") commitExemplar("good");
    if (e.key === "b") commitExemplar("bad");
    return;
  }
  if (!$("help").hidden) {
    if (e.key === "Escape" || e.key === "?") toggleHelp();
    return;
  }

  // typing in survey filters: don't hijack
  if (typing) {
    if (e.key === "Enter" && state.surface === "survey") loadSurvey(true);
    if (e.key === "Escape") e.target.blur();
    return;
  }

  const k = e.key;
  if (k === "1") return setSurface("inbox");
  if (k === "2") return setSurface("repair");
  if (k === "3") return setSurface("survey");
  if (k === "4") return setSurface("stats");
  if (k === "?") return toggleHelp();
  if (k === "u") return doUndo();
  if (k === "s") { e.preventDefault(); return openSession(); }
  if (k === "g") return startExemplar();

  if (state.surface === "inbox") inboxKeys(k, e);
  else if (state.surface === "repair") repairKeys(k, e);
  else if (state.surface === "survey") surveyKeys(k, e);
}

function inboxKeys(k, e) {
  const s = state.inbox;
  if (k === "j" || k === "ArrowDown") { s.idx = Math.min(s.idx + 1, s.cards.length - 1); s.ord = 0; s.flipped = false; renderInbox(); }
  else if (k === "k" || k === "ArrowUp") { s.idx = Math.max(s.idx - 1, 0); s.ord = 0; s.flipped = false; renderInbox(); }
  else if (k === "l" || k === "ArrowRight") { s.ord += 1; s.flipped = false; renderInbox(); }
  else if (k === "h" || k === "ArrowLeft") { s.ord -= 1; s.flipped = false; renderInbox(); }
  else if (k === " ") { e.preventDefault(); s.flipped = !s.flipped; renderInbox(); }
  else if (k === "a") approveCard();
  else if (k === "d") inboxAction("delete", "deleted → graveyard", "del");
  else if (k === "c") { e.preventDefault(); openCommenter(); }
  else if (k === "e") { e.preventDefault(); openEditor(); }
}

function repairKeys(k, e) {
  const s = state.repair;
  if (k === "j" || k === "ArrowDown") { s.idx = Math.min(s.idx + 1, s.cards.length - 1); s.flipped = false; renderRepair(); }
  else if (k === "k" || k === "ArrowUp") { s.idx = Math.max(s.idx - 1, 0); s.flipped = false; renderRepair(); }
  else if (k === " ") { e.preventDefault(); s.flipped = !s.flipped; renderRepair(); }
  else if (k === "e") { e.preventDefault(); openEditor(); }
}

function surveyKeys(k, e) {
  const s = state.survey;
  const cols = Math.max(1, Math.floor($("grid").clientWidth / 450));
  if (k === "j" || k === "ArrowDown") s.sel = Math.min(s.sel + cols, s.cards.length - 1);
  else if (k === "k" || k === "ArrowUp") s.sel = Math.max(s.sel - cols, 0);
  else if (k === "h" || k === "ArrowLeft") s.sel = Math.max(s.sel - 1, 0);
  else if (k === "l" || k === "ArrowRight") s.sel = Math.min(s.sel + 1, s.cards.length - 1);
  else if (k === " ") { e.preventDefault(); flipOne(s.sel); return; }
  else if (k === "f") { toggleFlipAll(); return; }
  else { return; }
  markSelection();
}

function flipOne(i) {
  const c = state.survey.cards[i];
  if (!c) return;
  const back = c._flipped == null ? state.survey.flipAll : c._flipped;
  c._flipped = !back;
  const div = $("grid").querySelectorAll(".gridcard")[i];
  if (div) { div.dataset.rendered = ""; renderGridCard(div); }
}

function toggleFlipAll() {
  state.survey.flipAll = !state.survey.flipAll;
  state.survey.cards.forEach((c) => (c._flipped = state.survey.flipAll));
  // re-render only cards already built; unbuilt ones pick up flipAll when shown
  $("grid").querySelectorAll(".gridcard").forEach((div) => {
    if (div.dataset.rendered) { div.dataset.rendered = ""; renderGridCard(div); }
  });
}

// --- util -----------------------------------------------------------------
function escapeHtml(s) {
  return String(s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
function stripTags(s) {
  return String(s || "").replace(/<[^>]*>/g, " ");
}

// --- wiring ---------------------------------------------------------------
document.querySelectorAll(".tab").forEach((t) =>
  t.addEventListener("click", () => setSurface(t.dataset.surface))
);
$("f-apply").addEventListener("click", () => loadSurvey(true));
$("f-flip").addEventListener("click", toggleFlipAll);
document.addEventListener("keydown", onKey);

// card iframes forward their keystrokes here (see cardDoc) so shortcuts keep
// working while a card is focused
window.addEventListener("message", (ev) => {
  const d = ev.data;
  if (!d || d.source !== "adw-card" || d.type !== "key") return;
  onKey({
    key: d.key, ctrlKey: d.ctrlKey, metaKey: d.metaKey, shiftKey: d.shiftKey, altKey: d.altKey,
    target: { tagName: "IFRAME" }, preventDefault() {},
  });
});

async function boot() {
  state.config = await api.get("/api/config");
  state.survey.flipAll = !!state.config.grid_show_backs;
  buildHelp();
  await pollStatus();
  setInterval(pollStatus, 15000);
  await refreshSession();
  await loadDecks();
  api.get("/api/models").catch(() => {}); // refresh data/note_types.* for generators
  setSurface("inbox");
}
boot();
