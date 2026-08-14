# Public-record CSV import

Drop one or more `.csv` files here to add off-MLS distress candidates (tax sales, sheriff sales, county notices, etc.). The scanner loads every `*.csv` on compile when wired via the `full` profile; an empty directory is a no-op.

## How to load

1. Drop one or more `.csv` files into this directory (`data/public_records/`).
2. Run a refresh that enables public records:
   - `python scan.py refresh full`, or
   - `scripts/parallel_full_refresh.py ... --include-public-records`
3. Suggested counties to source from: **LaSalle**, **DeKalb**, **Kendall**, **DuPage**.

Do not invent fake listing rows — only real tax / sheriff / county notice data.

## Required columns

| Column | Required | Notes |
|--------|----------|-------|
| `address` | **yes** | Street address (rows without address are skipped) |
| `city` | recommended | City / mailing city |
| `state` | optional | Defaults to `IL` |
| `zip` | optional | 5-digit ZIP |
| `notes` | **yes** | Why this is a candidate (sale type, hearing date, etc.). Rows without notes are skipped. |
| `source` | optional | e.g. `LaSalle tax sale 2026`, `DeKalb sheriff`. Defaults to `public-record`. |
| `pin` | optional | Parcel / PIN when known |

Header names are case-insensitive. Alternates accepted: `zip_code` / `postal` for ZIP; `parcel` / `parcel_id` / `parcel_pin` for PIN; `note` / `description` for notes.

## Example

```csv
address,city,state,zip,notes,source,pin
123 Main St,Sandwich,IL,60548,County tax sale parcel — certificate issued 2026-03-01,DeKalb tax sale,09-12-345-000
```

## Output shape

Each valid row becomes a normalized-ish record with:

- `listing_source`: `public-record`
- `distress_types`: includes `public-record`
- `notes`: from the CSV
- optional `pin` / `parcel_id`

Master compile merges these into the distressed inventory; they are not published as Realtor listings.
