"""
RQ3 -- how much does the recommendation depend on what we assumed?

    python -m common.sensitivity

The planner has five knobs that a reasonable person could set differently: which
simulator, what counts as served, how demanding the target is, which asset class,
and how route-km trades against area. Each is defensible; none is measured. So
the question is not "what is the answer" but "how far does the answer move when
the assumptions move", and which assumption moves it most.

This solves the siting problem at every combination of those five and reports:

  * the spread each factor induces on its own -- the mean distance between the
    sites chosen at its different settings, holding everything else fixed;
  * the consensus site, and the share of combinations that pick it;
  * how much coverage the consensus gives up against each combination's own
    optimum, which is what you actually pay for standardising on one answer.

WHY THIS IS THE HONEST FORM OF THE ANSWER. A single recommended site with a
confidence interval implies the uncertainty is statistical. Most of it is not --
it is the choice of objective, and that choice is a judgement rather than a
measurement. Reporting which knob dominates tells a reader what they would have
to settle to make the recommendation firm, which is more useful than a number
that hides the question.

Every solve reuses the tabulated candidate x cell matrix already in the bundle,
so the whole sweep is matrix arithmetic rather than re-running any simulator.
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path

import numpy as np

from .demand import ASSETS, haversine_m
from .schema import CoverageBundle, unpack_rsrp

ROOT = Path(__file__).resolve().parent.parent
WEIGHTS = [0.3, 0.7, 1.0]           # route-km share; area takes the remainder
TARGET_STEPS = 3                    # low / default / high, per criterion


def _matrix(b: CoverageBundle, agl: float):
    n = len(b.grid.lat)
    nc = len(b.prediction.candidates)
    k = b.prediction.agl_m.index(agl) if agl in b.prediction.agl_m else \
        int(np.argmin([abs(a - agl) for a in b.prediction.agl_m]))
    return unpack_rsrp(b.prediction.rsrp_q[k], (nc, n),
                       b.prediction.q_scale, b.prediction.q_offset)


def _threshold(b, crit, target):
    c = b.objective.criteria[crit]
    v = np.asarray(c.value)
    g = np.asarray(b.objective.rsrp_grid)
    ok = np.where(v >= target)[0]
    return float(g[ok[0]]) if len(ok) else np.inf


def run(bundle_paths=None, out="reports/sensitivity.json", verbose=True):
    paths = bundle_paths or sorted((ROOT / "bundles").glob("*.json"))
    bundles = {}
    for p in paths:
        b = CoverageBundle.load(p)
        bundles[b.simulator.name] = b
    if not bundles:
        raise SystemExit("no bundles; build one with common.bundle.build first")

    ref = next(iter(bundles.values()))
    rk = np.asarray(ref.grid.route_km, float)
    ar = np.full(len(rk), ref.grid.area_km2)
    tot_rk, tot_ar = rk.sum(), ar.sum()

    rows = []
    for mname, b in bundles.items():
        base = np.asarray(b.baseline_rsrp_dbm, float)
        clat = np.array([c["lat"] for c in b.prediction.candidates])
        clon = np.array([c["lon"] for c in b.prediction.candidates])
        donor = np.array([c["donor_rsrp_dbm"] for c in b.prediction.candidates])
        mats = {a: _matrix(b, a) for a in sorted({v["agl"] for v in ASSETS.values()})}

        for aname, A in ASSETS.items():
            R = mats[A["agl"]] - A["deficit"]
            feas = (donor >= A["donor_min"]) if A["donor_min"] is not None \
                else np.ones(len(clat), bool)
            if not feas.any():
                continue
            for cname, crit in b.objective.criteria.items():
                lo, hi = crit.threshold_min, crit.threshold_max
                targets = sorted({crit.default_threshold,
                                  lo + (hi - lo) * 0.25, lo + (hi - lo) * 0.6})
                for target in targets:
                    thr = _threshold(b, cname, target)
                    if not np.isfinite(thr):
                        continue
                    base_cov = base >= thr
                    # (candidates x cells) coverage after placing each candidate
                    cov = np.maximum(R, base[None, :]) >= thr
                    km = cov @ rk
                    area = cov @ ar
                    km0, area0 = rk[base_cov].sum(), ar[base_cov].sum()
                    for w in WEIGHTS:
                        sc = w * km / tot_rk + (1 - w) * area / tot_ar
                        sc = np.where(feas, sc, -np.inf)
                        i = int(np.argmax(sc))
                        gain = sc[i] - (w * km0 / tot_rk + (1 - w) * area0 / tot_ar)
                        rows.append({"model": mname, "asset": aname,
                                     "criterion": cname, "target": float(target),
                                     "w_route": w, "lat": float(clat[i]),
                                     "lon": float(clon[i]), "gain": float(gain),
                                     "route_pct": float(100 * km[i] / tot_rk),
                                     "idx": i})
        if verbose:
            print(f"[sens] {mname}: {len(rows)} combinations so far", flush=True)

    lat = np.array([r["lat"] for r in rows])
    lon = np.array([r["lon"] for r in rows])

    # --- which knob moves the site most -----------------------------------
    # For each factor, group the runs that differ ONLY in that factor and take
    # the mean pairwise distance inside each group. Holding everything else
    # fixed is what makes the comparison between factors fair.
    FACTORS = ["model", "asset", "criterion", "target", "w_route"]
    spread = {}
    for f in FACTORS:
        others = [x for x in FACTORS if x != f]
        groups = {}
        for k, r in enumerate(rows):
            groups.setdefault(tuple(r[x] for x in others), []).append(k)
        ds = []
        for idxs in groups.values():
            if len(idxs) < 2:
                continue
            for a, c in itertools.combinations(idxs, 2):
                ds.append(haversine_m(lat[a], lon[a], lat[c], lon[c]))
        spread[f] = float(np.mean(ds)) / 1000.0 if ds else 0.0

    # --- the consensus ----------------------------------------------------
    key = [f"{a:.5f},{o:.5f}" for a, o in zip(lat, lon)]
    uniq, counts = np.unique(key, return_counts=True)
    win = uniq[int(np.argmax(counts))]
    share = float(counts.max()) / len(rows)
    wlat, wlon = (float(x) for x in win.split(","))
    within2 = float(np.mean(haversine_m(wlat, wlon, lat, lon) <= 2000))

    # Asset class is a DECISION, not an assumption, and it dominates every
    # other factor simply because a relay must sit near its donor while a macro
    # need not. So the spreads that answer "how much does our answer depend on
    # what we assumed" are computed within each asset class, not across them.
    by_asset = {}
    for aname in sorted({r["asset"] for r in rows}):
        sub = [r for r in rows if r["asset"] == aname]
        sl = np.array([r["lat"] for r in sub]); so = np.array([r["lon"] for r in sub])
        sp = {}
        for f in ["model", "criterion", "target", "w_route"]:
            others = [x for x in ["model", "criterion", "target", "w_route"] if x != f]
            gr = {}
            for k, r in enumerate(sub):
                gr.setdefault(tuple(r[x] for x in others), []).append(k)
            ds = [haversine_m(sl[a], so[a], sl[c], so[c])
                  for idxs in gr.values() if len(idxs) > 1
                  for a, c in itertools.combinations(idxs, 2)]
            sp[f] = float(np.mean(ds)) / 1000.0 if ds else 0.0
        kk = [f"{a:.5f},{o:.5f}" for a, o in zip(sl, so)]
        u, c = np.unique(kk, return_counts=True)
        w = u[int(np.argmax(c))]
        wa, wo_ = (float(x) for x in w.split(","))
        per_model = {}
        for m in sorted({r["model"] for r in sub}):
            ms = [r for r in sub if r["model"] == m]
            mk = [f"{r['lat']:.5f},{r['lon']:.5f}" for r in ms]
            mu, mc = np.unique(mk, return_counts=True)
            mw = mu[int(np.argmax(mc))]
            per_model[m] = {"lat": float(mw.split(",")[0]),
                            "lon": float(mw.split(",")[1]),
                            "share": float(mc.max()) / len(ms)}
        by_asset[aname] = {
            "n": len(sub), "site_spread_km": sp,
            "ranked": sorted(sp, key=sp.get, reverse=True),
            "consensus": {"lat": wa, "lon": wo_,
                          "share": float(c.max()) / len(sub),
                          "share_within_2km": float(np.mean(
                              haversine_m(wa, wo_, sl, so) <= 2000))},
            "consensus_per_model": per_model}

    out_d = {
        "n_combinations": len(rows),
        "by_asset": by_asset,
        "factors": {"levels": {f: len({r[f] for r in rows}) for f in FACTORS},
                    "site_spread_km": spread,
                    "ranked": sorted(spread, key=spread.get, reverse=True)},
        "consensus": {"lat": wlat, "lon": wlon, "share": share,
                      "share_within_2km": within2},
        "runs": rows,
    }
    Path(ROOT / out).parent.mkdir(parents=True, exist_ok=True)
    (ROOT / out).write_text(json.dumps(out_d, indent=2))
    if verbose:
        print(f"\n{len(rows)} combinations over "
              f"{out_d['factors']['levels']}")
        print("\nhow far the recommended site moves when one knob changes, km")
        for f in out_d["factors"]["ranked"]:
            print(f"   {f:<12} {spread[f]:6.2f}")
        print(f"\nconsensus {wlat:.5f}, {wlon:.5f} — chosen by "
              f"{100*share:.0f}% of combinations, "
              f"{100*within2:.0f}% land within 2 km of it")
        print(f"[sens] wrote {out}")
    return out_d


if __name__ == "__main__":
    run()
