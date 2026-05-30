"""Scrape Järnvägen Cup 2026 from procup.se and write JSON to ../data/.

Filters matches involving HK Järnvägen (any team variant), pulls group standings
for every class HK Järnvägen plays in, and attempts to read playoff brackets.
Writes data/matches.json, data/groups.json, data/brackets.json, data/last_updated.json.
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, unquote, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup, Tag

EV = "39543"
BASE = "https://www.procup.se/cup"
LANG = "SVE"
TZ = ZoneInfo("Europe/Stockholm")
UA = "JVC2026-Tracker/1.0"
HK_NEEDLE = "järnvägen"
SCORE_RE = re.compile(r"^\s*(\d+)\s*[-–]\s*(\d+)\s*$")

DATA_DIR = Path(__file__).resolve().parent.parent / "site" / "data"


def fetch(url: str) -> str:
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    resp.raise_for_status()
    return resp.text


def schedule_url() -> str:
    return f"{BASE}/cupresgeneric_skin04.php?ev={EV}&lang={LANG}"


def class_group_url(klass: str) -> str:
    return f"{BASE}/cupresclassgroup_skin04.php?ev={EV}&lang={LANG}&Klass={klass}"


def group_url(klass: str, grp: str) -> str:
    return f"{BASE}/cupresclass_skin04.php?ev={EV}&lang={LANG}&Grp={grp}&Klass={klass}"


def playoff_url(klass: str, abcd: str = "A") -> str:
    return f"{BASE}/cupresplayoff_lista_skin04.php?ev={EV}&lang={LANG}&Klass={klass}&ABCD={abcd}"


def text(el: Tag | None) -> str:
    if el is None:
        return ""
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()


def involves_hk(team_text: str) -> bool:
    return HK_NEEDLE in team_text.lower()


def parse_date_link(td: Tag) -> str | None:
    """Extract YYYY-MM-DD from a Datum cell link href containing DAG=YYYY-MM-DD."""
    a = td.find("a", href=True)
    if not a:
        return None
    href = a["href"]
    q = parse_qs(urlparse(href).query)
    dag = q.get("DAG", [None])[0]
    if dag and re.match(r"^\d{4}-\d{2}-\d{2}$", dag):
        return dag
    return None


def parse_class_from_link(td: Tag) -> str | None:
    a = td.find("a", href=True)
    if not a:
        return text(td) or None
    q = parse_qs(urlparse(a["href"]).query)
    raw = q.get("Klass", [None])[0]
    return unquote(raw) if raw else text(td) or None


def parse_group_from_link(td: Tag) -> str | None:
    a = td.find("a", href=True)
    if not a:
        return text(td) or None
    q = parse_qs(urlparse(a["href"]).query)
    grp = q.get("Grp", [None])[0]
    return grp or text(td) or None


def parse_match_row(tr: Tag) -> dict | None:
    """Parse a <tr> from the main schedule table. Return None to skip.

    Column layout (8 td's): Mnr | Klass | Grupp | Datum | Tid | Match | Bana | Resultat
    """
    tds = tr.find_all("td", recursive=False)
    if len(tds) < 7:
        return None

    mnr = text(tds[0])
    klass = parse_class_from_link(tds[1]) or ""
    grupp = parse_group_from_link(tds[2]) or ""
    datum = parse_date_link(tds[3])  # YYYY-MM-DD or None
    tid = text(tds[4])  # HH:MM

    # tds[5] holds two team divs separated by a center "-" span (always "-")
    match_cell = tds[5]
    divs = match_cell.find_all("div", recursive=True)
    teams = [text(d) for d in divs if d.get("style") and "width:49%" in d.get("style", "")]
    if len(teams) < 2:
        team_divs = [d for d in match_cell.find_all("div") if text(d)]
        if len(team_divs) >= 2:
            teams = [text(team_divs[0]), text(team_divs[1])]
        else:
            return None

    hemma, borta = teams[0], teams[1]
    bana = text(tds[6])

    # Resultat ligger i sista kolumnen (tds[7]) som <b>15 - 22</b> när spelat
    resultat = None
    if len(tds) >= 8:
        result_cell = tds[7]
        # leta efter <b> först — det är där score läggs när matchen är klar
        b = result_cell.find("b")
        cand = text(b) if b else text(result_cell)
        cand = cand.replace("–", "-").strip()
        score_match = SCORE_RE.match(cand)
        if score_match:
            resultat = f"{score_match.group(1)}-{score_match.group(2)}"

    if not (involves_hk(hemma) or involves_hk(borta)):
        return None

    iso_start = None
    if datum and re.match(r"^\d{2}:\d{2}$", tid):
        try:
            dt = datetime.strptime(f"{datum} {tid}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
            iso_start = dt.isoformat()
        except ValueError:
            iso_start = None

    is_home = involves_hk(hemma)
    hk_team_raw = hemma if is_home else borta
    opponent = borta if is_home else hemma

    return {
        "mnr": mnr,
        "klass": klass,
        "grupp": grupp,
        "datum": datum,
        "tid": tid,
        "iso_start": iso_start,
        "hemmalag": hemma,
        "bortalag": borta,
        "bana": bana,
        "resultat": resultat,
        "hk_team_raw": hk_team_raw,
        "opponent": opponent,
        "is_home": is_home,
    }


def parse_schedule(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", class_="custom-table")
    if not table:
        return []
    tbody = table.find("tbody")
    if not tbody:
        return []

    matches: list[dict] = []
    skipped = 0
    for tr in tbody.find_all("tr", recursive=False):
        try:
            row = parse_match_row(tr)
            if row:
                matches.append(row)
        except Exception as e:  # noqa: BLE001 — defensive per-row guard
            skipped += 1
            print(f"  ! skipped a row: {e}", file=sys.stderr)
    if skipped:
        print(f"  ({skipped} rows skipped due to parse errors)", file=sys.stderr)
    return matches


def parse_groups_for_class(html: str, klass: str) -> dict:
    """Find groups that contain HK Järnvägen on the class-group page,
    then fetch each such group's standings + match list."""
    soup = BeautifulSoup(html, "lxml")
    cards = soup.find_all("div", class_="cst-card")
    out: list[dict] = []
    for card in cards:
        h = card.find("h3")
        if not h:
            continue
        title = text(h)  # e.g. "Grupp 2"
        m = re.match(r"Grupp\s+(\d+)", title)
        if not m:
            continue
        grp_num = m.group(1)
        team_links = card.find_all("a", title=re.compile("matcher"))
        team_names = [text(a) for a in team_links]
        if not any(involves_hk(t) for t in team_names):
            continue
        # Fetch the per-group page (standings + alla matcher)
        table_rows: list[dict] = []
        group_matches: list[dict] = []
        try:
            time.sleep(2)
            standings_html = fetch(group_url(klass, grp_num))
            table_rows = parse_standings(standings_html)
            group_matches = parse_group_matches(standings_html)
        except Exception as e:  # noqa: BLE001
            print(f"  ! group {klass}/{grp_num}: {e}", file=sys.stderr)
        out.append({
            "klass": klass,
            "grupp": grp_num,
            "table": table_rows,
            "teams": team_names,
            "matches": group_matches,
        })
    return {"groups": out}


def parse_group_matches(html: str) -> list[dict]:
    """Plocka alla matcher från ett gruppspels-sida.

    Tabellen har 6 kolumner: Mnr | Datum | Tid | Match | Bana | Resultat.
    """
    soup = BeautifulSoup(html, "lxml")
    matches: list[dict] = []
    # Hitta "Matcher"-rubriken och därefter tabellen
    h = soup.find("h3", string=re.compile(r"Matcher"))
    if not h:
        return matches
    table = h.find_next("table")
    if not table:
        return matches
    tbody = table.find("tbody")
    if not tbody:
        return matches
    for tr in tbody.find_all("tr"):
        try:
            tds = tr.find_all("td", recursive=False)
            if len(tds) < 5:
                continue
            mnr = text(tds[0])
            datum = parse_date_link(tds[1])
            tid = text(tds[2])
            match_cell = tds[3]
            divs = match_cell.find_all("div", recursive=True)
            teams = [text(d) for d in divs if d.get("style") and "width:49%" in d.get("style", "")]
            if len(teams) < 2:
                team_divs = [d for d in match_cell.find_all("div") if text(d)]
                if len(team_divs) < 2:
                    continue
                teams = [text(team_divs[0]), text(team_divs[1])]
            hemma, borta = teams[0], teams[1]
            bana = text(tds[4])
            resultat = None
            if len(tds) >= 6:
                b = tds[5].find("b")
                cand = (text(b) if b else text(tds[5])).replace("–", "-").strip()
                sm = SCORE_RE.match(cand)
                if sm:
                    resultat = f"{sm.group(1)}-{sm.group(2)}"
            iso_start = None
            if datum and re.match(r"^\d{2}:\d{2}$", tid):
                try:
                    iso_start = datetime.strptime(f"{datum} {tid}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ).isoformat()
                except ValueError:
                    pass
            matches.append({
                "mnr": mnr, "datum": datum, "tid": tid, "iso_start": iso_start,
                "hemmalag": hemma, "bortalag": borta, "bana": bana, "resultat": resultat,
            })
        except Exception as e:  # noqa: BLE001
            print(f"  ! group match row: {e}", file=sys.stderr)
            continue
    return matches


def parse_standings(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    h = soup.find("h3", string=re.compile(r"Tabell"))
    if not h:
        return []
    table = h.find_next("table")
    if not table:
        return []
    tbody = table.find("tbody")
    if not tbody:
        return []
    rows = []
    for tr in tbody.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 8:
            continue
        try:
            row = {
                "lag": text(tds[0]),
                "antal_spelade": text(tds[1]),
                "vinster": text(tds[2]),
                "oavgjorda": text(tds[3]),
                "forluster": text(tds[4]),
                "mal": text(tds[5]),
                "diff": text(tds[6]),
                "poang": text(tds[-1]),
            }
            rows.append(row)
        except Exception:  # noqa: BLE001
            continue
    return rows


def parse_playoff(html: str, klass: str, abcd: str) -> dict:
    """Best-effort: read the playoff list page. Empty pre-cup. Returns a list of matches."""
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", class_="custom-table")
    rows: list[dict] = []
    if table and table.find("tbody"):
        for tr in table.find("tbody").find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 6:
                continue
            try:
                rows.append({
                    "mnr": text(tds[0]),
                    "namn": text(tds[1]) if len(tds) > 1 else "",
                    "datum": text(tds[2]) if len(tds) > 2 else "",
                    "tid": text(tds[3]) if len(tds) > 3 else "",
                    "match": text(tds[4]) if len(tds) > 4 else "",
                    "bana": text(tds[5]) if len(tds) > 5 else "",
                })
            except Exception:  # noqa: BLE001
                continue
    return {"klass": klass, "abcd": abcd, "matches": rows}


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[{datetime.now(TZ).isoformat()}] Scraping schedule...")
    try:
        html = fetch(schedule_url())
    except Exception as e:  # noqa: BLE001
        print(f"FATAL: schedule fetch failed: {e}", file=sys.stderr)
        return 0  # keep last good data

    matches = parse_schedule(html)
    print(f"  found {len(matches)} HK Järnvägen matches")
    if not matches:
        print("WARN: 0 matches — leaving existing data untouched.")
        return 0

    classes = sorted({m["klass"] for m in matches if m["klass"]})
    print(f"  HK Järnvägen klasser: {classes}")

    groups_data: list[dict] = []
    for klass in classes:
        time.sleep(2)
        try:
            print(f"  groups for {klass}...")
            cg_html = fetch(class_group_url(klass))
            groups_data.append({"klass": klass, **parse_groups_for_class(cg_html, klass)})
        except Exception as e:  # noqa: BLE001
            print(f"  ! class {klass}: {e}", file=sys.stderr)

    brackets_data: list[dict] = []
    for klass in classes:
        for abcd in ("A", "B"):
            time.sleep(2)
            try:
                po_html = fetch(playoff_url(klass, abcd))
                brackets_data.append(parse_playoff(po_html, klass, abcd))
            except Exception as e:  # noqa: BLE001
                print(f"  ! playoff {klass}/{abcd}: {e}", file=sys.stderr)

    payload_meta = {
        "cup": "Järnvägen Cup 2026",
        "ev": EV,
        "source": schedule_url(),
        "scraped_at": datetime.now(TZ).isoformat(),
    }

    (DATA_DIR / "matches.json").write_text(
        json.dumps({"meta": payload_meta, "matches": matches}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DATA_DIR / "groups.json").write_text(
        json.dumps({"meta": payload_meta, "classes": groups_data}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DATA_DIR / "brackets.json").write_text(
        json.dumps({"meta": payload_meta, "brackets": brackets_data}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DATA_DIR / "last_updated.json").write_text(
        json.dumps({"iso": datetime.now(TZ).isoformat(), "matches_count": len(matches)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[{datetime.now(TZ).isoformat()}] Done. Wrote {len(matches)} matches, {len(groups_data)} classes, {len(brackets_data)} bracket sheets.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
