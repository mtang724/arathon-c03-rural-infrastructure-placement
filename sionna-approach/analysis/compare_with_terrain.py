"""Head-to-head: ray-tracing hybrid vs the terrain-approach fitted model.

Earlier comparisons put our number next to the one published in
../../terrain-approach/README.md, which is not a fair test: different row sets, different
blocking schemes, different test-set variance. This runs BOTH models on the SAME rows,
the SAME 2 km checkerboard, and the same metric, by importing terrain-approach's shipped
`fit_with_terrain` / `macro_rsrp` rather than reimplementing them.

It also tests whether the two stack. Their errors come from different mechanisms -- a
fitted two-slope law with orthogonalised terrain terms, against ray tracing plus
per-path ITU-R P.526 diffraction -- so a weighted blend may beat either. The weight is
fitted on training blocks only.

usage: compare_with_terrain.py <hybrid_surface.npz> <sionna_pred.npz> <features.npz>
                               <terrain-approach dir> [out.png]
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
SCENE = BASE.parent / "scene"
BLOCK = 2000.0
FC = 3.4608e9
LAMBDA = 299792458.0 / FC


def score(pred, obs):
    e = np.asarray(pred) - np.asarray(obs)
    return dict(n=int(len(e)), mae=float(np.abs(e).mean()),
                rmse=float(np.sqrt((e ** 2).mean())), bias=float(e.mean()),
                r2=float(1 - (e ** 2).sum() / ((obs - obs.mean()) ** 2).sum()))


def main():
    surf_p, pred_p, feat_p, tdir = sys.argv[1:5]
    png = sys.argv[5] if len(sys.argv) > 5 else None
    tdir = Path(tdir)
    sys.path.insert(0, str(tdir / "src"))

    from coverage_terrain import fit_with_terrain, macro_rsrp        # noqa: E402
    from propagation import DEM, TX_AGL, link_features                # noqa: E402
    from features import load_sites                                   # noqa: E402

    g = json.loads((SCENE / "georef.json").read_text())
    lat0r, lon0, R, K = (math.radians(g["origin_lat"]), g["origin_lon"],
                         g["radius"], g["k"])

    def from_geo(lat, lon):
        lat = np.radians(lat); lon = np.radians(lon - lon0)
        B = np.sin(lon) * np.cos(lat)
        return (0.5 * K * R * np.log((1 + B) / (1 - B)),
                K * R * (np.arctan(np.tan(lat) / np.cos(lon)) - lat0r))

    # ---- our model, at the measured points ----------------------------------
    d = np.load(pred_p, allow_pickle=True)
    f = np.load(feat_p)
    tx = [str(t) for t in d["tx_order"]]
    serv = np.array([tx.index(str(c)) for c in d["meas_cell"]])
    pg = d["meas_pg"][np.arange(len(serv)), serv]
    rsrp, mx, my = d["meas_rsrp"], d["meas_x"], d["meas_y"]
    mlat, mlon = d["meas_lat"], d["meas_lon"]
    J, los, valid, d_h = f["J_deygout"], f["is_los"] > 0.5, f["valid"] > 0.5, f["d_h"]
    linked = (pg > 0) & valid
    pgdb = np.where(pg > 0, 10 * np.log10(np.where(pg > 0, pg, 1.0)), np.nan)
    fs = 20 * np.log10(LAMBDA / (4 * np.pi * np.maximum(d_h, 1.0)))
    bx, by = np.floor(mx / BLOCK).astype(int), np.floor(my / BLOCK).astype(int)
    test = ((bx + by) % 2 == 1)

    a = linked & ~test
    A = np.column_stack([los[a].astype(float), (~los[a]).astype(float), -J[a]])
    c2, *_ = np.linalg.lstsq(A, rsrp[a] - pgdb[a], rcond=None)
    b = valid & ~test & ~linked
    cf, *_ = np.linalg.lstsq(np.column_stack([np.ones(b.sum()), -J[b]]),
                             rsrp[b] - fs[b], rcond=None)
    ours = np.where(linked, np.where(np.isfinite(pgdb), pgdb, 0.0)
                    + np.where(los, c2[0], c2[1]) - c2[2] * J, fs + cf[0] - cf[1] * J)

    # ---- their model, fitted on the SAME training blocks ---------------------
    lab = pd.read_csv(tdir / "data" / "labeled.csv", dtype={"cellid": str})
    lx, ly = from_geo(lab.lat.values, lab.lon.values)
    lbx, lby = np.floor(lx / BLOCK).astype(int), np.floor(ly / BLOCK).astype(int)
    lab_test = ((lbx + lby) % 2 == 1)
    # labeled_terrain.csv is a gitignored artifact nothing in the repo writes, so
    # rebuild the two terrain columns fit_with_terrain needs from the shipped
    # link_features -- same function the pipeline itself uses.
    dem = DEM()
    sites, _ = load_sites()
    tl, to = sites["Agronomy Farm"]
    F = link_features(dem, tl, to, lab.lat.values, lab.lon.values, tx_agl=TX_AGL)
    lab["fresnel_frac"], lab["diff_db"] = F["fresnel_frac"], F["diff_db"]
    print(f"terrain-approach: fitting on {int((~lab_test).sum()):,} training-block rows "
          f"of {len(lab):,}  (TX_AGL {TX_AGL:.3f} m)")
    pl = fit_with_terrain(lab[~lab_test])
    print(f"  fitted n_near {pl['n_exponent']:.2f}, n_far {pl['n_far']:.2f}, "
          f"sigma {pl['sigma']:.2f} dB")
    theirs = macro_rsrp(pl, dem, mlat, mlon)

    te = valid & test
    print("\n" + "=" * 78)
    print("HEAD TO HEAD -- same rows, same 2 km checkerboard, same metric")
    print("=" * 78)
    print(f"  {'model':<34}{'MAE':>7}{'RMSE':>8}{'bias':>8}{'R2':>8}{'n':>7}")
    res = {}
    for nm, p in (("terrain-approach (fitted law)", theirs),
                  ("sionna hybrid (RT + P.526)", ours)):
        s = score(p[te], rsrp[te]); res[nm] = s
        print(f"  {nm:<34}{s['mae']:>7.2f}{s['rmse']:>8.2f}{s['bias']:>8.2f}"
              f"{s['r2']:>8.3f}{s['n']:>7}")

    # ---- do they stack? weight fitted on training blocks only ---------------
    tr = valid & ~test
    M = np.column_stack([np.ones(tr.sum()), ours[tr], theirs[tr]])
    w, *_ = np.linalg.lstsq(M, rsrp[tr], rcond=None)
    blend = w[0] + w[1] * ours + w[2] * theirs
    s = score(blend[te], rsrp[te]); res["stacked"] = s
    print(f"  {'stacked (weights on train)':<34}{s['mae']:>7.2f}{s['rmse']:>8.2f}"
          f"{s['bias']:>8.2f}{s['r2']:>8.3f}{s['n']:>7}")
    print(f"    weights: intercept {w[0]:+.2f}, ours {w[1]:+.3f}, theirs {w[2]:+.3f}")
    simple = 0.5 * (ours + theirs)
    s2 = score(simple[te], rsrp[te]); res["mean of the two"] = s2
    print(f"  {'simple average':<34}{s2['mae']:>7.2f}{s2['rmse']:>8.2f}"
          f"{s2['bias']:>8.2f}{s2['r2']:>8.3f}{s2['n']:>7}")
    rho = float(np.corrcoef((ours - rsrp)[te], (theirs - rsrp)[te])[0, 1])
    print(f"\n  correlation of the two models' residuals: {rho:+.3f}")
    print("  Independent errors would blend well; highly correlated ones cannot.")

    # ---- surfaces ------------------------------------------------------------
    S = np.load(surf_p, allow_pickle=True)
    glat, glon = S["grid_lat"], S["grid_lon"]
    print(f"\nevaluating terrain-approach on our {len(glat):,}-cell grid")
    tgrid = macro_rsrp(pl, dem, glat, glon)
    ogrid = S["rsrp_mean"]
    dif = ogrid - tgrid
    print(f"  their surface: median {np.median(tgrid):.1f} dBm, "
          f"5-95 pct {np.percentile(tgrid,5):.0f} to {np.percentile(tgrid,95):.0f}")
    print(f"  ours:          median {np.median(ogrid):.1f} dBm, "
          f"5-95 pct {np.percentile(ogrid,5):.0f} to {np.percentile(ogrid,95):.0f}")
    print(f"  difference:    median {np.median(dif):+.1f} dB, "
          f"|diff| > 5 dB on {np.mean(np.abs(dif) > 5):.0%} of cells")
    for thr in (-100, -110):
        print(f"  cells above {thr} dBm:  theirs {np.mean(tgrid > thr):.1%}   "
              f"ours {np.mean(ogrid > thr):.1%}")

    (BASE / "compare_with_terrain_summary.json").write_text(json.dumps(
        {"heldout": res, "residual_corr": rho,
         "stack_weights": {"intercept": w[0], "ours": w[1], "theirs": w[2]}}, indent=2))

    if png:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.colors import Normalize, TwoSlopeNorm
        gok = S["gok"]; ny, nx = len(S["gy"]), len(S["gx"])
        def img(v):
            o = np.full(len(gok), np.nan); o[gok] = v
            return o.reshape(ny, nx)
        ext = [S["gx"][0], S["gx"][-1], S["gy"][0], S["gy"][-1]]
        fig, ax = plt.subplots(1, 3, figsize=(15, 4.6), constrained_layout=True)
        n1 = Normalize(-120, -50)
        for k, (t, v, nrm, cm) in enumerate([
                (f"a  terrain-approach fitted law — {res['terrain-approach (fitted law)']['rmse']:.2f} dB",
                 img(tgrid), n1, "viridis"),
                (f"b  sionna hybrid — {res['sionna hybrid (RT + P.526)']['rmse']:.2f} dB",
                 img(ogrid), n1, "viridis"),
                ("c  difference (b − a)", img(dif),
                 TwoSlopeNorm(0, -20, 20), "RdBu_r")]):
            im = ax[k].imshow(v, origin="lower", extent=ext, norm=nrm, cmap=cm,
                              interpolation="nearest")
            ax[k].set_title(t, loc="left", weight="bold", fontsize=10)
            ax[k].set_xticks([]); ax[k].set_yticks([]); ax[k].set_aspect("equal")
            ax[k].plot(float(S["site_x"]), float(S["site_y"]), "^", ms=10,
                       mfc="#e8453c", mec="white", mew=1.2)
            fig.colorbar(im, ax=ax[k], shrink=0.85,
                         label="dBm" if k < 2 else "dB")
        fig.suptitle("Two models of the same network, same grid, same held-out protocol",
                     fontsize=11, weight="bold")
        fig.savefig(png, dpi=140, bbox_inches="tight", facecolor="white")
        print(f"wrote {png}")


if __name__ == "__main__":
    main()
