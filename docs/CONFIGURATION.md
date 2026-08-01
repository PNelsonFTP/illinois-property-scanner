# Configuration (`config.yaml`)

## `scan`

| Key | Meaning |
|-----|---------|
| `radius_miles` | Default town search radius |
| `rural_radius_miles` | Default for optional towns |
| `exclude_pending` | HomeHarvest for-sale exclude_pending |
| `include_optional_towns` | Enable Leland / Earlville / Waterman / Sheridan (default true) |
| `include_zip_searches` | Extra ZIP queries per town |
| `include_county_searches` | County-wide sweeps (slow; parallel script can force with `--enable-counties`) |
| `include_distress_passes` | Land/mobile typed passes from `distress_passes` |
| `include_sold_pending_checks` | Fetch sold/pending negative inventories |
| `reverify_after_compile` | Deep reverify after distressed compile |
| `check_listing_urls` | Probe listing URLs during reverify |
| `stale_hours` | Staleness threshold |
| `include_new_listings` / `new_listings_days` | Gate + window for new-to-market mode |
| `include_pool_listings` | Gate pool mode on full scans |
| `include_large_land` | Gate large-land mode on full scans |

Note: `include_land` / `include_mobile` top-level-style flags are historical; typed passes are driven by `distress_passes`.

## `large_land`

| Key | Meaning |
|-----|---------|
| `min_acres` | Minimum tract size (default 20) |
| `radius_miles` | Miles from Lake Holiday center (default 40) |
| `center` | Label for the ring center |
| `property_types` | HomeHarvest types (`land`, `farm`) |
| `counties` / `hubs` | Discovery locations |

Acreage trust rules are code-side — see [ACREAGE.md](ACREAGE.md).

## `verification`

| Key | Meaning |
|-----|---------|
| `sold_lookback_days` / `pending_lookback_days` | Negative inventory windows |
| `dead_link_timeout_sec` | URL probe timeout |
| `consensus_min_sources` | Reserved; not fully enforced today |
| `require_reverify` | Reserved; reverify is gated by `scan.reverify_after_compile` |

## `towns` / `optional_towns`

Each town:

- `search_location` — HomeHarvest location string
- `county` — display / metadata
- `cities` — city names that map into this town
- `zips` — optional ZIP passes
- `radius_miles` — override

**Lake Holiday ≠ Sheridan.** Wildwood streets under Sandwich city map to Lake Holiday via `scanner/geo.py`.

## `distress` / `distress_passes`

Thresholds for high DOM, cheap land/mobile signals, min price-reduction percent, plus named fetch passes (`foreclosure`, `land`, `mobile`, …).

## `inactive_statuses` / `not_distressed_phrases`

Extra inactive status strings and flip/turnkey exclusion phrases.
