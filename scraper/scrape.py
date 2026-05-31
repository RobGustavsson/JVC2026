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


ROUND_ORDER = ["1/16", "1/8", "Kvart", "Semi", "Brons", "Final"]
ROUND_LABELS = {
    "1/16": "Sextondelsfinal",
    "1/8": "Åttondelsfinal",
    "Kvart": "Kvartsfinal",
    "Semi": "Semifinal",
    "Brons": "Bronsmatch",
    "Final": "Final",
}


def typ_to_round(typ: str) -> str:
    """Map procup Typ-string to canonical round name. Examples:
        'A-8-dels:05' -> '1/8'
        'B-Kvart:02'  -> 'Kvart'
        'A-Semi:01'   -> 'Semi'
        'A-Final'     -> 'Final'
        'B-Brons'     -> 'Brons'
    """
    t = typ.lower()
    if "16-dels" in t: return "1/16"
    if "8-dels" in t: return "1/8"
    if "kvart" in t: return "Kvart"
    if "brons" in t or "3:e" in t or "3e" in t: return "Brons"
    # "Semi" måste kollas före "final" (Semifinal innehåller båda)
    if "semi" in t: return "Semi"
    if "final" in t: return "Final"
    return typ


SWEDISH_DAYS = {"mån": 0, "tis": 1, "ons": 2, "tor": 3, "fre": 4, "lör": 5, "sön": 6}


def parse_swedish_date(s: str, year: int = 2026) -> str | None:
    """'Sön 31/5' -> '2026-05-31'"""
    if not s:
        return None
    m = re.search(r"(\d{1,2})/(\d{1,2})", s)
    if not m:
        return None
    day, month = int(m.group(1)), int(m.group(2))
    return f"{year:04d}-{month:02d}-{day:02d}"


def parse_playoff_list(html: str, klass: str, abcd: str) -> list[dict]:
    """Parse cupresplayoff_lista_skin04.php — all matches in this playoff branch
    with round info derived from the Typ column.

    Columns: Mnr | Typ | Datum | Tid | Lag (home/-/away) | Bana | Resultat
    """
    soup = BeautifulSoup(html, "lxml")
    out: list[dict] = []
    table = soup.find("table", class_="custom-table")
    if not table:
        return out
    tbody = table.find("tbody")
    if not tbody:
        return out
    for tr in tbody.find_all("tr", recursive=False):
        try:
            tds = tr.find_all("td", recursive=False)
            if len(tds) < 6:
                continue
            mnr = text(tds[0])
            typ = text(tds[1])
            datum_raw = text(tds[2])
            tid = text(tds[3])
            match_cell = tds[4]
            divs = match_cell.find_all("div", recursive=True)
            teams = [text(d) for d in divs if d.get("style") and "width:49%" in d.get("style", "")]
            if len(teams) < 2:
                team_divs = [d for d in match_cell.find_all("div") if text(d)]
                if len(team_divs) < 2:
                    continue
                teams = [text(team_divs[0]), text(team_divs[1])]
            hemma, borta = teams[0], teams[1]
            bana = text(tds[5])
            resultat = None
            if len(tds) >= 7:
                b = tds[6].find("b")
                cand = (text(b) if b else text(tds[6])).replace("–", "-").strip()
                sm = SCORE_RE.match(cand)
                if sm:
                    resultat = f"{sm.group(1)}-{sm.group(2)}"

            datum = parse_swedish_date(datum_raw)
            iso_start = None
            if datum and re.match(r"^\d{2}:\d{2}$", tid):
                try:
                    iso_start = datetime.strptime(f"{datum} {tid}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ).isoformat()
                except ValueError:
                    pass

            round_short = typ_to_round(typ)
            out.append({
                "mnr": mnr,
                "typ": typ,
                "round_short": round_short,
                "round_label": ROUND_LABELS.get(round_short, round_short),
                "klass": klass,
                "abcd": abcd,
                "datum": datum,
                "tid": tid,
                "iso_start": iso_start,
                "hemmalag": hemma,
                "bortalag": borta,
                "bana": bana,
                "resultat": resultat,
            })
        except Exception as e:  # noqa: BLE001
            print(f"  ! playoff row {klass}/{abcd}: {e}", file=sys.stderr)
            continue
    return out


def build_hk_playoff_summary(playoff_matches: list[dict]) -> list[dict]:
    """For each HK Järnvägen team appearing in any playoff list, gather their
    matches across rounds and compute current status (next match / eliminated).
    """
    by_team: dict[tuple[str, str], list[dict]] = {}
    for m in playoff_matches:
        for side in ("hemmalag", "bortalag"):
            name = m.get(side, "")
            if involves_hk(name):
                key = (m["klass"], name)
                by_team.setdefault(key, []).append({**m, "is_home": side == "hemmalag", "team_raw": name})

    def round_idx(r: str) -> int:
        try:
            return ROUND_ORDER.index(r)
        except ValueError:
            return -1

    teams_out = []
    for (klass, team_raw), ms in by_team.items():
        ms_sorted = sorted(ms, key=lambda x: (round_idx(x["round_short"]), x.get("iso_start") or ""))
        latest = ms_sorted[-1]
        # Avgör status utifrån den senaste rondens match
        status = "ongoing"
        if latest.get("resultat"):
            sm = SCORE_RE.match(latest["resultat"].replace("–", "-"))
            if sm:
                hk_score = int(sm.group(1)) if latest["is_home"] else int(sm.group(2))
                op_score = int(sm.group(2)) if latest["is_home"] else int(sm.group(1))
                if hk_score < op_score:
                    status = "eliminated"
                elif hk_score > op_score:
                    # Vinst i senaste — om det var Final har vi vunnit cupen, annars väntar nästa rond
                    status = "champion" if latest["round_short"] == "Final" else "won_awaiting_next"
                else:
                    # Oavgjort i slutspel betyder normalt straffar — utfallet ligger i procup, men vi vet inte här
                    status = "drew"
        teams_out.append({
            "klass": klass,
            "team_raw": team_raw,
            "squad": team_raw.replace("HK Järnvägen", "").lstrip(": ").strip(),
            "abcd": latest["abcd"],
            "status": status,
            "current_round": latest["round_short"],
            "current_round_label": latest["round_label"],
            "latest_match": latest,
            "all_matches": ms_sorted,
        })
    # Sortera: aktiva först, eliminated sist; inom varje grupp äldre klass först (U19→U12)
    def class_age(klass: str) -> int:
        nums = [int(n) for n in re.findall(r"\d+", klass or "")]
        return max(nums) if nums else 0
    def sort_key(t):
        active = 0 if t["status"] in ("ongoing", "won_awaiting_next", "champion") else 1
        return (active, -class_age(t["klass"]), t["klass"])
    teams_out.sort(key=sort_key)
    return teams_out


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

    all_playoff_matches: list[dict] = []
    for klass in classes:
        for abcd in ("A", "B"):
            time.sleep(2)
            try:
                po_html = fetch(playoff_url(klass, abcd))
                rows = parse_playoff_list(po_html, klass, abcd)
                all_playoff_matches.extend(rows)
            except Exception as e:  # noqa: BLE001
                print(f"  ! playoff {klass}/{abcd}: {e}", file=sys.stderr)

    # Bygg per-lag-sammanfattning för slutspels-fliken
    hk_playoff_teams = build_hk_playoff_summary(all_playoff_matches)
    print(f"  HK i slutspel: {len(hk_playoff_teams)} lag")

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
    (DATA_DIR / "playoffs.json").write_text(
        json.dumps({"meta": payload_meta, "teams": hk_playoff_teams, "all_matches": all_playoff_matches}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (DATA_DIR / "last_updated.json").write_text(
        json.dumps({"iso": datetime.now(TZ).isoformat(), "matches_count": len(matches)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[{datetime.now(TZ).isoformat()}] Done. Wrote {len(matches)} matches, {len(groups_data)} classes, {len(hk_playoff_teams)} playoff teams.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
