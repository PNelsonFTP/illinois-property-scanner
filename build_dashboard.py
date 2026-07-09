#!/usr/bin/env python3
"""Regenerate dashboard HTML from v2_compiled.json + new_listings_7d.json"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
COMPILED = PROJECT_ROOT / "v2_compiled.json"
NEW_LISTINGS = PROJECT_ROOT / "data" / "new_listings_7d.json"
OUT = PROJECT_ROOT / "dashboard" / "distressed-property-dashboard.html"

SCAN_DATE = os.environ.get("SCAN_DATE", "Unknown")
SCAN_TIME = os.environ.get("SCAN_TIME", "")
VERIFIED_NOTE = (
    "Live-verified + re-verified via Realtor.com MLS. "
    "Pending/contingent/sold/removed listings excluded. "
    "Optional towns: Leland, Earlville, Waterman, Sheridan."
)
NEW_NOTE = (
    "All active for-sale listings that came on the market in the last 7 days "
    "(geo/distance only — no distress filters). "
    "Refresh with <code>python scan.py --new-listings-only --include-optional</code>."
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


def main():
    with open(COMPILED) as f:
        data = json.load(f)

    new_data, new_days = load_new_listings()

    verified = sum(1 for p in data if "realtor.com" in (p.get("verification_source") or ""))
    reverified = sum(1 for p in data if p.get("verification_source") == "realtor.com-reverified")
    stale = sum(1 for p in data if p.get("is_stale"))
    ts = f"{SCAN_DATE} at {SCAN_TIME}" if SCAN_TIME else SCAN_DATE
    badges = compute_badges(data)
    area_stats = compute_area_stats(data)
    new_area_stats = compute_area_stats(new_data)

    towns_present = sorted({
        *(p.get("nearest_target") for p in data if p.get("nearest_target")),
        *(p.get("nearest_target") for p in new_data if p.get("nearest_target")),
    })
    town_options = "".join(f"<option>{t}</option>" for t in towns_present)

    props_json = json.dumps(data, separators=(",", ":"))
    new_json = json.dumps(new_data, separators=(",", ":"))
    badges_json = json.dumps(badges, separators=(",", ":"))
    area_json = json.dumps(area_stats, separators=(",", ":"))
    new_area_json = json.dumps(new_area_stats, separators=(",", ":"))

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
.v-stale{{color:var(--orange)}}
.cd[data-stale="1"]{{opacity:.85;border-style:dashed}}
.wrap{{max-width:1200px;margin:0 auto;padding:14px 20px}}
.mode-bar{{display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap}}
.mode-btn{{padding:8px 14px;border:1px solid var(--border);border-radius:var(--rs);background:var(--card);color:var(--text2);font-size:.8rem;font-weight:600;cursor:pointer}}
.mode-btn:hover{{border-color:var(--accent);color:var(--text)}}
.mode-btn.active{{background:var(--accent);border-color:var(--accent);color:#fff}}
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
.tp h3{{font-size:.8rem;font-weight:700;color:var(--red);margin-bottom:8px}}
.tp.new-mode h3{{color:var(--purple)}}
.tpi{{display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid rgba(239,68,68,.08);gap:10px}}
.tp.new-mode .tpi{{border-bottom-color:rgba(168,85,247,.1)}}
.tpi-a{{font-weight:600;font-size:.8rem;flex:1}}.tpi-p{{color:var(--green);font-weight:700;font-size:.8rem}}
.tpi-s{{min-width:28px;height:28px;display:flex;align-items:center;justify-content:center;border-radius:50%;font-weight:800;font-size:.7rem;color:#fff}}
.s-h{{background:var(--orange)}}.s-m{{background:var(--yellow);color:#000}}.s-l{{background:var(--green)}}
.s-new{{background:var(--purple)}}
.vb{{display:inline-flex;padding:5px 12px;background:var(--accent);color:#fff;border-radius:var(--rs);font-size:.7rem;font-weight:600}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px}}
.cd{{background:var(--card);border:1px solid var(--border);border-radius:var(--r);overflow:hidden;cursor:pointer;position:relative}}
.cd:hover{{border-color:var(--accent)}}
.cd-s{{position:absolute;top:8px;right:8px;width:32px;height:32px;display:flex;align-items:center;justify-content:center;border-radius:50%;font-weight:800;font-size:.7rem;color:#fff;z-index:2}}
.cd-ph,.cd-img{{width:100%;height:140px;object-fit:cover;background:var(--bg2)}}
.cd-ph{{display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:1.8rem}}
.cd-b{{padding:12px}}.cd-addr{{font-weight:700;font-size:.85rem}}.cd-city{{font-size:.7rem;color:var(--text2);margin:4px 0}}
.cd-price{{font-size:1.1rem;font-weight:800;color:var(--green)}}.cd-orig{{font-size:.7rem;color:var(--muted);text-decoration:line-through}}
.cd-det{{display:flex;flex-wrap:wrap;gap:8px;font-size:.7rem;color:var(--text2);margin:6px 0}}
.cd-tags{{display:flex;flex-wrap:wrap;gap:3px;margin-bottom:8px}}
.t{{padding:1px 7px;border-radius:10px;font-size:.6rem;font-weight:600}}
.t-fc{{background:rgba(239,68,68,.1);color:var(--red)}}.t-pr{{background:rgba(59,130,246,.1);color:var(--accent)}}
.t-hd{{background:rgba(107,114,128,.15);color:#9ca3af}}.t-ai{{background:rgba(234,179,8,.1);color:var(--yellow)}}
.t-d{{background:rgba(107,114,128,.1);color:#9ca3af}}
.t-new{{background:rgba(168,85,247,.15);color:var(--purple)}}
.cd-ft{{display:flex;justify-content:space-between;align-items:center}}.cd-src{{font-size:.65rem;color:var(--muted)}}
.cd-x{{display:none;padding:0 12px 12px;border-top:1px solid var(--border);margin-top:8px}}.cd.open .cd-x{{display:block}}
.xg{{display:grid;grid-template-columns:1fr 1fr;gap:4px}}.xi{{font-size:.7rem}}.xi .l{{color:var(--muted)}}
.v-ok{{color:var(--green)}}.v-warn{{color:var(--orange)}}
.src-note{{font-size:.7rem;color:var(--muted);margin-bottom:14px;padding:10px;background:var(--bg2);border-radius:var(--rs);border:1px solid var(--border)}}
.badges{{display:flex;flex-wrap:wrap;gap:5px;margin-top:10px}}
.bdg{{display:inline-flex;align-items:center;gap:3px;padding:2px 8px;border-radius:14px;font-size:.65rem;font-weight:600;background:var(--card);border:1px solid var(--border)}}
.bdg .n{{background:var(--accent);color:#fff;padding:0 5px;border-radius:8px;font-size:.6rem}}
.distress-only{{}}.new-only{{display:none}}
body.mode-new .distress-only{{display:none}}
body.mode-new .new-only{{display:block}}
body.mode-new .new-only-inline{{display:inline}}
body.mode-new .new-only-flex{{display:flex}}
.new-only-inline,.new-only-flex{{display:none}}
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
    </div>
  </div>
  <div class="badges distress-only" id="hBdg"></div>
</div></div>
<div class="wrap">
  <div class="mode-bar">
    <button type="button" class="mode-btn active" id="modeDistress" onclick="setMode('distress')">Distressed</button>
    <button type="button" class="mode-btn" id="modeNew" onclick="setMode('new')">New to market ({new_days} days)</button>
  </div>
  <div class="src-note distress-only">{VERIFIED_NOTE} Run <code>python scan.py --include-optional</code> to refresh. Use <code>--reverify-only</code> for a status-only pass.</div>
  <div class="src-note new-only">{NEW_NOTE}</div>
  <div class="ctrls">
    <div class="cg"><label>Town</label><select id="fA" onchange="go()"><option value="">All</option>{town_options}</select></div>
    <div class="cg"><label>Type</label><select id="fT" onchange="go()"><option value="">All</option><option value="SFH">Single Family</option><option value="Manufactured">Manufactured</option><option value="Land">Land</option><option value="Multi-Family">Multi-Family</option><option value="Townhome">Townhome</option></select></div>
    <div class="cg distress-only"><label>Distress</label><select id="fD" onchange="go()"><option value="">All</option><option value="foreclosure">Foreclosure</option><option value="as-is">As-Is/Fixer</option><option value="price-reduced">Price Reduced</option><option value="high-dom">High DOM</option><option value="below-market">Below Market</option></select></div>
    <div class="cg distress-only"><label>Verified</label><select id="fV" onchange="go()"><option value="">All</option><option value="live">Verified Only</option><option value="reverified">Re-verified Only</option></select></div>
    <div class="cg distress-only"><label>Freshness</label><select id="fFresh" onchange="go()"><option value="">All</option><option value="fresh">Fresh only</option><option value="stale">Stale only</option></select></div>
    <div class="cg"><label>Max Price</label><input type="number" id="fP" placeholder="No max" onchange="go()"></div>
    <div class="cg distress-only"><label>Min Score</label><select id="fS" onchange="go()"><option value="0">All</option><option value="3">3+</option><option value="4">4+</option><option value="5">5+</option></select></div>
    <div class="cg"><label>Sort</label><select id="fO" onchange="go()">
      <option value="score">Score</option>
      <option value="listed">Newest listed</option>
      <option value="dom">DOM / Age</option>
      <option value="price-asc">Price Low</option>
      <option value="price-desc">Price High</option>
    </select></div>
    <div class="cg"><label>Search</label><input type="text" id="fQ" placeholder="Address..." oninput="go()"></div>
  </div>
  <div class="rc" id="rc"></div>
  <div class="stats">
    <div class="sc"><h3>By Town</h3><table class="st" id="sA"></table></div>
    <div class="sc distress-only"><h3>Distress Types</h3><table class="st" id="sD"></table></div>
    <div class="sc"><h3>Property Types</h3><table class="st" id="sT"></table></div>
  </div>
  <div class="tp" id="tpBox"><h3 id="tpTitle">Top Picks</h3><div id="tpL"></div></div>
  <div class="grid" id="grd"></div>
</div>
<script>
const PD={props_json};
const PN={new_json};
const B={badges_json};
const ASD={area_json};
const ASN={new_area_json};
const NEW_DAYS={new_days};
const TC={{'foreclosure':'t-fc','as-is':'t-ai','as is':'t-ai','fixer':'t-ai','price-reduced':'t-pr','high-dom':'t-hd','below-market':'t-d','investor':'t-ai','estate':'t-d'}};
let mode='distress';
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
function setMode(m){{
  mode=m;
  document.body.classList.toggle('mode-new', m==='new');
  $('modeDistress').classList.toggle('active', m==='distress');
  $('modeNew').classList.toggle('active', m==='new');
  const sort=$('fO');
  if(m==='new'){{
    if(sort.value==='score')sort.value='listed';
    $('tpTitle').textContent='Newest listings';
    $('tpBox').classList.add('new-mode');
    $('hdrCount').textContent=PN.length+' new listings';
  }}else{{
    if(sort.value==='listed')sort.value='score';
    $('tpTitle').textContent='Top Picks';
    $('tpBox').classList.remove('new-mode');
    $('hdrCount').textContent=PD.length+' properties';
  }}
  renderStats();
  go();
}}
function renderStats(){{
  const P=mode==='new'?PN:PD;
  const AS=mode==='new'?ASN:ASD;
  let h='';
  AS.forEach(a=>{{h+=`<tr><td>${{a.area}}</td><td>${{a.count}}</td><td>${{a.avgPrice}}</td><td>${{a.avgDom}} ${{mode==='new'?'days':'DOM'}}</td></tr>`}});
  $('sA').innerHTML=h||'<tr><td colspan="4">No data yet — run new-listings scan</td></tr>';
  if(mode==='distress'){{
    h='';B.forEach(b=>{{h+=`<tr><td>${{b.tag}}</td><td>${{b.count}}</td></tr>`}});$('sD').innerHTML=h;
    $('hBdg').innerHTML=B.map(b=>`<span class="bdg">${{b.tag}}<span class="n">${{b.count}}</span></span>`).join('');
  }}
  h='';const ty={{}};P.forEach(p=>{{ty[p.property_type]=(ty[p.property_type]||0)+1}});
  Object.entries(ty).sort((a,b)=>b[1]-a[1]).forEach(([k,v])=>{{h+=`<tr><td>${{k}}</td><td>${{v}}</td></tr>`}});
  $('sT').innerHTML=h||'<tr><td colspan="2">—</td></tr>';
}}
function go(){{
  const P=mode==='new'?PN:PD;
  let f=[...P];
  const a=$('fA').value,t=$('fT').value,d=$('fD').value,v=$('fV').value,fr=$('fFresh').value,mp=parseFloat($('fP').value)||Infinity,ms=parseInt($('fS').value)||0,o=$('fO').value,q=$('fQ').value.toLowerCase().trim();
  if(a)f=f.filter(p=>p.nearest_target===a);
  if(t)f=f.filter(p=>p.property_type===t);
  if(mode==='distress'){{
    if(v==='live')f=f.filter(p=>(p.verification_source||'').includes('realtor.com'));
    if(v==='reverified')f=f.filter(p=>p.verification_source==='realtor.com-reverified');
    if(fr==='fresh')f=f.filter(p=>!p.is_stale);
    if(fr==='stale')f=f.filter(p=>p.is_stale);
    if(d)f=f.filter(p=>(p.distress_types||[]).some(x=>x.toLowerCase().includes(d)));
    if(ms)f=f.filter(p=>p.distress_score>=ms);
  }}
  if(mp<Infinity)f=f.filter(p=>p.list_price!=null&&p.list_price<=mp);
  if(q)f=f.filter(p=>(p.address+' '+(p.notes||'')+' '+(p.distress_types||[]).join(' ')+' '+(p.city||'')).toLowerCase().includes(q));
  f.sort((a,b)=>{{
    switch(o){{
      case'score':return(b.distress_score||0)-(a.distress_score||0)||(b.dom||0)-(a.dom||0);
      case'listed':{{
        const da=listDate(a),db=listDate(b);
        if(db!==da)return db.localeCompare(da);
        return (ageDays(a)??99)-(ageDays(b)??99);
      }}
      case'price-asc':return(a.list_price||1e9)-(b.list_price||1e9);
      case'price-desc':return(b.list_price||0)-(a.list_price||0);
      case'dom':return(ageDays(b)??0)-(ageDays(a)??0);
      default:return 0;
    }}
  }});
  const label=mode==='new'?`new (last ${{NEW_DAYS}}d)`:'properties';
  $('rc').innerHTML=`<strong>${{f.length}}</strong> of ${{P.length}} ${{label}}`;
  if(mode==='new'){{
    $('tpL').innerHTML=f.slice(0,8).map(p=>`<div class="tpi"><div class="tpi-s s-new">${{ageDays(p)??'—'}}</div><div class="tpi-a">${{e(p.address)}} · ${{e(p.nearest_target)}} · listed ${{e(listDate(p)||'?')}}</div><div class="tpi-p">${{fmt(p.list_price)}}</div><a href="${{e(p.listing_url)}}" target="_blank" class="vb">View →</a></div>`).join('')||'<div class="tpi"><div class="tpi-a">No new listings yet. Run the new-listings scan.</div></div>';
  }}else{{
    $('tpL').innerHTML=f.slice(0,8).map(p=>`<div class="tpi"><div class="tpi-s ${{tcl(p.distress_score)}}">${{p.distress_score}}</div><div class="tpi-a">${{e(p.address)}} · ${{e(p.nearest_target)}}</div><div class="tpi-p">${{fmt(p.list_price)}}</div><a href="${{e(p.listing_url)}}" target="_blank" class="vb">View →</a></div>`).join('');
  }}
  $('grd').innerHTML=f.map(p=>{{
    if(mode==='new'){{
      const age=ageDays(p);
      const det=[];if(p.beds!=null)det.push(p.beds+' bd');if(p.baths!=null)det.push(p.baths+' ba');
      if(listDate(p))det.push('Listed '+listDate(p));
      if(age!=null)det.push(age+'d on market');
      const img=p.photo_url?`<img class="cd-img" src="${{e(p.photo_url)}}" loading="lazy" onerror="this.outerHTML='<div class=cd-ph>🏠</div>'">`:'<div class="cd-ph">🏠</div>';
      return`<div class="cd" onclick="this.classList.toggle('open')"><div class="cd-s s-new">${{age??'N'}}</div>${{img}}<div class="cd-b">
        <div class="cd-addr">${{e(p.address)}}</div><div class="cd-city">${{e(p.city||p.nearest_target)}}, IL · ${{e(p.nearest_target)}}</div>
        <div class="cd-price">${{fmt(p.list_price)}}</div><div class="cd-det">${{det.map(d=>`<span>${{d}}</span>`).join('')}}</div>
        <div class="cd-tags"><span class="t t-new">new listing</span><span class="t t-d">${{e(p.property_type||'')}}</span></div>
        <div class="cd-ft"><a href="${{e(p.listing_url)}}" target="_blank" class="vb" onclick="event.stopPropagation()">View →</a><span class="cd-src">${{e(p.listing_source)}}</span></div>
        <div class="cd-x"><div class="xg">
          <div class="xi"><span class="l">Status:</span> <span class="v">${{e(p.status||p.mls_status)}}</span></div>
          <div class="xi"><span class="l">List date:</span> <span class="v">${{e(listDate(p)||'N/A')}}</span></div>
          <div class="xi"><span class="l">Sqft:</span> <span class="v">${{p.sqft||'N/A'}}</span></div>
          <div class="xi"><span class="l">Year:</span> <span class="v">${{p.year_built||'N/A'}}</span></div>
        </div>${{p.notes?`<div style="font-size:.7rem;color:var(--text2);margin-top:6px">${{e(String(p.notes).substring(0,300))}}</div>`:''}}</div>
      </div></div>`;
    }}
    const verified=(p.verification_source||'').includes('realtor.com');
    const rev=p.verification_source==='realtor.com-reverified';
    const tags=(p.distress_types||[]).slice(0,5).map(x=>`<span class="t ${{TC[x.toLowerCase()]||'t-d'}}">${{x}}</span>`).join('');
    const det=[];if(p.beds!=null)det.push(p.beds+' bd');if(p.baths!=null)det.push(p.baths+' ba');if(p.dom!=null)det.push(p.dom+' DOM');
    if(p.is_stale)det.push('STALE');
    const img=p.photo_url?`<img class="cd-img" src="${{e(p.photo_url)}}" loading="lazy" onerror="this.outerHTML='<div class=cd-ph>🏠</div>'">`:'<div class="cd-ph">🏠</div>';
    const vlabel=rev?'Re-verified':(verified?'Verified':'Legacy');
    const verifiedAt=p.verified_at?String(p.verified_at).replace('T',' ').slice(0,16):'N/A';
    return`<div class="cd" data-stale="${{p.is_stale?1:0}}" onclick="this.classList.toggle('open')"><div class="cd-s ${{tcl(p.distress_score)}}">${{p.distress_score}}</div>${{img}}<div class="cd-b">
      <div class="cd-addr">${{e(p.address)}}</div><div class="cd-city">${{e(p.city||p.nearest_target)}}, IL · ${{e(p.nearest_target)}}</div>
      <div class="cd-price">${{fmt(p.list_price)}}</div><div class="cd-det">${{det.map(d=>`<span>${{d}}</span>`).join('')}}</div><div class="cd-tags">${{tags}}</div>
      <div class="cd-ft"><a href="${{e(p.listing_url)}}" target="_blank" class="vb" onclick="event.stopPropagation()">View →</a><span class="cd-src">${{e(p.listing_source)}}</span></div>
      <div class="cd-x"><div class="xg">
        <div class="xi"><span class="l">Status:</span> <span class="v">${{e(p.status||p.mls_status)}}</span></div>
        <div class="xi"><span class="l">Verified:</span> <span class="v ${{verified?'v-ok':(p.is_stale?'v-stale':'v-warn')}}">${{vlabel}}</span></div>
        <div class="xi"><span class="l">Checked:</span> <span class="v">${{e(verifiedAt)}}</span></div>
        <div class="xi"><span class="l">DOM:</span> <span class="v">${{p.dom||'N/A'}}</span></div>
      </div>${{p.verification_note?`<div style="font-size:.65rem;color:var(--muted);margin-top:4px">${{e(String(p.verification_note).substring(0,200))}}</div>`:''}}
      ${{p.notes?`<div style="font-size:.7rem;color:var(--text2);margin-top:6px">${{e(String(p.notes).substring(0,300))}}</div>`:''}}</div>
    </div></div>`;
  }}).join('');
}}
renderStats();
go();
</script>
</body></html>"""

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html)
    print(
        f"Wrote dashboard: {OUT} "
        f"({len(data)} distressed, {len(new_data)} new/{new_days}d, "
        f"{verified} verified, {reverified} re-checked)"
    )


if __name__ == "__main__":
    main()
