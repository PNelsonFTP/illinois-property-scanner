# Distressed Property Scanner — Illinois

Automated scanner for distressed properties within ~3 miles of Wheaton, Oswego, Sandwich, Somonauk, and Lake Holiday (Sheridan), IL.

**Every listing is live-verified** against Realtor.com MLS status. Pending, contingent, and sold listings are excluded automatically.

## Quick Start

```bash
# One-time setup (requires Python 3.10+)
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run a full live scan
python scan.py

# Open the dashboard
open dashboard/distressed-property-dashboard.html
```

## What Changed (v3)

The original project was a **one-time manual snapshot** (April 2026) with stale data — many listings were already sold or contingent when reported. Key improvements:

| Before | After |
|--------|-------|
| Manual JSON curation | Automated live scan via Realtor.com (HomeHarvest) |
| No status verification | MLS status + pending/contingent flags checked at fetch time |
| 44 properties, many stale | 112+ live-verified distressed properties |
| Hardcoded `/home/user/workspace` paths | Portable project-relative paths |
| Status forced to `"active"` | Real MLS status preserved |
| Zillow bot-blocked, empty Oswego | Full coverage all 5 towns via Realtor.com |
| Renovated flips included | Flips with only weak signals excluded |

## How It Works

```
scan.py
  ├── fetch_all_towns()     → Realtor.com via HomeHarvest (all for_sale, exclude_pending)
  ├── compile_records()     → filter distress signals, verify status, deduplicate, score
  ├── build_markdown.py     → regenerate distressed-properties/ tree
  └── build_dashboard.py    → regenerate interactive HTML dashboard
```

### Verification

Each property must pass:
1. `exclude_pending=True` at fetch time (Realtor.com API)
2. No `is_pending` or `is_contingent` flags
3. MLS status must be Active (not Pending, Contingent, Sold, etc.)

### Distress Detection

Properties must have at least one signal: foreclosure, as-is/fixer language, high DOM (90+ days), meaningful price reduction, below-market land pricing, estate sale, investor special, etc.

Renovated flips with only a minor price cut are excluded.

## Project Layout

```
├── scan.py                    # Main entry point — run this
├── config.yaml                # Towns, radius, distress thresholds
├── scanner/                   # Core library
│   ├── fetch.py               # Live Realtor.com fetching
│   ├── compile.py             # Filter, dedup, score pipeline
│   ├── distress.py            # Distress signal detection
│   ├── status.py              # Active listing verification
│   └── normalize.py           # Schema normalization
├── v2_compiled.json           # Latest compiled results
├── data/raw/                  # Raw fetch snapshots (timestamped)
├── dashboard/                 # Interactive HTML dashboard
├── distressed-properties/     # Markdown views (by area, type, score)
└── v2-*.json                  # Legacy manual data (optional, unverified)
```

## Commands

```bash
python scan.py                 # Full live scan + rebuild everything
python scan.py --no-legacy     # Live data only (recommended)
python scan.py --verify-only   # Re-compile from last raw fetch
python scan.py --no-markdown   # Skip markdown/dashboard rebuild
```

## Configuration

Edit `config.yaml` to adjust:
- `scan.radius_miles` — search radius per town (default: 3)
- `distress.high_dom_days` — DOM threshold (default: 90)
- `towns` — target towns and nearby city name mappings

## Results

After scanning, browse:
- **Dashboard**: `dashboard/distressed-property-dashboard.html`
- **Index**: `distressed-properties/_index.md`
- **Raw data**: `distressed-properties/raw/all-properties.md`

Use the dashboard **"Live-Verified Only"** filter to hide any legacy unverified entries.

## Scoring

Distress score 1–10 based on weighted signals (foreclosure +3, high DOM tiers, price cuts, as-is/fixer +2, etc.). See `scanner/distress.py` for rules.

## Legacy Data

The original `v2-*.json` files (Redfin, Zillow, Auction.com, LandWatch) are kept for reference. Include them with `python scan.py` (default), but they are marked `legacy-unverified`. Prefer `--no-legacy` for a clean verified-only dataset.

## Requirements

- Python 3.10+ (3.12 recommended)
- Internet access for live scans
- Dependencies: `homeharvest`, `httpx`, `pyyaml`
