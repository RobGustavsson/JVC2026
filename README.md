# JVC 2026 — HK Järnvägens matcher

En statisk sajt som följer HK Järnvägens lag genom Järnvägen Cup 2026 (Hallsberg, 30 maj 2026). Tidslinje över dagen, gruppställningar och slutspel — uppdaterat var ~30:e minut via GitHub Actions som scrapar [procup.se](https://www.procup.se/cup/cupresgeneric_skin04.php?ev=39543&lang=SVE).

**Live:** https://robgustavsson.github.io/JVC2026/

## Lokal utveckling

```powershell
# Skapa venv + installera deps
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r scraper\requirements.txt

# Kör scrapern (skriver site/data/*.json)
python scraper\scrape.py

# Servera sajten lokalt
python -m http.server 8000 --directory site
# Öppna http://localhost:8000
```

## Struktur

- `scraper/scrape.py` — laddar procup.se-sidan, plockar HK Järnvägens matcher, hämtar gruppställningar för relevanta klasser, försöker läsa slutspelsträd.
- `site/` — statisk sajt (vanilla HTML + JS + CSS). Servas av GitHub Pages.
- `site/data/*.json` — scraperns output. Committas i git så Pages kan servera direkt.
- `.github/workflows/scrape.yml` — cron-jobb som kör scrapern och committar uppdaterad data.

## Deploy

1. Repo Settings → **Pages** → Source: *Deploy from branch*, branch `main`, mapp `/site`.
2. Settings → Actions → General → Workflow permissions: **Read and write**.
3. Actions-fliken → *Scrape procup* → **Run workflow** för att seed:a `site/data/`.
4. Verifiera på `https://robgustavsson.github.io/JVC2026/`.

## Schemat

- Pre-cup: scrapern kör 08:00 UTC dagligen.
- Cupdagen (30 maj 2026): var 30:e min mellan 06:00–20:00 UTC (08–22 svensk tid).
- Workflow:n hoppar över commit om datan är oförändrad → inga onödiga commits.
