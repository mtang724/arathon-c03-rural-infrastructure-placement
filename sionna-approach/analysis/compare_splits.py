"""Score the ray-tracing model under the terrain-approach's evaluation protocol.

`../../terrain-approach/` (Ishan's branch) fits a parametric two-slope path-loss law to
the measurements. It reports held-out RMSE 9.66 dB (KMeans blocks) and 9.78 dB (angular
wedges) against this approach's 8.08 dB on a 2 km checkerboard -- but those numbers are
NOT comparable, and the difference favours us for two reasons that have nothing to do
with the models:

  1. A checkerboard surrounds every test block with training blocks. The residual
     correlation length measured in `uncertainty.py` is ~300 m, so test points near a
     block boundary have correlated training data metres away. KMeans blocks are
     contiguous regions -- genuine extrapolation.
  2. terrain-approach drops training rows within 200 m of any test row. We do not.

This script re-scores the ray-tracing model under all four protocols so the comparison
is like-for-like, using the same metric set (MAE / RMSE / bias / R2).

Caveat that no amount of care removes: the two approaches evaluate on slightly different
row sets (they include outage rows and all sites; we use served Agronomy rows beyond
50 m). Treat this as indicative, not decisive.

usage: compare_splits.py <pred.npz> <features.npz>
"""
import json
import sys
from pathlib import Path

import numpy as np
from sklearn.cluster import KMeans

BASE = Path(__file__).resolve().parent
FC = 3.4608e9
LAMBDA = 299792458.0 / FC
BUFFER_M = 200.0
N_BLOCKS = 5
SEED = 0


def score(pred, obs):
    e = np.asarray(pred) - np.asarray(obs)
    return dict(n=int(len(e)), mae=float(np.abs(e).mean()),
                rmse=float(np.sqrt((e ** 2).mean())), bias=float(e.mean()),
                r2=float(1 - (e ** 2).sum() / ((obs - obs.mean()) ** 2).sum()))


def buffered_train(x, y, te, m=BUFFER_M):
    """Drop training rows within m of any test row (terrain-approach's rule)."""
    keep = np.ones((~te).sum(), bool)
    tx, ty = x[te][:, None], y[te][:, None]
    trx, tryy = x[~te], y[~te]
    for i in range(0, int(te.sum()), 400):
        D = np.hypot(tx[i:i + 400] - trx[None, :], ty[i:i + 400] - tryy[None, :])
        keep &= D.min(axis=0) > m
    out = np.zeros(len(x), bool)
    out[np.where(~te)[0][keep]] = True
    return out


def main():
    d = np.load(sys.argv[1], allow_pickle=True)
    f = np.load(sys.argv[2])
    tx_order = [str(t) for t in d["tx_order"]]
    serv = np.array([tx_order.index(str(c)) for c in d["meas_cell"]])
    pg = d["meas_pg"][np.arange(len(serv)), serv]
    rsrp, mx, my = d["meas_rsrp"], d["meas_x"], d["meas_y"]
    J, los, valid, d_h = f["J_deygout"], f["is_los"] > 0.5, f["valid"] > 0.5, f["d_h"]
    linked = (pg > 0) & valid
    pgdb = np.where(pg > 0, 10 * np.log10(np.where(pg > 0, pg, 1.0)), np.nan)
    fs = 20 * np.log10(LAMBDA / (4 * np.pi * np.maximum(d_h, 1.0)))
    sx, sy = float(d["site_x"]), float(d["site_y"])
    az = np.degrees(np.arctan2(mx - sx, my - sy)) % 360.0

    def fit_predict(tr):
        """Refit the 3+2 hybrid parameters on `tr`, predict everywhere."""
        a = linked & tr
        A = np.column_stack([los[a].astype(float), (~los[a]).astype(float), -J[a]])
        c2, *_ = np.linalg.lstsq(A, rsrp[a] - pgdb[a], rcond=None)
        b = valid & tr & ~linked
        if b.sum() > 10:
            cf, *_ = np.linalg.lstsq(np.column_stack([np.ones(b.sum()), -J[b]]),
                                     rsrp[b] - fs[b], rcond=None)
        else:
            cf = np.array([c2[1], c2[2]])
        hyb = np.where(linked, np.where(np.isfinite(pgdb), pgdb, 0.0)
                       + np.where(los, c2[0], c2[1]) - c2[2] * J, fs + cf[0] - cf[1] * J)
        off = float(np.mean(rsrp[a] - pgdb[a]))
        return pgdb + off, hyb

    xy = np.column_stack([mx, my])
    km = KMeans(N_BLOCKS, n_init=10, random_state=SEED).fit_predict(xy[valid])
    kmf = np.full(len(mx), -1); kmf[valid] = km
    wedge = np.floor((az % 360) / (360 / N_BLOCKS)).astype(int)
    bx, by = np.floor(mx / 2000).astype(int), np.floor(my / 2000).astype(int)

    protocols = {
        "checkerboard 2 km (ours, no buffer)": [((bx + by) % 2 == 1)],
        "checkerboard 2 km + 200 m buffer": [((bx + by) % 2 == 1)],
        "KMeans blocks + 200 m buffer": [(kmf == k) for k in range(N_BLOCKS)],
        "angular wedges + 200 m buffer": [(wedge == k) for k in range(N_BLOCKS)],
    }

    print("=" * 86)
    print("RAY-TRACING MODEL UNDER THE TERRAIN-APPROACH EVALUATION PROTOCOLS")
    print("=" * 86)
    print(f"  {'protocol':<38}{'model':<9}{'MAE':>7}{'RMSE':>8}{'bias':>8}"
          f"{'R2':>8}{'n':>7}")
    out = {}
    for name, folds in protocols.items():
        buf = "buffer" in name
        agg = {"P0": [], "P3+": []}
        for te in folds:
            te = te & valid
            if te.sum() < 30:
                continue
            tr = buffered_train(mx, my, te) if buf else (~te)
            tr = tr & valid
            if (linked & tr).sum() < 50:
                continue
            p0, hyb = fit_predict(tr)
            agg["P0"].append((p0[te & linked], rsrp[te & linked]))
            agg["P3+"].append((hyb[te], rsrp[te]))
        for tag in ("P0", "P3+"):
            if not agg[tag]:
                continue
            P = np.concatenate([a for a, _ in agg[tag]])
            O = np.concatenate([b for _, b in agg[tag]])
            s = score(P, O)
            out[f"{name}|{tag}"] = s
            label = name if tag == "P0" else ""
            print(f"  {label:<38}{tag:<9}{s['mae']:>7.2f}{s['rmse']:>8.2f}"
                  f"{s['bias']:>8.2f}{s['r2']:>8.3f}{s['n']:>7}")
        print()

    print("  terrain-approach, published, same two block schemes:")
    print(f"  {'KMeans blocks':<38}{'fitted':<9}{7.63:>7.2f}{9.66:>8.2f}"
          f"{'--':>8}{0.154:>8.3f}")
    print(f"  {'angular wedges':<38}{'fitted':<9}{8.05:>7.2f}{9.78:>8.2f}"
          f"{'--':>8}{0.054:>8.3f}")
    (BASE / "compare_splits_summary.json").write_text(json.dumps(out, indent=2))
    print(f"\nwrote {BASE/'compare_splits_summary.json'}")


if __name__ == "__main__":
    main()
