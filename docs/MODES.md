# Dashboard modes

The interactive dashboard (`dashboard/distressed-property-dashboard.html`) has five modes. Prefer opening it on GitHub Pages (see [PUBLISHING.md](PUBLISHING.md)).

## Distressed

- **Purpose:** Find fixer / foreclosure / high-DOM / meaningfully reduced listings in configured towns.
- **Filters:** Town toggles, property type, distress type, verified/freshness, min score, max price, search.
- **Pipeline:** `fetch_all_towns` → `compile_records` → `reverify_properties` → `v2_compiled.json`.
- **Markdown export:** `distressed-properties/` (this mode only).
- **CLI:** default `scan.py` / `parallel_full_refresh.py`.

## New to market (7 days)

- **Purpose:** Everything newly listed (geo only — no distress scoring).
- **Window:** `scan.new_listings_days` (default 7); override with `--new-days`.
- **Output:** `data/new_listings_7d.json`.
- **CLI:** `python scan.py --new-listings-only --include-optional`  
  Parallel path refreshes this after distressed/pools/land unless `--skip-new-listings`.

## Homes with pools

- **Purpose:** Active residential listings with MLS evidence of a private and/or community pool.
- **Evidence:** MLS tags (`swimming_pool`, `community_swimming_pool`), pool feature details, description patterns.
- **Geo:** Same town classification as distressed (location toggles apply).
- **Output:** `data/pool_listings.json`.
- **CLI:** `python scan.py --pool-listings-only`  
  Full scans compile pools from the same live inventory (no second residential fetch).

## Large land (20+ ac)

- **Purpose:** Land and farm tracts **≥20 acres** within **40 miles of Lake Holiday, IL**.
- **UI:** Town location panel is **hidden**. List is all-or-nothing for that ring (optional min-acres filter 20/40/80/160+).
- **Discovery:** Separate county + hub fetches (`config.yaml` → `large_land`), not the residential town list.
- **Acreage:** Prefer trusted MLS fields; see [ACREAGE.md](ACREAGE.md).
- **Cross-check links:** LandWatch / Lands of America / Zillow / Google (aggregators block scraping).
- **Output:** `data/large_land.json`.
- **CLI:** `python scan.py --large-land-only`.

## Caves & bunkers

- **Purpose:** Active listings with MLS text evidence of a cave, underground bunker, storm shelter, earth-sheltered / underground home, or similar.
- **Center:** ZIP **60189** (Wheaton). Drive hours ≈ haversine miles ÷ 55 mph.
- **Banding:** Prefer ≤4 hr; accept ≤8 hr; strong evidence may appear out to ~12 hr.
- **States:** IL, MO, AR, KY, IN, TN, MI (`config.yaml` → `caves_bunkers`).
- **UI:** Town location panel is **hidden** (all-or-nothing). Filters: max drive hours, feature type.
- **Discovery:** Regional hub fetches + description/details matching (HomeHarvest has no keyword search).
- **Output:** `data/caves_listings.json`.
- **CLI:** `python scan.py --caves-only`.

## Mode comparison

| Concern | Distressed | New 7d | Pools | Large land | Caves |
|---------|------------|--------|-------|------------|-------|
| Distress filter | Yes | No | No | No | No |
| Town toggles | Yes | Yes | Yes | No (40 mi ring) | No (60189 drive ring) |
| Deep reverify fetch | Yes (full path) | Light | Negatives only | Negatives only | Negatives only |
| Markdown export | Yes | No | No | No | No |
