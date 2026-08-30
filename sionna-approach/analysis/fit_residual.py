"""Correct the twin with per-path diffraction physics, and check that it transfers.

`fit_pattern.py` showed that a fitted function of tower-relative geometry (elevation,
azimuth, distance) does NOT generalise across spatial blocks -- it anti-transfers, because
the residual is location-specific shadowing rather than a pattern error.

`terrain_features.py` shows the residual IS a clean function of one path-specific physical
quantity: predicted knife-edge diffraction loss along the actual terrain profile. The model
over-predicts monotonically with it (bias +2.5 / +4.5 / +7.7 dB across J bands), and the
prediction it is built from loses most of its skill in NLOS (r 0.76 -> 0.42).

So the correction here is physics with one or two fitted scalars, not a flexible fit:

  P0  offset                              current model
  P1  offset + a*J_deygout                one extra parameter
  P2  per-LOS-state offset + a*J          two extra
  P3  hybrid: ray tracer where it has a real path, free space - J where it does not
                                          -- this is ACCURACY.md B2, and it also
                                             converts the 18% unlinked into predictions

Everything is fitted on TRAIN blocks and scored on the HELD-OUT checkerboard. Because the
van parks (601 of 4,121 samples in 6 cells of 20 m), metrics are reported both raw and
de-clustered, weighting each 20 m cell equally.

usage: fit_residual.py <pred.npz> [features.npz]
"""
import json
import math
import sys
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parent
SCENE = BASE.parent / "scene"
BLOCK = 2000.0
FC = 3.4608e9
LAMBDA = 299792458.0 / FC
CELL = 20.0


def wscore(pred, meas, wt):
    r = pred - meas
    w = wt / wt.sum()
    rmse = float(np.sqrt(np.sum(w * r**2)))
    bias = float(np.sum(w * r))
    mu_p, mu_m = np.sum(w * pred), np.sum(w * meas)
    cov = np.sum(w * (pred - mu_p) * (meas - mu_m))
    corr = float(cov / np.sqrt(np.sum(w * (pred - mu_p)**2) * np.sum(w * (meas - mu_m)**2)))
    return dict(n=int(len(r)), rmse=rmse, bias=bias, corr=corr)


def main():
    npz = sys.argv[1]
    feat = sys.argv[2] if len(sys.argv) > 2 else str(BASE / "terrain_features.npz")
    d = np.load(npz, allow_pickle=True)
    f = np.load(feat)

    tx_order = [str(t) for t in d["tx_order"]]
    serv = np.array([tx_order.index(str(c)) for c in d["meas_cell"]])
    pg = d["meas_pg"][np.arange(len(serv)), serv]
    rsrp, mx, my = d["meas_rsrp"], d["meas_x"], d["meas_y"]
    J, los, valid = f["J_deygout"], f["is_los"] > 0.5, f["valid"] > 0.5
    d_h = f["d_h"]

    linked = (pg > 0) & valid
    pgdb = np.where(pg > 0, 10 * np.log10(np.where(pg > 0, pg, 1.0)), np.nan)
    fs_db = 20 * np.log10(LAMBDA / (4 * np.pi * np.maximum(d_h, 1.0)))   # free-space gain

    bx, by = np.floor(mx / BLOCK).astype(int), np.floor(my / BLOCK).astype(int)
    test = ((bx + by) % 2 == 1)

    # de-clustering weights: every 20 m cell carries the same total weight
    cx, cy = np.floor(mx / CELL).astype(int), np.floor(my / CELL).astype(int)
    key = cx.astype(np.int64) * 1000003 + cy
    uq, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    wt_dc = 1.0 / cnt[inv]

    print("=" * 78)
    print("PER-PATH DIFFRACTION CORRECTION -- does physics transfer where geometry did not?")
    print("=" * 78)
    print(f"{valid.sum():,} usable points  |  linked by the tracer {linked.sum():,} "
          f"({linked.sum()/valid.sum():.1%})  |  unlinked {int(valid.sum()-linked.sum()):,}")

    rows = []

    def run(tag, pred, mask, note=""):
        tr, te = mask & ~test, mask & test
        s = wscore(pred[te], rsrp[te], np.ones(te.sum()))
        sd = wscore(pred[te], rsrp[te], wt_dc[te])
        st = wscore(pred[tr], rsrp[tr], np.ones(tr.sum()))
        rows.append((tag, st["rmse"], s, sd, note))
        print(f"  {tag:<5}{st['rmse']:>8.2f}{s['rmse']:>8.2f}{s['bias']:>8.2f}"
              f"{s['corr']:>7.3f}{sd['rmse']:>10.2f}{s['n']:>7}   {note}")

    print(f"\n--- fitted on TRAIN blocks, scored on HELD-OUT blocks ---")
    print(f"  {'model':<5}{'train':>8}{'TEST':>8}{'bias':>8}{'r':>7}{'TEST_dc':>10}"
          f"{'n':>7}   notes")

    # ---- P0: current model, linked points only -------------------------------
    tr0 = linked & ~test
    off0 = float(np.mean(rsrp[tr0] - pgdb[tr0]))
    run("P0", pgdb + off0, linked, f"offset {off0:.1f} dB (current model)")

    # ---- P1: one extra parameter, the diffraction coefficient ----------------
    A = np.column_stack([np.ones(tr0.sum()), -J[tr0]])
    coef, *_ = np.linalg.lstsq(A, rsrp[tr0] - pgdb[tr0], rcond=None)
    p1 = pgdb + coef[0] - coef[1] * J
    run("P1", p1, linked, f"offset {coef[0]:.1f}, alpha {coef[1]:.3f} x J_deygout")

    # ---- P2: separate offsets for LOS and NLOS, plus alpha -------------------
    A2 = np.column_stack([los[tr0].astype(float), (~los[tr0]).astype(float), -J[tr0]])
    c2, *_ = np.linalg.lstsq(A2, rsrp[tr0] - pgdb[tr0], rcond=None)
    p2 = pgdb + np.where(los, c2[0], c2[1]) - c2[2] * J
    run("P2", p2, linked, f"LOS {c2[0]:.1f} / NLOS {c2[1]:.1f}, alpha {c2[2]:.3f}")

    # ---- P3: hybrid -- tracer where it has a path, free-space minus J where not
    # fitted on train only, and evaluated on BOTH the linked subset (comparable to
    # P0) and on every usable point (the coverage the twin actually gains)
    trf = valid & ~test & ~linked
    if trf.sum() > 20:
        Af = np.column_stack([np.ones(trf.sum()), -J[trf]])
        cf, *_ = np.linalg.lstsq(Af, rsrp[trf] - fs_db[trf], rcond=None)
    else:
        cf = np.array([off0, 1.0])
    p3 = np.where(linked, pgdb + np.where(los, c2[0], c2[1]) - c2[2] * J,
                  fs_db + cf[0] - cf[1] * J)
    run("P3", p3, linked, "hybrid, scored on the same linked subset as P0")
    run("P3+", p3, valid, f"hybrid on ALL usable points "
                          f"(fs offset {cf[0]:.1f}, alpha {cf[1]:.3f})")

    # ---- CONTROLS: is the ray tracer earning its keep? -----------------------
    # P4 drops the tracer entirely and uses profile physics alone. If it matches the
    # hybrid, the expensive GPU pass is contributing nothing beyond free space + J.
    trv = valid & ~test
    A4 = np.column_stack([np.ones(trv.sum()), -J[trv]])
    c4, *_ = np.linalg.lstsq(A4, rsrp[trv] - fs_db[trv], rcond=None)
    p4 = fs_db + c4[0] - c4[1] * J
    run("P4", p4, linked, "CONTROL: free space - a*J only, NO ray tracing")
    run("P4+", p4, valid, f"CONTROL on all usable points (offset {c4[0]:.1f}, "
                          f"alpha {c4[1]:.3f})")

    # P5 gives a linear model both sources and lets the fit decide the weighting
    m5 = linked & ~test
    A5 = np.column_stack([np.ones(m5.sum()), pgdb[m5], fs_db[m5], -J[m5]])
    c5, *_ = np.linalg.lstsq(A5, rsrp[m5], rcond=None)
    p5 = c5[0] + c5[1] * np.where(np.isfinite(pgdb), pgdb, 0.0) + c5[2] * fs_db - c5[3] * J
    run("P5", p5, linked, f"both: w_rt {c5[1]:.2f}, w_fs {c5[2]:.2f}, alpha {c5[3]:.3f}")

    print("\n  TEST_dc weights each 20 m cell equally, so parked stops cannot dominate.")
    print("  P3+ covers more points than P0, so its RMSE is not comparable to P0's --")
    print("  it is the price of predicting the 18% the tracer silently drops.")

    # ---- how much of the gain is real? bootstrap over blocks -----------------
    print("\n--- block bootstrap on the held-out set (200 resamples of whole blocks) ---")
    blk = (bx * 10007 + by)[linked & test]
    ub = np.unique(blk)
    rng = np.random.default_rng(0)
    diffs = []
    r0 = (pgdb + off0 - rsrp)[linked & test]
    r2 = (p2 - rsrp)[linked & test]
    for _ in range(200):
        pick = rng.choice(ub, size=len(ub), replace=True)
        idx = np.concatenate([np.where(blk == b)[0] for b in pick])
        diffs.append(np.sqrt(np.mean(r0[idx]**2)) - np.sqrt(np.mean(r2[idx]**2)))
    diffs = np.array(diffs)
    print(f"  P0 - P2 RMSE improvement: {diffs.mean():+.2f} dB  "
          f"[{np.percentile(diffs,2.5):+.2f}, {np.percentile(diffs,97.5):+.2f}] 95% CI")
    print(f"  improvement is positive in {np.mean(diffs>0):.1%} of block resamples")

    out = BASE / "fit_residual_summary.json"
    out.write_text(json.dumps({
        "P0_offset": off0, "P1": coef.tolist(), "P2": c2.tolist(), "P3_fs": cf.tolist(),
        "heldout": {t: {"train_rmse": a, "test": b, "test_declustered": c, "note": n}
                    for t, a, b, c, n in rows},
        "bootstrap_P0_minus_P2_dB": {"mean": float(diffs.mean()),
                                     "lo": float(np.percentile(diffs, 2.5)),
                                     "hi": float(np.percentile(diffs, 97.5))}}, indent=2))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
