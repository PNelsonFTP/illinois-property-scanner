# Improvement backlog (25)

Synthesized from a multi-agent review (documentation audit, data quality, presentation, functionality) against the August 2026 codebase. Grouped by theme; ordered roughly by impact within each group.

---

## Data quality

1. **Tighten distress publish rules** — Too many score-1 / DOM-only / price-cut-only listings (including new-construction copy). Require a stronger composite (foreclosure/as-is **or** high-DOM **plus** cut) before publish.

2. **Stop scoring tiny cheap lots as top distress** — Earlville/Sheridan ~$20k subdivision lots hit `below-market` + `investor` and dominate Top Picks. Gate land distress by min acres / max lot size; ignore bare “INVESTORS” keywords.

3. **Hard-exclude renovated/turnkey when only weak tags remain** — Flip phrases still publish when `high-dom` or soft `as-is` is present. Treat flip language as exclude unless foreclosure/short-sale/tax-lien.

4. **Enforce true geo radius after classify** — Fetch uses radius, but compile only maps cities. Persist lat/lon and reject listings beyond each town’s `radius_miles`.

5. **Flag or reject large-land miles from city centroids** — ~half of large-land rows sit on city-center coords when MLS omits lat/lon. Prefer `needs_review` or a tighter inner radius for centroid-only distance.

6. **Dedup / change-detect by `property_id` first** — Empty-address rows never merge; fetch already keys by property id. Align compile dedup and change detection.

7. **Exact MLS status sets + backup/kick-out variants** — Substring inactive matching can miss near-pending statuses (e.g. “Take Backup”). Prefer normalized allow/deny sets and flags.

---

## Data completeness

8. **Scheduled county + public-record distress sources** — Realtor-only misses tax sales, sheriff sales, and off-MLS land. Add LaSalle/DeKalb/Kendall tax/sheriff ingest (even weekly CSV/manual import).

9. **Lake Holiday investor fields** — Parse waterfront, HOA dues, manufactured/lot-rent, subdivision privileges from MLS details; filterable on the dashboard.

10. **Assessor / parcel deep-links** — Attach county PIN/GIS search URLs and assessed-vs-list when available for underwriting before a drive-by.

11. **Richer new-listings discovery** — New-7d is heavily Oswego-skewed (city `past_days` only). Add ZIP (and optional county) passes like the distress path.

12. **Property-id negatives for pools & large land** — Those modes skip live reverify; strengthen sold/pending matching so leakage is less likely.

13. **Per-listing price/DOM history from archives** — Snapshots already land in `data/history/`; join them into “cut twice / DOM 120” timelines on cards.

---

## Presentation

14. **Homes-first Top Picks / default distress view** — Separate vacant lots from SFH/fixer tops so investors don’t see $20k lots as the product.

15. **Show price cuts on cards** — Data has original price / total reduced; render strikethrough and “−$X”. Add a short score legend.

16. **Land-mode place controls without polluting town toggles** — Keep global towns clean, but add city multi-select and/or max-miles slider using `miles_from_lake_holiday`.

17. **Mode-aware filters + URL deep links** — Hide irrelevant sorts per mode; add beds / exclude-land / max DOM; encode mode+filters in the hash so views are shareable.

18. **Mobile + accessibility pass** — Collapsible location panel, real focus styles, keyboard-expandable cards, `aria-pressed` on modes, image `alt` text.

19. **Markdown parity with dashboard links** — Markdown still ships Realtor-only “Source” links; prefer Zillow/Google columns and clarify distress-only scope vs Large land mode.

20. **Rename “Land” vs “Large land” in UI** — Distress type `Land` (tiny lots) vs mode `Large land (20+ ac)` confuses readers; use “Vacant lots” vs “Large tracts”.

---

## Functionality

21. **Nightly scheduled refresh + auto-publish to Pages** — GitHub Action or cron: `parallel_full_refresh.py` → commit → push `public` + `origin` → smoke-check scan timestamp.

22. **Alert digests on material changes** — Change detection already computes new/removed/price cuts; email/webhook/iMessage when Lake Holiday hits, score ≥ N, or new ≥20 ac tracts appear.

23. **“What’s new since last scan” on the dashboard** — Surface `changes-latest` (commit a slim copy; history is gitignored today) for overnight deltas across modes.

24. **Unify operator CLI / refresh profiles** — Align `scan.py` vs `parallel_full_refresh.py` (legacy default, skip flags, counties). Expose `quick` / `daily` / `full` profiles in config.

25. **Automated tests + fetch-health CI** — Pytest for Lake Holiday street classification, acreage trust (`.58` ≠ 58), flip exclusion, and a `--verify-only` smoke; fail loud when a town fetch returns empty after errors.

---

## Suggested sequencing

| Wave | Items | Outcome |
|------|-------|---------|
| 1 | 21, 22, 23 | Product loop: refresh → notice → act |
| 2 | 1–3, 14–15 | Cleaner distressed signal & presentation |
| 3 | 4–6, 9, 16–17 | Better geo + LH-specific UX |
| 4 | 8, 10, 13, 24–25 | Sources, underwriting, operator hardening |
