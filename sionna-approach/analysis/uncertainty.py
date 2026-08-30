"""Uncertainty model: per-point sigma and the spatial correlation of the residual.

Needed twice over. PLAN.md Phase 5.3 resamples the RSRP surface ~500 times *with its
spatial correlation* and re-runs the siting optimisation, so a recommendation can be
reported as stable-or-not under the model's own error. Phase 6 needs the same field to
choose where to measure next. And ACCURACY.md Stage C says whatever refuses to close
becomes this model.

It is also the honest test of whether a heavier generative model (e.g. a diffusion prior
over coverage fields) is warranted. A conditional Gaussian random field has tens of
parameters and fits the data we actually have -- one partially observed field. If its
ensemble is well calibrated on held-out blocks, a model with millions of parameters has
nothing left to add. If it is badly calibrated, that is the evidence that justifies one.

Three parts:
  1. sigma(x) -- heteroscedastic scale from per-path features, fitted on train blocks
  2. calibration -- do held-out residuals actually fall inside the predicted intervals?
  3. variogram of the standardised residual -- the correlation length that decides
     whether errors cancel between candidate sites (assuming independence would make
     the robustness test dishonestly optimistic)

usage: uncertainty.py <pred.npz> <features.npz>
"""
import json
import sys
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

BASE = Path(__file__).resolve().parent
BLOCK = 2000.0
CELL = 20.0
FC = 3.4608e9
LAMBDA = 299792458.0 / FC


def fit_sigma(x, r2, n_bins=8):
    """sigma as a lookup over quantile bins of one feature (fitted on train)."""
    e = np.quantile(x, np.linspace(0, 1, n_bins + 1))
    e[0] -= 1e-9; e[-1] += 1e-9
    c, v = [], []
    for k in range(n_bins):
        m = (x > e[k]) & (x <= e[k + 1])
        if m.sum() < 25:
            continue
        c.append(np.median(x[m])); v.append(np.sqrt(np.mean(r2[m])))
    return np.array(c), np.array(v)


def main():
    npz, feat = sys.argv[1], sys.argv[2]
    d = np.load(npz, allow_pickle=True); f = np.load(feat)
    tx = [str(t) for t in d["tx_order"]]
    serv = np.array([tx.index(str(c)) for c in d["meas_cell"]])
    pg = d["meas_pg"][np.arange(len(serv)), serv]
    rsrp, mx, my = d["meas_rsrp"], d["meas_x"], d["meas_y"]
    J, los, valid, d_h = f["J_deygout"], f["is_los"] > 0.5, f["valid"] > 0.5, f["d_h"]
    linked = (pg > 0) & valid
    pgdb = np.where(pg > 0, 10 * np.log10(np.where(pg > 0, pg, 1.0)), np.nan)
    fs = 20 * np.log10(LAMBDA / (4 * np.pi * np.maximum(d_h, 1.0)))
    bx, by = np.floor(mx / BLOCK).astype(int), np.floor(my / BLOCK).astype(int)
    test = ((bx + by) % 2 == 1)

    # rebuild the P3+ mean model on training blocks only
    t0 = linked & ~test
    A = np.column_stack([los[t0].astype(float), (~los[t0]).astype(float), -J[t0]])
    c2, *_ = np.linalg.lstsq(A, rsrp[t0] - pgdb[t0], rcond=None)
    tf = valid & ~test & ~linked
    cf, *_ = np.linalg.lstsq(np.column_stack([np.ones(tf.sum()), -J[tf]]),
                             rsrp[tf] - fs[tf], rcond=None)
    mean = np.where(linked, np.where(np.isfinite(pgdb), pgdb, 0.0)
                    + np.where(los, c2[0], c2[1]) - c2[2] * J, fs + cf[0] - cf[1] * J)
    res = rsrp - mean
    tr, te = valid & ~test, valid & test

    print("=" * 76)
    print("UNCERTAINTY MODEL")
    print("=" * 76)
    print(f"train {tr.sum():,}  test {te.sum():,}   "
          f"residual sd: train {res[tr].std():.2f}  test {res[te].std():.2f} dB")

    # ---- 1. which features predict error MAGNITUDE? --------------------------
    cand = {"J_deygout": J, "rough_m": f["rough_m"], "n_edges": f["n_edges"],
            "clear_ratio": np.clip(f["clear_ratio"], -20, 20),
            "log_d": np.log10(np.maximum(d_h, 1)), "rx_exposure": f["rx_exposure"],
            "linked": linked.astype(float)}
    print("\n  correlation of |residual| with each feature (train blocks):")
    ranked = sorted(((abs(np.corrcoef(v[tr], np.abs(res[tr]))[0, 1]), k)
                     for k, v in cand.items()), reverse=True)
    for a, k in ranked:
        print(f"    {k:<14}{a:+.3f}")
    best = ranked[0][1]

    # ---- 2. sigma model and its calibration ---------------------------------
    print(f"\n  sigma model on '{best}', 8 quantile bins, fitted on train blocks")
    ctr, val = fit_sigma(cand[best][tr], res[tr] ** 2)
    sig = np.interp(cand[best], ctr, val)
    sig_const = np.full(len(res), res[tr].std())

    print(f"\n  {'model':<16}{'z sd':>7}{'|z|>1':>8}{'|z|>2':>8}{'NLL':>9}   "
          f"(target 31.7% / 4.6%)")
    out = {}
    for tag, s in (("constant sigma", sig_const), (f"sigma({best})", sig)):
        z = res[te] / s[te]
        nll = float(np.mean(0.5 * z**2 + np.log(s[te])))
        out[tag] = dict(z_sd=float(z.std()), p1=float(np.mean(np.abs(z) > 1)),
                        p2=float(np.mean(np.abs(z) > 2)), nll=nll)
        print(f"  {tag:<16}{z.std():>7.2f}{np.mean(np.abs(z)>1):>8.1%}"
              f"{np.mean(np.abs(z)>2):>8.1%}{nll:>9.3f}")
    print("  z sd near 1.0 and the tail fractions near target = calibrated.")
    print("  Lower NLL is better; it rewards sharpness only when honest.")
    print(f"\n  sigma range across the map: {val.min():.1f} to {val.max():.1f} dB")
    print(f"  {'bin centre':>12}{'sigma dB':>10}")
    for a, b in zip(ctr, val):
        print(f"  {a:>12.2f}{b:>10.2f}")

    # ---- 3. spatial correlation of the standardised residual ----------------
    z = res / sig
    m = valid & np.isfinite(z)
    xy = np.column_stack([mx[m], my[m]])
    zz = z[m]
    tree = cKDTree(xy)
    pairs = tree.query_pairs(3000.0, output_type="ndarray")
    dd = np.hypot(*(xy[pairs[:, 0]] - xy[pairs[:, 1]]).T)
    vv = 0.5 * (zz[pairs[:, 0]] - zz[pairs[:, 1]]) ** 2
    edges = np.array([0, 50, 100, 200, 400, 700, 1000, 1500, 2000, 3000.0])
    print(f"\n  variogram of the standardised residual:")
    print(f"  {'lag m':>10}{'n pairs':>10}{'gamma':>9}{'implied corr':>14}")
    gam = []
    for k in range(len(edges) - 1):
        sel = (dd > edges[k]) & (dd <= edges[k + 1])
        if sel.sum() < 50:
            continue
        g = float(np.mean(vv[sel]))
        gam.append((0.5 * (edges[k] + edges[k + 1]), int(sel.sum()), g))
        print(f"  {gam[-1][0]:>10.0f}{sel.sum():>10,}{g:>9.3f}{1-g:>14.3f}")
    # correlation length: lag at which gamma reaches 63% of the sill
    sill = np.mean([g for _, _, g in gam[-3:]]) if len(gam) >= 3 else 1.0
    lo = [L for L, _, g in gam if g >= 0.632 * sill]
    corr_len = lo[0] if lo else float("nan")
    print(f"\n  sill {sill:.2f}, correlation length ~{corr_len:.0f} m")
    print("  Errors within this range do NOT cancel; the Monte Carlo in PLAN.md Phase 5")
    print("  must sample correlated fields, not independent per-cell noise.")

    verdict = (abs(out[f"sigma({best})"]["z_sd"] - 1) < 0.15
               and abs(out[f"sigma({best})"]["p2"] - 0.046) < 0.03)
    print("\n" + "=" * 76)
    print("VERDICT: " + ("the Gaussian random field is well calibrated on held-out "
                         "blocks.\n  A heavier generative prior (diffusion) has nothing "
                         "left to add for this deliverable."
                         if verdict else
                         "calibration is OFF -- a richer error model is justified."))
    (BASE / "uncertainty_summary.json").write_text(json.dumps(
        {"feature": best, "sigma_bins": {"centre": ctr.tolist(), "sigma": val.tolist()},
         "calibration": out, "correlation_length_m": corr_len,
         "variogram": [{"lag": a, "n": b, "gamma": g} for a, b, g in gam]}, indent=2))
    print(f"\nwrote {BASE/'uncertainty_summary.json'}")


if __name__ == "__main__":
    main()
