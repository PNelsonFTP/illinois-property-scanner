# Verification pipeline

Goal: publish only listings that still look **actively for sale**, not pending/sold/off-market.

## Layers

### 1. Fetch-time filters

- `exclude_pending=True` on for-sale HomeHarvest queries (`config.yaml` → `scan.exclude_pending`).
- Separate **sold** and **pending** inventories are fetched and tagged `_negative_check` (not published as inventory).

### 2. MLS status gate (`scanner/status.py`)

`is_verified_active()` rejects:

- `flags.is_pending` / `flags.is_contingent`
- Inactive MLS/status strings (sold, pending, contingent, under contract, expired, withdrawn, cancelled, off market, coming soon, …)
- Configurable extras via `inactive_statuses` in `config.yaml`

### 3. Compile-time negatives (`scanner/verify.py`)

Compiled candidates are checked against the sold/pending index from the same (or provided) raw fetch. Address-key matching is used; property-id matching is preferred where available.

### 4. Post-compile reverify (distressed path)

On full `scan.py` / `parallel_full_refresh.py` distressed compile:

- Batch re-fetch current for-sale by location
- Optional listing URL probes (`scan.check_listing_urls`)
- Consensus / staleness annotation (`scanner/audit.py`)

**Note:** Pool and large-land modes currently call `reverify_properties(..., do_reverify=False, check_urls=False)` and rely on the negative inventory from their fetch. Distressed mode gets the deepest reverify.

### 5. Audits & changes

- Rejection audits: `data/audit/rejections-*-latest.json` (gitignored)
- Change detection vs prior distressed compile: newly active / removed / price cuts
- Staleness flag when `verified_at` is older than `scan.stale_hours`

## Mode differences

| Mode | Sold/pending negatives | Live re-fetch reverify | URL checks |
|------|------------------------|------------------------|------------|
| Distressed | Yes | Yes (full path) | Yes (when enabled; often 429/inconclusive) |
| New 7d | Via its fetch | No deep pass | No |
| Pools | Via residential raw | No | No |
| Large land | Via land fetch | No | No |
| Caves / bunkers | Via caves hub fetch (all hubs) | No | No |
| Wheaton for-sale | Via Wheaton city + ZIP fetch | Live reverify when enabled in scan path | No |

## Operator tips

- Use `python scan.py --reverify-only` for a status-only distressed pass.
- If URL checks return widespread HTTP 429, treat them as inconclusive — do not assume links are dead.
- Prefer `parallel_full_refresh.py` for production refreshes so reverify runs once on the merged set.
