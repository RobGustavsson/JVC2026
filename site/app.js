// Delad render-logik för JVC2026.
const DATA_BASE = "data";  // relativ från /site/*.html → site/data/*.json

const FIVE_MIN = 5 * 60 * 1000;
const ONE_MIN = 60 * 1000;
const MATCH_LIVE_WINDOW_MIN = 50;

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function el(tag, opts = {}, ...children) {
  const e = document.createElement(tag);
  if (opts.class) e.className = opts.class;
  if (opts.text != null) e.textContent = opts.text;
  if (opts.html != null) e.innerHTML = opts.html;
  if (opts.attrs) for (const [k, v] of Object.entries(opts.attrs)) e.setAttribute(k, v);
  if (opts.style) e.style.cssText = opts.style;
  for (const c of children.flat()) {
    if (c == null) continue;
    e.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return e;
}

async function fetchJson(name) {
  const bucket = Math.floor(Date.now() / FIVE_MIN);
  const url = `${DATA_BASE}/${name}?t=${bucket}`;
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error(`fetch ${name}: ${r.status}`);
  return r.json();
}

function fmtRelative(isoStr) {
  if (!isoStr) return "";
  const then = new Date(isoStr).getTime();
  const diff = Date.now() - then;
  if (diff < 0) return "snart";
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just nu";
  if (m < 60) return `för ${m} min sedan`;
  const h = Math.floor(m / 60);
  if (h < 24) return `för ${h} h sedan`;
  return new Date(isoStr).toLocaleString("sv-SE");
}

function matchStatus(match, now = Date.now()) {
  if (match.resultat) return "done";
  if (!match.iso_start) return "scheduled";
  const start = new Date(match.iso_start).getTime();
  const end = start + MATCH_LIVE_WINDOW_MIN * 60 * 1000;
  if (now >= start && now <= end) return "live";
  if (now < start) return "scheduled";
  return "scheduled-late";  // start tid passerad men inget resultat — vis som väntar
}

function parseScore(s) {
  if (!s) return null;
  const m = s.match(/^(\d+)\s*-\s*(\d+)$/);
  return m ? { home: parseInt(m[1], 10), away: parseInt(m[2], 10) } : null;
}

function hkOutcome(match) {
  const sc = parseScore(match.resultat);
  if (!sc) return null;
  const hk = match.is_home ? sc.home : sc.away;
  const op = match.is_home ? sc.away : sc.home;
  if (hk > op) return "win";
  if (hk < op) return "loss";
  return "draw";
}

function renderMatch(match, opts = {}) {
  const T = window.JVC_TEAMS;
  const color = T.classColor(match.klass);
  const label = T.teamLabel(match.klass, match.hk_team_raw);
  const status = matchStatus(match);

  const isLive = status === "live";
  const isNext = !!opts.isNext;
  const isDone = status === "done";

  const card = el("a", {
    class: `match ${isLive ? "is-live" : ""} ${isNext ? "is-next" : ""} ${isDone ? "is-done" : ""}`.trim(),
    attrs: { href: `team.html?klass=${encodeURIComponent(match.klass)}` }
  });

  const left = el("div");
  left.appendChild(el("div", { class: "tid", text: match.tid || "—" }));
  left.appendChild(el("div", { class: "tid-sub", text: match.grupp ? `Gr ${match.grupp}` : "" }));
  card.appendChild(left);

  const meta = el("div", { class: "meta" });
  const home = el("span", { class: `home ${match.is_home ? "hk" : ""}`, text: match.hemmalag });
  const vs = el("span", { class: "vs", text: " – " });
  const away = el("span", { class: `away ${!match.is_home ? "hk" : ""}`, text: match.bortalag });
  const teams = el("div", { class: "teams" });
  teams.appendChild(home); teams.appendChild(vs); teams.appendChild(away);
  meta.appendChild(teams);

  const row2 = el("div", { class: "row2" });
  const pill = el("span", {
    class: "badge",
    text: label,
    style: `background:${color.bg};color:${color.fg};`
  });
  row2.appendChild(pill);
  if (match.bana) row2.appendChild(el("span", { text: match.bana }));
  if (isLive) row2.appendChild(el("span", { class: "badge live", text: "LIVE" }));
  else if (isNext) row2.appendChild(el("span", { class: "badge next", text: "NÄSTA" }));
  else if (isDone) row2.appendChild(el("span", { class: "badge done", text: "KLAR" }));
  meta.appendChild(row2);
  card.appendChild(meta);

  const score = el("div", { class: "score" });
  if (match.resultat) {
    const outcome = hkOutcome(match);
    score.classList.add(outcome || "");
    score.textContent = match.resultat;
  } else if (isLive) {
    score.classList.add("pending");
    score.textContent = "spelas";
  } else {
    score.classList.add("pending");
    score.textContent = "–";
  }
  card.appendChild(score);

  return card;
}

function findNextMatch(matches, now = Date.now()) {
  const upcoming = matches
    .filter(m => !m.resultat && m.iso_start)
    .map(m => ({ m, t: new Date(m.iso_start).getTime() }))
    .filter(x => x.t + MATCH_LIVE_WINDOW_MIN * 60 * 1000 >= now)
    .sort((a, b) => a.t - b.t);
  return upcoming[0]?.m;
}

function partitionMatches(matches, now = Date.now()) {
  const done = [];
  const live = [];
  const upcoming = [];
  for (const m of matches) {
    const s = matchStatus(m, now);
    if (s === "done") done.push(m);
    else if (s === "live") live.push(m);
    else upcoming.push(m);
  }
  const byTime = (a, b) => {
    const at = a.iso_start ? new Date(a.iso_start).getTime() : 0;
    const bt = b.iso_start ? new Date(b.iso_start).getTime() : 0;
    return at - bt;
  };
  done.sort(byTime);
  live.sort(byTime);
  upcoming.sort(byTime);
  return { done, live, upcoming };
}

function renderTimeline(root, matches) {
  root.innerHTML = "";
  if (!matches.length) {
    root.appendChild(el("div", { class: "empty", text: "Inga matcher hittade ännu." }));
    return;
  }
  const now = Date.now();
  const { done, live, upcoming } = partitionMatches(matches, now);
  const next = findNextMatch(matches, now);

  if (live.length) {
    root.appendChild(el("div", { class: "section-title", text: "Pågår nu" }));
    for (const m of live) root.appendChild(renderMatch(m, { isNext: false }));
  }

  if (upcoming.length) {
    root.appendChild(el("div", { class: "section-title", text: "Kommande" }));
    for (const m of upcoming) root.appendChild(renderMatch(m, { isNext: next && m.mnr === next.mnr }));
  }

  if (done.length) {
    const div = el("div", { class: "divider" });
    div.innerHTML = `<span class="now-pulse"></span>Spelade matcher`;
    root.appendChild(div);
    for (const m of done.slice().reverse()) root.appendChild(renderMatch(m));
  }
}

function renderNextBanner(root, matches) {
  const next = findNextMatch(matches);
  if (!next) { root.innerHTML = ""; return; }
  const T = window.JVC_TEAMS;
  const label = T.teamLabel(next.klass, next.hk_team_raw);
  const when = next.iso_start ? new Date(next.iso_start).toLocaleTimeString("sv-SE", { hour: "2-digit", minute: "2-digit" }) : next.tid;
  const opp = next.opponent;
  root.innerHTML = "";
  root.appendChild(el("div", { class: "label", text: "Nästa match" }));
  root.appendChild(el("div", { class: "who", text: `${label} mot ${opp}` }));
  root.appendChild(el("div", { class: "when", text: `${when} ${next.is_home ? "(hemma)" : "(borta)"}` }));
  if (next.bana) root.appendChild(el("div", { class: "where", text: next.bana }));
}

async function bootTimeline() {
  const timelineEl = $("#timeline");
  const updatedEl = $("#updated");
  const bannerEl = $("#next-banner");

  let lastMatches = [];
  async function reload() {
    try {
      const [data, meta] = await Promise.all([
        fetchJson("matches.json"),
        fetchJson("last_updated.json")
      ]);
      lastMatches = data.matches || [];
      renderTimeline(timelineEl, lastMatches);
      if (bannerEl) renderNextBanner(bannerEl, lastMatches);
      if (updatedEl) updatedEl.textContent = `Uppdaterad ${fmtRelative(meta.iso)}`;
    } catch (e) {
      console.error(e);
      if (!lastMatches.length) timelineEl.innerHTML = `<div class="empty">Kunde inte ladda data. <br><small>${e.message}</small></div>`;
    }
  }
  await reload();
  setInterval(reload, FIVE_MIN);
  setInterval(() => {
    if (lastMatches.length) renderTimeline(timelineEl, lastMatches);
  }, ONE_MIN);
}

window.JVC = { bootTimeline, fetchJson, fmtRelative, matchStatus, partitionMatches, renderMatch, renderTimeline, renderNextBanner, parseScore, hkOutcome, findNextMatch, el, $ , $$ };
