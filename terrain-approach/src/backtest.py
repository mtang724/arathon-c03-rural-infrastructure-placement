"""
Stage 13 -- does the simulator reproduce the measurements, with no new unit?

Everything downstream rests on one claim: that the model describes the network
as it is today. So before asking what an added site would do, run the simulator
with only the existing macro and compare it to what the van actually recorded.

This calls the shipped `fit_with_terrain` / `macro_rsrp` rather than
reimplementing them, so what is tested is what ships.

TWO BLOCKING SCHEMES, because on this dataset they measure different things.
The survey is a radial pattern around one tower, so geography and the model's
covariates (distance, bearing) are nearly the same variable. Any contiguous
region held out is also a slice of covariate space, and which slice depends on
how you cut it:

  * KMEANS ON POSITION carves compact regions. One of them is the near-tower
    cluster, so holding it out deletes every sample under ~2 km and the fit must
    extrapolate log-distance inward. That is the harshest test, and the least
    like deployment, where near-tower data always exists.

  * ANGULAR WEDGES cut the survey into bearing sectors. Each wedge spans the
    full distance range, so distance support survives and what is held out is a
    bearing sector -- which tests the antenna-pattern term instead.

Both are reported. Neither is cherry-picked, and the gap between them is a
finding about the survey geometry rather than about the model.
"""
import json

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans

from config import DATA, RANDOM_SEED, REPORTS, SERVING_SITE
from coverage import Scorer, build_grid
from coverage_terrain import (avail_threshold, fit_avail_terrain,
                              fit_with_terrain, macro_rsrp)
from features import haversine_m
from propagation import DEM

BUFFER_M = 200.0
N_BLOCKS = 5


def schemes(r):
    xy = np.column_stack([r.lat * 111.32, r.lon * 111.32 * np.cos(np.radians(42))])
    return {
        "kmeans_on_position": KMeans(N_BLOCKS, n_init=10,
                                     random_state=RANDOM_SEED).fit_predict(xy),
        "angular_wedges": np.floor((r.az_deg.to_numpy() % 360)
                                   / (360 / N_BLOCKS)).astype(int),
    }


def buffered_train(r, te, m=BUFFER_M):
    """Drop training rows within m of any test row, so no road segment is shared."""
    la, lo = r.lat.to_numpy(), r.lon.to_numpy()
    keep = np.ones((~te).sum(), bool)
    tl, to = la[te][:, None], lo[te][:, None]
    trl, tro = la[~te], lo[~te]
    for i in range(0, te.sum(), 400):
        D = haversine_m(tl[i:i + 400], to[i:i + 400], trl[None, :], tro[None, :])
        keep &= D.min(axis=0) > m
    return np.where(~te)[0][keep]


def score(pred, obs):
    e = np.asarray(pred) - np.asarray(obs)
    return {"mae": float(np.abs(e).mean()),
            "rmse": float(np.sqrt((e ** 2).mean())),
            "bias": float(e.mean()),
            "r2": float(1 - (e ** 2).sum() / ((obs - obs.mean()) ** 2).sum())}


def run(verbose=True):
    dem = DEM()
    df = pd.read_csv(DATA / "labeled_terrain.csv", dtype={"cellid": str})
    df["outage"] = df.cellid.isna() | df.cellid.eq("FFFFFFFFF")
    pl = fit_with_terrain(df)
    out = {"fit": pl}

    r = (df[df.site.eq(SERVING_SITE) & df.rsrp.notna() & (df.dist_m > 30)]
         .copy().reset_index(drop=True))
    y = r.rsrp.to_numpy()

    # ---------- A. in sample ---------------------------------------------
    out["A_in_sample"] = dict(
        score(macro_rsrp(pl, dem, r.lat.to_numpy(), r.lon.to_numpy()), y),
        n=int(len(r)))

    # ---------- B. held out, three ways -----------------------------------
    out["B_out_of_sample"] = {}
    rng = np.random.default_rng(RANDOM_SEED)
    order = ["random_split", "kmeans_on_position", "angular_wedges"]
    blocks_by = dict(random_split=rng.integers(0, N_BLOCKS, len(r)), **schemes(r))
    for nm in order:
        blocks = blocks_by[nm]
        folds, dropped = [], []
        for b in np.unique(blocks):
            te = blocks == b
            if te.sum() < 40 or (~te).sum() < 200:
                continue
            idx = (np.where(~te)[0] if nm == "random_split"
                   else buffered_train(r, te))
            if len(idx) < 200:
                continue
            dropped.append(1 - len(idx) / max(1, (~te).sum()))
            sub = fit_with_terrain(r.iloc[idx])
            p = macro_rsrp(sub, dem, r.lat.to_numpy()[te], r.lon.to_numpy()[te])
            folds.append(score(p, y[te]))
        out["B_out_of_sample"][nm] = dict(
            {k: float(np.mean([f[k] for f in folds])) for k in folds[0]},
            n_folds=len(folds),
            train_dropped_by_buffer=float(np.mean(dropped)))

    # ---------- C. coverage, the headline claim ---------------------------
    cells = build_grid(df)
    sc = Scorer(cells)
    clat, clon = cells.lat.to_numpy(), cells.lon.to_numpy()
    base = macro_rsrp(pl, dem, clat, clon)
    av = fit_avail_terrain(df, pl, dem)
    thr = avail_threshold(av, 0.50)
    pred_av = np.clip(av.predict(base), 0, 1)

    ma = 200 / 111_320.0
    mo = 200 / (111_320.0 * np.cos(np.radians(42.0)))
    g = df.assign(gy=np.round(df.lat / ma).astype(int),
                  gx=np.round(df.lon / mo).astype(int))
    obs = g.groupby(["gy", "gx"]).agg(
        n=("outage", "size"),
        avail=("outage", lambda s: 1 - s.mean())).reset_index()
    j = cells.assign(gy=np.round(cells.lat / ma).astype(int),
                     gx=np.round(cells.lon / mo).astype(int),
                     pred_av=pred_av, covered=base >= thr).merge(obs, on=["gy", "gx"])
    j = j[j.n >= 5]
    truth = (j.avail >= 0.50).to_numpy()
    agree = float((j.covered.to_numpy() == truth).mean())
    tot = float(j.route_km.sum())
    out["C_coverage"] = {
        "cells_compared": int(len(j)), "measured_route_km": tot,
        "observed_served_km": float(j.route_km[truth].sum()),
        "predicted_served_km": float(j.route_km[j.covered].sum()),
        "observed_pct": 100 * float(j.route_km[truth].sum()) / tot,
        "predicted_pct": 100 * float(j.route_km[j.covered].sum()) / tot,
        "cellwise_agreement": 100 * agree,
        "base_rate": 100 * float(truth.mean()),
        "brier": float(((j.pred_av - j.avail) ** 2).mean()),
        "rsrp_threshold_dbm": float(thr),
        "calibration": [
            {"predicted": float(j.pred_av[m].mean()),
             "observed": float(j.avail[m].mean()), "n": int(m.sum())}
            for m in [(j.pred_av >= a) & (j.pred_av < b)
                      for a, b in [(0, .25), (.25, .5), (.5, .75), (.75, 1.01)]]
            if m.sum() >= 10]}

    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "backtest.json").write_text(json.dumps(out, indent=2))

    if verbose:
        A, B, C = out["A_in_sample"], out["B_out_of_sample"], out["C_coverage"]
        print(f"MODEL  n_near {pl['n_exponent']:.2f}  n_far {pl['n_far']:.2f}  "
              f"break {pl['break_m']/1000:.1f} km  sigma {pl['sigma']:.2f} dB")
        print(f"\nA. RSRP in sample   n={A['n']:,}")
        print(f"   MAE {A['mae']:.2f}  RMSE {A['rmse']:.2f}  "
              f"R2 {A['r2']:+.3f}  bias {A['bias']:+.2f}")
        print("\nB. RSRP held out")
        print(f"   {'scheme':<22}{'folds':>6}{'MAE':>8}{'RMSE':>8}{'R2':>8}{'bias':>8}")
        for nm in order:
            v = B[nm]
            print(f"   {nm:<22}{v['n_folds']:>6}{v['mae']:>8.2f}{v['rmse']:>8.2f}"
                  f"{v['r2']:>8.3f}{v['bias']:>8.2f}")
        print(f"\nC. Coverage, no added unit, {C['cells_compared']} cells")
        print(f"   observed  {C['observed_pct']:.1f}% of route-km served")
        print(f"   simulated {C['predicted_pct']:.1f}%")
        print(f"   cellwise agreement {C['cellwise_agreement']:.1f}% "
              f"(base rate {C['base_rate']:.1f}%)   Brier {C['brier']:.3f}")
        for c in C["calibration"]:
            print(f"     predicted {c['predicted']:.2f}  "
                  f"observed {c['observed']:.2f}  (n={c['n']})")
        print("\n[backtest] wrote reports/backtest.json")
    return out


if __name__ == "__main__":
    run()
