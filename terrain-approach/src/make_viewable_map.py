"""
Emit coverage_view.html -- the same result as coverage_map.html but with zero
external dependencies, so it renders anywhere.

No Leaflet, no tile servers. The terrain is drawn directly from the 3DEP DEM as
a hillshade on canvas, which is what the satellite basemap was only ever
standing in for: in farmland the thing worth seeing under the coverage overlay
is the relief, not the crops.
"""
import json

import numpy as np
import pandas as pd

from config import DATA, REPORTS, ROOT, SERVING_SITE
from coverage import Scorer, build_grid
from coverage_terrain import avail_threshold, fit_avail_terrain, macro_rsrp, ASSETS, fit_with_terrain, rsrp_from_node
from features import haversine_m, load_sites
from model import fit_pathloss
from propagation import DEM, TX_AGL, link_features

STRIDE = 5          # DEM downsample for the embedded hillshade

TPL = r"""<title>Where the Coverage Goes</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>
:root{--ground:#FBFCFA;--surface:#F1F4EF;--ink:#16211C;--ink2:#3A4842;--mute:#65726B;
 --rule:#C3CCBF;--c1:#0F6E70;--c2:#8F6200;--c3:#5B3A9B;--c4:#8C1D40;
 --mono:"IBM Plex Mono",ui-monospace,Consolas,monospace;
 --sans:"Archivo","Helvetica Neue",Arial,sans-serif}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
 --ground:#0E1512;--surface:#161F1B;--ink:#E5EBE7;--ink2:#BFCAC4;--mute:#8A968F;
 --rule:#38473F;--c1:#4FB3B4;--c2:#D9A227;--c3:#A98BE0;--c4:#E86A93}}
:root[data-theme=dark]{--ground:#0E1512;--surface:#161F1B;--ink:#E5EBE7;--ink2:#BFCAC4;
 --mute:#8A968F;--rule:#38473F;--c1:#4FB3B4;--c2:#D9A227;--c3:#A98BE0;--c4:#E86A93}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--sans);font-size:14px}
.app{display:grid;grid-template-columns:1fr 310px;height:100vh}
@media(max-width:860px){.app{grid-template-columns:1fr;height:auto}#stage{height:64vh;min-height:420px}}
#stage{position:relative;background:var(--surface);overflow:hidden}
canvas{display:block;width:100%;height:100%;cursor:grab}
aside{border-left:1px solid var(--rule);overflow-y:auto;padding:16px 16px 40px;background:var(--ground)}
h1{font-size:15px;margin:0 0 2px;letter-spacing:-.01em}
.sub{font-family:var(--mono);font-size:10px;letter-spacing:.09em;text-transform:uppercase;
 color:var(--c1);margin-bottom:14px}
h2{font-family:var(--mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;
 color:var(--mute);font-weight:500;margin:18px 0 7px;padding-bottom:4px;border-bottom:1px solid var(--rule)}
.stat{display:flex;justify-content:space-between;align-items:baseline;font-family:var(--mono);
 font-size:11.5px;padding:3px 0;color:var(--ink2)}
.stat b{color:var(--ink);font-size:13px;font-variant-numeric:tabular-nums}
.big{font-family:var(--sans);font-size:26px;font-weight:700;letter-spacing:-.02em;line-height:1.1}
.up{color:var(--c3);font-family:var(--mono);font-size:11px}
.lg{display:flex;align-items:center;gap:7px;font-family:var(--mono);font-size:11px;
 color:var(--ink2);margin:4px 0;cursor:pointer;user-select:none}
.lg i{width:13px;height:13px;border-radius:2px;flex:none;border:1px solid rgba(128,128,128,.35)}
.lg.off{opacity:.38}
.hint{position:absolute;left:12px;top:12px;font-family:var(--mono);font-size:10.5px;
 letter-spacing:.05em;text-transform:uppercase;color:var(--mute);background:var(--ground);
 border:1px solid var(--rule);padding:5px 8px;pointer-events:none}
.note{font-size:11px;color:var(--mute);line-height:1.5;margin-top:8px}
table{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:11px}
td{padding:2.5px 0;color:var(--ink2)}td:last-child{text-align:right;color:var(--ink);
 font-variant-numeric:tabular-nums}
</style>
<div class="app">
 <div id="stage"><canvas id="cv"></canvas><div class="hint">drag to pan &middot; scroll to zoom</div></div>
 <aside>
  <h1>Where the Coverage Goes</h1>
  <div class="sub">ARA COTS &middot; terrain-aware siting</div>

  <h2>Route coverage</h2>
  <div class="big" id="rk"></div>
  <div class="up" id="rkup"></div>
  <h2>Area coverage</h2>
  <div class="big" id="ar"></div>
  <div class="up" id="arup"></div>

  <h2>Layers</h2>
  <div id="legend"></div>

  <h2>Recommended site</h2>
  <table id="site"></table>

  <h2>Model</h2>
  <table id="model"></table>
  <div class="note">Relief is drawn from the USGS 3DEP 1/3 arc-second DEM, lit from
   the north-west. The mid-range holes follow it: between 2 and 6 km a Fresnel-obstructed
   cell is about 2.3&times; more likely to have no service than a clear one the same
   distance out.</div>
 </aside>
</div>
<script>
const D=__DATA__;
const C=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const cv=document.getElementById('cv'),cx=cv.getContext('2d');
let VW=0,VH=0,zoom=1,panX=0,panY=0,drag=null;
const on={dead:1,fixed:1,nocell:1,served:0,relief:1};
const B=D.bounds,kx=Math.cos(42*Math.PI/180);

function fit(){const d=devicePixelRatio||1;VW=cv.clientWidth;VH=cv.clientHeight;
 cv.width=VW*d;cv.height=VH*d;cx.setTransform(d,0,0,d,0,0);}
function scl(){return Math.min(VW/((B[3]-B[1])*kx),VH/(B[2]-B[0]))*0.94*zoom;}
function proj(la,lo){const s=scl();
 return [VW/2+(lo-(B[1]+B[3])/2)*kx*s+panX, VH/2-(la-(B[0]+B[2])/2)*s+panY];}

/* hillshade, computed once into an offscreen canvas then scaled */
const shade=document.createElement('canvas');
(function(){
 const H=D.dem.ny,W=D.dem.nx,z=D.dem.z;
 shade.width=W;shade.height=H;
 const g=shade.getContext('2d'),img=g.createImageData(W,H);
 const dark=matchMedia('(prefers-color-scheme:dark)').matches;
 for(let i=0;i<H;i++)for(let j=0;j<W;j++){
   const i0=Math.max(0,i-1),i1=Math.min(H-1,i+1),j0=Math.max(0,j-1),j1=Math.min(W-1,j+1);
   const dzdx=(z[i*W+j1]-z[i*W+j0])/(2*D.dem.ew);
   const dzdy=(z[i1*W+j]-z[i0*W+j])/(2*D.dem.ns);
   // illuminate from the north-west at 45 deg
   let v=(1+( -dzdx*0.7071 + dzdy*0.7071))/2;
   v=Math.max(0,Math.min(1,0.5+2.6*(v-0.5)));
   const base=dark?38:214, rng=dark?46:44;
   const g2=Math.round(base+rng*(v-0.5)*2);
   const k=(i*W+j)*4;
   img.data[k]=g2; img.data[k+1]=Math.round(g2*(dark?1.03:1.0));
   img.data[k+2]=Math.round(g2*(dark?0.98:0.96)); img.data[k+3]=255;
 }
 g.putImageData(img,0,0);
})();

function draw(){
 cx.clearRect(0,0,VW,VH);cx.fillStyle=C('--surface');cx.fillRect(0,0,VW,VH);
 const [x0,y0]=proj(D.dem.n,D.dem.w),[x1,y1]=proj(D.dem.s,D.dem.e);
 if(on.relief){cx.imageSmoothingEnabled=true;cx.globalAlpha=1;
   cx.drawImage(shade,x0,y0,x1-x0,y1-y0);}
 const s=scl(),cell=D.cell_deg*s;
 const sz=Math.max(1.2,cell);
 D.cells.forEach(c=>{
   if(c[2]===1)return;                    // already covered
   const fixed=c[3]===1;
   if(fixed?!on.fixed:!on.dead)return;
   const [x,y]=proj(c[0],c[1]);
   if(x<-20||x>VW+20||y<-20||y>VH+20)return;
   cx.globalAlpha=fixed?.62:.4;
   cx.fillStyle=fixed?C('--c3'):C('--c4');
   cx.fillRect(x-sz/2,y-sz/2,sz,sz);
 });
 cx.globalAlpha=1;
 const r=Math.max(1,1.5*Math.sqrt(zoom));
 D.pts.forEach(p=>{
   if(p[2]?!on.served:!on.nocell)return;
   const [x,y]=proj(p[0],p[1]);
   if(x<-5||x>VW+5||y<-5||y>VH+5)return;
   cx.globalAlpha=.8;cx.fillStyle=p[2]?C('--c1'):C('--c4');
   cx.beginPath();cx.arc(x,y,r,0,7);cx.fill();
 });
 cx.globalAlpha=1;
 // link between tower and recommendation
 const [mx,my]=proj(D.macro.lat,D.macro.lon),[sx,sy]=proj(D.site.lat,D.site.lon);
 cx.strokeStyle=C('--c2');cx.lineWidth=1.6;cx.setLineDash([6,5]);
 cx.beginPath();cx.moveTo(mx,my);cx.lineTo(sx,sy);cx.stroke();cx.setLineDash([]);
 const pin=(x,y,fill,label,rr)=>{
   cx.beginPath();cx.arc(x,y,rr,0,7);cx.fillStyle=fill;cx.fill();
   cx.lineWidth=2.5;cx.strokeStyle=C('--ground');cx.stroke();
   cx.fillStyle=C('--ink');cx.font='600 11px '+C('--mono');
   cx.fillText(label,x+rr+5,y+4);
 };
 pin(mx,my,C('--ink'),'existing tower',7);
 pin(sx,sy,C('--c2'),'RECOMMENDED',9);
}

function legend(){
 const L=[['dead','Predicted dead now',C('--c4')],
          ['fixed','Fixed by new site',C('--c3')],
          ['nocell','Measured: no cell',C('--c4')],
          ['served','Measured: had service',C('--c1')],
          ['relief','Terrain relief','linear-gradient(135deg,#999,#ddd)']];
 document.getElementById('legend').innerHTML=L.map(([k,t,c])=>
  `<div class="lg ${on[k]?'':'off'}" data-k="${k}"><i style="background:${c}"></i>${t}</div>`).join('');
 document.querySelectorAll('.lg').forEach(el=>el.onclick=()=>{
   on[el.dataset.k]=!on[el.dataset.k];legend();draw();});
}
document.getElementById('rk').textContent=D.after.rk.toFixed(1)+' / '+D.tot.rk.toFixed(0)+' km';
document.getElementById('rkup').textContent=
 `${(100*D.before.rk/D.tot.rk).toFixed(1)}% → ${(100*D.after.rk/D.tot.rk).toFixed(1)}%  (+${(D.after.rk-D.before.rk).toFixed(1)} km)`;
document.getElementById('ar').textContent=D.after.ar.toFixed(0)+' / '+D.tot.ar.toFixed(0)+' km²';
document.getElementById('arup').textContent=
 `${(100*D.before.ar/D.tot.ar).toFixed(1)}% → ${(100*D.after.ar/D.tot.ar).toFixed(1)}%  (+${(D.after.ar-D.before.ar).toFixed(0)} km²)`;
document.getElementById('site').innerHTML=`
 <tr><td>latitude</td><td>${D.site.lat.toFixed(5)}</td></tr>
 <tr><td>longitude</td><td>${D.site.lon.toFixed(5)}</td></tr>
 <tr><td>from tower</td><td>${(D.site.dist/1000).toFixed(2)} km</td></tr>
 <tr><td>ground</td><td>${D.site.ground.toFixed(0)} m</td></tr>
 <tr><td>mast</td><td>${D.site.agl.toFixed(0)} m</td></tr>
 <tr><td>cells fixed</td><td>${D.fixed_cells.toLocaleString()}</td></tr>`;
document.getElementById('model').innerHTML=`
 <tr><td>path-loss n</td><td>${D.model.n.toFixed(2)}</td></tr>
 <tr><td>diffraction</td><td>${D.model.bdiff.toFixed(2)} dB/dB</td></tr>
 <tr><td>residual σ</td><td>${D.model.sigma.toFixed(2)} dB</td></tr>
 <tr><td>service test</td><td>≥ ${D.model.thr.toFixed(1)} dBm</td></tr>
 <tr><td>DEM relief</td><td>${D.model.relief.toFixed(0)} m</td></tr>`;
cv.addEventListener('mousedown',e=>{drag={x:e.offsetX,y:e.offsetY,px:panX,py:panY};});
addEventListener('mousemove',e=>{if(!drag)return;const b=cv.getBoundingClientRect();
 panX=drag.px+(e.clientX-b.left-drag.x);panY=drag.py+(e.clientY-b.top-drag.y);draw();});
addEventListener('mouseup',()=>drag=null);
cv.addEventListener('wheel',e=>{e.preventDefault();
 zoom=Math.max(.6,Math.min(18,zoom*(e.deltaY<0?1.15:1/1.15)));draw();},{passive:false});
addEventListener('resize',()=>{fit();draw();});
matchMedia('(prefers-color-scheme:dark)').addEventListener('change',()=>location.reload());
fit();legend();draw();
</script>"""


def build(verbose=True):
    dem = DEM()
    df = pd.read_csv(DATA / "labeled_terrain.csv", dtype={"cellid": str})
    plf = fit_pathloss(df);     pl = fit_with_terrain(df)
    df["outage"] = df.cellid.isna() | df.cellid.eq("FFFFFFFFF")
    av = fit_avail_terrain(df, pl, dem)
    thr = avail_threshold(av, 0.50)
    cells = build_grid(df); sc = Scorer(cells)
    clat, clon = cells.lat.to_numpy(), cells.lon.to_numpy()
    sites, _ = load_sites(); tl, to = sites[SERVING_SITE]

    before = macro_rsrp(pl, dem, clat, clon)

    res = json.load((REPORTS / "coverage_terrain.json").open())
    s = res["assets"]["macro"]["sites"][0]; A = ASSETS["macro"]
    Fs = link_features(dem, s["lat"], s["lon"], clat, clon, tx_agl=A["agl"])
    ds = haversine_m(s["lat"], s["lon"], clat, clon)
    after = np.maximum(before, rsrp_from_node(pl, ds, Fs["diff_db"], A["deficit"],
                                          Fs["fresnel_frac"]))
    cb, ca = before >= thr, after >= thr
    rkb, arb = sc.parts(cb); rka, ara = sc.parts(ca)

    z = dem.z[::STRIDE, ::STRIDE]
    served = df.cellid.notna() & df.cellid.ne("FFFFFFFFF")
    data = {
        "dem": {"ny": int(z.shape[0]), "nx": int(z.shape[1]),
                "z": [int(round(float(v))) for v in np.nan_to_num(z, nan=float(np.nanmedian(z))).ravel()],
                "n": float(dem.lats[0]), "s": float(dem.lats[-1]),
                "w": float(dem.lons[0]), "e": float(dem.lons[-1]),
                "ns": float(abs(dem.dlat) * STRIDE * 111320),
                "ew": float(abs(dem.dlon) * STRIDE * 111320 * np.cos(np.radians(42)))},
        "cells": [[round(float(x), 5), round(float(y), 5), int(p), int(q)]
                  for x, y, p, q in zip(clat, clon, cb, ca)],
        "cell_deg": 200 / 111320.0,
        "pts": [[round(float(x), 5), round(float(y), 5), int(v)]
                for x, y, v in zip(df.lat, df.lon, served)],
        "macro": {"lat": tl, "lon": to},
        "site": {"lat": s["lat"], "lon": s["lon"], "ground": s["ground_m"],
                 "agl": A["agl"], "dist": s["dist_from_macro_m"]},
        "before": {"rk": rkb, "ar": arb}, "after": {"rk": rka, "ar": ara},
        "tot": {"rk": sc.tot_rk, "ar": sc.tot_ar},
        "fixed_cells": int((ca & ~cb).sum()),
        "bounds": [float(df.lat.min()), float(df.lon.min()),
                   float(df.lat.max()), float(df.lon.max())],
        "model": {"n": pl["n_exponent"], "bdiff": pl["b_diff"], "sigma": pl["sigma"],
                  "thr": thr, "relief": float(np.nanmax(dem.z) - np.nanmin(dem.z))},
    }
    out = ROOT / "coverage_view.html"
    out.write_text(TPL.replace("__DATA__", json.dumps(data, separators=(",", ":"))),
                   encoding="utf-8")
    if verbose:
        print(f"[view] {out} ({out.stat().st_size/1e6:.2f} MB)")
        print(f"[view] hillshade {z.shape[0]}x{z.shape[1]} from {dem.z.shape}")
    return out


if __name__ == "__main__":
    build()
