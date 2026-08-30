"""Where would you build, and how much does that answer depend on what you assumed?

The brief asks for "sensitivity to placement constraints", and a single recommended
latitude and longitude does not answer it. A recommendation is a function of at least
five choices, and none of them is handed to us by the data:

    which MODEL predicts the radio
    which ASSET is being placed          relay / small cell / macro-class
    which CRITERION counts as service    availability / uplink / raw RSRP
    what THRESHOLD that criterion must clear
    how demand is WEIGHTED               route-km against area

This sweeps all of them and reports the recommendation for every combination, the
distance between models asked the identical question, and which choice moves the answer
furthest. A recommendation that survives the sweep is defensible; one that moves 5 km when
the threshold moves 5 dB needs saying so.

It is model-agnostic: it takes simulators through the `common.simulator` contract and never
imports an approach. The demand grid, the candidate set and the scorer are built ONCE and
shared, so any difference between models is the models, not their bookkeeping.

The cost is one node surface per (model, mast height) -- the same design decision as the
siting matrix. Everything else is arithmetic over those, so sweeping criteria, thresholds
and weightings is free.

usage:  python -m common.recommend --data terrain-approach/data/labeled.csv \
            --adapter "terrain-approach/src:adapter:ParametricSimulator" \
            --adapter "sionna-approach:adapter:SionnaHybridSimulator" \
            --out reports/recommendations.json
"""
from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import criteria as crit
from .demand import (ASSETS, Scorer, build_candidates, build_grid, greedy,
                     haversine_m)
from .schema import rsrp_grid

# the sweep. Thresholds are given per criterion because their units differ.
WEIGHTINGS = {"route 0.7 / area 0.3": (0.70, 0.30),
              "route only": (1.0, 0.0),
              "area only": (0.0, 1.0)}
TARGETS = {
    "availability": [0.50, 0.70, 0.90],
    "uplink_p50_mbps": [5.0, 10.0, 25.0],
    "uplink_p10_mbps": [2.0, 5.0],
    "rsrp": [-110.0, -100.0, -95.0],
}


def threshold_rsrp(c, target):
    """The predicted RSRP at which a criterion first reaches `target`.

    Criterion curves are monotone on the shared RSRP grid, so this is a scan. Returns
    +inf when the criterion never reaches the target, which correctly makes the
    combination unachievable rather than silently clamping it.
    """
    g, v = rsrp_grid(), np.asarray(c.value, float)
    ok = np.where(v >= target)[0]
    return float(g[ok[0]]) if len(ok) else float("inf")


def load_adapter(spec):
    """`dir:module:Class` -> instantiable class, without polluting sys.modules."""
    d, mod, cls = spec.split(":")
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root / d))
    path = root / d / f"{mod}.py"
    s = importlib.util.spec_from_file_location(f"_adapter_{mod}_{cls}", path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return getattr(m, cls)


def node_surfaces(sim, cand, cells, verbose=True):
    """RSRP from every candidate, per mast height. The only expensive step."""
    clat, clon = cells.lat.to_numpy(), cells.lon.to_numpy()
    out = {}
    for agl in sorted({a["agl"] for a in ASSETS.values()}):
        t0 = time.time()
        R = np.empty((len(cand), len(cells)), np.float32)
        for i, c in enumerate(cand.itertuples()):
            R[i] = sim.node_rsrp(c.lat, c.lon, agl, 0.0, clat, clon)
        out[agl] = R
        if verbose:
            print(f"    {agl:6.2f} m mast: {len(cand)} surfaces in "
                  f"{time.time()-t0:.0f} s", flush=True)
    return out


def sweep(sims, df, macro_lat, macro_lon, verbose=True):
    """Every (model, asset, criterion, threshold, weighting) -> a recommendation."""
    cells = build_grid(df)
    clat, clon = cells.lat.to_numpy(), cells.lon.to_numpy()
    # candidates from the FIRST simulator's donor test, then shared by all, so the
    # feasible set is identical and only the radio prediction differs
    cand = build_candidates(df, cells, macro_lat, macro_lon,
                            donor_rsrp_fn=sims[0].macro_rsrp)
    if verbose:
        print(f"[sweep] {len(cells):,} demand cells | {len(cand)} candidates | "
              f"{len(sims)} models")

    rows = []
    for sim in sims:
        if verbose:
            print(f"  {sim.info.name}")
        base = np.asarray(sim.macro_rsrp(clat, clon), float)
        cs = crit.build(df, sim, verbose=False)
        R_by_agl = node_surfaces(sim, cand, cells, verbose)
        for aname, a in ASSETS.items():
            R = R_by_agl[a["agl"]] - a["deficit"]
            for cname, targets in TARGETS.items():
                if cname not in cs:
                    continue
                for target in targets:
                    thr = threshold_rsrp(cs[cname], target)
                    if not np.isfinite(thr):
                        rows.append(dict(model=sim.info.name, asset=aname,
                                         criterion=cname, target=target,
                                         weighting=None, lat=None, lon=None,
                                         gain=None, base=None,
                                         note="criterion never reaches target"))
                        continue
                    for wname, (wr, wa) in WEIGHTINGS.items():
                        sc = Scorer(cells, w_route=wr, w_area=wa)
                        b = sc(base >= thr)
                        pick, gains = greedy(base, R, thr, sc, k=1)
                        rows.append(dict(
                            model=sim.info.name, asset=aname, criterion=cname,
                            target=target, weighting=wname, threshold_dbm=thr,
                            lat=(float(cand.lat.iloc[pick[0]]) if pick else None),
                            lon=(float(cand.lon.iloc[pick[0]]) if pick else None),
                            gain=(float(gains[0]) if gains else 0.0),
                            base=float(b),
                            note=(None if pick else
                                  "no candidate placement adds any coverage")))
    return pd.DataFrame(rows), cells, cand


def analyse(rec, verbose=True):
    """Cross-model distance, and which choice moves the recommendation furthest."""
    ok = rec[rec.lat.notna()].copy()
    key = ["asset", "criterion", "target", "weighting"]
    out = {}

    # -- 1. do the models agree, question by question? ----------------------
    pairs = []
    for _, grp in ok.groupby(key):
        if grp.model.nunique() < 2:
            continue
        g = grp.drop_duplicates("model")
        for (i, a), (j, b) in itertools.combinations(list(g.iterrows()), 2):
            pairs.append(dict(zip(key, [a[k] for k in key])) | dict(
                model_a=a.model, model_b=b.model,
                km=haversine_m(a.lat, a.lon, b.lat, b.lon) / 1000.0,
                gain_a=a.gain, gain_b=b.gain))
    P = pd.DataFrame(pairs)
    if len(P):
        out["cross_model"] = dict(
            n=len(P), median_km=float(P.km.median()), p90_km=float(P.km.quantile(0.9)),
            agree_within_500m=float((P.km < 0.5).mean()),
            agree_within_2km=float((P.km < 2.0).mean()))
        if verbose:
            print("\n" + "=" * 74)
            print("DO THE MODELS AGREE?  (identical question, different radio model)")
            print("=" * 74)
            print(f"  {len(P)} comparable questions")
            print(f"  identical site (<500 m):  {100*(P.km < 0.5).mean():.0f}%")
            print(f"  within 2 km:              {100*(P.km < 2.0).mean():.0f}%")
            print(f"  median separation:        {P.km.median():.2f} km"
                  f"   p90 {P.km.quantile(0.9):.2f} km")
            print("\n  worst disagreements:")
            for _, r in P.nlargest(5, "km").iterrows():
                print(f"    {r.asset:<10}{r.criterion:<18}{str(r.target):>6}  "
                      f"{r.weighting:<20}{r.km:6.2f} km")

    # -- 2. which CHOICE moves the answer most? -----------------------------
    sens = {}
    for var in ("asset", "criterion", "target", "weighting", "model"):
        others = [k for k in ["model"] + key if k != var]
        d = []
        for _, grp in ok.groupby(others):
            g = grp.drop_duplicates(var)
            if len(g) < 2:
                continue
            for (i, a), (j, b) in itertools.combinations(list(g.iterrows()), 2):
                d.append(haversine_m(a.lat, a.lon, b.lat, b.lon) / 1000.0)
        if d:
            sens[var] = dict(n=len(d), median_km=float(np.median(d)),
                             p90_km=float(np.quantile(d, 0.9)))
    out["sensitivity"] = sens
    if verbose and sens:
        print("\n" + "=" * 74)
        print("WHICH CHOICE MOVES THE RECOMMENDATION FURTHEST?")
        print("=" * 74)
        print(f"  {'varying':<14}{'comparisons':>12}{'median km':>12}{'p90 km':>10}")
        for k, v in sorted(sens.items(), key=lambda kv: -kv[1]["median_km"]):
            print(f"  {k:<14}{v['n']:>12}{v['median_km']:>12.2f}{v['p90_km']:>10.2f}")
        print("\n  A recommendation is only as stable as the choice above it.")

    # -- 3. the consensus site, if there is one -----------------------------
    if len(ok):
        pts = ok[["lat", "lon"]].to_numpy()
        D = np.array([[haversine_m(a[0], a[1], b[0], b[1]) / 1000.0 for b in pts]
                      for a in pts])
        within = (D < 2.0).sum(axis=1)
        best = int(np.argmax(within))
        r = ok.iloc[best]
        out["consensus"] = dict(lat=float(r.lat), lon=float(r.lon),
                                supported_by=int(within[best]), of=len(ok))
        if verbose:
            print("\n" + "=" * 74)
            print("MOST-SUPPORTED LOCATION")
            print("=" * 74)
            print(f"  {r.lat:.5f}, {r.lon:.5f}")
            print(f"  within 2 km of the pick for {within[best]} of {len(ok)} "
                  f"({100*within[best]/len(ok):.0f}%) parameter combinations")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--adapter", action="append", required=True,
                    help="dir:module:Class, repeatable")
    ap.add_argument("--site", default="Agronomy Farm")
    ap.add_argument("--macro", default=None, help="lat,lon of the existing site")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    df = pd.read_csv(a.data, dtype={"cellid": str})
    if "outage" not in df:
        df["outage"] = df.cellid.isna() | df.cellid.eq("FFFFFFFFF")
    rows = df[df.rsrp.notna()]
    if a.site and "site" in df:
        rows = rows[rows.site.eq(a.site)]
    if a.macro:
        mlat, mlon = (float(v) for v in a.macro.split(","))
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                               / "terrain-approach" / "src"))
        from features import load_sites
        mlat, mlon = load_sites()[0][a.site]

    sims = []
    for spec in a.adapter:
        cls = load_adapter(spec)
        sims.append(cls(rows))
        print(f"[load] {sims[-1].info.name}  sigma {sims[-1].sigma_db:.2f} dB")

    rec, cells, cand = sweep(sims, df, mlat, mlon)
    res = analyse(rec)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(
            {"summary": res, "recommendations": rec.to_dict("records")}, indent=2))
        rec.to_csv(str(a.out).replace(".json", ".csv"), index=False)
        print(f"\nwrote {a.out} and {str(a.out).replace('.json', '.csv')}")


if __name__ == "__main__":
    main()
