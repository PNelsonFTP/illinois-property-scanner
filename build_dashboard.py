#!/usr/bin/env python3
"""Regenerate dashboard HTML from distressed, new, pool, and large-land datasets."""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
COMPILED = PROJECT_ROOT / "v2_compiled.json"
NEW_LISTINGS = PROJECT_ROOT / "data" / "new_listings_7d.json"
POOL_LISTINGS = PROJECT_ROOT / "data" / "pool_listings.json"
LARGE_LAND = PROJECT_ROOT / "data" / "large_land.json"
CHANGES_LATEST = PROJECT_ROOT / "data" / "changes_latest.json"
OUT = PROJECT_ROOT / "dashboard" / "distressed-property-dashboard.html"

SCAN_DATE = os.environ.get("SCAN_DATE", "Unknown")
SCAN_TIME = os.environ.get("SCAN_TIME", "")
VERIFIED_NOTE = (
    "Live-verified + re-verified via Realtor.com MLS. "
    "Pending/contingent/sold/removed listings excluded. "
    "Optional towns: Leland, Earlville, Waterman, Sheridan. "
    "Score <strong>1–10</strong>: higher = stronger distress "
    "(foreclosure/as-is boost; DOM + price cuts stack; weak single signals stay low). "
    "Vacant lots under 20 ac are filtered server-side — use Large land mode for tracts. "
    "Open via <strong>Zillow</strong> or <strong>Google</strong> first — "
    "Realtor.com often blocks direct listing links after scanning."
)
NEW_NOTE = (
    "All active for-sale listings that came on the market in the last 7 days "
    "(geo/distance only — no distress filters). "
    "Refresh with <code>python scan.py --new-listings-only --include-optional</code>. "
    "Prefer Zillow/Google if Realtor.com shows a block page."
)
POOL_NOTE = (
    "All active residential listings with structured MLS evidence of a "
    "private or community pool. Geo/distance rules apply; distress and "
    "listing-age filters do not. Pool type is labeled on every property."
)
LAND_NOTE = (
    "Active land and farm tracts of <strong>20+ acres</strong> within "
    "<strong>40 miles of Lake Holiday, IL</strong> — shown as one list "
    "(no town toggles). Sold/pending/contingent listings are excluded. "
    "MLS/Realtor-sourced; each card also links to LandWatch, Lands of America, "
    "Zillow, and Google for cross-checks."
)


def compute_badges(data):
    counts = Counter()
    for p in data:
        for t in p.get("distress_types", []):
            counts[t.lower()] += 1
    return [{"tag": k, "count": v} for k, v in counts.most_common(12)]


def compute_area_stats(data):
    stats = {}
    for p in data:
        area = p.get("nearest_target", "Unknown")
        if area not in stats:
            stats[area] = {"count": 0, "prices": [], "doms": []}
        stats[area]["count"] += 1
        if p.get("list_price"):
            stats[area]["prices"].append(p["list_price"])
        if p.get("dom") is not None:
            stats[area]["doms"].append(p["dom"])
        elif p.get("days_since_listed") is not None:
            stats[area]["doms"].append(p["days_since_listed"])
    result = []
    for area, s in sorted(stats.items()):
        avg_p = sum(s["prices"]) / len(s["prices"]) if s["prices"] else 0
        avg_d = sum(s["doms"]) / len(s["doms"]) if s["doms"] else 0
        result.append({
            "area": area,
            "count": s["count"],
            "avgPrice": f"${avg_p:,.0f}" if avg_p else "N/A",
            "avgDom": str(int(avg_d)) if avg_d else "N/A",
        })
    return result


def load_new_listings():
    if not NEW_LISTINGS.exists():
        return [], 7
    with open(NEW_LISTINGS) as f:
        payload = json.load(f)
    if isinstance(payload, list):
        return payload, 7
    return payload.get("records", []), int(payload.get("window_days", 7))


def load_pool_listings():
    if not POOL_LISTINGS.exists():
        return []
    with open(POOL_LISTINGS) as f:
        payload = json.load(f)
    if isinstance(payload, list):
        return payload
    return payload.get("records", [])


def load_large_land():
    if not LARGE_LAND.exists():
        return []
    with open(LARGE_LAND) as f:
        payload = json.load(f)
    if isinstance(payload, list):
        return payload
    return payload.get("records", [])


def load_changes_latest():
    """Slim change digest committed as data/changes_latest.json (optional)."""
    if not CHANGES_LATEST.exists():
        return {}
    try:
        with open(CHANGES_LATEST) as f:
            payload = json.load(f)
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def main():
    with open(COMPILED) as f:
        data = json.load(f)

    new_data, new_days = load_new_listings()
    pool_data = load_pool_listings()
    land_data = load_large_land()
    changes = load_changes_latest()

    verified = sum(1 for p in data if "realtor.com" in (p.get("verification_source") or ""))
    reverified = sum(1 for p in data if p.get("verification_source") == "realtor.com-reverified")
    stale = sum(1 for p in data if p.get("is_stale"))
    ts = f"{SCAN_DATE} at {SCAN_TIME}" if SCAN_TIME else SCAN_DATE
    badges = compute_badges(data)
    area_stats = compute_area_stats(data)
    new_area_stats = compute_area_stats(new_data)
    pool_area_stats = compute_area_stats(pool_data)
    land_area_stats = compute_area_stats(land_data)

    # Land cities must NOT appear in location toggles — land mode is all-or-nothing.
    towns_present = sorted({
        *(p.get("nearest_target") for p in data if p.get("nearest_target")),
        *(p.get("nearest_target") for p in new_data if p.get("nearest_target")),
        *(p.get("nearest_target") for p in pool_data if p.get("nearest_target")),
    })
    towns_json = json.dumps(towns_present, separators=(",", ":"))
    town_toggles = "".join(
        f'<label class="loc-toggle" data-town="{t}">'
        f'<input type="checkbox" class="loc-cb" value="{t}" checked onchange="onTownToggle()">'
        f'<span class="loc-switch" aria-hidden="true"></span>'
        f'<span class="loc-name">{t}</span>'
        f'</label>'
        for t in towns_present
    )

    props_json = json.dumps(data, separators=(",", ":"))
    new_json = json.dumps(new_data, separators=(",", ":"))
    pool_json = json.dumps(pool_data, separators=(",", ":"))
    land_json = json.dumps(land_data, separators=(",", ":"))
    badges_json = json.dumps(badges, separators=(",", ":"))
    area_json = json.dumps(area_stats, separators=(",", ":"))
    new_area_json = json.dumps(new_area_stats, separators=(",", ":"))
    pool_area_json = json.dumps(pool_area_stats, separators=(",", ":"))
    land_area_json = json.dumps(land_area_stats, separators=(",", ":"))
    changes_json = json.dumps(changes, separators=(",", ":"))

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Distressed Property Scanner — Illinois</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --bg:#0b0d11;--bg2:#13161d;--card:#181b24;--text:#e2e4e9;--text2:#8b91a0;--muted:#5c6170;
  --accent:#3b82f6;--accent-h:#2563eb;--green:#22c55e;--green-bg:rgba(34,197,94,.1);
  --yellow:#eab308;--orange:#f97316;--red:#ef4444;--purple:#a855f7;
  --border:#222633;--r:10px;--rs:6px;
  --f:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
}}
body{{font-family:var(--f);background:var(--bg);color:var(--text);line-height:1.5}}
a{{color:var(--accent);text-decoration:none}}a:hover{{text-decoration:underline}}
.hdr{{background:var(--bg2);border-bottom:1px solid var(--border);padding:18px 20px;position:sticky;top:0;z-index:100}}
.hdr-in{{max-width:1200px;margin:0 auto}}
.hdr-top{{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px}}
.hdr h1{{font-size:1.25rem;font-weight:700}}.hdr h1 span{{color:var(--accent)}}
.hdr-meta{{display:flex;gap:14px;align-items:center;font-size:.75rem;color:var(--text2);flex-wrap:wrap}}
.hdr-meta strong{{color:var(--text)}}
.scope-badge{{background:var(--green-bg);color:var(--green);padding:2px 8px;border-radius:12px;font-size:.65rem;font-weight:600}}
.verify-badge{{background:rgba(59,130,246,.1);color:var(--accent);padding:2px 8px;border-radius:12px;font-size:.65rem;font-weight:600}}
.stale-badge{{background:rgba(249,115,22,.15);color:var(--orange);padding:2px 8px;border-radius:12px;font-size:.65rem;font-weight:600}}
.new-badge{{background:rgba(168,85,247,.15);color:var(--purple);padding:2px 8px;border-radius:12px;font-size:.65rem;font-weight:600}}
.pool-badge{{background:rgba(6,182,212,.14);color:#22d3ee;padding:2px 8px;border-radius:12px;font-size:.65rem;font-weight:600}}
.land-badge{{background:rgba(132,204,22,.14);color:#a3e635;padding:2px 8px;border-radius:12px;font-size:.65rem;font-weight:600}}
.v-stale{{color:var(--orange)}}
.cd[data-stale="1"]{{opacity:.85;border-style:dashed}}
.wrap{{max-width:1200px;margin:0 auto;padding:14px 20px}}
.mode-bar{{display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap}}
.mode-btn{{padding:8px 14px;border:1px solid var(--border);border-radius:var(--rs);background:var(--card);color:var(--text2);font-size:.8rem;font-weight:600;cursor:pointer}}
.mode-btn:hover{{border-color:var(--accent);color:var(--text)}}
.mode-btn.active{{background:var(--accent);border-color:var(--accent);color:#fff}}
.loc-panel{{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:12px;margin-bottom:12px}}
body.mode-land .loc-panel{{display:none}}
.loc-head{{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-bottom:10px}}
.loc-head h2{{font-size:.7rem;font-weight:700;color:var(--text2);text-transform:uppercase;letter-spacing:.04em}}
.loc-actions{{display:flex;gap:6px;flex-wrap:wrap}}
.loc-actions button{{padding:4px 10px;border:1px solid var(--border);border-radius:var(--rs);background:var(--card);color:var(--text2);font-size:.7rem;font-weight:600;cursor:pointer}}
.loc-actions button:hover{{border-color:var(--accent);color:var(--text)}}
.loc-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px}}
.loc-toggle{{display:flex;align-items:center;gap:10px;padding:8px 10px;background:var(--card);border:1px solid var(--border);border-radius:var(--rs);cursor:pointer;user-select:none}}
.loc-toggle:hover{{border-color:var(--accent)}}
.loc-toggle.off{{opacity:.55;border-style:dashed}}
.loc-cb{{position:absolute;opacity:0;pointer-events:none}}
.loc-switch{{position:relative;width:36px;height:20px;border-radius:999px;background:#3a3f4d;flex-shrink:0;transition:background .15s ease}}
.loc-switch::after{{content:"";position:absolute;top:2px;left:2px;width:16px;height:16px;border-radius:50%;background:#fff;transition:transform .15s ease}}
.loc-cb:checked + .loc-switch{{background:var(--accent)}}
.loc-cb:checked + .loc-switch::after{{transform:translateX(16px)}}
.loc-name{{font-size:.8rem;font-weight:600;color:var(--text)}}
.loc-meta{{font-size:.65rem;color:var(--muted);margin-left:auto}}
.ctrls{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px;margin-bottom:14px;background:var(--bg2);padding:12px;border-radius:var(--r);border:1px solid var(--border)}}
.cg label{{display:block;font-size:.65rem;font-weight:600;color:var(--text2);margin-bottom:3px;text-transform:uppercase}}
.cg select,.cg input{{width:100%;padding:6px 8px;border:1px solid var(--border);border-radius:var(--rs);background:var(--card);color:var(--text);font-size:.75rem}}
.rc{{font-size:.75rem;color:var(--text2);margin-bottom:10px}}.rc strong{{color:var(--text)}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin-bottom:16px}}
.sc{{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:14px}}
.sc h3{{font-size:.7rem;font-weight:600;color:var(--text2);margin-bottom:8px;text-transform:uppercase}}
.st{{width:100%;border-collapse:collapse}}.st td{{padding:4px 6px;font-size:.75rem;border-bottom:1px solid var(--border)}}
.st td:last-child{{text-align:right;font-weight:600}}
.tp{{background:linear-gradient(135deg,rgba(239,68,68,.06),rgba(249,115,22,.03));border:1px solid rgba(239,68,68,.15);border-radius:var(--r);padding:14px;margin-bottom:16px}}
.tp.new-mode{{background:linear-gradient(135deg,rgba(168,85,247,.08),rgba(59,130,246,.04));border-color:rgba(168,85,247,.2)}}
.tp.pool-mode{{background:linear-gradient(135deg,rgba(6,182,212,.09),rgba(59,130,246,.04));border-color:rgba(6,182,212,.24)}}
.tp.land-mode{{background:linear-gradient(135deg,rgba(132,204,22,.1),rgba(34,197,94,.04));border-color:rgba(132,204,22,.28)}}
.tp h3{{font-size:.8rem;font-weight:700;color:var(--red);margin-bottom:8px}}
.tp.new-mode h3{{color:var(--purple)}}
.tp.pool-mode h3{{color:#22d3ee}}
.tp.land-mode h3{{color:#a3e635}}
.tpi{{display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid rgba(239,68,68,.08);gap:10px}}
.tp.new-mode .tpi{{border-bottom-color:rgba(168,85,247,.1)}}
.tp.pool-mode .tpi{{border-bottom-color:rgba(6,182,212,.12)}}
.tp.land-mode .tpi{{border-bottom-color:rgba(132,204,22,.14)}}
.tpi-a{{font-weight:600;font-size:.8rem;flex:1}}.tpi-p{{color:var(--green);font-weight:700;font-size:.8rem}}
.tpi-s{{min-width:28px;height:28px;display:flex;align-items:center;justify-content:center;border-radius:50%;font-weight:800;font-size:.7rem;color:#fff}}
.s-h{{background:var(--orange)}}.s-m{{background:var(--yellow);color:#000}}.s-l{{background:var(--green)}}
.s-new{{background:var(--purple)}}
.s-pool{{background:#0891b2}}
.s-land{{background:#65a30d}}
.vb{{display:inline-flex;padding:5px 12px;background:var(--accent);color:#fff;border-radius:var(--rs);font-size:.7rem;font-weight:600}}
.vb-sm{{padding:4px 8px;font-size:.65rem;background:var(--card);color:var(--text2);border:1px solid var(--border)}}
.vb-sm:hover{{border-color:var(--accent);color:var(--text);text-decoration:none}}
.link-row{{display:flex;flex-wrap:wrap;gap:5px;align-items:center}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px}}
.cd{{background:var(--card);border:1px solid var(--border);border-radius:var(--r);overflow:hidden;cursor:pointer;position:relative}}
.cd:hover{{border-color:var(--accent)}}
.cd-s{{position:absolute;top:8px;right:8px;width:32px;height:32px;display:flex;align-items:center;justify-content:center;border-radius:50%;font-weight:800;font-size:.7rem;color:#fff;z-index:2}}
.cd-ph,.cd-img{{width:100%;height:140px;object-fit:cover;background:var(--bg2)}}
.cd-ph{{display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:1.8rem}}
.cd-b{{padding:12px}}.cd-addr{{font-weight:700;font-size:.85rem}}.cd-city{{font-size:.7rem;color:var(--text2);margin:4px 0}}
.cd-price{{font-size:1.1rem;font-weight:800;color:var(--green)}}.cd-orig{{font-size:.7rem;color:var(--muted);text-decoration:line-through;margin-left:6px;font-weight:500}}
.cd-cut{{font-size:.7rem;color:var(--orange);margin-left:6px;font-weight:700}}
.cd-det{{display:flex;flex-wrap:wrap;gap:8px;font-size:.7rem;color:var(--text2);margin:6px 0}}
.chg-strip{{display:none;font-size:.75rem;color:var(--text2);margin-bottom:12px;padding:10px 12px;background:rgba(59,130,246,.08);border:1px solid rgba(59,130,246,.25);border-radius:var(--r)}}
.chg-strip strong{{color:var(--text)}}
.chg-strip .chg-samples{{color:var(--muted)}}
body.mode-land .no-land{{display:none}}
body:not(.mode-pool) .sort-pool{{display:none}}
body:not(.mode-land) .sort-land{{display:none}}
body.mode-new .sort-distress,body.mode-pool .sort-distress,body.mode-land .sort-distress{{display:none}}
.cd-tags{{display:flex;flex-wrap:wrap;gap:3px;margin-bottom:8px}}
.t{{padding:1px 7px;border-radius:10px;font-size:.6rem;font-weight:600}}
.t-fc{{background:rgba(239,68,68,.1);color:var(--red)}}.t-pr{{background:rgba(59,130,246,.1);color:var(--accent)}}
.t-hd{{background:rgba(107,114,128,.15);color:#9ca3af}}.t-ai{{background:rgba(234,179,8,.1);color:var(--yellow)}}
.t-d{{background:rgba(107,114,128,.1);color:#9ca3af}}
.t-new{{background:rgba(168,85,247,.15);color:var(--purple)}}
.t-pool{{background:rgba(6,182,212,.15);color:#22d3ee}}
.t-land{{background:rgba(132,204,22,.16);color:#a3e635}}
.cd-ft{{display:flex;justify-content:space-between;align-items:center}}.cd-src{{font-size:.65rem;color:var(--muted)}}
.cd-x{{display:none;padding:0 12px 12px;border-top:1px solid var(--border);margin-top:8px}}.cd.open .cd-x{{display:block}}
.xg{{display:grid;grid-template-columns:1fr 1fr;gap:4px}}.xi{{font-size:.7rem}}.xi .l{{color:var(--muted)}}
.v-ok{{color:var(--green)}}.v-warn{{color:var(--orange)}}
.src-note{{font-size:.7rem;color:var(--muted);margin-bottom:14px;padding:10px;background:var(--bg2);border-radius:var(--rs);border:1px solid var(--border)}}
.badges{{display:flex;flex-wrap:wrap;gap:5px;margin-top:10px}}
.bdg{{display:inline-flex;align-items:center;gap:3px;padding:2px 8px;border-radius:14px;font-size:.65rem;font-weight:600;background:var(--card);border:1px solid var(--border)}}
.bdg .n{{background:var(--accent);color:#fff;padding:0 5px;border-radius:8px;font-size:.6rem}}
.distress-only{{}}.new-only,.pool-only,.land-only{{display:none}}
body.mode-new .distress-only,body.mode-pool .distress-only,body.mode-land .distress-only{{display:none}}
body.mode-new .new-only{{display:block}}
body.mode-new .new-only-inline{{display:inline}}
body.mode-new .new-only-flex{{display:flex}}
body.mode-pool .pool-only{{display:block}}
body.mode-pool .pool-only-inline{{display:inline}}
body.mode-pool .pool-only-flex{{display:flex}}
body.mode-land .land-only{{display:block}}
body.mode-land .land-only-inline{{display:inline}}
body.mode-land .land-only-flex{{display:flex}}
.new-only-inline,.new-only-flex,.pool-only-inline,.pool-only-flex,.land-only-inline,.land-only-flex{{display:none}}
</style>
</head>
<body>
<div class="hdr"><div class="hdr-in">
  <div class="hdr-top">
    <h1>Distressed Property Scanner — <span>Illinois</span></h1>
    <div class="hdr-meta">
      <span>Scan: {ts}</span>
      <strong id="hdrCount">{len(data)} properties</strong>
      <span class="scope-badge">core + optional towns</span>
      <span class="verify-badge distress-only">{verified} verified ({reverified} re-checked)</span>
      {f'<span class="stale-badge distress-only">{stale} stale</span>' if stale else ''}
      <span class="new-badge new-only-inline">{len(new_data)} new (last {new_days}d)</span>
      <span class="pool-badge pool-only-inline">{len(pool_data)} pool homes</span>
      <span class="land-badge land-only-inline">{len(land_data)} large tracts</span>
    </div>
  </div>
  <div class="badges distress-only" id="hBdg"></div>
</div></div>
<div class="wrap">
  <div class="mode-bar">
    <button type="button" class="mode-btn active" id="modeDistress" onclick="setMode('distress')">Distressed</button>
    <button type="button" class="mode-btn" id="modeNew" onclick="setMode('new')">New to market ({new_days} days)</button>
    <button type="button" class="mode-btn" id="modePool" onclick="setMode('pool')">Homes with pools</button>
    <button type="button" class="mode-btn" id="modeLand" onclick="setMode('land')">Large land (20+ ac)</button>
  </div>
  <div class="src-note distress-only">{VERIFIED_NOTE} Run <code>python scan.py --include-optional</code> to refresh. Use <code>--reverify-only</code> for a status-only pass.</div>
  <div class="src-note new-only">{NEW_NOTE}</div>
  <div class="src-note pool-only">{POOL_NOTE}</div>
  <div class="src-note land-only">{LAND_NOTE}</div>
  <div class="chg-strip" id="chgStrip"></div>
  <div class="loc-panel">
    <div class="loc-head">
      <h2>Locations</h2>
      <div class="loc-actions">
        <button type="button" onclick="setAllTowns(true)">All on</button>
        <button type="button" onclick="setAllTowns(false)">All off</button>
        <button type="button" onclick="invertTowns()">Invert</button>
      </div>
    </div>
    <div class="loc-grid" id="locGrid">{town_toggles}</div>
  </div>
  <div class="ctrls">
    <div class="cg"><label>Type</label><select id="fT" onchange="go()"><option value="">All</option><option value="SFH">Single Family</option><option value="Condo">Condo</option><option value="Manufactured">Manufactured</option><option value="Land">Large tracts only (rare in distress)</option><option value="Farm">Farm</option><option value="Multi-Family">Multi-Family</option><option value="Townhome">Townhome</option></select></div>
    <div class="cg pool-only"><label>Pool</label><select id="fPool" onchange="go()"><option value="">Private + community</option><option value="private">Private pool</option><option value="community">Community pool</option></select></div>
    <div class="cg land-only"><label>Min acres</label><select id="fAcres" onchange="go()"><option value="20">20+</option><option value="40">40+</option><option value="80">80+</option><option value="160">160+</option></select></div>
    <div class="cg distress-only"><label>Distress</label><select id="fD" onchange="go()"><option value="">All</option><option value="foreclosure">Foreclosure</option><option value="as-is">As-Is/Fixer</option><option value="price-reduced">Price Reduced</option><option value="high-dom">High DOM</option><option value="below-market">Below Market</option></select></div>
    <div class="cg distress-only"><label>Verified</label><select id="fV" onchange="go()"><option value="">All</option><option value="live">Verified Only</option><option value="reverified">Re-verified Only</option></select></div>
    <div class="cg distress-only"><label>Freshness</label><select id="fFresh" onchange="go()"><option value="">All</option><option value="fresh">Fresh only</option><option value="stale">Stale only</option></select></div>
    <div class="cg no-land"><label>Min beds</label><input type="number" id="fBeds" min="0" step="1" placeholder="Any" onchange="go()"></div>
    <div class="cg no-land"><label>Max DOM</label><input type="number" id="fDom" min="0" step="1" placeholder="No max" onchange="go()"></div>
    <div class="cg"><label>Max Price</label><input type="number" id="fP" placeholder="No max" onchange="go()"></div>
    <div class="cg distress-only"><label>Min Score</label><select id="fS" onchange="go()"><option value="0">All</option><option value="3">3+</option><option value="4">4+</option><option value="5">5+</option></select></div>
    <div class="cg"><label>Sort</label><select id="fO" onchange="go()">
      <option value="score" class="sort-distress">Score</option>
      <option value="listed">Newest listed</option>
      <option value="pool" class="sort-pool">Pool type</option>
      <option value="acres" class="sort-land">Acres High</option>
      <option value="ppa-asc" class="sort-land">$/acre Low</option>
      <option value="dom">DOM / Age</option>
      <option value="price-asc">Price Low</option>
      <option value="price-desc">Price High</option>
      <option value="ppsqft-asc">$/sqft Low</option>
      <option value="ppsqft-desc">$/sqft High</option>
    </select></div>
    <div class="cg"><label>Search</label><input type="text" id="fQ" placeholder="Address..." oninput="go()"></div>
  </div>
  <div class="rc" id="rc"></div>
  <div class="stats">
    <div class="sc"><h3 id="sATitle">By Town</h3><table class="st" id="sA"></table></div>
    <div class="sc distress-only"><h3>Distress Types</h3><table class="st" id="sD"></table></div>
    <div class="sc"><h3>Property Types</h3><table class="st" id="sT"></table></div>
  </div>
  <div class="tp" id="tpBox"><h3 id="tpTitle">Top Picks</h3><div id="tpL"></div></div>
  <div class="grid" id="grd"></div>
</div>
<script>
const PD={props_json};
const PN={new_json};
const PP={pool_json};
const PL={land_json};
const B={badges_json};
const ASD={area_json};
const ASN={new_area_json};
const ASP={pool_area_json};
const ASL={land_area_json};
const TOWNS={towns_json};
const NEW_DAYS={new_days};
const CHANGES={changes_json};
const LOC_KEY='dps-enabled-towns';
const TC={{'foreclosure':'t-fc','as-is':'t-ai','as is':'t-ai','fixer':'t-ai','price-reduced':'t-pr','high-dom':'t-hd','below-market':'t-d','investor':'t-ai','estate':'t-d'}};
let mode='distress';
let _hashQuiet=false;
function $(id){{return document.getElementById(id)}}
function fmt(n){{if(n==null)return'TBD';return'$'+n.toLocaleString('en-US',{{maximumFractionDigits:0}})}}
function e(s){{if(!s)return'';const d=document.createElement('div');d.textContent=s;return d.innerHTML}}
function tcl(s){{return s>=5?'s-h':s>=3?'s-m':'s-l'}}
function listDate(p){{return (p.list_date||'').toString().slice(0,10)}}
function ageDays(p){{
  if(p.days_since_listed!=null)return p.days_since_listed;
  if(p.dom!=null)return p.dom;
  return null;
}}
function ppsqft(p){{
  if(p.price_per_sqft!=null&&p.price_per_sqft>0)return p.price_per_sqft;
  if(p.list_price!=null&&p.sqft!=null&&p.sqft>0)return p.list_price/p.sqft;
  return null;
}}
function isLandFarm(p){{
  const t=(p.property_type||'').toLowerCase();
  return t==='land'||t==='farm';
}}
function priceCutAmount(p){{
  if(p.total_reduced!=null&&p.total_reduced>0)return p.total_reduced;
  if(p.original_list_price!=null&&p.list_price!=null&&p.original_list_price>p.list_price){{
    return p.original_list_price-p.list_price;
  }}
  return null;
}}
function priceBlock(p){{
  const cut=priceCutAmount(p);
  const showOrig=p.original_list_price!=null&&p.list_price!=null&&p.original_list_price>p.list_price;
  return `<div class="cd-price">${{fmt(p.list_price)}}${{showOrig?` <span class="cd-orig">${{fmt(p.original_list_price)}}</span>`:''}}${{cut?` <span class="cd-cut">−${{fmt(cut)}}</span>`:''}}</div>`;
}}
function fullAddr(p){{
  return [p.address,p.city||p.nearest_target,p.state||'IL',p.zip].filter(Boolean).join(' ');
}}
function googleUrl(p){{
  if(p.google_url)return p.google_url;
  return 'https://www.google.com/search?q='+encodeURIComponent(fullAddr(p)+' for sale');
}}
function zillowUrl(p){{
  if(p.zillow_url)return p.zillow_url;
  return 'https://www.zillow.com/homes/'+encodeURIComponent(fullAddr(p))+'_rb/';
}}
function redfinUrl(p){{
  if(p.redfin_url)return p.redfin_url;
  return 'https://www.redfin.com/stingray/do/location-search?location='+encodeURIComponent(fullAddr(p));
}}
function landwatchUrl(p){{
  if(p.landwatch_url)return p.landwatch_url;
  const q=(p.city||p.nearest_target||'')+' IL land for sale '+(p.acres?p.acres+' acres':'20+ acres');
  return 'https://www.landwatch.com/search?q='+encodeURIComponent(q);
}}
function loaUrl(p){{
  if(p.lands_of_america_url)return p.lands_of_america_url;
  return 'https://www.landsofamerica.com/search/?q='+encodeURIComponent((p.city||p.nearest_target||'')+', IL');
}}
function ppa(p){{
  if(p.price_per_acre!=null&&p.price_per_acre>0)return p.price_per_acre;
  if(p.list_price!=null&&p.acres!=null&&p.acres>0)return p.list_price/p.acres;
  return null;
}}
function linkButtons(p){{
  // Prefer Zillow/Google — Realtor.com frequently serves bot-block pages
  const z=zillowUrl(p), g=googleUrl(p), r=redfinUrl(p), rd=p.listing_url||'';
  const landExtra=mode==='land'?`<a href="${{e(landwatchUrl(p))}}" target="_blank" rel="noopener noreferrer" class="vb vb-sm">LandWatch</a>
    <a href="${{e(loaUrl(p))}}" target="_blank" rel="noopener noreferrer" class="vb vb-sm">LOA</a>`:'';
  return `<div class="link-row" onclick="event.stopPropagation()">
    <a href="${{e(z)}}" target="_blank" rel="noopener noreferrer" class="vb">Zillow →</a>
    <a href="${{e(g)}}" target="_blank" rel="noopener noreferrer" class="vb vb-sm">Google</a>
    <a href="${{e(r)}}" target="_blank" rel="noopener noreferrer" class="vb vb-sm">Redfin</a>
    ${{landExtra}}
    ${{rd?`<a href="${{e(rd)}}" target="_blank" rel="noopener noreferrer" class="vb vb-sm" title="May be blocked by Realtor.com">Realtor</a>`:''}}
  </div>`;
}}
function linkButtonsCompact(p){{
  const z=zillowUrl(p), g=googleUrl(p);
  if(mode==='land'){{
    return `<span class="link-row" onclick="event.stopPropagation()">
      <a href="${{e(z)}}" target="_blank" rel="noopener noreferrer" class="vb">Zillow →</a>
      <a href="${{e(landwatchUrl(p))}}" target="_blank" rel="noopener noreferrer" class="vb vb-sm">LandWatch</a>
    </span>`;
  }}
  return `<span class="link-row" onclick="event.stopPropagation()">
    <a href="${{e(z)}}" target="_blank" rel="noopener noreferrer" class="vb">Zillow →</a>
    <a href="${{e(g)}}" target="_blank" rel="noopener noreferrer" class="vb vb-sm">Google</a>
  </span>`;
}}
function enabledTowns(){{
  return new Set([...document.querySelectorAll('.loc-cb:checked')].map(cb=>cb.value));
}}
function syncTownVisuals(){{
  document.querySelectorAll('.loc-toggle').forEach(el=>{{
    const on=el.querySelector('.loc-cb').checked;
    el.classList.toggle('off', !on);
  }});
}}
function saveTownPrefs(){{
  try{{
    localStorage.setItem(LOC_KEY, JSON.stringify([...enabledTowns()]));
  }}catch(_err){{}}
}}
function loadTownPrefs(){{
  try{{
    const raw=localStorage.getItem(LOC_KEY);
    if(!raw)return;
    const saved=new Set(JSON.parse(raw));
    // Only apply if at least one known town is present (avoid wiping on empty/corrupt)
    const known=TOWNS.filter(t=>saved.has(t));
    if(!known.length && saved.size){{
      // Saved prefs exist but none match current towns — leave defaults (all on)
      return;
    }}
    if(!known.length)return;
    document.querySelectorAll('.loc-cb').forEach(cb=>{{
      cb.checked=saved.has(cb.value);
    }});
  }}catch(_err){{}}
}}
function onTownToggle(){{
  syncTownVisuals();
  saveTownPrefs();
  renderStats();
  go();
}}
function setAllTowns(on){{
  document.querySelectorAll('.loc-cb').forEach(cb=>{{cb.checked=!!on}});
  onTownToggle();
}}
function invertTowns(){{
  document.querySelectorAll('.loc-cb').forEach(cb=>{{cb.checked=!cb.checked}});
  onTownToggle();
}}
function currentData(){{
  if(mode==='new')return PN;
  if(mode==='pool')return PP;
  if(mode==='land')return PL;
  return PD;
}}
function currentAreaStats(){{
  if(mode==='new')return ASN;
  if(mode==='pool')return ASP;
  if(mode==='land')return ASL;
  return ASD;
}}
function renderChanges(){{
  const box=$('chgStrip');
  if(!box)return;
  const neu=CHANGES.newly_active||[];
  const rem=CHANGES.removed||CHANGES.removed_or_inactive||[];
  const cuts=CHANGES.price_cuts||[];
  if(!neu.length&&!rem.length&&!cuts.length){{box.style.display='none';return;}}
  const samples=[...neu,...cuts].map(p=>p&&p.address).filter(Boolean).slice(0,5).map(e);
  box.style.display='block';
  box.innerHTML=`<strong>Since last scan</strong> · +${{neu.length}} new · ${{rem.length}} removed · ${{cuts.length}} price cuts`+
    (samples.length?` <span class="chg-samples">· e.g. ${{samples.join(', ')}}</span>`:'');
}}
function writeHash(){{
  if(_hashQuiet)return;
  const p=new URLSearchParams();
  p.set('mode', mode);
  const towns=[...enabledTowns()];
  if(towns.length&&towns.length<TOWNS.length)p.set('towns', towns.join(','));
  const map=[['type','fT'],['distress','fD'],['verified','fV'],['fresh','fFresh'],['pool','fPool'],['acres','fAcres'],['price','fP'],['score','fS'],['beds','fBeds'],['dom','fDom'],['sort','fO'],['q','fQ']];
  map.forEach(([k,id])=>{{
    const el=$(id); if(!el)return;
    const v=(el.value||'').trim();
    if(!v||(k==='score'&&v==='0')||(k==='acres'&&v==='20'&&mode!=='land'))return;
    if(k==='acres'&&mode!=='land')return;
    if(k==='pool'&&mode!=='pool')return;
    if((k==='distress'||k==='verified'||k==='fresh'||k==='score')&&mode!=='distress')return;
    p.set(k,v);
  }});
  const next='#'+p.toString();
  if(location.hash!==next)history.replaceState(null,'',next);
}}
function applyHash(){{
  const raw=location.hash.replace(/^#/,'');
  if(!raw)return false;
  const p=new URLSearchParams(raw);
  _hashQuiet=true;
  try{{
    const m=p.get('mode');
    if(m&&['distress','new','pool','land'].includes(m)){{
      // setMode below; stash filters first
    }}
    const towns=p.get('towns');
    if(towns){{
      const want=new Set(towns.split(',').map(s=>s.trim()).filter(Boolean));
      document.querySelectorAll('.loc-cb').forEach(cb=>{{cb.checked=want.has(cb.value)}});
      syncTownVisuals();
    }}
    const setIf=(id,key)=>{{const el=$(id); if(el&&p.has(key))el.value=p.get(key);}};
    setIf('fT','type'); setIf('fD','distress'); setIf('fV','verified'); setIf('fFresh','fresh');
    setIf('fPool','pool'); setIf('fAcres','acres'); setIf('fP','price'); setIf('fS','score');
    setIf('fBeds','beds'); setIf('fDom','dom'); setIf('fO','sort'); setIf('fQ','q');
    if(m&&['distress','new','pool','land'].includes(m))setMode(m,true);
  }}finally{{_hashQuiet=false;}}
  return true;
}}
function setMode(m, fromHash){{
  mode=m;
  document.body.classList.toggle('mode-new', m==='new');
  document.body.classList.toggle('mode-pool', m==='pool');
  document.body.classList.toggle('mode-land', m==='land');
  $('modeDistress').classList.toggle('active', m==='distress');
  $('modeNew').classList.toggle('active', m==='new');
  $('modePool').classList.toggle('active', m==='pool');
  $('modeLand').classList.toggle('active', m==='land');
  const sort=$('fO');
  $('tpBox').classList.remove('new-mode','pool-mode','land-mode');
  if(m==='new'){{
    if(!fromHash&&(sort.value==='score'||sort.value==='pool'||sort.value==='acres'||sort.value==='ppa-asc'))sort.value='listed';
    $('tpTitle').textContent='Newest listings';
    $('tpBox').classList.add('new-mode');
    $('hdrCount').textContent=PN.length+' new listings';
  }}else if(m==='pool'){{
    if(!fromHash)sort.value='pool';
    $('tpTitle').textContent='Homes with pools';
    $('tpBox').classList.add('pool-mode');
    $('hdrCount').textContent=PP.length+' pool homes';
  }}else if(m==='land'){{
    if(!fromHash)sort.value='acres';
    $('tpTitle').textContent='Largest tracts';
    $('tpBox').classList.add('land-mode');
    $('hdrCount').textContent=PL.length+' large tracts';
  }}else{{
    if(!fromHash&&(sort.value==='listed'||sort.value==='pool'||sort.value==='acres'||sort.value==='ppa-asc'))sort.value='score';
    $('tpTitle').textContent='Top Picks';
    $('hdrCount').textContent=PD.length+' properties';
  }}
  renderStats();
  go();
}}
function renderStats(){{
  const P=currentData();
  const AS=currentAreaStats();
  const towns=enabledTowns();
  let h='';
  const saTitle=$('sATitle');
  if(saTitle)saTitle.textContent=mode==='land'?'By City':'By Town';
  const areas=mode==='land'?AS:AS.filter(a=>towns.has(a.area));
  areas.forEach(a=>{{h+=`<tr><td>${{a.area}}</td><td>${{a.count}}</td><td>${{a.avgPrice}}</td><td>${{a.avgDom}} ${{mode==='new'?'days':'DOM'}}</td></tr>`}});
  $('sA').innerHTML=h||'<tr><td colspan="4">No locations enabled</td></tr>';
  if(mode==='distress'){{
    h='';B.forEach(b=>{{h+=`<tr><td>${{b.tag}}</td><td>${{b.count}}</td></tr>`}});$('sD').innerHTML=h;
    $('hBdg').innerHTML=B.map(b=>`<span class="bdg">${{b.tag}}<span class="n">${{b.count}}</span></span>`).join('');
  }}
  const filtered=mode==='land'?P:P.filter(p=>towns.has(p.nearest_target));
  h='';const ty={{}};filtered.forEach(p=>{{ty[p.property_type]=(ty[p.property_type]||0)+1}});
  Object.entries(ty).sort((a,b)=>b[1]-a[1]).forEach(([k,v])=>{{h+=`<tr><td>${{k}}</td><td>${{v}}</td></tr>`}});
  $('sT').innerHTML=h||'<tr><td colspan="2">—</td></tr>';
}}
function go(){{
  const P=currentData();
  let f=[...P];
  const towns=enabledTowns();
  const t=$('fT').value,d=$('fD').value,v=$('fV').value,fr=$('fFresh').value,pt=$('fPool').value,minAc=parseFloat(($('fAcres')||{{}}).value)||20,mp=parseFloat($('fP').value)||Infinity,ms=parseInt($('fS').value)||0,o=$('fO').value,q=$('fQ').value.toLowerCase().trim();
  const minBeds=parseFloat(($('fBeds')||{{}}).value);
  const maxDom=parseFloat(($('fDom')||{{}}).value);
  // Land mode is all-or-nothing — never gated by the town toggles.
  if(mode!=='land')f=f.filter(p=>towns.has(p.nearest_target));
  if(t)f=f.filter(p=>p.property_type===t);
  if(mode==='distress'){{
    if(v==='live')f=f.filter(p=>(p.verification_source||'').includes('realtor.com'));
    if(v==='reverified')f=f.filter(p=>p.verification_source==='realtor.com-reverified');
    if(fr==='fresh')f=f.filter(p=>!p.is_stale);
    if(fr==='stale')f=f.filter(p=>p.is_stale);
    if(d)f=f.filter(p=>(p.distress_types||[]).some(x=>x.toLowerCase().includes(d)));
    if(ms)f=f.filter(p=>p.distress_score>=ms);
  }}
  if(mode==='pool'&&pt)f=f.filter(p=>(p.pool_type||'').toLowerCase().includes(pt));
  if(mode==='land')f=f.filter(p=>(p.acres||0)>=minAc);
  if(mode!=='land'&&!Number.isNaN(minBeds))f=f.filter(p=>p.beds!=null&&p.beds>=minBeds);
  if(mode!=='land'&&!Number.isNaN(maxDom))f=f.filter(p=>{{const a=ageDays(p);return a!=null&&a<=maxDom}});
  if(mp<Infinity)f=f.filter(p=>p.list_price!=null&&p.list_price<=mp);
  if(q)f=f.filter(p=>(p.address+' '+(p.notes||'')+' '+(p.distress_types||[]).join(' ')+' '+(p.pool_evidence||[]).join(' ')+' '+(p.land_evidence||[]).join(' ')+' '+(p.city||'')).toLowerCase().includes(q));
  f.sort((a,b)=>{{
    switch(o){{
      case'score':{{
        const ha=isLandFarm(a)?1:0, hb=isLandFarm(b)?1:0;
        if(ha!==hb)return ha-hb;
        return(b.distress_score||0)-(a.distress_score||0)||(b.dom||0)-(a.dom||0);
      }}
      case'listed':{{
        const da=listDate(a),db=listDate(b);
        if(db!==da)return db.localeCompare(da);
        return (ageDays(a)??99)-(ageDays(b)??99);
      }}
      case'price-asc':return(a.list_price||1e9)-(b.list_price||1e9);
      case'price-desc':return(b.list_price||0)-(a.list_price||0);
      case'ppsqft-asc':return(ppsqft(a)??1e9)-(ppsqft(b)??1e9);
      case'ppsqft-desc':return(ppsqft(b)??0)-(ppsqft(a)??0);
      case'dom':return(ageDays(b)??0)-(ageDays(a)??0);
      case'acres':return(b.acres||0)-(a.acres||0)||(a.list_price||1e9)-(b.list_price||1e9);
      case'ppa-asc':return(ppa(a)??1e9)-(ppa(b)??1e9);
      case'pool':{{
        const rank={{'Private + Community':0,'Private':1,'Community':2}};
        return(rank[a.pool_type]??9)-(rank[b.pool_type]??9)||(a.list_price||1e9)-(b.list_price||1e9);
      }}
      default:return 0;
    }}
  }});
  const label=mode==='new'?`new (last ${{NEW_DAYS}}d)`:mode==='pool'?'pool homes':mode==='land'?'large tracts':'properties';
  if(mode==='land'){{
    $('rc').innerHTML=`<strong>${{f.length}}</strong> of ${{P.length}} ${{label}} · within 40 mi of Lake Holiday`;
  }}else{{
    const onCount=towns.size;
    $('rc').innerHTML=`<strong>${{f.length}}</strong> of ${{P.length}} ${{label}} · <strong>${{onCount}}</strong>/${{TOWNS.length}} locations on`;
  }}
  if(mode==='new'){{
    $('tpL').innerHTML=f.slice(0,8).map(p=>`<div class="tpi"><div class="tpi-s s-new">${{ageDays(p)??'—'}}</div><div class="tpi-a">${{e(p.address)}} · ${{e(p.nearest_target)}} · listed ${{e(listDate(p)||'?')}}</div><div class="tpi-p">${{fmt(p.list_price)}}</div>${{linkButtonsCompact(p)}}</div>`).join('')||'<div class="tpi"><div class="tpi-a">No new listings yet. Run the new-listings scan.</div></div>';
  }}else if(mode==='pool'){{
    $('tpL').innerHTML=f.slice(0,8).map(p=>`<div class="tpi"><div class="tpi-s s-pool">🏊</div><div class="tpi-a">${{e(p.address)}} · ${{e(p.nearest_target)}} · ${{e(p.pool_type)}}</div><div class="tpi-p">${{fmt(p.list_price)}}</div>${{linkButtonsCompact(p)}}</div>`).join('')||'<div class="tpi"><div class="tpi-a">No pool homes in the enabled locations.</div></div>';
  }}else if(mode==='land'){{
    $('tpL').innerHTML=f.slice(0,8).map(p=>`<div class="tpi"><div class="tpi-s s-land">${{Math.round(p.acres||0)}}</div><div class="tpi-a">${{e(p.address)}} · ${{e(p.city||p.nearest_target)}} · ${{e(p.miles_from_lake_holiday)}} mi</div><div class="tpi-p">${{fmt(p.list_price)}}</div>${{linkButtonsCompact(p)}}</div>`).join('')||'<div class="tpi"><div class="tpi-a">No large tracts within 40 mi of Lake Holiday.</div></div>';
  }}else{{
    const homes=f.filter(p=>!isLandFarm(p));
    $('tpL').innerHTML=homes.slice(0,8).map(p=>`<div class="tpi"><div class="tpi-s ${{tcl(p.distress_score)}}">${{p.distress_score}}</div><div class="tpi-a">${{e(p.address)}} · ${{e(p.nearest_target)}}</div><div class="tpi-p">${{fmt(p.list_price)}}</div>${{linkButtonsCompact(p)}}</div>`).join('')||'<div class="tpi"><div class="tpi-a">No home Top Picks in the current filters (land/farm excluded from this list).</div></div>';
  }}
  $('grd').innerHTML=f.map(p=>{{
    if(mode==='new'){{
      const age=ageDays(p);
      const det=[];if(p.beds!=null)det.push(p.beds+' bd');if(p.baths!=null)det.push(p.baths+' ba');
      if(listDate(p))det.push('Listed '+listDate(p));
      if(age!=null)det.push(age+'d on market');
      const psf=ppsqft(p);if(psf!=null)det.push('$'+Math.round(psf)+'/sqft');
      const img=p.photo_url?`<img class="cd-img" src="${{e(p.photo_url)}}" loading="lazy" onerror="this.outerHTML='<div class=cd-ph>🏠</div>'">`:'<div class="cd-ph">🏠</div>';
      return`<div class="cd" onclick="this.classList.toggle('open')"><div class="cd-s s-new">${{age??'N'}}</div>${{img}}<div class="cd-b">
        <div class="cd-addr">${{e(p.address)}}</div><div class="cd-city">${{e(p.city||p.nearest_target)}}, IL · ${{e(p.nearest_target)}}</div>
        ${{priceBlock(p)}}<div class="cd-det">${{det.map(d=>`<span>${{d}}</span>`).join('')}}</div>
        <div class="cd-tags"><span class="t t-new">new listing</span><span class="t t-d">${{e(p.property_type||'')}}</span></div>
        <div class="cd-ft">${{linkButtons(p)}}</div>
        <div class="cd-x"><div class="xg">
          <div class="xi"><span class="l">Status:</span> <span class="v">${{e(p.status||p.mls_status)}}</span></div>
          <div class="xi"><span class="l">List date:</span> <span class="v">${{e(listDate(p)||'N/A')}}</span></div>
          <div class="xi"><span class="l">Sqft:</span> <span class="v">${{p.sqft||'N/A'}}</span></div>
          <div class="xi"><span class="l">Year:</span> <span class="v">${{p.year_built||'N/A'}}</span></div>
        </div>${{p.notes?`<div style="font-size:.7rem;color:var(--text2);margin-top:6px">${{e(String(p.notes).substring(0,300))}}</div>`:''}}</div>
      </div></div>`;
    }}
    if(mode==='pool'){{
      const det=[];if(p.beds!=null)det.push(p.beds+' bd');if(p.baths!=null)det.push(p.baths+' ba');if(p.dom!=null)det.push(p.dom+' DOM');
      const psf=ppsqft(p);if(psf!=null)det.push('$'+Math.round(psf)+'/sqft');
      const img=p.photo_url?`<img class="cd-img" src="${{e(p.photo_url)}}" loading="lazy" onerror="this.outerHTML='<div class=cd-ph>🏠</div>'">`:'<div class="cd-ph">🏠</div>';
      const evidence=(p.pool_evidence||[]).map(x=>e(x)).join(' · ');
      const verifiedAt=p.verified_at?String(p.verified_at).replace('T',' ').slice(0,16):'N/A';
      return`<div class="cd" onclick="this.classList.toggle('open')"><div class="cd-s s-pool">🏊</div>${{img}}<div class="cd-b">
        <div class="cd-addr">${{e(p.address)}}</div><div class="cd-city">${{e(p.city||p.nearest_target)}}, IL · ${{e(p.nearest_target)}}</div>
        ${{priceBlock(p)}}<div class="cd-det">${{det.map(d=>`<span>${{d}}</span>`).join('')}}</div>
        <div class="cd-tags"><span class="t t-pool">${{e(p.pool_type||'Pool')}}</span><span class="t t-d">${{e(p.property_type||'')}}</span></div>
        <div class="cd-ft">${{linkButtons(p)}}</div>
        <div class="cd-x"><div class="xg">
          <div class="xi"><span class="l">Status:</span> <span class="v">${{e(p.status||p.mls_status)}}</span></div>
          <div class="xi"><span class="l">Verified:</span> <span class="v v-ok">Live inventory</span></div>
          <div class="xi"><span class="l">Checked:</span> <span class="v">${{e(verifiedAt)}}</span></div>
          <div class="xi"><span class="l">Pool:</span> <span class="v">${{e(p.pool_type||'Yes')}}</span></div>
        </div>${{evidence?`<div style="font-size:.65rem;color:var(--muted);margin-top:4px">${{evidence}}</div>`:''}}
        ${{p.notes?`<div style="font-size:.7rem;color:var(--text2);margin-top:6px">${{e(String(p.notes).substring(0,300))}}</div>`:''}}</div>
      </div></div>`;
    }}
    if(mode==='land'){{
      const det=[];
      if(p.acres!=null)det.push(p.acres+' acres');
      if(p.miles_from_lake_holiday!=null)det.push(p.miles_from_lake_holiday+' mi from LH');
      if(p.dom!=null)det.push(p.dom+' DOM');
      const acrePrice=ppa(p);if(acrePrice!=null)det.push('$'+Math.round(acrePrice).toLocaleString('en-US')+'/acre');
      const img=p.photo_url?`<img class="cd-img" src="${{e(p.photo_url)}}" loading="lazy" onerror="this.outerHTML='<div class=cd-ph>🌾</div>'">`:'<div class="cd-ph">🌾</div>';
      const evidence=(p.land_evidence||[]).map(x=>e(x)).join(' · ');
      const verifiedAt=p.verified_at?String(p.verified_at).replace('T',' ').slice(0,16):'N/A';
      return`<div class="cd" onclick="this.classList.toggle('open')"><div class="cd-s s-land">${{Math.round(p.acres||0)}}</div>${{img}}<div class="cd-b">
        <div class="cd-addr">${{e(p.address)}}</div><div class="cd-city">${{e(p.city||p.nearest_target)}}, IL · ${{e(p.nearest_target)}}</div>
        ${{priceBlock(p)}}<div class="cd-det">${{det.map(d=>`<span>${{d}}</span>`).join('')}}</div>
        <div class="cd-tags"><span class="t t-land">${{e(p.acres)}} acres</span><span class="t t-d">${{e(p.property_type||'Land')}}</span></div>
        <div class="cd-ft">${{linkButtons(p)}}</div>
        <div class="cd-x"><div class="xg">
          <div class="xi"><span class="l">Status:</span> <span class="v">${{e(p.status||p.mls_status)}}</span></div>
          <div class="xi"><span class="l">Verified:</span> <span class="v v-ok">Live inventory</span></div>
          <div class="xi"><span class="l">Checked:</span> <span class="v">${{e(verifiedAt)}}</span></div>
          <div class="xi"><span class="l">From LH:</span> <span class="v">${{p.miles_from_lake_holiday!=null?p.miles_from_lake_holiday+' mi':'N/A'}}</span></div>
        </div>${{evidence?`<div style="font-size:.65rem;color:var(--muted);margin-top:4px">${{evidence}}</div>`:''}}
        ${{p.notes?`<div style="font-size:.7rem;color:var(--text2);margin-top:6px">${{e(String(p.notes).substring(0,300))}}</div>`:''}}</div>
      </div></div>`;
    }}
    const verified=(p.verification_source||'').includes('realtor.com');
    const rev=p.verification_source==='realtor.com-reverified';
    const tags=(p.distress_types||[]).slice(0,5).map(x=>`<span class="t ${{TC[x.toLowerCase()]||'t-d'}}">${{x}}</span>`).join('');
    const det=[];if(p.beds!=null)det.push(p.beds+' bd');if(p.baths!=null)det.push(p.baths+' ba');if(p.dom!=null)det.push(p.dom+' DOM');
    const psf=ppsqft(p);if(psf!=null)det.push('$'+Math.round(psf)+'/sqft');
    if(p.is_stale)det.push('STALE');
    const img=p.photo_url?`<img class="cd-img" src="${{e(p.photo_url)}}" loading="lazy" onerror="this.outerHTML='<div class=cd-ph>🏠</div>'">`:'<div class="cd-ph">🏠</div>';
    const vlabel=rev?'Re-verified':(verified?'Verified':'Legacy');
    const verifiedAt=p.verified_at?String(p.verified_at).replace('T',' ').slice(0,16):'N/A';
    return`<div class="cd" data-stale="${{p.is_stale?1:0}}" onclick="this.classList.toggle('open')"><div class="cd-s ${{tcl(p.distress_score)}}">${{p.distress_score}}</div>${{img}}<div class="cd-b">
      <div class="cd-addr">${{e(p.address)}}</div><div class="cd-city">${{e(p.city||p.nearest_target)}}, IL · ${{e(p.nearest_target)}}</div>
      ${{priceBlock(p)}}<div class="cd-det">${{det.map(d=>`<span>${{d}}</span>`).join('')}}</div><div class="cd-tags">${{tags}}</div>
      <div class="cd-ft">${{linkButtons(p)}}</div>
      <div class="cd-x"><div class="xg">
        <div class="xi"><span class="l">Status:</span> <span class="v">${{e(p.status||p.mls_status)}}</span></div>
        <div class="xi"><span class="l">Verified:</span> <span class="v ${{verified?'v-ok':(p.is_stale?'v-stale':'v-warn')}}">${{vlabel}}</span></div>
        <div class="xi"><span class="l">Checked:</span> <span class="v">${{e(verifiedAt)}}</span></div>
        <div class="xi"><span class="l">DOM:</span> <span class="v">${{p.dom||'N/A'}}</span></div>
      </div>${{p.verification_note?`<div style="font-size:.65rem;color:var(--muted);margin-top:4px">${{e(String(p.verification_note).substring(0,200))}}</div>`:''}}
      ${{p.notes?`<div style="font-size:.7rem;color:var(--text2);margin-top:6px">${{e(String(p.notes).substring(0,300))}}</div>`:''}}</div>
    </div></div>`;
  }}).join('');
  writeHash();
}}
loadTownPrefs();
syncTownVisuals();
renderChanges();
if(!applyHash()){{
  renderStats();
  go();
}}
window.addEventListener('hashchange',()=>{{if(!_hashQuiet)applyHash();}});
</script>
</body></html>"""

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html)
    print(
        f"Wrote dashboard: {OUT} "
        f"({len(data)} distressed, {len(new_data)} new/{new_days}d, "
        f"{len(pool_data)} pool homes, {len(land_data)} large tracts, "
        f"{verified} verified, {reverified} re-checked)"
    )


if __name__ == "__main__":
    main()
