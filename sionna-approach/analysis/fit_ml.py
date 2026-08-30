"""Can a learned model beat the physics correction? Blocked-CV gradient boosting.

Two earlier experiments bracket this one. `fit_pattern.py` fitted flexible functions of
tower-relative geometry and they anti-transferred across spatial blocks. `fit_residual.py`
fitted 2-3 physical parameters on per-path terrain features and they transferred, taking
held-out RMSE from 9.09 to 8.08 dB with 28% more coverage.

Neither is a real ML model. This is: gradient boosting over every per-path feature at once,
with the hyperparameters chosen by GroupKFold over 2 km blocks *inside* the training set,
so model selection faces the same spatial-generalisation task as the final evaluation.

Three guards against repeating the earlier mistake:

  1. NO absolute position features (x, y, lat, lon). Those let the model memorise where the
     shadowing is, which inflates a checkerboard score and transfers to nothing -- the
     unmeasured 89% is the actual deliverable.
  2. Learn the RESIDUAL from the physics model, not raw RSRP, so the learner starts from
     P3 and can only add. If there is nothing left to learn it predicts ~0 and ties.
  3. De-clustering weights in the fit, so the 6 cells holding 601 samples cannot dominate.

usage: fit_ml.py <pred.npz> [features.npz]
"""
import json
import sys
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import RidgeCV
from sklearn.inspection import permutation_importance
from sklearn.model_selection import GroupKFold

BASE = Path(__file__).resolve().parent
SCENE = BASE.parent / "scene"
BLOCK = 2000.0
CELL = 20.0
FC = 3.4608e9
LAMBDA = 299792458.0 / FC


def wrmse(pred, meas, w):
    w = w / w.sum()
    return float(np.sqrt(np.sum(w * (pred - meas) ** 2)))


def main():
    npz = sys.argv[1]
    feat = sys.argv[2] if len(sys.argv) > 2 else str(BASE / "terrain_features.npz")
    d = np.load(npz, allow_pickle=True)
    f = np.load(feat)

    tx_order = [str(t) for t in d["tx_order"]]
    serv = np.array([tx_order.index(str(c)) for c in d["meas_cell"]])
    pg = d["meas_pg"][np.arange(len(serv)), serv]
    rsrp, mx, my = d["meas_rsrp"], d["meas_x"], d["meas_y"]
    J, los = f["J_deygout"], f["is_los"] > 0.5
    valid = f["valid"] > 0.5
    d_h = f["d_h"]

    linked = (pg > 0) & valid
    pgdb = np.where(pg > 0, 10 * np.log10(np.where(pg > 0, pg, 1.0)), np.nan)
    fs_db = 20 * np.log10(LAMBDA / (4 * np.pi * np.maximum(d_h, 1.0)))

    bx, by = np.floor(mx / BLOCK).astype(int), np.floor(my / BLOCK).astype(int)
    test = ((bx + by) % 2 == 1)
    block_id = bx * 10007 + by

    cx, cy = np.floor(mx / CELL).astype(int), np.floor(my / CELL).astype(int)
    _, inv, cnt = np.unique(cx.astype(np.int64) * 1000003 + cy,
                            return_inverse=True, return_counts=True)
    wt = 1.0 / cnt[inv]

    # ---- rebuild the P3 physics model exactly as fit_residual.py does ---------
    tr0 = linked & ~test
    A2 = np.column_stack([los[tr0].astype(float), (~los[tr0]).astype(float), -J[tr0]])
    c2, *_ = np.linalg.lstsq(A2, rsrp[tr0] - pgdb[tr0], rcond=None)
    trf = valid & ~test & ~linked
    Af = np.column_stack([np.ones(trf.sum()), -J[trf]])
    cf, *_ = np.linalg.lstsq(Af, rsrp[trf] - fs_db[trf], rcond=None)
    phys = np.where(linked, np.where(np.isfinite(pgdb), pgdb, 0.0)
                    + np.where(los, c2[0], c2[1]) - c2[2] * J,
                    fs_db + cf[0] - cf[1] * J)

    # ---- features: per-path only, no absolute position -----------------------
    dx, dy = mx - float(d["site_x"]), my - float(d["site_y"])
    AZ = {"00019C00B": 0.0, "00019C015": 115.0, "00019C01F": 240.0}
    bore = np.array([AZ[tx_order[s]] for s in serv])
    brg = np.degrees(np.arctan2(dx, dy)) % 360.0
    az_off = (brg - bore + 180.0) % 360.0 - 180.0

    names = ["pg_db", "fs_db", "J_deygout", "nu_max", "clear_ratio", "frac_blocked",
             "n_edges", "rough_m", "rx_exposure", "log_d", "is_los", "az_off",
             "linked", "sector"]
    X = np.column_stack([
        np.where(np.isfinite(pgdb), pgdb, -300.0), fs_db, J, f["nu_max"],
        np.clip(f["clear_ratio"], -20, 20), f["frac_blocked"], f["n_edges"],
        f["rough_m"], f["rx_exposure"], np.log10(np.maximum(d_h, 1.0)),
        los.astype(float), az_off, linked.astype(float), serv.astype(float)])

    m = valid
    tr, te = m & ~test, m & test
    y_res = rsrp - phys           # what the physics model leaves on the table

    print("=" * 78)
    print("ML ON PER-PATH FEATURES -- blocked CV, learning the physics residual")
    print("=" * 78)
    print(f"train {tr.sum():,}   test {te.sum():,}   features {X.shape[1]}   "
          f"target = RSRP - physics")
    print(f"physics model P3+ held-out RMSE: "
          f"{wrmse(phys[te], rsrp[te], np.ones(te.sum())):.2f} dB\n")

    # ---- blocked CV inside the training set ----------------------------------
    groups = block_id[tr]
    n_splits = min(5, len(np.unique(groups)))
    gkf = GroupKFold(n_splits=n_splits)
    grid = [dict(max_leaf_nodes=l, learning_rate=r, l2_regularization=z,
                 max_iter=400, min_samples_leaf=40, early_stopping=False)
            for l in (4, 8, 15) for r in (0.03, 0.1) for z in (0.0, 1.0)]
    print(f"  GroupKFold({n_splits}) over 2 km blocks, {len(grid)} configurations")
    best, best_cv = None, np.inf
    for gp in grid:
        errs = []
        for itr, iva in gkf.split(X[tr], y_res[tr], groups):
            mdl = HistGradientBoostingRegressor(random_state=0, **gp)
            mdl.fit(X[tr][itr], y_res[tr][itr], sample_weight=wt[tr][itr])
            errs.append(wrmse(phys[tr][iva] + mdl.predict(X[tr][iva]),
                              rsrp[tr][iva], wt[tr][iva]))
        cv = float(np.mean(errs))
        if cv < best_cv:
            best_cv, best = cv, gp
    # the null model: predict zero correction, i.e. keep the physics
    cv_null = float(np.mean([wrmse(phys[tr][iva], rsrp[tr][iva], wt[tr][iva])
                             for _, iva in gkf.split(X[tr], y_res[tr], groups)]))
    print(f"  best blocked-CV RMSE {best_cv:.2f} dB   vs physics-only {cv_null:.2f} dB")
    print(f"  best config: {best}")

    if best_cv >= cv_null:
        print("\n  Blocked CV says the learner does NOT beat the physics model.")
        print("  Shrinking to zero correction is the honest choice.")

    # ---- final fit on all training blocks, scored on held out ----------------
    print(f"\n  {'model':<26}{'train':>8}{'TEST':>8}{'TEST_dc':>10}{'r':>8}")
    rows = {}

    def rep(tag, p):
        a = wrmse(p[tr], rsrp[tr], np.ones(tr.sum()))
        b = wrmse(p[te], rsrp[te], np.ones(te.sum()))
        c = wrmse(p[te], rsrp[te], wt[te])
        r = float(np.corrcoef(p[te], rsrp[te])[0, 1])
        rows[tag] = dict(train=a, test=b, test_dc=c, corr=r)
        print(f"  {tag:<26}{a:>8.2f}{b:>8.2f}{c:>10.2f}{r:>8.3f}")

    rep("physics P3+", phys)

    gbm = HistGradientBoostingRegressor(random_state=0, **best)
    gbm.fit(X[tr], y_res[tr], sample_weight=wt[tr])
    rep("physics + GBM residual", phys + gbm.predict(X))

    rid = RidgeCV(alphas=np.logspace(-2, 4, 25))
    mu, sd = X[tr].mean(0), X[tr].std(0) + 1e-9
    rid.fit((X[tr] - mu) / sd, y_res[tr], sample_weight=wt[tr])
    rep("physics + ridge residual", phys + rid.predict((X - mu) / sd))

    gbm_raw = HistGradientBoostingRegressor(random_state=0, **best)
    gbm_raw.fit(X[tr], rsrp[tr], sample_weight=wt[tr])
    rep("GBM on raw RSRP", gbm_raw.predict(X))

    # ---- what is the learner actually using? ---------------------------------
    pi = permutation_importance(gbm, X[te], y_res[te], n_repeats=10,
                                random_state=0, scoring="neg_root_mean_squared_error")
    print("\n  permutation importance on held-out (dB of RMSE lost if shuffled):")
    for i in np.argsort(pi.importances_mean)[::-1][:8]:
        print(f"    {names[i]:<14}{pi.importances_mean[i]:>+7.3f} "
              f"+- {pi.importances_std[i]:.3f}")

    out = BASE / "fit_ml_summary.json"
    out.write_text(json.dumps({"cv_best": best_cv, "cv_physics_only": cv_null,
                               "best_config": best, "heldout": rows,
                               "importance": {names[i]: float(pi.importances_mean[i])
                                              for i in range(len(names))}}, indent=2))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
