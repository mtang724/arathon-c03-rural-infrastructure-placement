"""The parameterised planner page. One template, any number of simulators.

`__DATA__` is replaced at build time by build_planner.py. Everything the page
knows arrives through that blob; there is no model-specific code below this
line, only the two prediction modes the bundle format defines.
"""

TPL = r"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rural Coverage Planner</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>
:root{--bg:#0e1116;--pan:#151a21;--ln:#242c37;--fg:#e6edf3;--mut:#8b97a6;
--acc:#4da3ff;--good:#3ddc97;--bad:#ff6b6b;--warn:#ffb454;--font:'IBM Plex Mono',ui-monospace,monospace}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:13px/1.5 var(--font)}
h1{font:700 19px Archivo,sans-serif;margin:0}
h2{font:600 11px Archivo,sans-serif;letter-spacing:.10em;text-transform:uppercase;
color:var(--mut);margin:20px 0 8px;padding-bottom:5px;border-bottom:1px solid var(--ln)}
.app{display:flex;height:100vh;overflow:hidden}
#stage{flex:1;position:relative;min-width:0;background:#0a0d11}
canvas{display:block;width:100%;height:100%;cursor:crosshair}
.hint,.busy{position:absolute;left:12px;background:rgba(10,13,17,.85);
border:1px solid var(--ln);border-radius:4px;padding:5px 9px;font-size:11px;color:var(--mut)}
.hint{bottom:12px}
.busy{top:12px;color:var(--warn);display:none}
.busy.on{display:block}
#side{width:430px;flex:none;background:var(--pan);border-left:1px solid var(--ln);
overflow-y:auto;padding:18px 18px 60px}
.sub{color:var(--mut);font-size:11px;margin-top:3px}
select,input[type=range]{width:100%}
select{background:#0e1116;color:var(--fg);border:1px solid var(--ln);border-radius:4px;
padding:6px 8px;font:12px var(--font)}
.ctl{margin:10px 0}
.ctl label{display:flex;justify-content:space-between;font-size:11px;color:var(--mut);margin-bottom:4px}
.ctl label b{color:var(--fg)}
.seg{display:flex;gap:4px;flex-wrap:wrap}
.seg button{flex:1;min-width:74px;background:#0e1116;border:1px solid var(--ln);color:var(--mut);
border-radius:4px;padding:6px 4px;font:12px var(--font);cursor:pointer}
.seg button.on{background:var(--acc);border-color:var(--acc);color:#06121f;font-weight:600}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.kpi{background:#0e1116;border:1px solid var(--ln);border-radius:5px;padding:9px 10px}
.kpi .l{font-size:10px;color:var(--mut);text-transform:uppercase;letter-spacing:.06em}
.kpi .v{font:600 17px Archivo,sans-serif;margin-top:2px}
.kpi .d{font-size:11px;color:var(--good);margin-top:1px}
table{width:100%;border-collapse:collapse;font-size:11.5px}
td,th{padding:4px 5px;border-bottom:1px solid var(--ln);text-align:left;vertical-align:top}
th{color:var(--mut);font-weight:500}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.act{width:100%;margin-top:8px;background:var(--acc);border:0;color:#06121f;font:600 12px var(--font);
padding:9px;border-radius:5px;cursor:pointer}
.act.ghost{background:transparent;border:1px solid var(--ln);color:var(--mut)}
.note{font-size:11px;color:var(--mut);margin-top:6px}
.warn{border-left:2px solid var(--warn);padding-left:8px;color:var(--warn);font-size:11px;margin-top:8px}
.tag{display:inline-block;font-size:10px;border:1px solid var(--ln);border-radius:3px;
padding:1px 5px;color:var(--mut);margin-left:5px}
</style>
<div class="app">
 <div id="stage">
  <canvas id="cv"></canvas>
  <div class="hint" id="hint">click to place &middot; drag to pan &middot; scroll to zoom</div>
  <div class="busy" id="busy">computing&hellip;</div>
 </div>
 <div id="side">
  <h1>Rural Coverage Planner</h1>
  <div class="sub">ARA COTS &middot; any simulator, any objective</div>

  <h2>Simulator</h2>
  <select id="sim"></select>
  <div class="note" id="simNote"></div>

  <h2>What counts as served</h2>
  <select id="crit"></select>
  <div class="ctl">
   <label>Target <b><span id="thrV"></span></b></label>
   <input type="range" id="thr">
  </div>
  <div class="note" id="critNote"></div>
  <div class="note">Service test: RSRP &ge; <b id="thrDb"></b> dBm</div>

  <h2>What we are optimising</h2>
  <div class="ctl">
   <label>Route-km weight <b><span id="wV"></span></b></label>
   <input type="range" id="w" min="0" max="100" step="5">
  </div>
  <div class="note">Area weight is the remainder. Route demand measures the
   survey, not the population; area demand does not.</div>

  <h2>Asset</h2>
  <div class="seg" id="asset"></div>
  <div class="ctl">
   <label>Mast height <b><span id="aglV"></span> m</b></label>
   <input type="range" id="agl" min="6" max="60" step="1">
  </div>
  <div class="ctl">
   <label>Power vs the tower <b>&minus;<span id="dfcV"></span> dB</b></label>
   <input type="range" id="dfc" min="0" max="34" step="1">
  </div>
  <div id="warn"></div>

  <h2>Before &rarr; after</h2>
  <div class="grid2">
   <div class="kpi"><div class="l">Route-km</div><div class="v" id="kRk"></div><div class="d" id="dRk"></div></div>
   <div class="kpi"><div class="l">Area km&sup2;</div><div class="v" id="kAr"></div><div class="d" id="dAr"></div></div>
   <div class="kpi"><div class="l">Score</div><div class="v" id="kSc"></div><div class="d" id="dSc"></div></div>
   <div class="kpi"><div class="l">Cells fixed</div><div class="v" id="kFx"></div><div class="d" id="kDead"></div></div>
  </div>

  <h2>Optimised siting</h2>
  <button class="act" id="opt">Find the best site</button>
  <table id="best"></table>
  <button class="act ghost" id="useRec">Use the top site</button>
  <button class="act ghost" id="clear">Clear placement</button>

  <h2>Does the answer depend on the objective?</h2>
  <button class="act ghost" id="sweepC">Sweep every criterion</button>
  <button class="act ghost" id="sweepW">Sweep the route/area weight</button>
  <button class="act ghost" id="sweepS">Compare every simulator</button>
  <table id="sweep"></table>

  <h2>Placed site</h2>
  <table id="site"></table>

  <h2>Model</h2>
  <table id="model"></table>
 </div>
</div>
<script>
const D=__DATA__;
const $=i=>document.getElementById(i);
const cv=$('cv'),cx=cv.getContext('2d');
const R_EARTH=6371000;
let VW=0,VH=0,zoom=1,panX=0,panY=0,drag=null,placed=null;
let bi=0,asset='macro',agl=0,dfc=0,critKey='',target=0,wRoute=0.70;
let matCache={};                 // "bi|agl" -> Float32Array(nCand*nCell)

function B(){return D.bundles[bi];}
function nCells(){return B().grid.lat.length;}

/* ---------------- geometry, ported from propagation.py ---------------- */
function hav(a,b,c,d){const p1=a*Math.PI/180,p2=c*Math.PI/180,dp=p2-p1,dl=(d-b)*Math.PI/180;
 const x=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;
 return 2*R_EARTH*Math.asin(Math.sqrt(Math.min(1,Math.max(0,x))));}
function bearing(a,b,c,d){const p1=a*Math.PI/180,p2=c*Math.PI/180,dl=(d-b)*Math.PI/180;
 return Math.atan2(Math.sin(dl)*Math.cos(p2),
   Math.cos(p1)*Math.sin(p2)-Math.sin(p1)*Math.cos(p2)*Math.cos(dl));}
function knife(v){if(v<=-0.78)return 0;const w=v-0.1;
 return Math.max(0,6.9+20*Math.log10(Math.sqrt(w*w+1)+w));}
function demAt(la,lo){const M=D.dem;
 let fi=(la-M.lat0)/M.dlat, fj=(lo-M.lon0)/M.dlon;
 fi=Math.min(Math.max(fi,0),M.ny-1.001); fj=Math.min(Math.max(fj,0),M.nx-1.001);
 const i0=fi|0,j0=fj|0,ti=fi-i0,tj=fj-j0,z=M.z;
 return (1-ti)*(1-tj)*z[i0*M.nx+j0]+ti*(1-tj)*z[(i0+1)*M.nx+j0]
      +(1-ti)*tj*z[i0*M.nx+j0+1]+ti*tj*z[(i0+1)*M.nx+j0+1];}

/* Worst knife-edge and worst Fresnel clearance along one path.
   Both are needed: family two_slope_terrain/1 carries a coefficient on each,
   and the old planner shipped only the first, which is why it was optimistic
   by a mean of 5.95 dB against its own optimiser. */
function pathTerms(tLa,tLo,tAgl,rLa,rLo,NS){
 const K=B().prediction.coefficients,lam=K.lambda_m,REF=R_EARTH*K.k_earth;
 const tz=demAt(tLa,tLo)+tAgl, rz=demAt(rLa,rLo)+K.rx_agl_m;
 const dtot=Math.max(1,hav(tLa,tLo,rLa,rLo));
 let vmax=-1e9, fmin=1e9;
 for(let s=1;s<NS-1;s++){
  const f=s/(NS-1), d1=dtot*f, d2=dtot-d1;
  const g=demAt(tLa+(rLa-tLa)*f,tLo+(rLo-tLo)*f)+d1*d2/(2*REF);
  const clear=(tz+(rz-tz)*f)-g;
  const F1=Math.sqrt(Math.max(1e-9,lam*d1*d2/dtot));
  const fr=clear/F1;
  if(fr<fmin)fmin=fr;
  const v=-Math.SQRT2*fr; if(v>vmax)vmax=v;
 }
 return {diff:knife(vmax),fres:Math.min(3,Math.max(-3,fmin)),d:dtot};
}
/* family two_slope_terrain/1, complete. Keep in step with
   common/schema.py::FAMILIES and terrain-approach coverage_terrain.py. */
function analytic(t,deficit,az){
 const K=B().prediction.coefficients, ld=Math.log10(Math.max(30,t.d));
 const dual=Math.max(0,ld-Math.log10(K.break_m));
 const diff=t.diff-(K.orth_diff[0]+K.orth_diff[1]*ld);
 const fres=t.fres-(K.orth_fres[0]+K.orth_fres[1]*ld);
 let r=K.b0+K.slope*ld+K.b_dual*dual-deficit+K.b_diff*diff+K.b_fres*fres;
 if(az!==undefined)r+=K.az[0]*Math.cos(az)+K.az[1]*Math.sin(az);
 return r;
}
function nodeToCells(la,lo,a,deficit,NS){
 const b=B(),n=b.grid.lat.length,out=new Float32Array(n);
 for(let i=0;i<n;i++){
  const t=pathTerms(la,lo,a,b.grid.lat[i],b.grid.lon[i],NS||48);
  out[i]=analytic(t,deficit);
 }
 return out;
}

/* ---------------- criterion -> RSRP threshold ---------------- */
/* The one inversion in the system: first grid point at or above the target.
   common/schema.py::CoverageBundle.threshold_dbm does exactly this scan. */
function thresholdDbm(){
 const b=B(),c=b.objective.criteria[critKey],g=b.objective.rsrp_grid;
 for(let i=0;i<c.value.length;i++) if(c.value[i]>=target) return g[i];
 return Infinity;
}

/* ---------------- scoring ---------------- */
function scoreOf(cov){
 const b=B(),rk=b.grid.route_km;let r=0,a=0;
 for(let i=0;i<cov.length;i++) if(cov[i]){r+=rk[i];a+=b.grid.area_km2;}
 return {rk:r,ar:a,
   s:wRoute*r/b.grid.total_route_km+(1-wRoute)*a/b.grid.total_area_km2};
}
function coverOf(arr,thr){const c=new Uint8Array(arr.length);
 for(let i=0;i<arr.length;i++)c[i]=arr[i]>=thr?1:0;return c;}

/* ---------------- the candidate matrix ---------------- */
/* Analytic bundles build it once in the page, so they cost nothing to ship and
   can still evaluate a pin dropped anywhere. Tabulated bundles carry it,
   because a ray tracer or a neural operator has no closed form to hand a
   browser -- and those bundles snap a dropped pin to the nearest candidate. */
function matrix(a,cb){
 const key=bi+'|'+a;
 if(matCache[key]){cb(matCache[key]);return;}
 const b=B(),nc=b.prediction.candidates.length,n=b.grid.lat.length;
 if(b.prediction.mode==='tabulated'){
  const k=b.prediction.agl_m.indexOf(a);
  const raw=atob(b.prediction.rsrp_q[k>=0?k:0]);
  const M=new Float32Array(nc*n);
  for(let i=0;i<M.length;i++)
    M[i]=raw.charCodeAt(i)*b.prediction.q_scale+b.prediction.q_offset;
  matCache[key]=M;cb(M);return;
 }
 const M=new Float32Array(nc*n);
 $('busy').classList.add('on');
 let i=0;
 (function step(){
  const end=Math.min(nc,i+12);
  for(;i<end;i++){
   const c=b.prediction.candidates[i];
   M.set(nodeToCells(c.lat,c.lon,a,0,32),i*n);
  }
  $('busy').textContent='computing coverage surfaces '+i+'/'+nc;
  if(i<nc)setTimeout(step,0);
  else{$('busy').classList.remove('on');matCache[key]=M;cb(M);}
 })();
}

/* ---------------- greedy max-coverage ---------------- */
function solve(M,k,cb){
 const b=B(),n=b.grid.lat.length,nc=b.prediction.candidates.length;
 const thr=thresholdDbm(),base=Float32Array.from(b.baseline_rsrp_dbm);
 const A=D.assets[asset];
 const feas=b.prediction.candidates.map(c=>A.donor_min_dbm===null
    ||c.donor_rsrp_dbm>=A.donor_min_dbm);
 let cur=Float32Array.from(base);
 let s0=scoreOf(coverOf(cur,thr)).s;
 const picks=[];
 for(let round=0;round<k;round++){
  let best=-1,bg=1e-12,bestArr=null;
  for(let i=0;i<nc;i++){
   if(!feas[i])continue;
   const off=i*n;let r=0,a=0;
   for(let j=0;j<n;j++){
    const v=Math.max(cur[j],M[off+j]-dfc);
    if(v>=thr){r+=b.grid.route_km[j];a+=b.grid.area_km2;}
   }
   const s=wRoute*r/b.grid.total_route_km+(1-wRoute)*a/b.grid.total_area_km2-s0;
   if(s>bg){bg=s;best=i;}
  }
  if(best<0)break;
  bestArr=new Float32Array(n);
  for(let j=0;j<n;j++)bestArr[j]=Math.max(cur[j],M[best*n+j]-dfc);
  cur=bestArr;s0+=bg;picks.push({i:best,gain:bg});
 }
 cb(picks);
}

/* ---------------- rendering ---------------- */
function proj(la,lo){const b=D.bounds,kx=Math.cos(42*Math.PI/180);
 const w=(b[3]-b[1])*kx,h=(b[2]-b[0]);
 const sc=Math.min(VW/w,VH/h)*zoom;
 return [(lo-b[1])*kx*sc+panX+(VW-w*sc)/2,(b[2]-la)*sc+panY+(VH-h*sc)/2,sc];
}
function draw(){
 const b=B();cx.setTransform(1,0,0,1,0,0);cx.clearRect(0,0,VW,VH);
 const thr=thresholdDbm();
 const base=b.baseline_rsrp_dbm;
 const after=placed?placed.arr:null;
 const cd=D.cell_deg,kx=Math.cos(42*Math.PI/180);
 for(let i=0;i<b.grid.lat.length;i++){
  const p=proj(b.grid.lat[i]+cd/2,b.grid.lon[i]-cd/2/kx),sc=p[2];
  const w=cd*kx*sc,h=cd*sc;
  if(p[0]<-w||p[0]>VW||p[1]<-h||p[1]>VH)continue;
  const wasOn=base[i]>=thr, nowOn=after?(Math.max(base[i],after[i])>=thr):wasOn;
  let col=null;
  if(wasOn)col='rgba(61,220,151,.20)';
  else if(nowOn)col='rgba(77,163,255,.55)';
  else col='rgba(255,107,107,.16)';
  cx.fillStyle=col;cx.fillRect(p[0],p[1],Math.max(1,w),Math.max(1,h));
 }
 const m=proj(b.macro.lat,b.macro.lon);
 cx.fillStyle='#ffb454';cx.beginPath();cx.arc(m[0],m[1],5,0,7);cx.fill();
 if(placed){const q=proj(placed.lat,placed.lon);
  cx.strokeStyle='#4da3ff';cx.lineWidth=2;cx.beginPath();cx.arc(q[0],q[1],7,0,7);cx.stroke();}
}

/* ---------------- UI ---------------- */
function fmtT(){const c=B().objective.criteria[critKey];
 return c.unit==='fraction'?Math.round(target*100)+'%':target.toFixed(
   c.threshold_step<1?1:0)+' '+c.unit;}

function refreshCrit(){
 const b=B(),sel=$('crit');sel.innerHTML='';
 Object.keys(b.objective.criteria).forEach(k=>{
  const c=b.objective.criteria[k];
  sel.innerHTML+='<option value="'+k+'"'+(k===critKey?' selected':'')+'>'+c.label+
   ' ('+c.unit+')</option>';});
 const c=b.objective.criteria[critKey];
 const t=$('thr');t.min=c.threshold_min;t.max=c.threshold_max;t.step=c.threshold_step;
 t.value=target;
 $('thrV').textContent=fmtT();
 $('critNote').textContent=c.blurb;
 const d=thresholdDbm();
 $('thrDb').textContent=isFinite(d)?d.toFixed(1):'unreachable';
}
function refreshKPI(){
 const b=B(),thr=thresholdDbm();
 const base=Float32Array.from(b.baseline_rsrp_dbm);
 const cb=coverOf(base,thr),sb=scoreOf(cb);
 let ca=cb,sa=sb;
 if(placed){const arr=new Float32Array(base.length);
  for(let i=0;i<base.length;i++)arr[i]=Math.max(base[i],placed.arr[i]);
  ca=coverOf(arr,thr);sa=scoreOf(ca);}
 let fixed=0,dead=0;
 for(let i=0;i<cb.length;i++){if(!cb[i])dead++;if(!cb[i]&&ca[i])fixed++;}
 $('kRk').textContent=sa.rk.toFixed(1)+' / '+b.grid.total_route_km.toFixed(0);
 $('dRk').textContent=(sa.rk-sb.rk>=0?'+':'')+(sa.rk-sb.rk).toFixed(1)+' km ('
  +(100*sa.rk/b.grid.total_route_km).toFixed(1)+'%)';
 $('kAr').textContent=sa.ar.toFixed(1);
 $('dAr').textContent=(sa.ar-sb.ar>=0?'+':'')+(sa.ar-sb.ar).toFixed(1)+' km² ('
  +(100*sa.ar/b.grid.total_area_km2).toFixed(1)+'%)';
 $('kSc').textContent=sa.s.toFixed(3);
 $('dSc').textContent=(sa.s-sb.s>=0?'+':'')+(sa.s-sb.s).toFixed(3);
 $('kFx').textContent=fixed;$('kDead').textContent='of '+dead+' unserved';
}
function refreshModel(){
 const b=B(),s=b.simulator;
 let h='<tr><td>simulator</td><td>'+s.label+'</td></tr>'
  +'<tr><td>approach</td><td>'+s.approach+'</td></tr>'
  +'<tr><td>mode</td><td>'+b.prediction.mode
  +(b.prediction.family?' &middot; '+b.prediction.family:'')+'</td></tr>'
  +'<tr><td>fitted on</td><td>'+(s.fitted_on_rows?s.fitted_on_rows.toLocaleString()
    +' rows':'nothing &mdash; physics only')+'</td></tr>'
  +'<tr><td>residual &sigma;</td><td>'+s.sigma_db.toFixed(2)+' dB</td></tr>';
 if(b.prediction.mode==='analytic')
  Object.keys(b.prediction.coefficients).forEach(k=>{
   const v=b.prediction.coefficients[k];
   h+='<tr><td>'+k+'</td><td>'+(Array.isArray(v)?v.map(x=>(+x).toFixed(3)).join(', ')
     :(typeof v==='number'?(+v).toFixed(4):v))+'</td></tr>';});
 $('model').innerHTML=h;
 $('simNote').textContent=s.notes;
 $('hint').textContent=b.prediction.mode==='analytic'
  ? 'click to place anywhere · drag to pan · scroll to zoom'
  : 'click snaps to the nearest precomputed candidate · drag to pan';
}
function place(la,lo){
 const b=B();
 if(b.prediction.mode==='analytic'){
  placed={lat:la,lon:lo,arr:nodeToCells(la,lo,agl,dfc,64),snapped:0};
  after();
 }else{
  let bestI=0,bd=1e18;
  b.prediction.candidates.forEach((c,i)=>{const d=hav(la,lo,c.lat,c.lon);
   if(d<bd){bd=d;bestI=i;}});
  matrix(nearestAgl(),M=>{
   const n=b.grid.lat.length,arr=new Float32Array(n);
   for(let j=0;j<n;j++)arr[j]=M[bestI*n+j]-dfc;
   const c=b.prediction.candidates[bestI];
   placed={lat:c.lat,lon:c.lon,arr:arr,snapped:bd};after();});
 }
}
function nearestAgl(){const l=B().prediction.agl_m;
 let b=l[0];l.forEach(v=>{if(Math.abs(v-agl)<Math.abs(b-agl))b=v;});return b;}
function after(){
 let h='';
 if(placed){
  h='<tr><td>position</td><td>'+placed.lat.toFixed(5)+', '+placed.lon.toFixed(5)+'</td></tr>';
  if(placed.snapped>1) h+='<tr><td>snapped</td><td>'+placed.snapped.toFixed(0)
   +' m to the nearest candidate</td></tr>';
  const A=D.assets[asset];
  if(A.donor_min_dbm!==null){
   const b=B();let dn=-999;
   b.prediction.candidates.forEach(c=>{if(hav(c.lat,c.lon,placed.lat,placed.lon)<300)
     dn=Math.max(dn,c.donor_rsrp_dbm);});
   $('warn').innerHTML=(dn<A.donor_min_dbm)?'<div class="warn">A donor-fed relay '
    +'needs a signal to rebroadcast. Here the donor link is about '+dn.toFixed(0)
    +' dBm, below the '+A.donor_min_dbm+' dBm this class needs.</div>':'';
  } else $('warn').innerHTML='';
 }
 $('site').innerHTML=h;
 refreshKPI();draw();
}
function showBest(picks){
 const b=B();let h='<tr><th>#</th><th>position</th><th class="n">marginal</th></tr>';
 let prev=0;
 picks.forEach((p,k)=>{const c=b.prediction.candidates[p.i];
  h+='<tr><td>'+(k+1)+'</td><td>'+c.lat.toFixed(5)+', '+c.lon.toFixed(5)
   +'<span class="tag">'+c.kind+'</span></td><td class="n">+'
   +(p.gain-prev).toFixed(3)+'</td></tr>';prev=p.gain;});
 $('best').innerHTML=h;
 window.__picks=picks;
}
function optimise(){
 matrix(nearestAgl(),M=>{solve(M,3,picks=>{showBest(picks);
  if(picks.length){const c=B().prediction.candidates[picks[0].i];
   place(c.lat,c.lon);}});});
}

/* ---------------- sweeps: does the answer move? ---------------- */
function sweepRows(rows,head){
 let h='<tr><th>'+head+'</th><th>best site</th><th class="n">route %</th><th class="n">move</th></tr>';
 rows.forEach(r=>{h+='<tr><td>'+r.k+'</td><td>'+(r.lat?r.lat.toFixed(5)+', '
  +r.lon.toFixed(5):'&mdash;')+'</td><td class="n">'+r.rk.toFixed(1)+'</td>'
  +'<td class="n">'+(r.mv===null?'&mdash;':r.mv.toFixed(0)+' m')+'</td></tr>';});
 $('sweep').innerHTML=h;
}
function oneSolve(M,cb){solve(M,1,p=>cb(p));}
function sweepCriteria(){
 const b=B(),keys=Object.keys(b.objective.criteria);
 matrix(nearestAgl(),M=>{
  const rows=[],save=[critKey,target];let ref=null;
  keys.forEach(k=>{
   critKey=k;target=b.objective.criteria[k].default_threshold;
   const thr=thresholdDbm();if(!isFinite(thr)){rows.push({k:k,rk:0,mv:null});return;}
   let picks=null;oneSolve(M,p=>picks=p);
   if(!picks||!picks.length){rows.push({k:k,rk:0,mv:null});return;}
   const c=b.prediction.candidates[picks[0].i];
   const n=b.grid.lat.length,arr=new Float32Array(n);
   for(let j=0;j<n;j++)arr[j]=Math.max(b.baseline_rsrp_dbm[j],M[picks[0].i*n+j]-dfc);
   const s=scoreOf(coverOf(arr,thr));
   if(!ref)ref=c;
   rows.push({k:b.objective.criteria[k].label,lat:c.lat,lon:c.lon,
    rk:100*s.rk/b.grid.total_route_km,mv:hav(ref.lat,ref.lon,c.lat,c.lon)});
  });
  critKey=save[0];target=save[1];refreshCrit();refreshKPI();
  sweepRows(rows,'criterion');
 });
}
function sweepWeights(){
 const b=B();matrix(nearestAgl(),M=>{
  const rows=[],save=wRoute;let ref=null;
  [0,0.25,0.5,0.7,0.9,1].forEach(w=>{
   wRoute=w;const thr=thresholdDbm();
   let picks=null;oneSolve(M,p=>picks=p);
   if(!picks||!picks.length){rows.push({k:w.toFixed(2),rk:0,mv:null});return;}
   const c=b.prediction.candidates[picks[0].i];
   const n=b.grid.lat.length,arr=new Float32Array(n);
   for(let j=0;j<n;j++)arr[j]=Math.max(b.baseline_rsrp_dbm[j],M[picks[0].i*n+j]-dfc);
   const s=scoreOf(coverOf(arr,thr));
   if(!ref)ref=c;
   rows.push({k:'route '+w.toFixed(2),lat:c.lat,lon:c.lon,
    rk:100*s.rk/b.grid.total_route_km,mv:hav(ref.lat,ref.lon,c.lat,c.lon)});
  });
  wRoute=save;$('w').value=Math.round(wRoute*100);$('wV').textContent=wRoute.toFixed(2);
  refreshKPI();sweepRows(rows,'weighting');
 });
}
function sweepSims(){
 const save=bi,rows=[];let ref=null,k=0;
 (function next(){
  if(k>=D.bundles.length){bi=save;refreshAll();sweepRows(rows,'simulator');return;}
  bi=k;
  const b=B();
  if(!b.objective.criteria[critKey]){k++;next();return;}
  matrix(nearestAgl(),M=>{
   let picks=null;oneSolve(M,p=>picks=p);
   const thr=thresholdDbm();
   if(picks&&picks.length){
    const c=b.prediction.candidates[picks[0].i];
    const n=b.grid.lat.length,arr=new Float32Array(n);
    for(let j=0;j<n;j++)arr[j]=Math.max(b.baseline_rsrp_dbm[j],M[picks[0].i*n+j]-dfc);
    const s=scoreOf(coverOf(arr,thr));
    if(!ref)ref=c;
    rows.push({k:b.simulator.label,lat:c.lat,lon:c.lon,
     rk:100*s.rk/b.grid.total_route_km,mv:hav(ref.lat,ref.lon,c.lat,c.lon)});
   } else rows.push({k:b.simulator.label,rk:0,mv:null});
   k++;next();
  });
 })();
}

/* ---------------- wiring ---------------- */
function refreshAll(){
 const b=B();
 if(!b.objective.criteria[critKey])critKey=b.objective.default_criterion;
 target=b.objective.criteria[critKey].default_threshold;
 placed=null;$('best').innerHTML='';$('site').innerHTML='';
 refreshCrit();refreshModel();refreshKPI();draw();
}
function init(){
 const b0=D.bundles[0];
 critKey=b0.objective.default_criterion;
 target=b0.objective.criteria[critKey].default_threshold;
 wRoute=b0.objective.w_route;
 asset='macro';agl=D.assets.macro.agl_m;dfc=D.assets.macro.deficit_db;

 $('sim').innerHTML=D.bundles.map((b,i)=>'<option value="'+i+'">'+b.simulator.label
   +'</option>').join('');
 $('asset').innerHTML=Object.keys(D.assets).map(k=>'<button data-k="'+k+'"'
   +(k===asset?' class="on"':'')+'>'+D.assets[k].label.split(' ')[0]+'</button>').join('');
 $('agl').value=agl;$('aglV').textContent=agl.toFixed(0);
 $('dfc').value=dfc;$('dfcV').textContent=dfc.toFixed(0);
 $('w').value=Math.round(wRoute*100);$('wV').textContent=wRoute.toFixed(2);

 $('sim').addEventListener('change',e=>{bi=+e.target.value;matCache={};refreshAll();});
 $('crit').addEventListener('change',e=>{critKey=e.target.value;
   target=B().objective.criteria[critKey].default_threshold;
   refreshCrit();refreshKPI();draw();});
 $('thr').addEventListener('input',e=>{target=+e.target.value;
   $('thrV').textContent=fmtT();const d=thresholdDbm();
   $('thrDb').textContent=isFinite(d)?d.toFixed(1):'unreachable';
   refreshKPI();draw();});
 $('w').addEventListener('input',e=>{wRoute=+e.target.value/100;
   $('wV').textContent=wRoute.toFixed(2);refreshKPI();});
 $('agl').addEventListener('input',e=>{agl=+e.target.value;
   $('aglV').textContent=agl.toFixed(0);if(placed)place(placed.lat,placed.lon);});
 $('dfc').addEventListener('input',e=>{dfc=+e.target.value;
   $('dfcV').textContent=dfc.toFixed(0);if(placed)place(placed.lat,placed.lon);});
 $('asset').addEventListener('click',e=>{const k=e.target.getAttribute('data-k');
   if(!k)return;asset=k;agl=D.assets[k].agl_m;dfc=D.assets[k].deficit_db;
   $('agl').value=agl;$('aglV').textContent=agl.toFixed(0);
   $('dfc').value=dfc;$('dfcV').textContent=dfc.toFixed(0);
   Array.prototype.forEach.call($('asset').children,
     x=>x.className=(x.getAttribute('data-k')===k?'on':''));
   if(placed)place(placed.lat,placed.lon);});
 $('opt').addEventListener('click',optimise);
 $('sweepC').addEventListener('click',sweepCriteria);
 $('sweepW').addEventListener('click',sweepWeights);
 $('sweepS').addEventListener('click',sweepSims);
 $('clear').addEventListener('click',()=>{placed=null;after();});
 $('useRec').addEventListener('click',()=>{if(window.__picks&&window.__picks.length){
   const c=B().prediction.candidates[window.__picks[0].i];place(c.lat,c.lon);}});

 cv.addEventListener('mousedown',e=>drag={x:e.clientX,y:e.clientY,px:panX,py:panY,m:0});
 window.addEventListener('mousemove',e=>{if(!drag)return;
   panX=drag.px+(e.clientX-drag.x);panY=drag.py+(e.clientY-drag.y);
   if(Math.abs(e.clientX-drag.x)+Math.abs(e.clientY-drag.y)>4)drag.m=1;draw();});
 window.addEventListener('mouseup',e=>{
   if(drag&&!drag.m){const r=cv.getBoundingClientRect(),b=D.bounds,
     kx=Math.cos(42*Math.PI/180),w=(b[3]-b[1])*kx,h=(b[2]-b[0]);
     const sc=Math.min(VW/w,VH/h)*zoom;
     const x=e.clientX-r.left-panX-(VW-w*sc)/2, y=e.clientY-r.top-panY-(VH-h*sc)/2;
     place(b[2]-y/sc, b[1]+x/(kx*sc));}
   drag=null;});
 cv.addEventListener('wheel',e=>{e.preventDefault();
   zoom=Math.min(12,Math.max(1,zoom*(e.deltaY<0?1.15:1/1.15)));draw();});
 window.addEventListener('resize',size);
 size();refreshAll();
}
function size(){const r=cv.parentNode.getBoundingClientRect();
 VW=cv.width=r.width|0;VH=cv.height=r.height|0;draw();}
init();
</script>
"""
