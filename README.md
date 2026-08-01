# Illinois Property Scanner

Live-verified property scanner for northern Illinois markets around **Wheaton, Oswego, Sandwich, Somonauk, Lake Holiday**, plus optional towns (**Leland, Earlville, Waterman, Sheridan**).

**Primary viewing surface (GitHub Pages):**  
https://pnelsonftp.github.io/illinois-property-scanner/

**Dashboard:**  
https://pnelsonftp.github.io/illinois-property-scanner/dashboard/distressed-property-dashboard.html

Listings are discovered via Realtor.com MLS (HomeHarvest), then filtered for active status. Pending, contingent, and sold inventory is used as a negative check so those deals do not publish as available.

> **Lake Holiday is not Sheridan.** Sheridan is its own optional town. Lake Holiday includes the Wildwood community even when the mailing city is Sandwich.

---

## Dashboard modes

| Mode | What it shows | Data file |
|------|----------------|-----------|
| **Distressed** | Scored fixer / foreclosure / high-DOM / price-cut opportunities in configured towns | `v2_compiled.json` |
| **New to market (7 days)** | All active for-sale listings listed in the last N days (geo only, no distress filter) | `data/new_listings_7d.json` |
| **Homes with pools** | Active residential homes with MLS private or community pool evidence | `data/pool_listings.json` |
| **Large land (20+ ac)** | Land/farm tracts ≥20 acres within 40 miles of Lake Holiday (all-or-nothing; no town toggles) | `data/large_land.json` |

Location toggles apply to Distressed, New, and Pools. Large land is a separate 40-mile ring search and hides town filters on purpose.

---

## Quick start

```bash
# One-time setup (Python 3.10+; 3.12 recommended)
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Recommended full refresh (parallel fetch + reverify + all modes)
.venv/bin/python scripts/parallel_full_refresh.py --workers 3 --enable-counties

# Or sequential full scan
.venv/bin/python scan.py --include-optional --no-legacy
```

After a refresh you asked to publish, commit outputs and push **both** remotes (`public` + `origin`) so Pages updates. See [docs/PUBLISHING.md](docs/PUBLISHING.md).

---

## How it works

```
parallel_full_refresh.py  (or scan.py)
  ├── fetch towns / ZIPs / optional counties     → raw MLS snapshots
  ├── compile distressed + reverify             → v2_compiled.json
  ├── compile pools from active inventory       → data/pool_listings.json
  ├── fetch/compile large land (counties+hubs)  → data/large_land.json
  ├── fetch/compile new listings (7d)           → data/new_listings_7d.json
  ├── build_markdown.py                         → distressed-properties/
  └── build_dashboard.py                        → dashboard HTML
```

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [docs/VERIFICATION.md](docs/VERIFICATION.md) · [docs/ACREAGE.md](docs/ACREAGE.md)

---

## Common commands

```bash
# Full sequential scan (all modes by default)
python scan.py --no-legacy

# Mode-only refreshes
python scan.py --new-listings-only --include-optional
python scan.py --pool-listings-only --include-optional
python scan.py --large-land-only

# Status-only pass on existing distressed list
python scan.py --reverify-only

# Re-compile from latest raw without fetching
python scan.py --verify-only --no-legacy

# Parallel daily/full refresh
python scripts/parallel_full_refresh.py --workers 3
python scripts/parallel_full_refresh.py --workers 3 --enable-counties
```

More CLI detail: [docs/OPERATIONS.md](docs/OPERATIONS.md)

---

## Configuration

Edit [`config.yaml`](config.yaml):

- Town radii (`scan.radius_miles`, optional rural radius)
- Optional towns, ZIP/county passes, sold/pending checks
- Distress thresholds (`high_dom_days`, land/mobile price signals)
- Large-land ring (`large_land.min_acres`, `radius_miles`, counties, hubs)

Walkthrough: [docs/CONFIGURATION.md](docs/CONFIGURATION.md)

---

## Project layout

```
├── scan.py                      # Sequential entry point
├── scripts/parallel_full_refresh.py
├── config.yaml
├── scanner/                     # fetch, compile, verify, modes, geo, links
├── build_dashboard.py           # Multi-mode HTML dashboard
├── build_markdown.py            # Distressed-only markdown export
├── v2_compiled.json             # Distressed results
├── data/
│   ├── new_listings_7d.json
│   ├── pool_listings.json
│   ├── large_land.json
│   ├── last_scan.json
│   └── raw/                     # gitignored fetch snapshots
├── dashboard/                   # Generated HTML
├── distressed-properties/       # Generated distressed markdown
├── docs/                        # Project documentation
└── index.html                   # Pages redirect → dashboard
```

---

## Documentation

| Doc | Topic |
|-----|--------|
| [docs/MODES.md](docs/MODES.md) | Four dashboard modes |
| [docs/PUBLISHING.md](docs/PUBLISHING.md) | GitHub Pages + dual remotes |
| [docs/VERIFICATION.md](docs/VERIFICATION.md) | Active-status pipeline |
| [docs/ACREAGE.md](docs/ACREAGE.md) | Large-land acreage rules |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Pipeline & data files |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | `config.yaml` keys |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Refresh workflows & CLI |
| [docs/IMPROVEMENT_BACKLOG.md](docs/IMPROVEMENT_BACKLOG.md) | Ranked improvement ideas |
| [CHANGELOG.md](CHANGELOG.md) | Notable changes |

---

## Scoring (distressed mode)

Distress score 1–10 from weighted signals (foreclosure, as-is/fixer, high DOM, price cuts, etc.). See `scanner/distress.py`. Renovated/turnkey flips with only weak signals are filtered out when possible.

---

## Requirements

- Python 3.10+ (3.12 recommended)
- Network access for live MLS scans
- Dependencies in `requirements.txt`: `homeharvest`, `httpx`, `beautifulsoup4`, `lxml`, `pyyaml`

---

## Remotes

| Remote | Repo | Role |
|--------|------|------|
| `public` | [illinois-property-scanner](https://github.com/PNelsonFTP/illinois-property-scanner) | GitHub Pages site |
| `origin` | [distressed-property-scanner](https://github.com/PNelsonFTP/distressed-property-scanner) | Private mirror |
