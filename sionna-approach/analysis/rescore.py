"""Rescore GPU runs on a COMMON LINKED SUBSET with a receiver sensitivity floor.

Two documented open problems both come from the same scoring defect, recorded in
RUNNING.md section 5 and ACCURACY.md sections 0 and A3: RMSE is computed over whichever
receivers a given configuration happened to link, so configurations that link MORE
receivers are graded on a harder set and look worse. Every comparison in RESULTS.md
between runs with different link rates is therefore confounded.

Two fixes, applied together:

  common linked subset  -- score every configuration on the receivers linked by ALL of
                           them, so the comparison is paired
  sensitivity floor     -- a predicted level below what a UE can report is "no service",
                           not a number to regress against. Without this, links 70 dB
                           below free space are scored as numeric predictions and a
                           handful of 50 dB residuals dominate the RMSE.

usage: rescore.py <dump1.npz> <dump2.npz> ...
"""
import sys
from pathlib import Path

import numpy as np

BLOCK = 2000.0
FLOOR_DBM = -140.0        # the minimum RSRP the UE ever reported in this dataset
CELL = 20.0


def main():
    paths = sys.argv[1:]
    runs = {}
    for p in paths:
        d = np.load(p, allow_pickle=True)
        tag = str(d["tag"])
        tx = [str(t) for t in d["tx_order"]]
        serv = np.array([tx.index(str(c)) for c in d["meas_cell"]])
        runs[tag] = dict(pg=d["meas_pg"][np.arange(len(serv)), serv],
                         rsrp=d["meas_rsrp"], x=d["meas_x"], y=d["meas_y"],
                         lat=d["meas_lat"], h=float(d["h_ant"]))

    # every run used the same seed and n_rx, so the receiver lists must be identical
    ref = runs[list(runs)[0]]
    for t, r in runs.items():
        assert len(r["x"]) == len(ref["x"]) and np.allclose(r["x"], ref["x"]), \
            f"{t} has a different receiver set -- cannot pair"
    n = len(ref["x"])
    rsrp, x, y = ref["rsrp"], ref["x"], ref["y"]
    bx, by = np.floor(x / BLOCK).astype(int), np.floor(y / BLOCK).astype(int)
    test = ((bx + by) % 2 == 1)
    cx, cy = np.floor(x / CELL).astype(int), np.floor(y / CELL).astype(int)
    _, inv, cnt = np.unique(cx.astype(np.int64) * 1000003 + cy,
                            return_inverse=True, return_counts=True)
    wt = 1.0 / cnt[inv]

    linked = {t: r["pg"] > 0 for t, r in runs.items()}
    common = np.logical_and.reduce(list(linked.values()))
    print("=" * 78)
    print("RESCORED ON A COMMON LINKED SUBSET, WITH A SENSITIVITY FLOOR")
    print("=" * 78)
    print(f"{n:,} receivers; per-run link rates: "
          + ", ".join(f"{t} {linked[t].mean():.2f}" for t in runs))
    print(f"common linked subset: {common.sum():,} "
          f"({common.mean():.1%})   floor {FLOOR_DBM:.0f} dBm\n")

    print(f"  {'run':<18}{'own-set':>9}{'COMMON':>9}{'common_dc':>11}{'bias':>8}"
          f"{'r':>7}{'n<floor':>9}")
    for t, r in runs.items():
        pgdb = np.where(r["pg"] > 0, 10 * np.log10(np.where(r["pg"] > 0, r["pg"], 1)), np.nan)

        # (a) the run's own linked set, as RESULTS.md scores it
        own_tr, own_te = linked[t] & ~test, linked[t] & test
        off_own = float(np.mean(rsrp[own_tr] - pgdb[own_tr]))
        own = float(np.sqrt(np.mean((pgdb[own_te] + off_own - rsrp[own_te]) ** 2)))

        # (b) the common subset, offset refitted on that subset's training blocks
        c_tr, c_te = common & ~test, common & test
        off = float(np.mean(rsrp[c_tr] - pgdb[c_tr]))
        pred = pgdb + off
        below = int(np.sum((pred[c_te] < FLOOR_DBM)))
        keep = c_te & (pred > FLOOR_DBM)
        res = pred[keep] - rsrp[keep]
        w = wt[keep] / wt[keep].sum()
        print(f"  {t:<18}{own:>9.2f}{np.sqrt(np.mean(res**2)):>9.2f}"
              f"{np.sqrt(np.sum(w*res**2)):>11.2f}{res.mean():>8.2f}"
              f"{np.corrcoef(pred[keep], rsrp[keep])[0,1]:>7.3f}{below:>9}")

    print("\n  'own-set' reproduces RESULTS.md. 'COMMON' is the paired comparison.")
    print("  A configuration that links more receivers is graded on a harder set in")
    print("  the first column and a fair one in the second.")

    # link rate is itself a result: coverage prediction needs it
    print(f"\n  {'run':<18}{'link rate':>11}{'extra vs ref':>14}")
    ref_t = list(runs)[0]
    for t in runs:
        print(f"  {t:<18}{linked[t].mean():>11.3f}"
              f"{int(linked[t].sum()-linked[ref_t].sum()):>14}")


if __name__ == "__main__":
    main()
