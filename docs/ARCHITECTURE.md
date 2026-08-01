# Architecture

## Entry points

| Entry | Role |
|-------|------|
| `scan.py` | Sequential fetch/compile; all modes; richest CLI flags |
| `scripts/parallel_full_refresh.py` | Concurrent town-group fetch, then single-process compile + reverify; recommended for full refreshes |

Both rebuild markdown + dashboard unless `--no-markdown`.

## Modules (`scanner/`)

| Module | Responsibility |
|--------|----------------|
| `fetch.py` | HomeHarvest multi-pass discovery (city, ZIP, county, foreclosure, property types, sold/pending) |
| `normalize.py` | Raw Realtor → internal schema |
| `geo.py` | Town classification; Lake Holiday ≠ Sheridan; haversine helpers; city centers |
| `distress.py` | Signal detection + scoring |
| `status.py` | Active vs inactive MLS status |
| `compile.py` | Distressed publish path |
| `verify.py` | Negatives, batch reverify, URL probes |
| `dedup.py` | Address-based merge |
| `audit.py` | Staleness, change detection, rejection audits, snapshots |
| `new_listings.py` | 7-day all-listings mode |
| `pool_listings.py` | Pool evidence mode |
| `large_land.py` | 20+ acre / 40 mi Lake Holiday mode |
| `links.py` | Zillow / Google / Redfin / LandWatch / LOA open URLs |
| `config.py` | Paths + YAML loader |

## Build scripts

| Script | Input → Output |
|--------|----------------|
| `build_dashboard.py` | All four datasets → `dashboard/distressed-property-dashboard.html` |
| `build_markdown.py` | `v2_compiled.json` only → `distressed-properties/**` |

## Data files

| Path | Contents |
|------|----------|
| `v2_compiled.json` | Distressed listings |
| `data/new_listings_7d.json` | `{ window_days, records }` |
| `data/pool_listings.json` | `{ count, records }` |
| `data/large_land.json` | `{ min_acres, radius_miles, records }` |
| `data/last_scan.json` | Scan timestamp + counts |
| `data/raw/*.json` | Raw fetches (gitignored) |
| `data/history/` | Snapshots & change reports (gitignored) |
| `data/audit/` | Rejection audits (gitignored) |

## Geo model

- **Core towns** (~3 mi default): Wheaton, Oswego, Sandwich, Somonauk, Lake Holiday
- **Optional towns** (~6 mi default): Leland, Earlville, Waterman, Sheridan
- Classification is primarily **city / subdivision / street heuristics**, not a hard post-filter haversine (except large land’s Lake Holiday ring)
- Fetch radius is applied at the HomeHarvest query; compile maps cities into towns

## Sources

- **Primary inventory:** Realtor.com via HomeHarvest
- **Open links:** Zillow / Google / Redfin preferred in the UI (Realtor deep-links often bot-block)
- **Land specialty sites:** link-only cross-checks (scraping blocked)
