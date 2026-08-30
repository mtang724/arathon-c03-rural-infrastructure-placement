"""Build a constrained variant of the planner, without touching the original.

Reads the already-built planner.html, computes open-data siting constraints for every
candidate, and writes planner_constrained.html with a Constraints panel: five sliders that
shrink the feasible set, a live count of what survives, and -- the point of the exercise --
the distance between the constrained recommendation and the unconstrained one, plus the
score given up to respect the constraints.

  python common/build_planner_constrained.py [in.html] [out.html]

Every layer is an open-data proxy, not a utility record. The page says so on its face.
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import constraints as C

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "planner.html"
DST = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "planner_constrained.html"

# default thresholds: generous, because the proxies under-map rural infrastructure
DEFAULTS = {"power": 2000, "road": 250, "structure": 500, "backhaul": 8000, "water": 50}
CAPS     = {"power": 6000, "road": 1000, "structure": 1000, "backhaul": 13000, "water": 500}
NOTE = {
    "power":     "OpenStreetMap maps transmission towers well and rural distribution poorly, "
                 "so this reads pessimistically. Real utility data would replace it.",
    "road":      "Any mapped highway. Stands in for legal access and construction access.",
    "structure": "A building, silo, mast or tower to mount on instead of raising new steel.",
    "backhaul":  "Distance to an existing base station, as a proxy for fibre or a donor link.",
    "water":     "A hard exclusion: minimum distance from mapped water.",
}

html = SRC.read_text(encoding="utf-8", errors="replace")
m = re.search(r"const D\s*=\s*(\{.*?\});\s*\n", html, re.S)
D = json.loads(m.group(1))
cands = D["bundles"][0]["prediction"]["candidates"]
clat = np.array([c["lat"] for c in cands]); clon = np.array([c["lon"] for c in cands])
print(f"{len(cands)} candidates")

layers = C.extract(verbose=True)
dist = C.distances(clat, clon, layers)
for k, v in dist.items():
    for c, x in zip(cands, v):
        c[f"d_{k}"] = None if not np.isfinite(x) else round(float(x))
D["constraints"] = {
    "defaults": DEFAULTS, "caps": CAPS,
    "labels": {k: C.LAYERS[k]["label"] for k in C.LAYERS},
    "proxy":  {k: C.LAYERS[k]["proxy"] for k in C.LAYERS},
    "note":   NOTE,
    "counts": {k: int(len(v)) for k, v in layers.items()},
}

PANEL = """
  <h2>Placement constraints <span class="pill">open-data proxy</span></h2>
  <div class="sub" id="cxNote">The measurement data says where service is poor, not where
  an asset may be built. These five layers come from OpenStreetMap and building footprints,
  not from utility or land records — they are evidence, not permission.</div>
  <div id="cxRows"></div>
  <div class="kpis" style="margin-top:8px">
    <div class="kpi"><div class="k">Feasible sites</div><div class="v" id="cxN">—</div>
      <div class="d" id="cxPct">of 0 candidates</div></div>
    <div class="kpi"><div class="k">Cost of constraints</div><div class="v" id="cxCost">—</div>
      <div class="d" id="cxMoved">score given up</div></div>
  </div>
  <div class="sub" id="cxCompare"></div>
"""

CSS = """
.pill{font-size:10px;padding:1px 6px;border-radius:8px;background:#243244;color:#9fd0ff;
 vertical-align:middle;margin-left:6px;letter-spacing:0}
.cxrow{margin:7px 0}
.cxhead{display:flex;justify-content:space-between;align-items:baseline;gap:6px}
.cxhead label{display:flex;gap:6px;align-items:center;cursor:pointer}
.cxv{font-variant-numeric:tabular-nums;color:#9fd0ff}
.cxwhy{font-size:10.5px;color:#7b8794;margin-top:2px;line-height:1.35}
.cxoff{opacity:.42}
"""

JS = r"""
/* ---- placement constraints -------------------------------------------------
   The feasible set is the intersection of five open-data proxies. Everything the
   optimiser does downstream runs on that subset, so tightening a slider both shrinks
   the candidate lattice and changes which site wins. */
const CX = D.constraints, CXKEYS = ["power","road","structure","backhaul","water"];
const cxState = {};
CXKEYS.forEach(k => cxState[k] = {on:true, val:CX.defaults[k]});

function cxFeasible(cands){
  return cands.map(c => CXKEYS.every(k => {
    if(!cxState[k].on) return true;
    const d = c["d_"+k];
    if(d === null || d === undefined) return k === "water";   /* no water mapped nearby is fine */
    return k === "water" ? d >= cxState[k].val : d <= cxState[k].val;
  }));
}

function cxBuildUI(){
  const host = $("cxRows"); let h = "";
  CXKEYS.forEach(k => {
    const s = cxState[k], cap = CX.caps[k];
    const rel = k === "water" ? "at least" : "within";
    h += '<div class="cxrow'+(s.on?'':' cxoff')+'" id="cxrow_'+k+'">'
      +  '<div class="cxhead"><label><input type="checkbox" id="cxon_'+k+'"'+(s.on?' checked':'')
      +  '> '+CX.labels[k]+'</label><span class="cxv" id="cxval_'+k+'">'+rel+' '+s.val+' m</span></div>'
      +  '<input type="range" id="cxsl_'+k+'" min="0" max="'+cap+'" step="25" value="'+s.val+'">'
      +  '<div class="cxwhy">'+CX.note[k]+' <b>'+CX.counts[k].toLocaleString()+'</b> features mapped.</div>'
      +  '</div>';
  });
  host.innerHTML = h;
  CXKEYS.forEach(k => {
    $("cxon_"+k).onchange = e => { cxState[k].on = e.target.checked;
      $("cxrow_"+k).className = "cxrow" + (e.target.checked ? "" : " cxoff"); cxRefresh(); };
    $("cxsl_"+k).oninput = e => { cxState[k].val = +e.target.value;
      $("cxval_"+k).textContent = (k === "water" ? "at least " : "within ") + cxState[k].val + " m";
      cxRefresh(); };
  });
}

function cxRefresh(){
  const b = B(), f = cxFeasible(b.prediction.candidates);
  const n = f.filter(Boolean).length;
  $("cxN").textContent = n;
  $("cxPct").textContent = "of " + f.length + " candidates ("
    + Math.round(100*n/f.length) + "%)";
  if(!n) $("cxCompare").innerHTML =
    '<b style="color:#e8896a">No candidate satisfies every constraint.</b> '
    + 'Relax one, or accept that this asset class cannot be sited on open-data evidence alone.';
  draw();
}

/* Solve twice — once on everything, once on the feasible subset — and report the gap.
   That difference IS the sensitivity to placement constraints. */
function cxCompare(){
  const b = B();
  matrix(nearestAgl(), M => {
    solveSubset(M, 'all', free => {
      solveSubset(M, cxFeasible(b.prediction.candidates), lim => {
        const cf = free.length ? b.prediction.candidates[free[0].i] : null;
        const cl = lim.length  ? b.prediction.candidates[lim[0].i]  : null;
        if(!cf){ $("cxCompare").textContent = "No site helps under any setting."; return; }
        if(!cl){ $("cxCost").textContent = "∞";
          $("cxCompare").innerHTML = "The unconstrained optimum gains <b>"
            + free[0].gain.toFixed(3) + "</b>, but nothing feasible does."; return; }
        const cost = free[0].gain - lim[0].gain;
        const dm = haversine(cf.lat, cf.lon, cl.lat, cl.lon);
        $("cxCost").textContent = (cost <= 0 ? "0.000" : "−" + cost.toFixed(3));
        $("cxMoved").textContent = "and moves " + (dm >= 1000
          ? (dm/1000).toFixed(1) + " km" : Math.round(dm) + " m");
        $("cxCompare").innerHTML =
            'Unconstrained best <b>' + cf.lat.toFixed(5) + ', ' + cf.lon.toFixed(5)
          + '</b> gains ' + free[0].gain.toFixed(3) + '.<br>Feasible best <b>'
          + cl.lat.toFixed(5) + ', ' + cl.lon.toFixed(5) + '</b> gains ' + lim[0].gain.toFixed(3)
          + ' — <b>' + (dm >= 1000 ? (dm/1000).toFixed(1)+' km' : Math.round(dm)+' m')
          + '</b> away, giving up <b>' + (cost <= 0 ? "nothing" : cost.toFixed(3)) + '</b>.'
          + (cost <= 0 ? ' The constraints cost nothing here.' : '');
        showBest(lim); place(cl.lat, cl.lon);
      });
    });
  });
}

function haversine(a,b,c,d){const R=6371000,r=Math.PI/180;
 const p1=a*r,p2=c*r,dp=(c-a)*r,dl=(d-b)*r;
 const x=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;
 return 2*R*Math.asin(Math.sqrt(x));}
"""

# --- surgical edits ---------------------------------------------------------
n_edits = 0

# 1. constraints must gate the optimiser's feasible set
old_feas = """ const feas=b.prediction.candidates.map(c=>A.donor_min_dbm===null
    ||c.donor_rsrp_dbm>=A.donor_min_dbm);"""
new_feas = """ /* Three modes. __subset === 'all' means genuinely unconstrained -- the baseline the
    comparison is measured against. An array means that explicit feasible set. null means
    "whatever the sliders currently say", which is what the ordinary optimiser uses. */
 const _sub=(typeof __subset!=='undefined')?__subset:null;
 const _cx=(typeof cxFeasible==='function')?cxFeasible(b.prediction.candidates):null;
 const feas=b.prediction.candidates.map((c,i)=>{
   if(!(A.donor_min_dbm===null||c.donor_rsrp_dbm>=A.donor_min_dbm))return false;
   if(_sub==='all')return true;
   if(Array.isArray(_sub))return !!_sub[i];
   return _cx?_cx[i]:true;
 });"""
if old_feas in html:
    html = html.replace(old_feas, new_feas); n_edits += 1

# 2. a solve() that can be pointed at an explicit subset (for the with/without comparison)
html = html.replace("function solve(M,k,cb){",
                    "let __subset=null;\nfunction solveSubset(M,sub,cb){__subset=sub;"
                    "solve(M,3,p=>{__subset=null;cb(p);});}\nfunction solve(M,k,cb){", 1)
n_edits += 1

# 3. panel, styles, script
html = html.replace("  <h2>Optimised siting</h2>", PANEL + "\n  <h2>Optimised siting</h2>", 1); n_edits += 1
html = html.replace("</style>", CSS + "\n</style>", 1); n_edits += 1
html = html.replace("const D=", "const D=", 1)
html = re.sub(r"(const D\s*=\s*)\{.*?\};\s*\n",
              lambda mm: mm.group(1) + json.dumps(D, separators=(",", ":")) + ";\n",
              html, count=1, flags=re.S); n_edits += 1

# 4. a button, and boot the panel after the page's own init
html = html.replace('<button class="act" id="opt">Find the best site</button>',
                    '<button class="act" id="opt">Find the best site</button>\n'
                    '  <button class="act" id="cxbtn" style="margin-top:6px">'
                    'Best feasible site, and what it costs</button>', 1); n_edits += 1
html = html.replace("</script>", JS + """
try{ cxBuildUI(); cxRefresh();
     $("cxbtn").onclick = cxCompare;
     const _o=$("opt").onclick; $("opt").onclick=()=>{cxRefresh(); _o&&_o();};
}catch(e){ console.error("constraint panel failed:", e); }
</script>""", 1); n_edits += 1

DST.write_text(html, encoding="utf-8")
print(f"\n{n_edits} edits -> {DST.name}  ({DST.stat().st_size/1e6:.1f} MB)")
print(f"original untouched: {SRC.name}")
