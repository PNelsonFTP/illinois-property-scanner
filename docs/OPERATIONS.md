# Operations & CLI

## Recommended daily / full refresh

```bash
.venv/bin/python scripts/parallel_full_refresh.py --workers 3 --enable-counties
```

What it does:

1. Parallel distress discovery by town groups (optional towns forced on)
2. Merge → compile → full reverify + URL checks
3. Compile pools from that inventory
4. Dedicated large-land fetch/compile
5. Parallel new-listings fetch/compile
6. Rebuild markdown + dashboard

Flags:

- `--workers N` — parallel town-group workers (default 3)
- `--enable-counties` — turn on county sweeps for this run
- `--skip-new-listings` / `--skip-large-land`
- `--no-markdown` — skip rebuild
- `--new-days N` — new-listings window

Then publish: [PUBLISHING.md](PUBLISHING.md).

## Sequential `scan.py`

Useful for mode-only work or debugging.

```bash
python scan.py --no-legacy                      # full sequential
python scan.py --new-listings-only --include-optional
python scan.py --pool-listings-only --include-optional
python scan.py --large-land-only
python scan.py --reverify-only
python scan.py --verify-only --no-legacy
python scan.py --towns Sheridan,Leland --no-legacy
```

Skip flags on a full run: `--no-new-listings`, `--no-pool-listings`, `--no-large-land`, `--no-reverify`, `--no-markdown`, `--no-optional`.

**Legacy note:** `scan.py` still includes `v2-*.json` unless `--no-legacy`. Parallel refresh always excludes legacy. Prefer `--no-legacy` (or parallel) for clean live data.

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
