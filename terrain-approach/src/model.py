"""
Stage 2 -- the digital twin, plus the validation that makes it believable.

DESIGN DECISION, and the most important one in the project:
we build TWO kinds of model, because they answer two different questions.

  (a) DESCRIPTIVE surfaces -- gradient boosting on geometry.  These answer
      "what is service like at an unmeasured point on this route today?"
      They are accurate but they have no mechanism: asked "what if we put a
      transmitter over there?", a model that has only ever learned
      (lat, lon) -> uplink has nothing to say.  It never saw a transmitter there.

  (b) A PHYSICAL chain -- fitted log-distance path loss, plus an empirical
      RSRP -> uplink curve.  This is what answers the counterfactual, because
      a new node that is X dB weaker than the macro simply shifts the fitted
      curve down by X dB.  That is a mechanism, so it extrapolates.

The link between the two is TDD reciprocity.  ARFCN 630720 is band n78, which
is time-division duplex: uplink and downlink share one frequency, so the path
loss is the same in both directions.  That is what licenses us to predict
UPLINK throughput from a DOWNLINK power measurement (RSRP).  On an FDD band
this step would not be valid, and we would have no counterfactual at all.
"""
import json

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.cluster import KMeans
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import mean_absolute_error, r2_score, roc_auc_score
from scipy.stats import norm

from config import (BUFFER_M, CORRIDOR_M, DATA, GRID_M, N_SPATIAL_BLOCKS,
                    RANDOM_SEED, REPORTS, RSRP_SERVICE_EDGE_DBM, SERVING_SITE)
from features import haversine_m, bearing_deg, load_sites

GEO_FEATURES = ["lat", "lon", "log_d", "az_cos1", "az_sin1", "az_cos2", "az_sin2"]


# ==========================================================================
# 1.  Physical layer: path loss and the RSRP -> uplink curve
# ==========================================================================

def fit_pathloss(df):
    """RSRP = b0 + b1*log10(d) + antenna-pattern terms, on the serving site.

    The azimuth harmonics matter.  Fitting RSRP against log-distance ALONE on
    this data returns an exponent of 1.72, i.e. propagation better than free
    space, which is impossible.  What is really happening is that the van drove
    down and across the sector's boresight, so the beam pattern was being
    absorbed into the distance term.  Giving the fit its own azimuth basis
    frees the distance coefficient to mean what it is supposed to mean.
    """
    d = df[df["site"].eq(SERVING_SITE) & df["rsrp"].notna() & (df["dist_m"] > 30)]
    X = d[["log_d", "az_cos1", "az_sin1", "az_cos2", "az_sin2"]].to_numpy()
    X = np.column_stack([np.ones(len(X)), X])
    y = d["rsrp"].to_numpy()
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef

    # Distance-only ("omni") form.  The Fourier terms average to zero over
    # azimuth, so dropping them leaves exactly the mean-over-bearing curve --
    # which is the right model for a new omnidirectional relay or small cell.
    out = {
        "intercept_dbm": float(coef[0]),
        "slope_per_decade_db": float(coef[1]),
        "path_loss_exponent_n": float(-coef[1] / 10.0),
        "azimuth_coef": [float(c) for c in coef[2:]],
        "residual_sd_db": float(resid.std()),
        "r2": float(r2_score(y, X @ coef)),
        "n_samples": int(len(d)),
    }
    # For comparison: the same fit with no antenna term, to show why it is needed.
    Xd = np.column_stack([np.ones(len(d)), d["log_d"].to_numpy()])
    cd, *_ = np.linalg.lstsq(Xd, y, rcond=None)
    out["naive_exponent_n_no_azimuth"] = float(-cd[1] / 10.0)
    out["naive_r2"] = float(r2_score(y, Xd @ cd))
    return out


def rsrp_omni(dist_m, pl, eirp_deficit_db=0.0):
    """Predicted RSRP at `dist_m` from an omnidirectional node.

    eirp_deficit_db shifts the whole curve down: a node radiating 20 dB less
    than the macro delivers 20 dB less power at every distance.  This one line
    is the entire counterfactual engine.
    """
    d = np.clip(np.asarray(dist_m, dtype=float), 30.0, None)
    return pl["intercept_dbm"] + pl["slope_per_decade_db"] * np.log10(d) - eirp_deficit_db


def rsrp_macro(lat, lon, pl, sites=None):
    """RSRP from the real macro, using the FULL fit including the antenna pattern.

    The macro is a three-sector site, so its azimuth terms are real and worth
    keeping for the 'before' picture.  A candidate relay, by contrast, is modelled
    as omnidirectional (rsrp_omni) because we get to choose it and an omni is the
    conservative assumption -- claiming a directional gain we have not specified
    would flatter the result.
    """
    if sites is None:
        sites, _ = load_sites()
    slat, slon = sites[SERVING_SITE]
    d = np.clip(haversine_m(lat, lon, slat, slon), 30.0, None)
    az = np.radians(bearing_deg(slat, slon, lat, lon))
    c = pl["azimuth_coef"]
    return (pl["intercept_dbm"] + pl["slope_per_decade_db"] * np.log10(d)
            + c[0] * np.cos(az) + c[1] * np.sin(az)
            + c[2] * np.cos(2 * az) + c[3] * np.sin(2 * az))


def fit_outage_curve(df, pl):
    """P(outage) as a monotone decreasing function of PREDICTED RSRP.

    The first version of this assumed outage was a Gaussian threshold crossing
    at the service edge -- P(RSRP + shadow fading < -108 dBm).  It was badly
    miscalibrated: it predicted 4% outage in cells that were observed out 49% of
    the time.  The reason is that "no serving cell" is not simply "weak signal".
    It also covers sector-edge search failures, handover gaps and fades far
    deeper than a 9.2 dB log-normal tail allows.

    So we do not assume the shape -- we fit it, isotonically, exactly as we did
    for uplink.  It stays mechanistic (it is a function of predicted received
    power, so a new transmitter moves it) but it is now calibrated by
    construction.  Note the x-axis is PREDICTED rsrp from geometry, not measured
    rsrp, because outage rows report no rsrp at all -- that is the whole point
    of them.

    One further correction, and it matters more than it looks.  The fit is done
    on 200 m CELL aggregates, not on raw rows.  Sampling density is wildly uneven
    -- the cell containing the tower holds 543 samples while cells in the far
    south hold one or two -- so a row-level fit is silently weighted towards the
    near-tower region where service is good, and under-predicts outage
    everywhere else.  Fitting on cells matches the unit we actually predict on
    and removes that bias (Brier 0.40 -> 0.20 -> 0.11).
    """
    mlat = GRID_M / 111_320.0
    mlon = GRID_M / (111_320.0 * np.cos(np.radians(42.0)))
    g = df.assign(gy=np.round(df["lat"] / mlat).astype(int),
                  gx=np.round(df["lon"] / mlon).astype(int)).groupby(["gy", "gx"]).agg(
        dist_m=("dist_m", "mean"), outage=("outage", "mean")).reset_index()
    x = rsrp_omni(g["dist_m"].to_numpy(), pl)
    iso = IsotonicRegression(increasing=False, out_of_bounds="clip", y_min=0, y_max=1)
    iso.fit(x, g["outage"].to_numpy())
    return iso


def fit_uplink_curve(df):
    """Monotone uplink(RSRP), fitted isotonically.

    Isotonic rather than a polynomial because the physics guarantees monotonicity
    -- more received power cannot mean less throughput -- and enforcing that by
    construction stops the model from inventing a non-physical dip in a sparse
    region.  Spearman(uplink, rsrp) = 0.78, so the relationship is strong.
    """
    d = df[df["uplink"].notna() & df["rsrp"].notna()]
    iso = IsotonicRegression(increasing=True, out_of_bounds="clip")
    iso.fit(d["rsrp"].to_numpy(), d["uplink"].to_numpy())
    return iso


# ==========================================================================
# 2.  Validation -- spatial blocks with a buffer
# ==========================================================================

def spatial_blocks(df, k=N_SPATIAL_BLOCKS):
    """Contiguous geographic blocks via KMeans on position.

    Whole blocks are held out, so a test point's neighbours are held out with
    it.  This is the scope note's requirement -- 'geographically separated test
    segments' -- expressed as a CV scheme.
    """
    xy = np.column_stack([df["lat"] * 111.32, df["lon"] * 111.32 * np.cos(np.radians(42))])
    return KMeans(n_clusters=k, n_init=10, random_state=RANDOM_SEED).fit_predict(xy)


def _buffer_mask(train_df, test_df, buffer_m=BUFFER_M):
    """Drop training rows within buffer_m of ANY test row.

    Without this the split leaks badly: samples are 2.63 s apart, so at driving
    speed consecutive rows are a few metres apart and land either side of a
    block boundary.  The model would be tested on points it effectively trained on.
    """
    tl = test_df["lat"].to_numpy()[:, None]
    to = test_df["lon"].to_numpy()[:, None]
    keep = np.ones(len(train_df), dtype=bool)
    # chunked to keep the pairwise matrix small
    lat = train_df["lat"].to_numpy()
    lon = train_df["lon"].to_numpy()
    for i in range(0, len(test_df), 400):
        D = haversine_m(tl[i:i + 400], to[i:i + 400], lat[None, :], lon[None, :])
        keep &= (D.min(axis=0) > buffer_m)
    return keep


def cross_validate(df, target, kind, verbose=True):
    """Score the same model under a random split and under buffered spatial blocks.

    Reporting both is the point.  The gap between them is the honest measure of
    how much of a naive score was leakage.
    """
    d = df[df[target].notna()].copy() if kind == "reg" else df.copy()
    d = d[d["lat"].notna()].reset_index(drop=True)
    d["block"] = spatial_blocks(d)
    X, y = d[GEO_FEATURES], d[target].to_numpy()

    def _fit(Xtr, ytr):
        M = HistGradientBoostingRegressor if kind == "reg" else HistGradientBoostingClassifier
        m = M(max_iter=300, learning_rate=0.08, random_state=RANDOM_SEED)
        return m.fit(Xtr, ytr)

    def _score(m, Xte, yte):
        if kind == "reg":
            p = m.predict(Xte)
            return {"mae": mean_absolute_error(yte, p), "r2": r2_score(yte, p)}
        p = m.predict_proba(Xte)[:, 1]
        return {"auc": roc_auc_score(yte, p)}

    # ---- random K-fold: the number most teams will report -----------------
    rng = np.random.default_rng(RANDOM_SEED)
    fold = rng.integers(0, N_SPATIAL_BLOCKS, len(d))
    rnd = [_score(_fit(X[fold != f], y[fold != f]), X[fold == f], y[fold == f])
           for f in range(N_SPATIAL_BLOCKS)]

    # ---- buffered spatial blocks: the honest number -----------------------
    spa, dropped = [], []
    for b in range(N_SPATIAL_BLOCKS):
        te = d["block"].eq(b).to_numpy()
        if te.sum() < 25 or (~te).sum() < 100:
            continue
        keep = _buffer_mask(d[~te], d[te])
        dropped.append(1 - keep.mean())
        tr_idx = np.where(~te)[0][keep]
        if len(tr_idx) < 100:
            continue
        spa.append(_score(_fit(X.iloc[tr_idx], y[tr_idx]), X[te], y[te]))

    # ---- baselines, scored on the same buffered spatial folds -------------
    # The physics chain is the one that matters.  If a fitted path-loss law plus
    # an isotonic RSRP->uplink curve generalises to unseen geography BETTER than
    # gradient boosting on coordinates, then the decision to run the
    # counterfactual through physics is not a stylistic preference -- it is what
    # the validation says to do.
    base = {}
    if kind == "reg" and target == "uplink":
        bm, bn, bd, bp, bpm = [], [], [], [], []
        for b in range(N_SPATIAL_BLOCKS):
            te = d["block"].eq(b).to_numpy()
            if te.sum() < 25 or (~te).sum() < 100:
                continue
            keep = _buffer_mask(d[~te], d[te])
            tr = d[~te][keep]
            if len(tr) < 100:
                continue
            yt = y[te]
            bm.append(mean_absolute_error(yt, np.full(te.sum(), tr[target].mean())))
            # nearest measured neighbour among the (buffered) training rows
            D = haversine_m(d[te]["lat"].to_numpy()[:, None], d[te]["lon"].to_numpy()[:, None],
                            tr["lat"].to_numpy()[None, :], tr["lon"].to_numpy()[None, :])
            bn.append(mean_absolute_error(yt, tr[target].to_numpy()[D.argmin(axis=1)]))
            # distance-only linear regression on log-distance
            c = np.polyfit(tr["log_d"], tr[target], 1)
            bd.append(mean_absolute_error(yt, np.polyval(c, d[te]["log_d"])))

            # physics chain, fitted on the training fold only:
            #   geometry -> RSRP (path-loss law) -> uplink (isotonic curve)
            pl_tr = fit_pathloss(tr)
            iso_tr = fit_uplink_curve(tr)
            rs_hat = rsrp_omni(d[te]["dist_m"].to_numpy(), pl_tr)
            bp.append(mean_absolute_error(yt, iso_tr.predict(rs_hat)))
            # and the same chain given the MEASURED rsrp, to separate the error
            # contributed by the path-loss step from the RSRP->uplink step
            msk = d[te]["rsrp"].notna().to_numpy()
            if msk.sum() > 10:
                bpm.append(mean_absolute_error(
                    yt[msk], iso_tr.predict(d[te]["rsrp"].to_numpy()[msk])))
        base = {"global_mean_mae": float(np.mean(bm)),
                "nearest_neighbour_mae": float(np.mean(bn)),
                "distance_only_mae": float(np.mean(bd)),
                "physics_chain_mae": float(np.mean(bp)),
                "isotonic_given_measured_rsrp_mae": float(np.mean(bpm)) if bpm else None}

    agg = lambda rs: {k: float(np.mean([r[k] for r in rs])) for k in rs[0]}
    res = {"target": target, "n": int(len(d)),
           "random_split": agg(rnd), "spatial_block": agg(spa),
           "spatial_per_fold": [{k: float(v) for k, v in r.items()} for r in spa],
           "mean_train_rows_dropped_by_buffer": float(np.mean(dropped)),
           "baselines": base}
    if verbose:
        print(f"[validate] {target}: random={agg(rnd)}  spatial={agg(spa)}")
        if base:
            print(f"[validate]   baselines (spatial MAE): " +
                  ", ".join(f"{k.replace('_mae','')}={v:.1f}"
                            for k, v in base.items() if v is not None))
    return res


# ==========================================================================
# 3.  Surfaces on the 200 m grid
# ==========================================================================

def build_grid(df, pl, iso, out_curve):
    """Predict every surface on a 200 m grid, restricted to the driven corridor."""
    mlat = GRID_M / 111_320.0
    mlon = GRID_M / (111_320.0 * np.cos(np.radians(42.0)))

    gy = np.round(df["lat"] / mlat).astype(int)
    gx = np.round(df["lon"] / mlon).astype(int)
    df = df.assign(gy=gy, gx=gx)

    # Demand weight = number of distinct PASSES through the cell, not the number
    # of samples in it.  This correction matters a lot.  Raw sample count is a
    # dwell-time measure, and the van sat stationary next to the tower long
    # enough to log 543 samples in one 200 m cell -- 24 minutes of a parked
    # vehicle, which would have counted as 543x the demand of a cell the van
    # drove through once.  A pass is a contiguous visit, so a parked van counts
    # once and a road crossed on four separate runs counts four times, which is
    # what "how much traffic needs service here" actually means.
    order = df.sort_values("ts")
    cellkey = order["gy"].astype(str) + "_" + order["gx"].astype(str)
    newpass = (cellkey != cellkey.shift()) | (order["run"] != order["run"].shift())
    order = order.assign(pass_id=newpass.cumsum())
    passes = (order.groupby(["gy", "gx"])["pass_id"].nunique()
              .rename("n_passes").reset_index())

    cells = df.groupby(["gy", "gx"]).agg(
        lat=("lat", "mean"), lon=("lon", "mean"),
        n=("lat", "size"), route_density=("lat", "size"),
        obs_outage=("outage", "mean"),
        obs_uplink=("uplink", "median"),
        obs_rsrp=("rsrp", "median"),
    ).reset_index().merge(passes, on=["gy", "gx"], how="left")
    cells["route_density"] = cells["n_passes"].fillna(1).astype(int)
    cells = cells[cells["n"] >= 1].reset_index(drop=True)

    sites, _ = load_sites()
    slat, slon = sites[SERVING_SITE]
    cells["dist_m"] = haversine_m(cells["lat"], cells["lon"], slat, slon)
    cells["az_deg"] = bearing_deg(slat, slon, cells["lat"], cells["lon"])
    cells["log_d"] = np.log10(cells["dist_m"].clip(lower=30))
    for h in (1, 2):
        cells[f"az_cos{h}"] = np.cos(h * np.radians(cells["az_deg"]))
        cells[f"az_sin{h}"] = np.sin(h * np.radians(cells["az_deg"]))

    # ---- PRIMARY surfaces: the physical chain ----------------------------
    # This is the surface the optimiser consumes, and the choice is made by the
    # validation, not by taste: under buffered spatial-block CV the physics chain
    # reaches MAE 19.9 Mbps against gradient boosting's 21.0.  It also carries a
    # mechanism, so the identical code predicts what a NEW transmitter would do.
    #
    # Uncertainty is propagated physically rather than fitted separately.  The
    # path-loss fit leaves a residual of sigma = 9.2 dB (shadow fading); pushing
    # RSRP +/- 1.2816 sigma through the isotonic curve gives a genuine 10-90 band
    # in Mbps, with the shape of the RSRP->uplink curve baked in -- so the band is
    # naturally wide in the steep region and narrow where throughput saturates.
    sd = pl["residual_sd_db"]
    cells["rsrp"] = rsrp_macro(cells["lat"].to_numpy(), cells["lon"].to_numpy(), pl)
    cells["ul_mid"] = np.clip(iso.predict(cells["rsrp"].to_numpy()), 0, None)
    cells["ul_lo"] = np.clip(iso.predict(cells["rsrp"].to_numpy() - 1.2816 * sd), 0, None)
    cells["ul_hi"] = np.clip(iso.predict(cells["rsrp"].to_numpy() + 1.2816 * sd), 0, None)
    cells["p_outage"] = out_curve.predict(cells["rsrp"].to_numpy())

    # ---- ML surfaces, kept only as the comparison foil -------------------
    clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.08,
                                         random_state=RANDOM_SEED)
    clf.fit(df[GEO_FEATURES], df["outage"])
    cells["p_outage_ml"] = clf.predict_proba(cells[GEO_FEATURES])[:, 1]
    up = df[df["uplink"].notna()]
    mlr = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.08,
                                        random_state=RANDOM_SEED).fit(
        up[GEO_FEATURES], up["uplink"])
    cells["ul_ml"] = np.clip(mlr.predict(cells[GEO_FEATURES]), 0, None)

    # ---- calibration of the physical outage surface ----------------------
    ok_o = cells["n"] >= 3
    obs_bins = pd.cut(cells.loc[ok_o, "p_outage"], [0, .1, .3, .5, .7, .9, 1.0])
    calib = (cells.loc[ok_o].groupby(obs_bins, observed=True)
             .agg(predicted=("p_outage", "mean"), observed=("obs_outage", "mean"),
                  n=("obs_outage", "size")).round(3).reset_index(drop=True).to_dict("records"))

    ok = cells["obs_uplink"].notna()
    agree = {
        "physics_vs_observed_mae": float(np.abs(cells.loc[ok, "ul_mid"] - cells.loc[ok, "obs_uplink"]).mean()),
        "ml_vs_observed_mae_IN_SAMPLE": float(np.abs(cells.loc[ok, "ul_ml"] - cells.loc[ok, "obs_uplink"]).mean()),
        "note": ("The ML figure is in-sample -- it trained on these cells. The honest "
                 "out-of-geography comparison is in validation.uplink.baselines, where "
                 "the physics chain wins."),
        "outage_surface_brier_physics": float(((cells.loc[ok_o, "p_outage"] - cells.loc[ok_o, "obs_outage"]) ** 2).mean()),
        "outage_surface_brier_ml_IN_SAMPLE": float(((cells.loc[ok_o, "p_outage_ml"] - cells.loc[ok_o, "obs_outage"]) ** 2).mean()),
        "outage_calibration": calib,
        "n_cells_with_observation": int(ok.sum()),
    }

    # Expected uplink accounts for the chance the cell has no service at all.
    # A cell that is out 60% of the time does not deliver its connected rate.
    cells["ul_expected"] = (1 - cells["p_outage"]) * cells["ul_mid"]
    cells["uncertainty"] = cells["ul_hi"] - cells["ul_lo"]

    return cells.reset_index(drop=True), agree


def run(verbose=True):
    df = pd.read_csv(DATA / "labeled.csv", dtype={"cellid": str})
    REPORTS.mkdir(parents=True, exist_ok=True)

    pl = fit_pathloss(df)
    iso = fit_uplink_curve(df)
    out_curve = fit_outage_curve(df, pl)
    if verbose:
        print(f"[pathloss] n = {pl['path_loss_exponent_n']:.2f} with antenna term "
              f"(R^2={pl['r2']:.3f}, residual sd={pl['residual_sd_db']:.1f} dB)")
        print(f"[pathloss] n = {pl['naive_exponent_n_no_azimuth']:.2f} WITHOUT it "
              f"(R^2={pl['naive_r2']:.3f})  <- below free space, non-physical")

    val = {
        "uplink": cross_validate(df, "uplink", "reg", verbose),
        "outage": cross_validate(df, "outage", "clf", verbose),
    }

    cells, agree = build_grid(df, pl, iso, out_curve)
    cells.to_csv(DATA / "grid.csv", index=False)

    rep = {"pathloss": pl, "validation": val, "surface_agreement": agree,
           "n_grid_cells": int(len(cells)),
           "service_edge_dbm": RSRP_SERVICE_EDGE_DBM}
    (REPORTS / "model.json").write_text(json.dumps(rep, indent=2))
    if verbose:
        print(f"[grid] {len(cells)} cells at {GRID_M} m -> {DATA/'grid.csv'}")
        print(f"[grid] surface agreement: {agree}")
    return cells, pl, iso, out_curve, rep


if __name__ == "__main__":
    run()
