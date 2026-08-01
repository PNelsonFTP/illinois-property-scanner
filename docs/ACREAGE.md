# Large-land acreage rules

Configured in `config.yaml` under `large_land` (defaults: **≥20 acres**, **≤40 miles** from Lake Holiday, IL).

Implementation: `scanner/large_land.py`.

## Why this exists

Marketing copy often says `.58 Acre lot` or `.43 Acre lot`. A naive regex that ignores the leading decimal reads those as **58** and **43** acres and incorrectly publishes house lots as “large land.”

## Trusted sources (preferred order)

1. **MLS `Lot Size Acres:`** detail line → `mls_lot_size_acres`
2. **Description `lot_sqft`** → acres = sqft / 43,560 → `description_lot_sqft`
3. **MLS `Lot Size Square Feet:`** → `mls_lot_sqft`
4. **`Lot Size Dimensions: N ACRE`** (e.g. `.71 ACRE`) → `mls_dimensions_acres`
5. **Feet dimensions** (e.g. `110 X 232.7 X …`) → first length×width / 43,560 → `mls_dimensions_feet`

These tags are stored on each record as `acres_source`.

## Text fallback (last resort)

Free-text parsing:

- Captures leading-dot fractions (`.58` → 0.58)
- Scrubs amenity phrases like “23-acre recreational lake”
- Prefer lot-context windows (“lot”, “parcel”, “tract”)
- If small-lot and large-tract numbers conflict without MLS acres/sqft, prefer the **small** lot

Large tracts published from text alone are tracked as `accepted_text_acres` in compile stats. Prefer MLS-backed acres in production data.

## Distance gate

`miles_from_lake_holiday` uses listing coordinates when present, otherwise city-center fallbacks in `scanner/geo.py` (`CITY_CENTER_COORDS`). City-center miles are approximate — edge cases can wrong-include/exclude.

## Specialty sites

LandWatch / Lands of America / Zillow land pages block automated scraping (HTTP 403). The scanner attaches **search links** for manual cross-check; they are not inventory sources.

## Regression checklist

When changing acreage logic, verify these stay **under 20 acres** (excluded):

- Minooka `2813 Ninovan Ln` — `.58 Acre` + 110×232 dimensions
- Sandwich Lafayette vacant lot — `.43 Acre` + ~134×143 dimensions
- Peru `70X Wenzel Rd` — dimensions `.71 ACRE`
