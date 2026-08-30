"""
Emit survey_extent.html -- the survey bounding box on real satellite imagery,
with every measurement point coloured by whether it had a serving cell.

Opened from disk this loads live tiles, so it shows the actual terrain, roads
and field boundaries underneath the survey -- which a Google Maps URL cannot be
made to do, because the URL scheme has no polygon parameter.
"""
import json

import pandas as pd

from config import DATASET, ROOT
from features import load_sites

TPL = """<!doctype html><html><head><meta charset="utf-8">
<title>ARA survey extent</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
html,body,#map{height:100%;margin:0;font-family:ui-sans-serif,system-ui,sans-serif}
.panel{position:absolute;top:10px;right:10px;z-index:1000;background:#fff;padding:10px 12px;
  border-radius:6px;box-shadow:0 1px 6px rgba(0,0,0,.3);font-size:12px;line-height:1.6;max-width:270px}
.panel b{font-size:13px}
.sw{display:inline-block;width:11px;height:11px;border-radius:50%;vertical-align:-1px;margin-right:5px}
code{background:#eee;padding:1px 4px;border-radius:3px;font-size:11px}
</style></head><body>
<div id="map"></div>
<div class="panel">
<b>ARA COTS survey extent</b><br>
11.01 &times; 16.20 km &middot; 178 km&sup2;<br>
<span style="color:#666">6.84 &times; 10.07 mi &middot; 68.8 sq mi</span>
<hr style="border:0;border-top:1px solid #ddd;margin:7px 0">
<span class="sw" style="background:#0F6E70"></span>had a serving cell (4,121)<br>
<span class="sw" style="background:#C1121F"></span>no serving cell (3,023)<br>
<span class="sw" style="background:#000"></span>base station
<hr style="border:0;border-top:1px solid #ddd;margin:7px 0">
<span style="color:#666">N</span> <code>__N__</code><br>
<span style="color:#666">S</span> <code>__S__</code><br>
<span style="color:#666">E</span> <code>__E__</code><br>
<span style="color:#666">W</span> <code>__W__</code>
</div>
<script>
var D=__DATA__;
var map=L.map('map');
var sat=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
  {maxZoom:19,attribution:'Esri World Imagery'}).addTo(map);
var osm=L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  {maxZoom:19,attribution:'OpenStreetMap'});
var b=D.box;
var rect=L.rectangle([[b.s,b.w],[b.n,b.e]],
  {color:'#FFD400',weight:3,fill:false,dashArray:'8 6'}).addTo(map);
map.fitBounds(rect.getBounds(),{padding:[24,24]});
var served=L.layerGroup(), none=L.layerGroup();
D.pts.forEach(function(p){
  L.circleMarker([p[0],p[1]],{radius:2.2,stroke:false,
    fillColor:p[2]?'#0F6E70':'#C1121F',fillOpacity:.75}).addTo(p[2]?served:none);
});
none.addTo(map); served.addTo(map);
D.sites.forEach(function(s){
  L.circleMarker([s.lat,s.lon],{radius:8,color:'#fff',weight:2,fillColor:'#000',fillOpacity:1})
    .addTo(map).bindTooltip(s.name+'<br>'+s.lat.toFixed(6)+', '+s.lon.toFixed(6),{sticky:true});
});
D.corners.forEach(function(c){
  L.marker([c[1],c[2]]).addTo(map).bindTooltip(c[0]+'  '+c[1].toFixed(6)+', '+c[2].toFixed(6),
    {permanent:false,sticky:true});
});
L.control.layers({'Satellite':sat,'Street map':osm},
  {'Had service':served,'No service':none,'Survey box':L.layerGroup([rect])}).addTo(map);
</script></body></html>"""


def build(verbose=True):
    df = pd.read_csv(DATASET / "COTS.csv", dtype={"cellid": str})
    served = df["cellid"].notna() & df["cellid"].ne("FFFFFFFFF")
    N, S = float(df.lat.max()), float(df.lat.min())
    E, W = float(df.lon.max()), float(df.lon.min())
    sites, _ = load_sites()

    data = {
        "box": {"n": N, "s": S, "e": E, "w": W},
        "pts": [[round(float(a), 6), round(float(b), 6), int(c)]
                for a, b, c in zip(df.lat, df.lon, served)],
        "sites": [{"name": k, "lat": v[0], "lon": v[1]} for k, v in sites.items()],
        "corners": [["NW corner", N, W], ["NE corner", N, E],
                    ["SE corner", S, E], ["SW corner", S, W]],
    }
    html = (TPL.replace("__DATA__", json.dumps(data, separators=(",", ":")))
               .replace("__N__", f"{N:.7f}").replace("__S__", f"{S:.7f}")
               .replace("__E__", f"{E:.7f}").replace("__W__", f"{W:.7f}"))
    out = ROOT / "survey_extent.html"
    out.write_text(html, encoding="utf-8")
    if verbose:
        print(f"[map] {out}  ({out.stat().st_size/1e6:.2f} MB)")
        print(f"[map] {len(data['pts'])} points, {int(served.sum())} served / "
              f"{int((~served).sum())} without a cell")
    return out


if __name__ == "__main__":
    build()
