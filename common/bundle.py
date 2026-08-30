"""
Turn any simulator into a coverage bundle.

This is the one function a new approach has to call. Give it a simulator that
satisfies `common.simulator.Simulator` and a frame of measurements, and it
produces the file every tool in the repository reads.

    from common.bundle import build
    build(my_sim, df, out="bundles/my-model.json")

WHAT IT DOES, IN ORDER

  1. Builds the shared demand grid and candidate set -- identical for every
     simulator, so two models are scored against the same thing.
  2. Asks the simulator for the baseline: what the existing network delivers.
  3. Calibrates every service criterion against THAT simulator's own predicted
     RSRP. Never against another model's. See common/criteria.py.
  4. Precomputes RSRP from every candidate to every demand cell, at each mast
     height the asset classes use.
  5. Solves the greedy siting under the default objective, so the bundle opens
     with an answer already in it.

WHY STEP 4 EXISTS AT ALL. The planner lets the user change the criterion, the
threshold and the route/area weights, and re-solve. Re-solving means scoring 627
candidates against 4,731 cells. Analytically that is three million path profiles
per solve -- far too slow in a browser. Precomputed, it is a comparison over a
matrix already in memory, and the answer comes back instantly for any
combination the user dials in. It is also the ONLY way a model with no closed
form -- a ray tracer, a neural operator -- can drive an interactive planner at
all.

The matrix is stored once per mast height at zero EIRP deficit, because a
deficit is a constant offset: a relay 20 dB down is the macro matrix minus 20.
That is three asset classes out of two stored matrices.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from . import criteria as crit
from .demand import (ASSETS, GRID_M, W_AREA, W_ROUTE, Scorer, build_candidates,
                     build_grid, greedy, haversine_m)
from .schema import (CoverageBundle, DemandGrid, Objective, Prediction,
                     SimulatorInfo, pack_rsrp, rsrp_grid)

Q_SCALE, Q_OFFSET = 0.5, -150.0


def _solution(sim, base_r, by_agl, cand, cells, scorer, thr, draws, seed):
    """Greedy siting per asset class, plus how much the answer can be trusted."""
    rng = np.random.default_rng(seed)
    b_km, b_ar = scorer.parts(base_r >= thr)
    out = {}
    for key, A in ASSETS.items():
        feas = (cand.donor_rsrp.to_numpy() >= A["donor_min"]
                if A["donor_min"] is not None else np.ones(len(cand), bool))
        R = by_agl[A["agl"]][feas] - A["deficit"]
        cf = cand[feas].reset_index(drop=True)
        chosen, gains = greedy(base_r, R, thr, scorer, 3)
        if not chosen:
            out[key] = {"label": A["label"], "sites": [], "feasible": int(len(cf))}
            continue
        km1, ar1 = scorer.parts(np.maximum(base_r, R[chosen[0]]) >= thr)

        # Robustness: the site is only worth reporting if it survives the model's
        # own uncertainty. Shadow fading is drawn per cell and applied to the
        # baseline and the candidate alike, because both look through the same
        # ground -- an earlier version drew independently and reported 100%
        # confidence for a site that beat its runner-up by 0.5%.
        wins = np.zeros(len(cf), int)
        for _ in range(draws):
            sh = rng.normal(0, sim.sigma_db, len(cells)).astype(np.float32)
            bb = base_r + sh
            bs = scorer(bb >= thr)
            sc = np.array([scorer(np.maximum(bb, R[i] + sh) >= thr) - bs
                           for i in range(len(cf))])
            wins[int(np.argmax(sc))] += 1
        freq = wins / max(1, draws)
        dref = haversine_m(cf.loc[chosen[0], "lat"], cf.loc[chosen[0], "lon"],
                           cf.lat.to_numpy(), cf.lon.to_numpy())
        out[key] = {
            "label": A["label"], "feasible": int(len(cf)),
            "sites": [{"rank": i + 1, "lat": float(cf.loc[c, "lat"]),
                       "lon": float(cf.loc[c, "lon"]), "kind": cf.loc[c, "kind"],
                       "cumulative_gain": g} for i, (c, g) in
                      enumerate(zip(chosen, gains))],
            "marginal_gain": [gains[0]] + [gains[i] - gains[i - 1]
                                           for i in range(1, len(gains))],
            "one_asset": {"route_km": km1, "area_km2": ar1,
                          "route_pct": 100 * km1 / scorer.tot_rk,
                          "area_pct": 100 * ar1 / scorer.tot_ar,
                          "route_km_added": km1 - b_km,
                          "area_km2_added": ar1 - b_ar},
            "robustness": {"exact": float(freq[chosen[0]]),
                           "within_2km": float(freq[dref <= 2000].sum())}}
    return out


def build(sim, df, macro_lat, macro_lon, out=None, draws=200, seed=42,
          include_analytic=True, verbose=True) -> CoverageBundle:
    """One simulator in, one coverage bundle out.

    `include_analytic` asks the simulator for a closed form via an optional
    `bundle_prediction()` method. Models that have one get a planner that can
    evaluate a pin dropped anywhere; models that do not are tabulated only, and
    the planner snaps to the nearest candidate and says so.
    """
    t0 = time.time()
    if "outage" not in df:
        df = df.assign(outage=df.cellid.isna() | df.cellid.eq("FFFFFFFFF"))
    cells = build_grid(df)
    scorer = Scorer(cells)
    clat, clon = cells.lat.to_numpy(), cells.lon.to_numpy()
    cand = build_candidates(df, cells, macro_lat, macro_lon,
                            donor_rsrp_fn=sim.macro_rsrp)
    if verbose:
        print(f"[bundle] {sim.info.name}: {len(cells):,} cells | "
              f"{scorer.tot_rk:.1f} route-km | {len(cand)} candidates", flush=True)

    base_r = np.asarray(sim.macro_rsrp(clat, clon), float)
    cs = crit.build(df, sim, verbose=verbose)

    by_agl = {}
    for agl in sorted({a["agl"] for a in ASSETS.values()}):
        t1 = time.time()
        R = np.empty((len(cand), len(cells)), np.float32)
        for i, c in enumerate(cand.itertuples()):
            R[i] = sim.node_rsrp(c.lat, c.lon, agl, 0.0, clat, clon)
        by_agl[agl] = R
        if verbose:
            print(f"[bundle]   {agl:.0f} m mast: {len(cand)} surfaces in "
                  f"{time.time() - t1:.0f} s", flush=True)

    grid = rsrp_grid()
    default = "availability" if "availability" in cs else next(iter(cs))
    c0 = cs[default]
    ok = np.where(np.asarray(c0.value) >= c0.default_threshold)[0]
    thr = float(grid[ok[0]]) if len(ok) else float("inf")

    family, coeffs = (None, {})
    if include_analytic and hasattr(sim, "bundle_prediction"):
        family, coeffs = sim.bundle_prediction()

    agls = sorted(by_agl)
    b = CoverageBundle(
        simulator=SimulatorInfo(**{**sim.info.__dict__,
                                   "sigma_db": float(sim.sigma_db)}),
        grid=DemandGrid(
            grid_m=GRID_M,
            lat=[round(float(v), 5) for v in clat],
            lon=[round(float(v), 5) for v in clon],
            route_km=[round(float(v), 4) for v in cells.route_km],
            area_km2=float(cells.area_km2.iloc[0]),
            total_route_km=scorer.tot_rk, total_area_km2=scorer.tot_ar),
        objective=Objective(criteria=cs, default_criterion=default,
                            rsrp_grid=[round(float(v), 2) for v in grid],
                            w_route=W_ROUTE, w_area=W_AREA),
        baseline_rsrp_dbm=[round(float(v), 2) for v in base_r],
        prediction=Prediction(
            mode="analytic" if family else "tabulated",
            family=family, coefficients=coeffs,
            candidates=[{"lat": round(float(r.lat), 5),
                         "lon": round(float(r.lon), 5), "kind": r.kind,
                         "donor_rsrp_dbm": round(float(r.donor_rsrp), 2)}
                        for r in cand.itertuples()],
            agl_m=[float(a) for a in agls],
            rsrp_q=[pack_rsrp(by_agl[a], Q_SCALE, Q_OFFSET) for a in agls],
            q_scale=Q_SCALE, q_offset=Q_OFFSET),
        assets={k: {"label": v["label"], "deficit_db": v["deficit"],
                    "agl_m": v["agl"], "donor_min_dbm": v["donor_min"]}
                for k, v in ASSETS.items()},
        solution=_solution(sim, base_r, by_agl, cand, cells, scorer, thr,
                           draws, seed),
        macro={"lat": float(macro_lat), "lon": float(macro_lon)})

    if out:
        p = b.save(out)
        if verbose:
            print(f"[bundle] {p} ({p.stat().st_size / 1e6:.2f} MB) in "
                  f"{time.time() - t0:.0f} s", flush=True)
    return b


__all__ = ["build"]
