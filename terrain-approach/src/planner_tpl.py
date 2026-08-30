"""The planner page template, kept separate because it is mostly JavaScript.

Covers all four things the brief asks a team to demonstrate:
  1. before/after coverage under EXPLICIT service thresholds  -> Thresholds tab
  2. robustness to model uncertainty                          -> Robustness tab
  3. gains per intervention and sensitivity to constraints    -> Gains, Sensitivity tabs
  4. a scenario planner judges can click                      -> the map itself

Every panel recomputes in the browser from the terrain model. The robustness tab
re-solves the placed site against fresh shadow-fading draws using the same
path-specific correlation model as the offline pipeline, so the uncertainty a
judge sees is generated live rather than looked up.
"""

TPL = r"""<title>Rural Coverage Planner</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>
:root{--ground:#FBFCFA;--surface:#F1F4EF;--surface2:#E8EDE6;--ink:#16211C;--ink2:#3A4842;
 --mute:#65726B;--rule:#C3CCBF;--grid:#E4E9E1;--c1:#0F6E70;--c2:#8F6200;--c3:#5B3A9B;--c4:#8C1D40;
 --mono:"IBM Plex Mono",ui-monospace,Consolas,monospace;--sans:"Archivo",Arial,sans-serif}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
 --ground:#0E1512;--surface:#161F1B;--surface2:#1E2823;--ink:#E5EBE7;--ink2:#BFCAC4;
 --mute:#8A968F;--rule:#38473F;--grid:#212D27;--c1:#4FB3B4;--c2:#D9A227;--c3:#A98BE0;--c4:#E86A93}}
:root[data-theme=dark]{--ground:#0E1512;--surface:#161F1B;--surface2:#1E2823;--ink:#E5EBE7;
 --ink2:#BFCAC4;--mute:#8A968F;--rule:#38473F;--grid:#212D27;--c1:#4FB3B4;--c2:#D9A227;
 --c3:#A98BE0;--c4:#E86A93}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--sans);font-size:14px}
.app{display:grid;grid-template-columns:1fr 372px;height:100vh}
@media(max-width:900px){.app{grid-template-columns:1fr;height:auto}#stage{height:58vh;min-height:380px}}
#stage{position:relative;background:var(--surface);overflow:hidden}
canvas{display:block;width:100%;height:100%;cursor:crosshair}
aside{border-left:1px solid var(--rule);overflow-y:auto;padding:14px 14px 40px;background:var(--ground)}
h1{font-size:15px;margin:0 0 1px}
.sub{font-family:var(--mono);font-size:9px;letter-spacing:.09em;text-transform:uppercase;
 color:var(--c1);margin-bottom:12px}
h2{font-family:var(--mono);font-size:9px;letter-spacing:.1em;text-transform:uppercase;
 color:var(--mute);font-weight:500;margin:15px 0 6px;padding-bottom:3px;border-bottom:1px solid var(--rule)}
.seg{display:flex;gap:1px;background:var(--rule);border:1px solid var(--rule)}
.seg button{flex:1;background:var(--surface);border:0;color:var(--ink2);font-family:var(--mono);
 font-size:9.5px;padding:6px 2px;cursor:pointer}
.seg button[aria-pressed=true]{background:var(--c1);color:#fff}
.ctl{margin:8px 0}
.ctl label{display:flex;justify-content:space-between;font-family:var(--mono);font-size:10px;
 color:var(--ink2);margin-bottom:2px}
.ctl label b{color:var(--ink)}
input[type=range]{width:100%;accent-color:var(--c1)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--rule);
 border:1px solid var(--rule);margin:7px 0}
.kpi{background:var(--surface);padding:7px 8px}
.kpi .l{font-family:var(--mono);font-size:8.5px;letter-spacing:.07em;text-transform:uppercase;color:var(--mute)}
.kpi .v{font-size:18px;font-weight:700;letter-spacing:-.02em;font-variant-numeric:tabular-nums;line-height:1.15}
.kpi .d{font-family:var(--mono);font-size:9.5px;color:var(--c3)}
.kpi .d.zero{color:var(--mute)}
button.act{width:100%;background:var(--c1);color:#fff;border:0;padding:6px;font-family:var(--mono);
 font-size:9.5px;letter-spacing:.06em;text-transform:uppercase;cursor:pointer;margin-top:5px}
button.act.ghost{background:transparent;color:var(--ink2);border:1px solid var(--rule)}
.lg{display:flex;align-items:center;gap:6px;font-family:var(--mono);font-size:10px;
 color:var(--ink2);margin:3px 0;cursor:pointer;user-select:none}
.lg i{width:11px;height:11px;border-radius:2px;flex:none;border:1px solid rgba(128,128,128,.3)}
.lg.off{opacity:.35}
table{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:10px}
td,th{padding:2px 0;color:var(--ink2);text-align:right;font-weight:400}
td:first-child,th:first-child{text-align:left}
th{color:var(--mute);font-size:8.5px;letter-spacing:.06em;text-transform:uppercase;
 border-bottom:1px solid var(--rule);padding-bottom:3px}
td:not(:first-child){color:var(--ink);font-variant-numeric:tabular-nums}
tr.hi td{color:var(--c1);font-weight:600}
.tabs{display:flex;gap:1px;background:var(--rule);border:1px solid var(--rule);margin-bottom:8px}
.tabs button{flex:1;background:var(--surface);border:0;color:var(--ink2);font-family:var(--mono);
 font-size:9px;padding:6px 1px;cursor:pointer;letter-spacing:.03em}
.tabs button[aria-pressed=true]{background:var(--ink);color:var(--ground)}
.pane{display:none}.pane.on{display:block}
svg{display:block;width:100%;height:auto;overflow:visible}
.hint{position:absolute;left:11px;top:11px;font-family:var(--mono);font-size:9.5px;
 letter-spacing:.05em;text-transform:uppercase;color:var(--mute);background:var(--ground);
 border:1px solid var(--rule);padding:5px 8px;pointer-events:none}
.busy{position:absolute;right:11px;top:11px;font-family:var(--mono);font-size:9.5px;
 color:var(--c2);background:var(--ground);border:1px solid var(--c2);padding:4px 8px;opacity:0;
 transition:opacity .1s}
.note{font-size:10px;color:var(--mute);line-height:1.45;margin-top:6px}
.warn{font-family:var(--mono);font-size:9.5px;color:var(--c2);margin-top:5px;line-height:1.4}
</style>
<div class="app">
 <div id="stage">
  <canvas id="cv"></canvas>
  <div class="hint">click to place a site &middot; drag to pan &middot; scroll to zoom</div>
  <div class="busy" id="busy">computing&hellip;</div>
 </div>
 <aside>
  <h1>Rural Coverage Planner</h1>
  <div class="sub">ARA COTS &middot; terrain-aware scenario planner</div>

  <h2>Asset</h2>
  <div class="seg" id="asset"></div>
  <div class="ctl" style="margin-top:8px">
   <label>Mast height <b><span id="aglV"></span> m</b></label>
   <input type="range" id="agl" min="6" max="60" step="1">
  </div>
  <div class="ctl">
   <label>Power vs the tower <b>&minus;<span id="dfcV"></span> dB</b></label>
   <input type="range" id="dfc" min="0" max="34" step="1">
  </div>
  <div class="ctl">
   <label>Service threshold <b>available &ge;<span id="thrV"></span>%</b></label>
   <input type="range" id="thr" min="20" max="90" step="5">
  </div>
  <div id="warn"></div>

  <h2>Before &rarr; after</h2>
  <div class="grid2">
   <div class="kpi"><div class="l">Route-km</div><div class="v" id="kRk"></div><div class="d" id="dRk"></div></div>
   <div class="kpi"><div class="l">Area km&sup2;</div><div class="v" id="kAr"></div><div class="d" id="dAr"></div></div>
   <div class="kpi"><div class="l">Cells fixed</div><div class="v" id="kFx"></div><div class="d">of <span id="kDead"></span> dead</div></div>
   <div class="kpi"><div class="l">Score</div><div class="v" id="kSc"></div><div class="d" id="dSc"></div></div>
  </div>

  <h2>Analysis</h2>
  <div class="tabs" id="tabs">
   <button data-t="thr" aria-pressed="true">Thresholds</button>
   <button data-t="gain" aria-pressed="false">Gains</button>
   <button data-t="rob" aria-pressed="false">Robustness</button>
   <button data-t="sens" aria-pressed="false">Sensitivity</button>
  </div>
  <div class="pane on" id="p-thr">
   <table id="tThr"></table>
   <div class="note">Coverage under four explicit service definitions, recomputed
    for the site you placed.</div>
  </div>
  <div class="pane" id="p-gain">
   <div id="cGainAsset"></div>
   <div id="cGainSeq"></div>
   <div class="note">Top: what each device class delivers at <em>this</em> location.
    Bottom: the marginal gain of the 1st, 2nd and 3rd installation, from the
    offline greedy solve.</div>
  </div>
  <div class="pane" id="p-rob">
   <div id="cRob"></div>
   <table id="tRob"></table>
   <div class="note">150 fresh shadow-fading draws, path-specific correlation
    (&rho;<sub>0</sub>=0.60, &theta;<sub>c</sub>=45&deg;). Computed live, not looked up.</div>
  </div>
  <div class="pane" id="p-sens">
   <div id="cSensAgl"></div>
   <div id="cSensDfc"></div>
   <div class="note">Gain at this location as the two siting constraints move.
    Mast height changes what terrain the site can see; power scales the reach.</div>
  </div>

  <h2>Placed site</h2>
  <table id="site"></table>
  <button class="act" id="useRec">Use the optimiser's site</button>
  <button class="act ghost" id="clear">Clear</button>

  <h2>Layers</h2>
  <div id="legend"></div>

  <h2>Model</h2>
  <table id="model"></table>
 </aside>
</div>
<script>
const D=__DATA__;
const C=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const $=i=>document.getElementById(i);
const cv=$('cv'),cx=cv.getContext('2d');
let VW=0,VH=0,zoom=1,panX=0,panY=0,drag=null,placed=null,tab='thr';
let asset='macro', agl=D.assets.macro.agl, dfc=D.assets.macro.deficit, availPct=50;
const on={dead:1,fixed:1,nocell:1,served:0,relief:1};
const B=D.bounds,kx=Math.cos(42*Math.PI/180);
const N=D.cells.lat.length, LA=D.cells.lat, LO=D.cells.lon, RK=D.cells.rk, AR=D.cells.ar;
const baseR=Float32Array.from(D.cells.base);
let afterR=new Float32Array(N), covB=new Uint8Array(N), covA=new Uint8Array(N);
let placedDiff=null;                       // diffraction from the placed site, cached

/* ---------- physics, ported from propagation.py ---------- */
const DM=D.dem, R_EARTH=6371000, R_EFF=R_EARTH*4/3, LAM=D.model.lambda, NSEG=160;
function demAt(la,lo){
  let fi=(la-DM.lat0)/DM.dlat, fj=(lo-DM.lon0)/DM.dlon;
  fi=fi<0?0:(fi>DM.ny-1.001?DM.ny-1.001:fi);
  fj=fj<0?0:(fj>DM.nx-1.001?DM.nx-1.001:fj);
  const i0=fi|0,j0=fj|0,ti=fi-i0,tj=fj-j0,z=DM.z,w=DM.nx;
  return (1-ti)*(1-tj)*z[i0*w+j0]+(1-ti)*tj*z[i0*w+j0+1]
        +ti*(1-tj)*z[(i0+1)*w+j0]+ti*tj*z[(i0+1)*w+j0+1];
}
function hav(a,b,c,d){const p1=a*Math.PI/180,p2=c*Math.PI/180,dp=p2-p1,dl=(d-b)*Math.PI/180;
 const q=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;
 return 2*R_EARTH*Math.asin(Math.sqrt(Math.min(1,q)));}
function bearing(a,b,c,d){const p1=a*Math.PI/180,p2=c*Math.PI/180,dl=(d-b)*Math.PI/180;
 return (Math.atan2(Math.sin(dl)*Math.cos(p2),
   Math.cos(p1)*Math.sin(p2)-Math.sin(p1)*Math.cos(p2)*Math.cos(dl))*180/Math.PI+360)%360;}
function knife(v){if(v<=-0.78)return 0;const w=v-0.1;
 return Math.max(0,6.9+20*Math.log10(Math.sqrt(w*w+1)+w));}
function diffToCells(tLat,tLon,tAgl){
  const out=new Float32Array(N), tz=demAt(tLat,tLon)+tAgl;
  for(let c=0;c<N;c++){
    const rl=LA[c],ro=LO[c], dt=hav(tLat,tLon,rl,ro);
    if(dt<40){out[c]=0;continue;}
    const rz=demAt(rl,ro)+D.model.rx_agl; let vm=-9;
    for(let k=1;k<NSEG;k++){
      const f=k/NSEG, g=demAt(tLat+(rl-tLat)*f,tLon+(ro-tLon)*f);
      const d1=dt*f,d2=dt-d1, clear=(tz+(rz-tz)*f)-(g+d1*d2/(2*R_EFF));
      const v=-Math.SQRT2*(clear/Math.sqrt(LAM*d1*d2/dt));
      if(v>vm)vm=v;
    }
    out[c]=knife(vm);
  }
  return out;
}
function diffOne(tLat,tLon,tAgl,rLat,rLon,rAgl){
  const dt=hav(tLat,tLon,rLat,rLon); if(dt<40)return 0;
  const tz=demAt(tLat,tLon)+tAgl, rz=demAt(rLat,rLon)+rAgl; let vm=-9;
  for(let k=1;k<NSEG;k++){
    const f=k/NSEG, g=demAt(tLat+(rLat-tLat)*f,tLon+(rLon-tLon)*f);
    const d1=dt*f,d2=dt-d1, clear=(tz+(rz-tz)*f)-(g+d1*d2/(2*R_EFF));
    const v=-Math.SQRT2*(clear/Math.sqrt(LAM*d1*d2/dt));
    if(v>vm)vm=v;
  }
  return knife(vm);
}
function thrFor(pct){const t=pct/100,X=D.avail.x,Y=D.avail.y;
 for(let i=0;i<X.length;i++) if(Y[i]>=t) return X[i]; return 999;}
function siteRsrp(dd){                       // RSRP at every cell from the placed site
  const r=new Float32Array(N);
  for(let i=0;i<N;i++){
    const d=Math.max(30,hav(placed.lat,placed.lon,LA[i],LO[i]));
    r[i]=D.model.b0+D.model.slope*Math.log10(d)-dfc+D.model.bdiff*dd[i];
  }
  return r;
}
function cov(arr,thr){let rk=0,n=0;
 for(let i=0;i<N;i++) if(arr[i]>=thr){rk+=RK[i];n++;}
 const ar=n*AR;
 return {rk:rk,ar:ar,n:n,s:D.weights.route*rk/D.tot.rk+D.weights.area*ar/D.tot.ar};}

/* ---------- core recompute ---------- */
function recompute(){
  const thr=thrFor(availPct);
  placedDiff = placed ? diffToCells(placed.lat,placed.lon,agl) : null;
  if(!placed) afterR.set(baseR);
  else { const r=siteRsrp(placedDiff);
         for(let i=0;i<N;i++) afterR[i]=Math.max(baseR[i],r[i]); }
  let fixed=0,dead=0;
  for(let i=0;i<N;i++){covB[i]=baseR[i]>=thr?1:0;covA[i]=afterR[i]>=thr?1:0;
    if(!covB[i]){dead++; if(covA[i])fixed++;}}
  const a=cov(afterR,thr), b=cov(baseR,thr);
  $('kRk').textContent=a.rk.toFixed(1); $('kAr').textContent=a.ar.toFixed(0);
  $('kFx').textContent=fixed.toLocaleString(); $('kDead').textContent=dead.toLocaleString();
  $('kSc').textContent=a.s.toFixed(3);
  const put=(id,v,u)=>{const e=$(id);e.textContent=(v>0.049?'+':'')+v.toFixed(u==='km2'?0:1)+' '+u;
   e.className='d'+(v>0.049?'':' zero');};
  put('dRk',a.rk-b.rk,'km'); put('dAr',a.ar-b.ar,'km2');
  $('dSc').textContent=(a.s-b.s>0.0005?'+':'')+(a.s-b.s).toFixed(3);
  $('dSc').className='d'+(a.s-b.s>0.0005?'':' zero');
  siteTable(thr); renderTab(); draw();
}
function siteTable(thr){
  const t=$('site');
  if(!placed){t.innerHTML='<tr><td>none placed</td><td></td></tr>';$('warn').innerHTML='';return;}
  const dm=hav(D.macro.lat,D.macro.lon,placed.lat,placed.lon);
  const dD=diffOne(D.macro.lat,D.macro.lon,D.model.tx_agl,placed.lat,placed.lon,agl);
  const donor=D.model.b0+D.model.slope*Math.log10(Math.max(30,dm))+D.model.bdiff*dD;
  let rad=0; for(let r=100;r<16000;r+=100){
    if(D.model.b0+D.model.slope*Math.log10(r)-dfc>=thr)rad=r; else break;}
  t.innerHTML=`<tr><td>position</td><td>${placed.lat.toFixed(5)}, ${placed.lon.toFixed(5)}</td></tr>
   <tr><td>ground / antenna</td><td>${demAt(placed.lat,placed.lon).toFixed(0)} / ${(demAt(placed.lat,placed.lon)+agl).toFixed(0)} m</td></tr>
   <tr><td>from tower</td><td>${(dm/1000).toFixed(2)} km</td></tr>
   <tr><td>donor RSRP</td><td>${donor.toFixed(1)} dBm</td></tr>
   <tr><td>service radius</td><td>${rad} m</td></tr>`;
  const cfg=D.assets[asset];
  $('warn').innerHTML=(cfg.donor_min!==null&&dfc>=15&&donor<cfg.donor_min)
   ?`<div class="warn">Infeasible as a repeater: donor RSRP ${donor.toFixed(1)} dBm is below
     ${cfg.donor_min} dBm. Nothing here to rebroadcast — this site needs backhaul.</div>`:'';
}

/* ---------- tiny SVG charts ---------- */
const NS='http://www.w3.org/2000/svg';
function mk(t,a){const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);return e;}
function chart(host,title,W2,H2){
  const el=$(host); el.innerHTML='';
  if(title){const d=document.createElement('div');
    d.style.cssText='font-family:var(--mono);font-size:8.5px;letter-spacing:.07em;'+
      'text-transform:uppercase;color:var(--mute);margin:6px 0 2px';
    d.textContent=title; el.appendChild(d);}
  const s=mk('svg',{viewBox:`0 0 ${W2} ${H2}`}); el.appendChild(s); return s;
}
function hbars(host,title,rows,maxv,fmt,colors){
  const W2=340,rh=22,P={l:78,r:44,t:4,b:4};
  const s=chart(host,title,W2,P.t+rows.length*rh+P.b);
  rows.forEach((r,i)=>{
    const y=P.t+i*rh+rh/2, w=Math.max(1,(W2-P.l-P.r)*Math.min(1,r[1]/maxv));
    s.appendChild(mk('rect',{x:P.l,y:y-6,width:w,height:12,rx:2,
      fill:colors?colors[i]:C('--c1'),opacity:.9}));
    const a=mk('text',{x:P.l-6,y:y+3.5,'text-anchor':'end',fill:C('--ink2'),
      'font-size':9.5,'font-family':C('--mono')});a.textContent=r[0];s.appendChild(a);
    const b=mk('text',{x:P.l+w+5,y:y+3.5,fill:C('--ink'),'font-size':9.5,
      'font-weight':600,'font-family':C('--mono')});b.textContent=fmt(r[1]);s.appendChild(b);
  });
}
function lineChart(host,title,xs,ys,fmtx,fmty,mark){
  const W2=340,H2=104,P={l:38,r:12,t:8,b:20};
  const s=chart(host,title,W2,H2);
  const x0=Math.min(...xs),x1=Math.max(...xs),y1=Math.max(...ys,1e-6);
  const X=v=>P.l+(v-x0)/((x1-x0)||1)*(W2-P.l-P.r), Y=v=>H2-P.b-(v/y1)*(H2-P.t-P.b);
  [0,y1/2,y1].forEach(v=>{s.appendChild(mk('line',{x1:P.l,x2:W2-P.r,y1:Y(v),y2:Y(v),
    stroke:C('--grid'),'stroke-width':1}));
    const t=mk('text',{x:P.l-5,y:Y(v)+3,'text-anchor':'end',fill:C('--mute'),
      'font-size':8,'font-family':C('--mono')});t.textContent=fmty(v);s.appendChild(t);});
  s.appendChild(mk('path',{d:xs.map((v,i)=>(i?'L':'M')+X(v).toFixed(1)+' '+Y(ys[i]).toFixed(1)).join(' '),
    fill:'none',stroke:C('--c1'),'stroke-width':2}));
  xs.forEach((v,i)=>{s.appendChild(mk('circle',{cx:X(v),cy:Y(ys[i]),r:2.6,fill:C('--c1')}));
    if(i%2===0||i===xs.length-1){const t=mk('text',{x:X(v),y:H2-6,'text-anchor':'middle',
      fill:C('--mute'),'font-size':8,'font-family':C('--mono')});t.textContent=fmtx(v);s.appendChild(t);}});
  if(mark!==undefined&&mark>=x0&&mark<=x1)
    s.appendChild(mk('line',{x1:X(mark),x2:X(mark),y1:P.t,y2:H2-P.b,stroke:C('--c2'),
      'stroke-width':1.5,'stroke-dasharray':'3 3'}));
}

/* ---------- analysis panes ---------- */
function paneThresholds(){
  const rows=[25,50,75,90].map(p=>{
    const t=thrFor(p), b=cov(baseR,t), a=cov(afterR,t);
    return [p,b.rk/D.tot.rk*100,a.rk/D.tot.rk*100,b.ar/D.tot.ar*100,a.ar/D.tot.ar*100];
  });
  $('tThr').innerHTML='<tr><th>available</th><th>route now</th><th>after</th>'
    +'<th>area now</th><th>after</th></tr>'+rows.map(r=>
    `<tr class="${r[0]===availPct?'hi':''}"><td>&ge;${r[0]}%</td><td>${r[1].toFixed(1)}%</td>`
    +`<td>${r[2].toFixed(1)}%</td><td>${r[3].toFixed(1)}%</td><td>${r[4].toFixed(1)}%</td></tr>`).join('');
}
function paneGains(){
  const thr=thrFor(availPct), b=cov(baseR,thr).s;
  const rows=[];
  if(placed){
    for(const k of Object.keys(D.assets)){
      const cfg=D.assets[k], dd=diffToCells(placed.lat,placed.lon,cfg.agl);
      const r=new Float32Array(N);
      for(let i=0;i<N;i++){
        const d=Math.max(30,hav(placed.lat,placed.lon,LA[i],LO[i]));
        r[i]=Math.max(baseR[i],D.model.b0+D.model.slope*Math.log10(d)-cfg.deficit+D.model.bdiff*dd[i]);
      }
      rows.push([cfg.short,cov(r,thr).s-b]);
    }
  }
  const mx=Math.max(0.001,...rows.map(r=>r[1]),...D.marginal.macro);
  hbars('cGainAsset', placed?'gain by device, at this location':'place a site to compare devices',
        rows, mx, v=>v.toFixed(3), [C('--c2'),C('--c4'),C('--c1')]);
  hbars('cGainSeq','marginal gain per successive macro (offline solve)',
        D.marginal.macro.map((v,i)=>['site '+(i+1),v]), mx, v=>v.toFixed(3),
        [C('--c1'),C('--c1'),C('--c1')]);
}
let nrm=null;
function gauss(){ if(nrm!==null){const v=nrm;nrm=null;return v;}
  let u=0,v=0; while(!u)u=Math.random(); while(!v)v=Math.random();
  const r=Math.sqrt(-2*Math.log(u)); nrm=r*Math.sin(2*Math.PI*v); return r*Math.cos(2*Math.PI*v);}
function paneRobustness(){
  if(!placed){ chart('cRob','place a site to run the uncertainty draws',340,10);
    $('tRob').innerHTML=''; return; }
  const thr=thrFor(availPct), sg=D.model.sigma, R0=D.model.rho0, TC=D.model.theta_c;
  const site=siteRsrp(placedDiff);
  const w=new Float32Array(N), wm=Math.sqrt(R0);
  for(let i=0;i<N;i++){
    const th=Math.abs(((bearing(LA[i],LO[i],placed.lat,placed.lon)
                       -bearing(LA[i],LO[i],D.macro.lat,D.macro.lon))+540)%360-180);
    w[i]=Math.sqrt(R0*Math.exp(-th/TC));
  }
  const G=[], nD=150;
  for(let d=0;d<nD;d++){
    let rk0=0,rk1=0,a0=0,a1=0;
    for(let i=0;i<N;i++){
      const com=gauss()*sg;
      const sm=wm*com+Math.sqrt(1-R0)*gauss()*sg;
      const ss=w[i]*com+Math.sqrt(Math.max(0,1-w[i]*w[i]))*gauss()*sg;
      const bb=baseR[i]+sm, aa=Math.max(bb,site[i]+ss);
      if(bb>=thr){rk0+=RK[i];a0+=AR;}
      if(aa>=thr){rk1+=RK[i];a1+=AR;}
    }
    G.push((D.weights.route*(rk1-rk0)/D.tot.rk)+(D.weights.area*(a1-a0)/D.tot.ar));
  }
  G.sort((x,y)=>x-y);
  const q=p=>G[Math.min(G.length-1,Math.floor(p*G.length))];
  const pos=G.filter(v=>v>0.0005).length/G.length;
  // histogram
  const W2=340,H2=92,P={l:8,r:8,t:6,b:16}, nb=22;
  const s=chart('cRob','distribution of gain over '+nD+' draws',W2,H2);
  const lo=G[0],hi=G[G.length-1],bw=(hi-lo)/nb||1e-9;
  const h=new Array(nb).fill(0); G.forEach(v=>h[Math.min(nb-1,Math.floor((v-lo)/bw))]++);
  const mx=Math.max(...h);
  h.forEach((v,i)=>{const x=P.l+i*(W2-P.l-P.r)/nb;
    s.appendChild(mk('rect',{x:x,y:H2-P.b-(v/mx)*(H2-P.t-P.b),
      width:(W2-P.l-P.r)/nb-1.2,height:(v/mx)*(H2-P.t-P.b),fill:C('--c1'),opacity:.85}));});
  const X=v=>P.l+(v-lo)/((hi-lo)||1)*(W2-P.l-P.r);
  if(lo<0&&hi>0) s.appendChild(mk('line',{x1:X(0),x2:X(0),y1:P.t,y2:H2-P.b,
    stroke:C('--c4'),'stroke-width':1.5}));
  [[lo,'min'],[hi,'max']].forEach(([v,t])=>{const e=mk('text',{x:X(v),y:H2-4,
    'text-anchor':v===lo?'start':'end',fill:C('--mute'),'font-size':8,
    'font-family':C('--mono')});e.textContent=v.toFixed(3);s.appendChild(e);});
  $('tRob').innerHTML='<tr><th>statistic</th><th>gain</th></tr>'
    +[['p10',q(.10)],['median',q(.50)],['p90',q(.90)]].map(r=>
      `<tr><td>${r[0]}</td><td>${r[1].toFixed(3)}</td></tr>`).join('')
    +`<tr class="hi"><td>draws with a positive gain</td><td>${(100*pos).toFixed(0)}%</td></tr>`;
}
function paneSensitivity(){
  if(!placed){ chart('cSensAgl','place a site to sweep the constraints',340,10);
    $('cSensDfc').innerHTML=''; return; }
  const thr=thrFor(availPct), b=cov(baseR,thr).s;
  const gainFor=(dd,deficit)=>{
    let rk=0,n=0;
    for(let i=0;i<N;i++){
      const d=Math.max(30,hav(placed.lat,placed.lon,LA[i],LO[i]));
      const v=Math.max(baseR[i],D.model.b0+D.model.slope*Math.log10(d)-deficit+D.model.bdiff*dd[i]);
      if(v>=thr){rk+=RK[i];n++;}
    }
    return D.weights.route*rk/D.tot.rk+D.weights.area*(n*AR)/D.tot.ar-b;
  };
  const hs=[6,12,20,28,37,48,60], gh=hs.map(h=>gainFor(diffToCells(placed.lat,placed.lon,h),dfc));
  lineChart('cSensAgl','gain vs mast height',hs,gh,v=>v+'m',v=>v.toFixed(2),agl);
  const ds=[0,5,10,15,20,26,32], gd=ds.map(x=>gainFor(placedDiff,x));
  lineChart('cSensDfc','gain vs power below the tower',ds,gd,v=>'-'+v,v=>v.toFixed(2),dfc);
}
function renderTab(){
  if(tab==='thr')paneThresholds();
  else if(tab==='gain')paneGains();
  else if(tab==='rob')paneRobustness();
  else paneSensitivity();
}

/* ---------- map ---------- */
function fit(){const d=devicePixelRatio||1;VW=cv.clientWidth;VH=cv.clientHeight;
 cv.width=VW*d;cv.height=VH*d;cx.setTransform(d,0,0,d,0,0);}
function scl(){return Math.min(VW/((B[3]-B[1])*kx),VH/(B[2]-B[0]))*0.94*zoom;}
function proj(la,lo){const s=scl();
 return [VW/2+(lo-(B[1]+B[3])/2)*kx*s+panX, VH/2-(la-(B[0]+B[2])/2)*s+panY];}
function unproj(px,py){const s=scl();
 return [(B[0]+B[2])/2-(py-panY-VH/2)/s,(B[1]+B[3])/2+(px-panX-VW/2)/(kx*s)];}
const shade=document.createElement('canvas');
(function(){const H2=DM.ny,W2=DM.nx,z=DM.z;shade.width=W2;shade.height=H2;
 const g=shade.getContext('2d'),img=g.createImageData(W2,H2);
 const dark=matchMedia('(prefers-color-scheme:dark)').matches;
 for(let i=0;i<H2;i++)for(let j=0;j<W2;j++){
   const i0=i>0?i-1:0,i1=i<H2-1?i+1:H2-1,j0=j>0?j-1:0,j1=j<W2-1?j+1:W2-1;
   const dx=(z[i*W2+j1]-z[i*W2+j0])/(2*DM.ew), dy=(z[i1*W2+j]-z[i0*W2+j])/(2*DM.ns);
   let v=(1+(-dx*0.7071+dy*0.7071))/2; v=Math.max(0,Math.min(1,0.5+2.6*(v-0.5)));
   const base=dark?38:214,rg=dark?46:44,g2=Math.round(base+rg*(v-0.5)*2),k=(i*W2+j)*4;
   img.data[k]=g2;img.data[k+1]=g2;img.data[k+2]=Math.round(g2*.97);img.data[k+3]=255;}
 g.putImageData(img,0,0);})();
function draw(){
 cx.clearRect(0,0,VW,VH);cx.fillStyle=C('--surface');cx.fillRect(0,0,VW,VH);
 const [x0,y0]=proj(DM.n,DM.w),[x1,y1]=proj(DM.s,DM.e);
 if(on.relief)cx.drawImage(shade,x0,y0,x1-x0,y1-y0);
 const sz=Math.max(1.3,D.cell_deg*scl());
 for(let i=0;i<N;i++){
   if(covB[i])continue; const fx=covA[i]===1;
   if(fx?!on.fixed:!on.dead)continue;
   const [x,y]=proj(LA[i],LO[i]);
   if(x<-20||x>VW+20||y<-20||y>VH+20)continue;
   cx.globalAlpha=fx?.66:.32;cx.fillStyle=fx?C('--c3'):C('--c4');
   cx.fillRect(x-sz/2,y-sz/2,sz,sz);}
 cx.globalAlpha=1;
 const r=Math.max(1,1.4*Math.sqrt(zoom));
 D.pts.forEach(p=>{if(p[2]?!on.served:!on.nocell)return;
   const [x,y]=proj(p[0],p[1]); if(x<-5||x>VW+5||y<-5||y>VH+5)return;
   cx.globalAlpha=.85;cx.fillStyle=p[2]?C('--c1'):C('--c4');
   cx.beginPath();cx.arc(x,y,r,0,7);cx.fill();});
 cx.globalAlpha=1;
 const pin=(la,lo,fill,label,rr)=>{const[x,y]=proj(la,lo);
   cx.beginPath();cx.arc(x,y,rr,0,7);cx.fillStyle=fill;cx.fill();
   cx.lineWidth=2.4;cx.strokeStyle=C('--ground');cx.stroke();
   cx.fillStyle=C('--ink');cx.font='600 10.5px '+C('--mono');cx.fillText(label,x+rr+5,y+4);};
 const rec=D.assets[asset].site; if(rec)pin(rec.lat,rec.lon,C('--c2'),'optimiser',7);
 pin(D.macro.lat,D.macro.lon,C('--ink'),'existing tower',7);
 if(placed)pin(placed.lat,placed.lon,C('--c3'),'YOUR SITE',9);
}
function legend(){
 const L=[['dead','Dead now',C('--c4')],['fixed','Fixed by this site',C('--c3')],
          ['nocell','Measured: no cell',C('--c4')],['served','Measured: served',C('--c1')],
          ['relief','Terrain relief','#bbb']];
 $('legend').innerHTML=L.map(([k,t,c])=>
  `<div class="lg ${on[k]?'':'off'}" data-k="${k}"><i style="background:${c}"></i>${t}</div>`).join('');
 document.querySelectorAll('.lg').forEach(e=>e.onclick=()=>{on[e.dataset.k]=!on[e.dataset.k];legend();draw();});
}
function busy(fn){$('busy').style.opacity=1;setTimeout(()=>{fn();$('busy').style.opacity=0;},16);}
$('asset').innerHTML=Object.keys(D.assets).map(k=>
 `<button data-a="${k}" aria-pressed="${k===asset}">${D.assets[k].short}</button>`).join('');
$('asset').onclick=e=>{const b=e.target.closest('button');if(!b)return;
 asset=b.dataset.a; agl=D.assets[asset].agl; dfc=D.assets[asset].deficit;
 [...$('asset').children].forEach(x=>x.setAttribute('aria-pressed',x===b));
 $('agl').value=agl;$('aglV').textContent=agl.toFixed(0);
 $('dfc').value=dfc;$('dfcV').textContent=dfc.toFixed(0);
 busy(recompute);};
$('tabs').onclick=e=>{const b=e.target.closest('button');if(!b)return;
 tab=b.dataset.t;[...$('tabs').children].forEach(x=>x.setAttribute('aria-pressed',x===b));
 ['thr','gain','rob','sens'].forEach(t=>$('p-'+t).className='pane'+(t===tab?' on':''));
 busy(renderTab);};
$('agl').oninput=e=>{agl=+e.target.value;$('aglV').textContent=agl;busy(recompute);};
$('dfc').oninput=e=>{dfc=+e.target.value;$('dfcV').textContent=dfc;busy(recompute);};
$('thr').oninput=e=>{availPct=+e.target.value;$('thrV').textContent=availPct;busy(recompute);};
$('useRec').onclick=()=>{const s=D.assets[asset].site;
 if(s){placed={lat:s.lat,lon:s.lon};busy(recompute);}};
$('clear').onclick=()=>{placed=null;busy(recompute);};
cv.addEventListener('mousedown',e=>{drag={x:e.offsetX,y:e.offsetY,px:panX,py:panY,moved:false};});
addEventListener('mousemove',e=>{if(!drag)return;const b=cv.getBoundingClientRect();
 const ox=e.clientX-b.left,oy=e.clientY-b.top;
 if(Math.abs(ox-drag.x)+Math.abs(oy-drag.y)>4)drag.moved=true;
 panX=drag.px+(ox-drag.x);panY=drag.py+(oy-drag.y);draw();});
addEventListener('mouseup',()=>{if(drag&&!drag.moved){const[la,lo]=unproj(drag.x,drag.y);
 placed={lat:la,lon:lo};busy(recompute);} drag=null;});
cv.addEventListener('wheel',e=>{e.preventDefault();
 zoom=Math.max(.6,Math.min(20,zoom*(e.deltaY<0?1.15:1/1.15)));draw();},{passive:false});
addEventListener('resize',()=>{fit();draw();});
matchMedia('(prefers-color-scheme:dark)').addEventListener('change',()=>location.reload());
$('model').innerHTML=`
 <tr><td>path-loss n</td><td>${D.model.n.toFixed(2)}</td></tr>
 <tr><td>diffraction</td><td>${D.model.bdiff.toFixed(2)} dB/dB</td></tr>
 <tr><td>residual &sigma;</td><td>${D.model.sigma.toFixed(2)} dB</td></tr>
 <tr><td>DEM posts</td><td>${D.model.post_m.toFixed(0)} m</td></tr>
 <tr><td>demand cells</td><td>${N.toLocaleString()}</td></tr>
 <tr><td>weighting</td><td>${(100*D.weights.route).toFixed(0)}% route / ${(100*D.weights.area).toFixed(0)}% area</td></tr>`;
$('agl').value=agl;$('aglV').textContent=agl.toFixed(0);
$('dfc').value=dfc;$('dfcV').textContent=dfc.toFixed(0);
$('thr').value=availPct;$('thrV').textContent=availPct;
fit();legend();recompute();
</script>"""
