# Operations & CLI

## Named refresh profiles

```bash
python scan.py refresh quick   # reverify distressed + new listings
python scan.py refresh daily   # parallel discovery, no county sweeps
python scan.py refresh full    # parallel + counties + public-record CSV + all modes
```

Profiles are defined in `config.yaml` under `refresh_profiles`:

| Profile | Intent |
|---------|--------|
| `quick` | Reverify distressed + refresh new listings |
| `daily` | Parallel full discovery (no county sweeps) |
| `full` | Parallel + counties + public-record CSV + all modes |

## Recommended daily / full refresh

```bash
.venv/bin/python scan.py refresh full
# or directly:
.venv/bin/python scripts/parallel_full_refresh.py --workers 3 --enable-counties --include-public-records
```

What it does:

1. Parallel distress discovery by town groups (optional towns forced on)
2. Merge → compile → full reverify + URL checks (+ public CSV when enabled)
3. Compile pools from that inventory
4. Dedicated large-land fetch/compile
5. Dedicated caves/bunkers fetch/compile (ZIP 60189 ring)
6. Parallel new-listings fetch/compile (city + ZIP; counties when enabled)
7. Rebuild markdown + dashboard

Flags:

- `--workers N` — parallel town-group workers (default 3)
- `--enable-counties` — turn on county sweeps for this run
- `--include-public-records` — merge `data/public_records/*.csv`
- `--skip-new-listings` / `--skip-large-land` / `--skip-pool-listings` / `--skip-caves`
- `--no-markdown` — skip rebuild
- `--new-days N` — new-listings window

Then publish: [PUBLISHING.md](PUBLISHING.md).

## Public-record CSV import

Drop tax/sheriff/off-MLS candidates into `data/public_records/*.csv` (see README there). Empty directory = no-op. Loaded on `full` profile / `--include-public-records`.

## Sequential `scan.py`

Useful for mode-only work or debugging.

```bash
python scan.py                              # full sequential (legacy off by default)
python scan.py --include-legacy             # opt in to curated v2-*.json
python scan.py --new-listings-only --include-optional
python scan.py --pool-listings-only --include-optional
python scan.py --large-land-only
python scan.py --caves-only
python scan.py --reverify-only
python scan.py --verify-only
python scan.py --towns Sheridan,Leland
```

Skip flags on a full run: `--no-new-listings`, `--no-pool-listings`, `--no-large-land`, `--no-caves`, `--no-reverify`, `--no-markdown`, `--no-optional`.

**Legacy note:** Sequential and parallel paths exclude `v2-*.json` by default. Use `--include-legacy` only when needed.

## Mode docs

See [MODES.md](MODES.md).

## Troubleshooting

| Symptom | Likely cause | What to do |
|---------|--------------|------------|
| Town looks empty | Fetch swallowed an error / rate limit | Re-run that town; check logs for “Fetch failed” |
| URL checks all 429 | Realtor throttling | Ignore URL layer; rely on MLS status + negatives |
| Tiny lots in Large land | Acreage regression | See [ACREAGE.md](ACREAGE.md) checklist |
| Pages shows old scan | Push missed or CDN lag | Confirm both remotes pushed; hard-refresh |
| Local vs Pages mismatch | Viewing `file://` or old server | Use Pages URL |
