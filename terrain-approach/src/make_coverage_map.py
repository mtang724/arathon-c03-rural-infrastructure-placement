"""
Emit coverage_map.html -- terrain, measured service, and the recommended site.

Layers: shaded relief from the 10 m DEM, the measured points coloured by whether
they had a serving cell, predicted coverage before and after the recommended
macro, and the site itself. Opened from disk so real tiles load underneath.
"""
import json

import numpy as np
import pandas as pd

from config import DATA, REPORTS, ROOT, SERVING_SITE
from coverage import Scorer, build_grid
from features import haversine_m, load_sites
from model import fit_pathloss
from propagation import DEM, TX_AGL, link_features
from coverage_terrain import avail_threshold, fit_avail_terrain, macro_rsrp, ASSETS, fit_with_terrain, rsrp_from_node

TPL = """<!doctype html><html><head><meta charset="utf-8">
<title>ARA coverage &amp; terrain</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
html,body,#map{height:100%;margin:0;font-family:ui-sans-serif,system-ui,sans-serif}
.panel{position:absolute;top:10px;right:10px;z-index:1000;background:#fff;padding:11px 13px;
 border-radius:6px;box-shadow:0 1px 8px rgba(0,0,0,.35);font-size:12px;line-height:1.55;max-width:290px}
.panel b{font-size:13px}
.sw{display:inline-block;width:11px;height:11px;border-radius:2px;vertical-align:-1px;margin-right:5px}
.dot{border-radius:50%}
hr{border:0;border-top:1px solid #ddd;margin:8px 0}
table{width:100%;font-size:11px;border-collapse:collapse}
td{padding:1px 0}td:last-child{text-align:right;font-variant-numeric:tabular-nums}
</style></head><body>
<div id="map"></div>
<div class="panel">
<b>Coverage &amp; terrain</b><br>
<span style="color:#666">service = available &ge;50% of the time</span>
<hr>
<table>
<tr><td>route-km now</td><td>__RKB__ / __RKT__</td></tr>
<tr><td>route-km with new site</td><td><b>__RKA__</b></td></tr>
<tr><td>area km&sup2; now</td><td>__ARB__ / __ART__</td></tr>
<tr><td>area km&sup2; with new site</td><td><b>__ARA__</b></td></tr>
</table>
<hr>
<span class="sw dot" style="background:#0F6E70"></span>measured: had service<br>
<span class="sw dot" style="background:#C1121F"></span>measured: no serving cell<br>
<span class="sw" style="background:#8C1D40;opacity:.55"></span>predicted dead now<br>
<span class="sw" style="background:#5B3A9B;opacity:.75"></span>fixed by new site<br>
<span class="sw dot" style="background:#000"></span>existing tower &nbsp;
<span class="sw dot" style="background:#FFD400"></span>recommended
<hr>
<span style="color:#666">DEM: USGS 3DEP 1/3 arc-second, relief __RELIEF__ m<br>
mast __AGL__ m &middot; n=__NEXP__ &middot; &sigma;=__SIG__ dB</span>
</div>
<script>
var D=__DATA__;
var map=L.map('map',{preferCanvas:true});
map.createPane('pts'); map.getPane('pts').style.zIndex=450;
var sat=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
 {maxZoom:19,attribution:'Esri'}).addTo(map);
var topo=L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
 {maxZoom:17,attribution:'OpenTopoMap'});
var osm=L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'OSM'});

var dead=L.layerGroup(), fixed=L.layerGroup(), meas=L.layerGroup(), nomeas=L.layerGroup();
var h=D.cell_deg/2;
D.cells.forEach(function(c){
  // c = [lat, lon, coveredBefore, coveredAfter]
  if(c[2]===1) return;
  var box=[[c[0]-h,c[1]-h],[c[0]+h,c[1]+h]];
  if(c[3]===1) L.rectangle(box,{stroke:false,fillColor:'#5B3A9B',fillOpacity:.40}).addTo(fixed);
  else         L.rectangle(box,{stroke:false,fillColor:'#8C1D40',fillOpacity:.25}).addTo(dead);
});
D.pts.forEach(function(p){
  L.circleMarker([p[0],p[1]],{radius:2.6,stroke:true,weight:0.6,color:'#fff',
    pane:'pts',fillColor:p[2]?'#0F6E70':'#C1121F',fillOpacity:.95}).addTo(p[2]?meas:nomeas);
});
dead.addTo(map); fixed.addTo(map); nomeas.addTo(map); meas.addTo(map);

L.circleMarker([D.macro.lat,D.macro.lon],{radius:9,color:'#fff',weight:3,
  fillColor:'#000',fillOpacity:1}).addTo(map)
  .bindTooltip('Agronomy Farm (existing)<br>'+D.macro.lat.toFixed(6)+', '+D.macro.lon.toFixed(6)+
   '<br>mast '+D.tx_agl.toFixed(1)+' m',{sticky:true});
L.circleMarker([D.site.lat,D.site.lon],{radius:11,color:'#000',weight:3,
  fillColor:'#FFD400',fillOpacity:1}).addTo(map)
  .bindTooltip('<b>RECOMMENDED</b><br>'+D.site.lat.toFixed(6)+', '+D.site.lon.toFixed(6)+
   '<br>ground '+D.site.ground_m.toFixed(0)+' m, mast '+D.site.agl+' m'+
   '<br>'+(D.site.dist_from_macro_m/1000).toFixed(2)+' km from the tower',{sticky:true,permanent:false});
L.polyline([[D.macro.lat,D.macro.lon],[D.site.lat,D.site.lon]],
  {color:'#FFD400',weight:2,dashArray:'6 5',opacity:.9}).addTo(map);

map.fitBounds(L.latLngBounds(D.bounds),{padding:[20,20]});
L.control.layers({'Satellite':sat,'Topographic':topo,'Street':osm},
 {'Predicted dead now':dead,'Fixed by new site':fixed,
  'Measured: no cell':nomeas,'Measured: served':meas}).addTo(map);
</script></body></html>"""


def build(verbose=True):
    dem = DEM()
    df = pd.read_csv(DATA / "labeled_terrain.csv", dtype={"cellid": str})
    plf = fit_pathloss(df);     pl = fit_with_terrain(df)
    df["outage"] = df.cellid.isna() | df.cellid.eq("FFFFFFFFF")
    av = fit_avail_terrain(df, pl, dem)
    r_thr = avail_threshold(av, 0.50)
    cells = build_grid(df); scorer = Scorer(cells)
    clat, clon = cells.lat.to_numpy(), cells.lon.to_numpy()
    sites, _ = load_sites(); tl, to = sites[SERVING_SITE]

    Fm = link_features(dem, tl, to, clat, clon, tx_agl=TX_AGL)
    dm = haversine_m(tl, to, clat, clon)
    az = np.arctan2(np.sin(np.radians(clon - to)) * np.cos(np.radians(clat)),
                    np.cos(np.radians(tl)) * np.sin(np.radians(clat)) -
                    np.sin(np.radians(tl)) * np.cos(np.radians(clat)) *
                    np.cos(np.radians(clon - to)))
    before = macro_rsrp(pl, dem, clat, clon)

    res = json.load((REPORTS / "coverage_terrain.json").open())
    s = res["assets"]["macro"]["sites"][0]
    A = ASSETS["macro"]
    Fs = link_features(dem, s["lat"], s["lon"], clat, clon, tx_agl=A["agl"])
    ds = haversine_m(s["lat"], s["lon"], clat, clon)
    after = np.maximum(before, rsrp_from_node(pl, ds, Fs["diff_db"], A["deficit"],
                                          Fs["fresnel_frac"]))

    cb, ca = before >= r_thr, after >= r_thr
    rkb, arb = scorer.parts(cb); rka, ara = scorer.parts(ca)
    served = df.cellid.notna() & df.cellid.ne("FFFFFFFFF")
    mdeg = GRID = (200 / 111_320.0)

    data = {
        "cells": [[round(float(la), 5), round(float(lo), 5), int(x), int(y)]
                  for la, lo, x, y in zip(clat, clon, cb, ca)],
        "cell_deg": mdeg,
        "pts": [[round(float(x), 6), round(float(y), 6), int(z)]
                for x, y, z in zip(df.lat, df.lon, served)],
        "macro": {"lat": tl, "lon": to}, "tx_agl": TX_AGL,
        "site": {"lat": s["lat"], "lon": s["lon"], "ground_m": s["ground_m"],
                 "agl": A["agl"], "dist_from_macro_m": s["dist_from_macro_m"]},
        "bounds": [[float(df.lat.min()), float(df.lon.min())],
                   [float(df.lat.max()), float(df.lon.max())]],
    }
    html = TPL.replace("__DATA__", json.dumps(data, separators=(",", ":")))
    for k, v in [("__RKB__", f"{rkb:.1f}"), ("__RKA__", f"{rka:.1f}"),
                 ("__RKT__", f"{scorer.tot_rk:.0f}"), ("__ARB__", f"{arb:.0f}"),
                 ("__ARA__", f"{ara:.0f}"), ("__ART__", f"{scorer.tot_ar:.0f}"),
                 ("__RELIEF__", f"{np.nanmax(dem.z)-np.nanmin(dem.z):.0f}"),
                 ("__AGL__", f"{A['agl']:.0f}"), ("__NEXP__", f"{pl['n_exponent']:.2f}"),
                 ("__SIG__", f"{pl['sigma']:.1f}")]:
        html = html.replace(k, v)
    out = ROOT / "coverage_map.html"
    out.write_text(html, encoding="utf-8")
    if verbose:
        print(f"[map] {out} ({out.stat().st_size/1e6:.2f} MB)")
        print(f"[map] route-km {rkb:.1f} -> {rka:.1f} of {scorer.tot_rk:.1f}")
        print(f"[map] area km2 {arb:.1f} -> {ara:.1f} of {scorer.tot_ar:.1f}")
        print(f"[map] cells fixed: {int((ca & ~cb).sum()):,} of "
              f"{int((~cb).sum()):,} currently dead")
    return out


if __name__ == "__main__":
    build()
