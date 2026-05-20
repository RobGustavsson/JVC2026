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

const DAYS = ["Sön", "Mån", "Tis", "Ons", "Tor", "Fre", "Lör"];
const DAYS_LONG = ["Söndag", "Måndag", "Tisdag", "Onsdag", "Torsdag", "Fredag", "Lördag"];
const MONTHS = ["jan", "feb", "mar", "apr", "maj", "jun", "jul", "aug", "sep", "okt", "nov", "dec"];

function fmtDayLong(datum) {
  if (!datum) return "";
  const d = new Date(datum + "T12:00:00");
  return `${DAYS_LONG[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]}`;
}

function matchStatus(match, now = Date.now()) {
  if (match.resultat) return "done";
  if (!match.iso_start) return "scheduled";
  const start = new Date(match.iso_start).getTime();
  const end = start + MATCH_LIVE_WINDOW_MIN * 60 * 1000;
  if (now >= start && now <= end) return "live";
  if (now < start) return "scheduled";
  return "scheduled-late";
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

function banaNumber(bana) {
  if (!bana) return null;
  const m = String(bana).match(/(\d+)/);
  return m ? m[1] : bana;
}

function renderMatch(match, opts = {}) {
  const T = window.JVC_TEAMS;
  const suffix = T.squadSuffix(match.hk_team_raw);
  const status = matchStatus(match);

  const isLive = status === "live";
  const isNext = !!opts.isNext;
  const isDone = status === "done";

  const card = el("a", {
    class: `match ${isLive ? "is-live" : ""} ${isNext ? "is-next" : ""} ${isDone ? "is-done" : ""}`.trim(),
    attrs: { href: `team.html?klass=${encodeURIComponent(match.klass)}` }
  });

  // TOPPRAD: klass · grupp · status-badge
  const top = el("div", { class: "match-top" });
  const classText = suffix ? `${match.klass} · ${suffix}` : match.klass;
  top.appendChild(el("span", { class: "match-class", text: classText }));
  if (match.grupp) top.appendChild(el("span", { class: "match-grupp", text: `Grupp ${match.grupp}` }));
  let badge = null;
  if (isLive) badge = el("span", { class: "badge live", text: "● LIVE" });
  else if (isNext) badge = el("span", { class: "badge next", text: "NÄSTA" });
  else if (isDone) badge = el("span", { class: "badge done", text: "KLAR" });
  if (badge) top.appendChild(badge);
  card.appendChild(top);

  // MATCH-RAD: hemma — vs/score — borta — gate (bana)
  const row = el("div", { class: "match-row" });
  const home = el("div", {
    class: `match-team home ${match.is_home ? "hk" : ""}`.trim(),
    text: match.hemmalag,
  });
  const away = el("div", {
    class: `match-team away ${!match.is_home ? "hk" : ""}`.trim(),
    text: match.bortalag,
  });
  row.appendChild(home);

  const vs = el("div", { class: "match-vs" });
  if (match.resultat) {
    const outcome = hkOutcome(match);
    if (outcome) vs.classList.add(outcome);
    vs.textContent = match.resultat.replace("-", " – ");
  } else if (isLive) {
    vs.classList.add("live-pulse");
    vs.textContent = "● spelas";
  } else {
    vs.textContent = "–";
  }
  row.appendChild(vs);
  row.appendChild(away);

  const banaNum = banaNumber(match.bana);
  if (banaNum) {
    const gate = el("div", { class: "match-gate" });
    gate.appendChild(el("div", { class: "gate-label", text: "Bana" }));
    gate.appendChild(el("div", { class: "gate-num", text: banaNum }));
    row.appendChild(gate);
  } else {
    row.appendChild(el("div"));  // tom platshållare för grid-alignment
  }
  card.appendChild(row);

  return card;
}

function findNextMatch(matches, now = Date.now()) {
  return findNextMatches(matches, now)[0];
}

// Returnera ALLA matcher som delar den tidigaste kommande avsparken (för "NÄSTA"-markering vid krock).
function findNextMatches(matches, now = Date.now()) {
  const upcoming = matches
    .filter(m => !m.resultat && m.iso_start)
    .map(m => ({ m, t: new Date(m.iso_start).getTime() }))
    .filter(x => x.t + MATCH_LIVE_WINDOW_MIN * 60 * 1000 >= now)
    .sort((a, b) => a.t - b.t);
  if (!upcoming.length) return [];
  const earliest = upcoming[0].t;
  return upcoming.filter(x => x.t === earliest).map(x => x.m);
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

// Gruppera matcher: först per datum, sedan per tid inom dagen.
function groupByDateAndTime(matches) {
  const byDate = new Map();  // datum -> Map<tid, [matches]>
  for (const m of matches) {
    const d = m.datum || "okänt";
    if (!byDate.has(d)) byDate.set(d, new Map());
    const byTime = byDate.get(d);
    const t = m.tid || "??:??";
    if (!byTime.has(t)) byTime.set(t, []);
    byTime.get(t).push(m);
  }
  // sortera dagar
  const sortedDates = [...byDate.keys()].sort();
  return sortedDates.map(date => ({
    date,
    slots: [...byDate.get(date).entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([tid, ms]) => ({ tid, matches: ms }))
  }));
}

// Renderar en grupp av matcher som delar samma tidpunkt.
function renderTimeSlot(slot, opts = {}) {
  const wrap = el("div", { class: `time-slot ${slot.matches.length > 1 ? "is-clash" : ""}` });
  const head = el("div", { class: "time-head" });
  head.appendChild(el("span", { class: "time-big", text: slot.tid }));
  if (slot.matches.length > 1) {
    head.appendChild(el("span", { class: "clash-note", text: `${slot.matches.length} matcher samtidigt` }));
  }
  wrap.appendChild(head);

  const cards = el("div", { class: "time-cards" });
  for (const m of slot.matches) {
    const isNext = opts.nextMnrs && opts.nextMnrs.has(m.mnr);
    cards.appendChild(renderMatch(m, { isNext }));
  }
  wrap.appendChild(cards);
  return wrap;
}

function renderDaySection(day, opts = {}) {
  const section = el("section", { class: "day-section" });
  const header = el("div", { class: "day-header" });
  header.appendChild(el("div", { class: "day-name", text: fmtDayLong(day.date) }));
  header.appendChild(el("div", { class: "day-count", text: `${day.slots.reduce((n, s) => n + s.matches.length, 0)} matcher` }));
  section.appendChild(header);

  for (const slot of day.slots) {
    section.appendChild(renderTimeSlot(slot, opts));
  }
  return section;
}

function renderTimeline(root, matches) {
  root.innerHTML = "";
  if (!matches.length) {
    root.appendChild(el("div", { class: "empty", text: "Inga matcher hittade ännu." }));
    return;
  }
  const now = Date.now();
  const { done, live, upcoming } = partitionMatches(matches, now);
  const nextMatches = findNextMatches(matches, now);
  const nextMnrs = new Set(nextMatches.map(m => m.mnr));

  if (live.length) {
    const section = el("section", { class: "day-section live-section" });
    const header = el("div", { class: "day-header live" });
    header.appendChild(el("div", { class: "day-name", text: "● Pågår nu" }));
    header.appendChild(el("div", { class: "day-count", text: `${live.length} match${live.length > 1 ? "er" : ""}` }));
    section.appendChild(header);
    const liveGroups = groupByDateAndTime(live);
    for (const d of liveGroups) for (const slot of d.slots) section.appendChild(renderTimeSlot(slot));
    root.appendChild(section);
  }

  if (upcoming.length) {
    const upcomingDays = groupByDateAndTime(upcoming);
    for (const day of upcomingDays) {
      root.appendChild(renderDaySection(day, { nextMnrs }));
    }
  }

  if (done.length) {
    const doneDays = groupByDateAndTime(done);
    for (const day of doneDays.reverse()) {
      const section = renderDaySection(day);
      section.classList.add("done-day");
      // omvänd ordning i klara dagar — senaste först
      const slots = $$(".time-slot", section);
      const head = $(".day-header", section);
      const parent = head.parentNode;
      for (const s of slots.reverse()) parent.appendChild(s);
      root.appendChild(section);
    }
  }
}

function renderNextBanner(root, matches) {
  const nexts = findNextMatches(matches);
  if (!nexts.length) { root.innerHTML = ""; return; }
  const T = window.JVC_TEAMS;
  const first = nexts[0];
  const when = first.iso_start
    ? new Date(first.iso_start).toLocaleString("sv-SE", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })
    : first.tid;
  root.innerHTML = "";
  root.appendChild(el("div", { class: "label", text: nexts.length > 1 ? `Nästa matcher (${nexts.length} samtidigt)` : "Nästa match" }));
  root.appendChild(el("div", { class: "when", text: when }));
  const list = el("div", { class: "next-list" });
  for (const m of nexts) {
    const suffix = T.squadSuffix(m.hk_team_raw);
    const label = suffix ? `${m.klass} · ${suffix}` : m.klass;
    const row = el("div", { class: "next-row" });
    row.appendChild(el("span", { class: "next-team", text: label }));
    row.appendChild(el("span", { class: "next-versus", text: `${m.is_home ? "hemma" : "borta"} mot ${m.opponent}` }));
    if (m.bana) row.appendChild(el("span", { class: "next-bana", text: m.bana }));
    list.appendChild(row);
  }
  root.appendChild(list);
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
      if (updatedEl) {
        updatedEl.textContent = `Uppdaterad ${fmtRelative(meta.iso)}`;
        const ageMs = meta.iso ? (Date.now() - new Date(meta.iso).getTime()) : 0;
        updatedEl.classList.toggle("stale", ageMs > 60 * 60 * 1000);
      }
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

window.JVC = { bootTimeline, fetchJson, fmtRelative, matchStatus, partitionMatches, renderMatch, renderTimeline, renderNextBanner, parseScore, hkOutcome, findNextMatch, findNextMatches, groupByDateAndTime, renderTimeSlot, renderDaySection, el, $ , $$ };
