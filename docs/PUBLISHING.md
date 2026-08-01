# Publishing to GitHub Pages

GitHub Pages is the **primary** place to view results. Do not rely on a local `http.server` unless you explicitly want one for debugging.

## Live URLs

- Site root: https://pnelsonftp.github.io/illinois-property-scanner/
- Dashboard: https://pnelsonftp.github.io/illinois-property-scanner/dashboard/distressed-property-dashboard.html

`index.html` redirects the root to the dashboard.

## Remotes

| Remote | Repository | Purpose |
|--------|------------|---------|
| `public` | `PNelsonFTP/illinois-property-scanner` | Public Pages source |
| `origin` | `PNelsonFTP/distressed-property-scanner` | Private mirror |

After a refresh that should go live:

```bash
git add v2_compiled.json data/*.json dashboard/ distressed-properties/ data/last_scan.json
# plus any docs/code you intend to ship
git commit -m "Refresh live scan data and publish via GitHub Pages."
git push public HEAD:main
git push origin HEAD:main
```

Confirm Pages shows the new `Scan:` timestamp (may take a minute for CDN).

## Artifacts usually committed

- `v2_compiled.json`
- `data/new_listings_7d.json`, `data/pool_listings.json`, `data/large_land.json`, `data/last_scan.json`
- `dashboard/distressed-property-dashboard.html`
- `distressed-properties/**` (distressed markdown export)
- `index.html`, `.nojekyll` (Pages plumbing)

## Usually not committed (gitignored)

- `data/raw/` — timestamped fetch dumps
- `data/history/` — compiled snapshots & change JSON
- `data/audit/` — rejection audits

## Preferred refresh before publish

```bash
.venv/bin/python scripts/parallel_full_refresh.py --workers 3 --enable-counties
```

This rebuilds all four modes and the dashboard in one run.
