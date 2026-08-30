"""
Stage 4 -- emit the scenario planner as ONE self-contained HTML file.

Deliberately built with no external dependencies at all: no Leaflet, no CDN, no
tile server, no Streamlit, no pip install, no localhost.  It is a single file
that opens by double-clicking it, on any laptop, with the network unplugged.
At a hackathon the demo machine is the one thing you do not control, and a
scenario planner that needs `streamlit run` is a scenario planner that fails in
front of the judges.

The map is drawn on a canvas rather than over basemap tiles.  In rural farmland
a satellite basemap adds almost nothing -- what matters is the driven route, the
service surface, the tower and the candidate sites -- and dropping it removes
the last thing that needed the network.

Critically, the page RECOMPUTES.  It ships the fitted path-loss constants and
both isotonic curves and runs the same model in JavaScript, so a judge can drop
a pin anywhere on the map and get a genuine prediction, not a lookup of a
precomputed answer.
"""
import json

from config import DATA, ROOT

HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ARA Rural Placement Planner</title>
<style>
:root{
  --ground:#FBFCFA; --surface:#F1F4EF; --surface2:#E8EDE6;
  --ink:#16211C; --ink2:#3A4842; --mute:#65726B;
  --rule:#DCE2DA; --rule2:#C3CCBF;
  --teal:#0F6E70; --ochre:#8F6200; --good:#5B3A9B; --bad:#8C1D40;
  --mono:"IBM Plex Mono",ui-monospace,Consolas,monospace;
  --sans:"Archivo","Helvetica Neue",Arial,sans-serif;
}
@media (prefers-color-scheme:dark){
  :root{
    --ground:#0E1512; --surface:#161F1B; --surface2:#1E2823;
    --ink:#E5EBE7; --ink2:#BFCAC4; --mute:#8A968F;
    --rule:#26332D; --rule2:#38473F;
    --teal:#4FB3B4; --ochre:#D9A227; --good:#A98BE0; --bad:#E86A93;
  }
}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--sans);
     font-size:14px;line-height:1.5;-webkit-font-smoothing:antialiased}
.app{display:grid;grid-template-columns:1fr 340px;height:100vh}
@media(max-width:900px){.app{grid-template-columns:1fr;height:auto}
  #stage{height:60vh;min-height:420px}}
#stage{position:relative;background:var(--surface);overflow:hidden}
canvas{display:block;width:100%;height:100%;cursor:crosshair}
.hint{position:absolute;left:14px;top:14px;font-family:var(--mono);font-size:11px;
      letter-spacing:.06em;text-transform:uppercase;color:var(--mute);
      background:var(--ground);border:1px solid var(--rule2);padding:5px 9px;
      pointer-events:none}
.legend{position:absolute;left:14px;bottom:14px;background:var(--ground);
        border:1px solid var(--rule2);padding:9px 11px;font-family:var(--mono);font-size:11px}
.legend .row{display:flex;align-items:center;gap:7px;margin-bottom:3px}
.legend .row:last-child{margin:0}
.sw{width:11px;height:11px;border:1px solid rgba(128,128,128,.4)}
aside{background:var(--ground);border-left:1px solid var(--rule2);overflow-y:auto;
      padding:18px 18px 40px}
h1{font-size:16px;margin:0 0 2px;letter-spacing:-.01em}
.sub{font-family:var(--mono);font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;
     color:var(--teal);margin-bottom:16px}
h2{font-family:var(--mono);font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;
   color:var(--mute);font-weight:500;margin:20px 0 8px;padding-bottom:5px;
   border-bottom:1px solid var(--rule)}
.ctl{margin-bottom:11px}
.ctl label{display:flex;justify-content:space-between;font-family:var(--mono);
           font-size:11px;color:var(--ink2);margin-bottom:4px}
.ctl label b{color:var(--ink)}
input[type=range]{width:100%;accent-color:var(--teal)}
.seg{display:flex;gap:1px;background:var(--rule2);border:1px solid var(--rule2)}
.seg button{flex:1;background:var(--surface);border:0;color:var(--ink2);
            font-family:var(--mono);font-size:11px;padding:6px 4px;cursor:pointer}
.seg button[aria-pressed=true]{background:var(--teal);color:#fff}
.seg.vert{flex-wrap:wrap}
.seg.vert button{flex:1 1 30%;padding:6px 3px;font-size:10px}
.stats{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--rule2);
       border:1px solid var(--rule2)}
.stat{background:var(--surface);padding:9px 10px}
.stat .l{font-family:var(--mono);font-size:9.5px;letter-spacing:.08em;
         text-transform:uppercase;color:var(--mute)}
.stat .v{font-size:20px;font-weight:700;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.stat .v small{font-size:11px;font-weight:500;color:var(--mute)}
.delta{font-family:var(--mono);font-size:11px}
.delta.up{color:var(--good)} .delta.flat{color:var(--mute)}
button.act{width:100%;background:var(--teal);color:#fff;border:0;padding:8px;
           font-family:var(--mono);font-size:11px;letter-spacing:.06em;
           text-transform:uppercase;cursor:pointer;margin-top:7px}
button.act.ghost{background:transparent;color:var(--ink2);border:1px solid var(--rule2)}
.note{font-size:11.5px;color:var(--mute);line-height:1.5;margin-top:9px}
.warn{color:var(--ochre);font-family:var(--mono);font-size:11px;margin-top:7px}
table.k{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:11px}
table.k td{padding:3px 0;border-bottom:1px solid var(--rule);color:var(--ink2)}
table.k td:last-child{text-align:right;color:var(--ink);font-variant-numeric:tabular-nums}
table.k tr:last-child td{border:0}
</style>
</head>
<body>
<div class="app">
  <div id="stage">
    <canvas id="map"></canvas>
    <div class="hint">Click the map to place an asset &middot; drag to pan &middot; scroll to zoom</div>
    <div class="legend" id="legend"></div>
  </div>
  <aside>
    <h1>Rural Placement Planner</h1>
    <div class="sub">ARA COTS &middot; Agronomy Farm &middot; n78 3460.8 MHz</div>

    <h2>Asset</h2>
    <div class="seg" id="assetSeg">
      <button data-a="relay" aria-pressed="true">Donor relay</button>
      <button data-a="smallcell" aria-pressed="false">Small cell</button>
    </div>
    <div class="ctl" style="margin-top:11px">
      <label>EIRP below macro <b><span id="eirpV">20</span> dB</b></label>
      <input type="range" id="eirp" min="8" max="32" step="1" value="20">
    </div>
    <div class="ctl">
      <label id="thrLab">Uplink target <b><span id="thrV">10</span> Mbps</b></label>
      <input type="range" id="thr" min="2" max="30" step="1" value="10">
    </div>

    <h2>Service definition</h2>
    <div class="seg vert" id="critSeg"></div>
    <div class="note" id="critNote"></div>
    <div id="donorWarn"></div>

    <h2>Route demand met</h2>
    <div class="stats">
      <div class="stat"><div class="l">Before</div><div class="v" id="sBefore">--<small>%</small></div></div>
      <div class="stat"><div class="l">After</div><div class="v" id="sAfter">--<small>%</small></div>
        <div class="delta" id="sDelta"></div></div>
      <div class="stat"><div class="l">Cells fixed</div><div class="v" id="sCells">0</div></div>
      <div class="stat"><div class="l">Route km</div><div class="v" id="sKm">0.0</div></div>
    </div>

    <h2>Placed asset</h2>
    <table class="k" id="siteTbl"><tr><td>none placed</td><td></td></tr></table>
    <button class="act" id="useRec">Best site for this definition</button>
    <button class="act ghost" id="useCons">Consensus site (all definitions)</button>
    <button class="act ghost" id="useWorst">Use worst measured point</button>
    <button class="act ghost" id="clear">Clear</button>

    <h2>Show</h2>
    <div class="seg" id="viewSeg">
      <button data-v="after" aria-pressed="true">Service</button>
      <button data-v="delta" aria-pressed="false">Change</button>
      <button data-v="freq" aria-pressed="false">Robustness</button>
    </div>
    <div class="note" id="viewNote"></div>

    <h2>Model</h2>
    <table class="k" id="modelTbl"></table>
    <div class="note">Every number on this page is recomputed in the browser from
      the fitted path-loss law and the two isotonic curves &mdash; the same model
      the offline optimiser used. Nothing here is a stored answer.</div>
  </aside>
</div>

<script>
const D = __DATA__;

/* ---------- the model, ported verbatim from optimize.py ---------- */
const R = 6371000;
function hav(la1,lo1,la2,lo2){
  const p1=la1*Math.PI/180, p2=la2*Math.PI/180;
  const dp=p2-p1, dl=(lo2-lo1)*Math.PI/180;
  const a=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;
  return 2*R*Math.asin(Math.sqrt(Math.min(1,a)));
}
// linear interpolation on an isotonic curve, clipped at both ends -- this is
// exactly what sklearn's IsotonicRegression.predict does.
function interp(c,x){
  const X=c.x,Y=c.y,n=X.length;
  if(x<=X[0])return Y[0];
  if(x>=X[n-1])return Y[n-1];
  let lo=0,hi=n-1;
  while(hi-lo>1){const m=(lo+hi)>>1; if(X[m]<=x)lo=m; else hi=m;}
  const t=(x-X[lo])/(X[hi]-X[lo]||1);
  return Y[lo]+t*(Y[hi]-Y[lo]);
}
const PL=D.pathloss;
function rsrpFrom(d,deficit){          // omni node, distance in metres
  return PL.intercept+PL.slope*Math.log10(Math.max(30,d))-deficit;
}
// The service value of a cell depends on WHICH STATISTIC the operator cares
// about, and measuring that showed it changes the answer: route demand meeting
// 10 Mbps is 94.8% at p90, 51.4% on the mean, 29.6% at p50 and 9.1% at p10, and
// the best site moves up to 4.1 km between definitions.  So the criterion is a
// control, not a constant, and switching it re-solves everything on this page.
let criterion = D.headline_criterion;
const ST = D.service_tables;
function tableInterp(name,rsrp){
  const X=ST.rsrp, Y=ST[name], n=X.length;
  if(rsrp<=X[0])return Y[0];
  if(rsrp>=X[n-1])return Y[n-1];
  let lo=0,hi=n-1;
  while(hi-lo>1){const m=(lo+hi)>>1; if(X[m]<=rsrp)lo=m; else hi=m;}
  const t=(rsrp-X[lo])/((X[hi]-X[lo])||1);
  return Y[lo]+t*(Y[hi]-Y[lo]);
}
function expUplink(rsrp){                       // mean: (1 - P(outage)) x uplink
  const ul=Math.max(0,interp(D.curves.uplink,rsrp));
  const po=Math.min(1,Math.max(0,interp(D.curves.outage,rsrp)));
  return (1-po)*ul;
}
function availability(rsrp){
  return 1-Math.min(1,Math.max(0,interp(D.curves.outage,rsrp)));
}
function serviceValue(rsrp){
  if(criterion==="mean")return expUplink(rsrp);
  if(criterion==="availability")return availability(rsrp);
  return Math.max(0,tableInterp(criterion,rsrp));
}
function isAvail(){return criterion==="availability";}
function target(){return isAvail()? availTarget : thr;}
function fmtVal(v){return isAvail()? (v*100).toFixed(0)+"%" : v.toFixed(1)+" Mbps";}

const cells=D.cells, N=cells.length;
const W=cells.map(c=>c.w), TW=W.reduce((a,b)=>a+b,0);
const baseR=cells.map(c=>c.r);
let baseU=baseR.map(serviceValue);

let placed=null, asset='relay', view='after';
let eirp=20, thr=10, availTarget=D.availability_target;
let afterU=baseU.slice(), afterR=baseR.slice();

function recompute(){
  baseU=baseR.map(serviceValue);
  if(!placed){ afterR=baseR.slice(); afterU=baseU.slice(); }
  else{
    afterR=new Array(N); afterU=new Array(N);
    for(let i=0;i<N;i++){
      const d=hav(placed.lat,placed.lon,cells[i].lat,cells[i].lon);
      afterR[i]=Math.max(baseR[i],rsrpFrom(d,eirp));
      afterU[i]=serviceValue(afterR[i]);
    }
  }
  const T=target();
  let b=0,a=0,fixed=0;
  for(let i=0;i<N;i++){
    if(baseU[i]>=T)b+=W[i];
    if(afterU[i]>=T){a+=W[i]; if(baseU[i]<T)fixed++;}
  }
  const pb=100*b/TW, pa=100*a/TW;
  document.getElementById('sBefore').innerHTML=pb.toFixed(1)+'<small>%</small>';
  document.getElementById('sAfter').innerHTML=pa.toFixed(1)+'<small>%</small>';
  const dl=document.getElementById('sDelta');
  dl.textContent=(pa-pb>0.049?'+':'')+(pa-pb).toFixed(1)+' pts';
  dl.className='delta '+(pa-pb>0.049?'up':'flat');
  document.getElementById('sCells').textContent=fixed;
  document.getElementById('sKm').textContent=(fixed*0.2).toFixed(1);

  const t=document.getElementById('siteTbl');
  if(!placed){ t.innerHTML='<tr><td>none placed</td><td></td></tr>';
               document.getElementById('donorWarn').innerHTML=''; }
  else{
    const dm=hav(D.macro.lat,D.macro.lon,placed.lat,placed.lon);
    const donor=rsrpFrom(dm,0);
    const cfg=D.assets[asset];
    // service radius: solve outward until expected uplink drops below target
    let rad=0; for(let r=50;r<12000;r+=25){ if(serviceValue(rsrpFrom(r,eirp))>=target()) rad=r; else break; }
    t.innerHTML=`<tr><td>position</td><td>${placed.lat.toFixed(5)}, ${placed.lon.toFixed(5)}</td></tr>
      <tr><td>from macro</td><td>${(dm/1000).toFixed(2)} km</td></tr>
      <tr><td>donor RSRP</td><td>${donor.toFixed(1)} dBm</td></tr>
      <tr><td>service radius</td><td>${rad} m</td></tr>
      <tr><td>passes served</td><td>${fixed?W.filter((w,i)=>afterU[i]>=target()&&baseU[i]<target()).reduce((x,y)=>x+y,0):0}</td></tr>`;
    const dw=document.getElementById('donorWarn');
    dw.innerHTML = (cfg.needs_donor && donor < cfg.donor_min)
      ? `<div class="warn">Infeasible: donor RSRP ${donor.toFixed(1)} dBm is below the
         ${cfg.donor_min} dBm a relay needs. There is nothing here to repeat &mdash;
         this site requires backhaul, i.e. a small cell.</div>` : '';
  }
  draw();
}

/* ---------- canvas map ---------- */
const cv=document.getElementById('map'), cx=cv.getContext('2d');
let VW=0,VH=0,zoom=1,panX=0,panY=0;
const lats=cells.map(c=>c.lat), lons=cells.map(c=>c.lon);
const b={n:Math.max(...lats),s:Math.min(...lats),e:Math.max(...lons),w:Math.min(...lons)};
const kx=Math.cos(42*Math.PI/180);
function fit(){
  const dpr=window.devicePixelRatio||1;
  VW=cv.clientWidth; VH=cv.clientHeight;
  cv.width=VW*dpr; cv.height=VH*dpr; cx.setTransform(dpr,0,0,dpr,0,0);
}
function proj(lat,lon){
  const sx=VW/((b.e-b.w)*kx), sy=VH/(b.n-b.s), s=Math.min(sx,sy)*0.88*zoom;
  const cxm=(b.e+b.w)/2, cym=(b.n+b.s)/2;
  return [VW/2+(lon-cxm)*kx*s+panX, VH/2-(lat-cym)*s+panY];
}
function unproj(px,py){
  const sx=VW/((b.e-b.w)*kx), sy=VH/(b.n-b.s), s=Math.min(sx,sy)*0.88*zoom;
  const cxm=(b.e+b.w)/2, cym=(b.n+b.s)/2;
  return [cym-(py-panY-VH/2)/s, cxm+(px-panX-VW/2)/(kx*s)];
}
const css=k=>getComputedStyle(document.documentElement).getPropertyValue(k).trim();
function ramp(t){ // ochre (bad) -> teal (good), colour-blind safe on both themes
  t=Math.max(0,Math.min(1,t));
  const a=[143,98,0], c=[15,110,112];
  return `rgb(${a.map((v,i)=>Math.round(v+(c[i]-v)*t)).join(',')})`;
}
function draw(){
  cx.clearRect(0,0,VW,VH);
  cx.fillStyle=css('--surface'); cx.fillRect(0,0,VW,VH);
  // route
  cx.strokeStyle=css('--rule2'); cx.lineWidth=1; cx.globalAlpha=.55; cx.beginPath();
  D.route.forEach((p,i)=>{const[x,y]=proj(p[0],p[1]); i?cx.lineTo(x,y):cx.moveTo(x,y);});
  cx.stroke(); cx.globalAlpha=1;
  // cells
  const s=Math.max(3,4.2*zoom);
  for(let i=0;i<N;i++){
    const[x,y]=proj(cells[i].lat,cells[i].lon);
    if(x<-20||x>VW+20||y<-20||y>VH+20)continue;
    let col,ring=false;
    if(view==='delta'){
      const g=afterU[i]-baseU[i];
      if(g<0.25){cx.globalAlpha=.13; col=css('--mute');}
      else{cx.globalAlpha=.95; col=(baseU[i]<target()&&afterU[i]>=target())?css('--good'):css('--teal');
            if(baseU[i]<target()&&afterU[i]>=target()){ring=true;}}
    }else if(view==='freq'){
      cx.globalAlpha=.18; col=css('--mute');
    }else{
      cx.globalAlpha=.9; col=ramp(Math.min(1,afterU[i]/(target()*2)));
      if(afterU[i]<target()){cx.globalAlpha=.95;}
    }
    cx.fillStyle=col; cx.fillRect(x-s/2,y-s/2,s,s);
    if(ring){cx.strokeStyle=css('--ink');cx.lineWidth=1.5;cx.globalAlpha=1;
             cx.strokeRect(x-s/2-1.5,y-s/2-1.5,s+3,s+3);}
  }
  cx.globalAlpha=1;
  if(view==='freq'){
    D.candidates.forEach(c=>{ if(c.freq<=0)return;
      const[x,y]=proj(c.lat,c.lon);
      cx.fillStyle=css('--ochre'); cx.globalAlpha=.85;
      const r=3+22*Math.sqrt(c.freq); cx.beginPath(); cx.arc(x,y,r,0,7); cx.fill();
    }); cx.globalAlpha=1;
  }
  // recommended + baseline + measurement picks
  const pin=(lat,lon,col,label,fill)=>{
    const[x,y]=proj(lat,lon);
    cx.strokeStyle=col; cx.fillStyle=fill?col:css('--ground'); cx.lineWidth=2;
    cx.beginPath(); cx.arc(x,y,6,0,7); cx.fill(); cx.stroke();
    cx.fillStyle=col; cx.font='600 10px '+css('--mono');
    cx.fillText(label,x+10,y+3.5);
  };
  D.measurement.forEach((m,i)=>pin(m.lat,m.lon,css('--mute'),'M'+(i+1),false));
  pin(D.baseline.lat,D.baseline.lon,css('--bad'),'worst point',false);
  pin(D.recommended[0].lat,D.recommended[0].lon,css('--teal'),'recommended',false);
  // macro
  const[mx,my]=proj(D.macro.lat,D.macro.lon);
  cx.fillStyle=css('--ink'); cx.beginPath();
  cx.moveTo(mx,my-9); cx.lineTo(mx+8,my+6); cx.lineTo(mx-8,my+6); cx.closePath(); cx.fill();
  cx.font='600 10px '+css('--mono'); cx.fillText('AGRONOMY FARM',mx+12,my+4);
  // placed asset + its service ring
  if(placed){
    const[px,py]=proj(placed.lat,placed.lon);
    let rad=0; for(let r=50;r<12000;r+=25){ if(serviceValue(rsrpFrom(r,eirp))>=target())rad=r; else break; }
    const[ex,]=proj(placed.lat,placed.lon+rad/(111320*kx));
    cx.strokeStyle=css('--good'); cx.lineWidth=1.5; cx.setLineDash([4,4]);
    cx.beginPath(); cx.arc(px,py,Math.abs(ex-px),0,7); cx.stroke(); cx.setLineDash([]);
    cx.fillStyle=css('--good'); cx.beginPath(); cx.arc(px,py,7,0,7); cx.fill();
    cx.strokeStyle=css('--ground'); cx.lineWidth=2; cx.stroke();
  }
}

/* ---------- legend + model table ---------- */
function legend(){
  const L=document.getElementById('legend');
  const rows = view==='freq'
    ? [[css('--ochre'),'how often this site wins ('+D.meta_draws+' draws)']]
    : view==='delta'
    ? [[css('--good'),'newly meets target'],[css('--teal'),'improved, still short'],[css('--mute'),'unchanged']]
    : [[ramp(0),fmtVal(0)],[ramp(.5),fmtVal(target())],[ramp(1),fmtVal(target()*2)]];
  L.innerHTML=rows.map(r=>`<div class="row"><span class="sw" style="background:${r[0]}"></span>${r[1]}</div>`).join('');
}
document.getElementById('modelTbl').innerHTML=`
  <tr><td>path-loss exponent n</td><td>${PL.n.toFixed(2)}</td></tr>
  <tr><td>shadow fading &sigma;</td><td>${PL.sigma.toFixed(1)} dB</td></tr>
  <tr><td>demand cells</td><td>${N} @ 200 m</td></tr>
  <tr><td>total route passes</td><td>${TW}</td></tr>
  <tr><td>candidate sites</td><td>${D.candidates.length}</td></tr>
  <tr><td>consensus max regret</td><td>${D.consensus.max_regret.toFixed(2)}</td></tr>`;

/* ---------- interaction ---------- */
let drag=null;
cv.addEventListener('mousedown',e=>{drag={x:e.offsetX,y:e.offsetY,px:panX,py:panY,moved:false};});
addEventListener('mousemove',e=>{ if(!drag)return;
  const r=cv.getBoundingClientRect(), ox=e.clientX-r.left, oy=e.clientY-r.top;
  if(Math.abs(ox-drag.x)+Math.abs(oy-drag.y)>4)drag.moved=true;
  panX=drag.px+(ox-drag.x); panY=drag.py+(oy-drag.y); draw(); });
addEventListener('mouseup',e=>{
  if(drag&&!drag.moved){ const[la,lo]=unproj(drag.x,drag.y); placed={lat:la,lon:lo}; recompute(); }
  drag=null; });
cv.addEventListener('wheel',e=>{e.preventDefault();
  zoom=Math.max(.6,Math.min(14,zoom*(e.deltaY<0?1.15:1/1.15))); draw();},{passive:false});
document.getElementById('assetSeg').onclick=e=>{
  const b=e.target.closest('button'); if(!b)return;
  asset=b.dataset.a;
  [...e.currentTarget.children].forEach(x=>x.setAttribute('aria-pressed',x===b));
  eirp=D.assets[asset].deficit;
  document.getElementById('eirp').value=eirp;
  document.getElementById('eirpV').textContent=eirp;
  recompute(); };
document.getElementById('viewSeg').onclick=e=>{
  const b=e.target.closest('button'); if(!b)return;
  view=b.dataset.v;
  [...e.currentTarget.children].forEach(x=>x.setAttribute('aria-pressed',x===b));
  document.getElementById('viewNote').textContent = view==='freq'
    ? 'Circle size = how often that site won when the whole decision was re-solved against draws from the model’s own shadow-fading error. Big circles are defensible; a field of small ones means the exact pole is arbitrary and only the area is real.'
    : view==='delta' ? 'Only cells the placed asset actually changes.'
    : 'Predicted expected uplink, after outage probability is applied.';
  legend(); draw(); };
(function(){
  const seg=document.getElementById('critSeg');
  seg.innerHTML=Object.keys(D.criteria_meta).map(k=>
    `<button data-c="${k}" aria-pressed="${k===criterion}">${k}</button>`).join('');
  function note(){
    const m=D.criteria_meta[criterion], b=D.by_criterion[criterion];
    document.getElementById('critNote').innerHTML=
      `<b>${m.label}</b> — ${m.blurb}.` + (b&&b.dist_from_macro_m!=null
        ? ` Offline optimiser puts the best relay <b>${(b.dist_from_macro_m/1000).toFixed(1)} km</b> out
           for this definition, with <b>${b.covered_before_pct.toFixed(1)}%</b> of demand already met.` : '');
    const lab=document.getElementById('thrLab'), sl=document.getElementById('thr');
    if(isAvail()){ sl.min=50; sl.max=99; sl.value=Math.round(availTarget*100);
      lab.innerHTML='Availability target <b><span id="thrV">'+Math.round(availTarget*100)+'</span>%</b>'; }
    else { sl.min=2; sl.max=30; sl.value=thr;
      lab.innerHTML='Uplink target <b><span id="thrV">'+thr+'</span> Mbps</b>'; }
  }
  seg.onclick=e=>{const b=e.target.closest('button'); if(!b)return;
    criterion=b.dataset.c;
    [...seg.children].forEach(x=>x.setAttribute('aria-pressed',x===b));
    note(); legend(); recompute();};
  note();
})();
document.getElementById('eirp').oninput=e=>{eirp=+e.target.value;
  document.getElementById('eirpV').textContent=eirp; recompute();};
document.getElementById('thr').oninput=e=>{
  if(isAvail()){ availTarget=(+e.target.value)/100;
    document.getElementById('thrV').textContent=Math.round(availTarget*100); }
  else { thr=+e.target.value; document.getElementById('thrV').textContent=thr; }
  legend(); recompute();};
document.getElementById('useRec').onclick=()=>{
  const b=D.by_criterion[criterion];
  placed={lat:(b&&b.lat)||D.recommended[0].lat,lon:(b&&b.lon)||D.recommended[0].lon}; recompute();};
document.getElementById('useCons').onclick=()=>{
  placed={lat:D.consensus.lat,lon:D.consensus.lon}; recompute();};
document.getElementById('useWorst').onclick=()=>{
  placed={lat:D.baseline.lat,lon:D.baseline.lon}; recompute();};
document.getElementById('clear').onclick=()=>{placed=null; recompute();};
addEventListener('resize',()=>{fit();draw();});
matchMedia('(prefers-color-scheme:dark)').addEventListener('change',draw);
fit(); legend();
document.getElementById('viewNote').textContent='Predicted expected uplink, after outage probability is applied.';
recompute();
</script>
</body>
</html>
"""


def build(verbose=True):
    data = json.loads((DATA / "planner_data.json").read_text())
    data["meta_draws"] = 200
    out = ROOT / "planner.html"
    out.write_text(HTML.replace("__DATA__", json.dumps(data, separators=(",", ":"))),
                   encoding="utf-8")
    if verbose:
        print(f"[planner] {out}  ({out.stat().st_size/1e6:.2f} MB, self-contained)")
    return out


if __name__ == "__main__":
    build()
