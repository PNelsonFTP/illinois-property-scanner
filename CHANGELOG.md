# Changelog

## 2026-08-01

- Documentation overhaul: README rewrite, new `docs/` set (modes, publishing, verification, acreage, architecture, configuration, operations, improvement backlog).
- Live refresh published: ~149 distressed, 93 new/7d, 58 pools, 43 large land.

## 2026-07-30

- Added **Large land (20+ ac)** mode within 40 miles of Lake Holiday (county/hub MLS sweeps, sold/pending negatives).
- Fixed acreage misreads of fractional lots (`.58` / `.43` acres).
- Land mode is all-or-nothing (does not add cities to location toggles).
- Homes-with-pools mode, $/sqft sorting, Zillow/Google-first open links.
- GitHub Pages is the primary viewing surface (`public` + `origin` remotes).

## 2026-07 (earlier)

- Optional towns: Leland, Earlville, Waterman, Sheridan.
- Reverify / audit / change-detection pipeline.
- New-to-market (7-day) view.
- Parallel full refresh script for faster discovery with a single accuracy gate.

## v3 (initial automation)

- Replaced one-time manual snapshot with live Realtor.com (HomeHarvest) scanning.
- MLS status verification; pending/contingent/sold exclusion.
- Portable project paths; interactive HTML dashboard + markdown exports.
