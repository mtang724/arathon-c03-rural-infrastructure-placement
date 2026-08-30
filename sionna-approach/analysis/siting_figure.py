"""Before / after / where-it-helps, for the Challenge 3 deliverable.

Four panels answering the brief directly:

  a  coverage today, with the service threshold drawn
  b  coverage with the best-placed asset of the chosen class
  c  the RSRP change that asset buys, and where
  d  coverage gain as a function of WHERE the asset goes -- the siting objective
     itself, which is the map that answers "where would it help most"

usage: siting_figure.py <before.npz> <siting_prefix> <asset> <out.png> [threshold_dBm]
"""
import json
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize, TwoSlopeNorm

BASE = Path(__file__).resolve().parent
SCENE = BASE.parent / "scene"
FC = 3.4608e9
LAMBDA = 299792458.0 / FC
N_SC_DB = 10 * np.log10(273 * 12)
ASSETS = {"relay/repeater": (2.0, 13.0, 10.0), "small cell": (5.0, 13.0, 10.0),
          "macro-class": (128.0, 18.1, 36.576)}


def main():
    before_p, prefix, asset, out = sys.argv[1:5]
    thr = float(sys.argv[5]) if len(sys.argv) > 5 else -100.0
    S = np.load(before_p, allow_pickle=True)
    gx, gy = S["grid_x"], S["grid_y"]
    before = S["rsrp_mean"]
    alpha = float(S["alpha_unlinked"])
    gok, gxs, gys = S["gok"], S["gx"], S["gy"]

    d = np.load(f"{prefix}_G.npz", allow_pickle=True)
    G, order = d["G"], [str(t) for t in d["tx_names"]]
    cand = np.column_stack([d["cand_x"], d["cand_y"]])
    J = np.load(f"{prefix}_J.npy")

    watts, gdbi, mast = ASSETS[asset]
    off = 10 * np.log10(watts * 1e3) - N_SC_DB + gdbi
    idx = {nm: i for i, nm in enumerate(order)}
    cols = [idx[f"c{k}_h{mast:g}"] for k in range(len(cand))]
    pg = G[:, cols]
    linked = pg > 0
    D = np.hypot(gx[:, None] - cand[None, :, 0], gy[:, None] - cand[None, :, 1])
    fs = 20 * np.log10(LAMBDA / (4 * np.pi * np.maximum(D, 1.0)))
    with np.errstate(divide="ignore"):
        pgdb = np.where(linked, 10 * np.log10(np.where(linked, pg, 1.0)), 0.0)
    cand_rsrp = np.where(linked, pgdb + off, fs + off - alpha * J)

    after_all = np.maximum(before[:, None], cand_rsrp)
    cov_b = float(np.mean(before > thr))
    cov_a = np.mean(after_all > thr, axis=0)
    k = int(np.argmax(cov_a))
    after = after_all[:, k]
    delta = after - before
    print(f"{asset} at {mast:g} m, per-RE EIRP {off:.1f} dBm, threshold {thr:.0f} dBm")
    print(f"  best candidate #{k} at ({cand[k,0]:.0f}, {cand[k,1]:.0f}) m")
    print(f"  coverage {100*cov_b:.1f}% -> {100*cov_a[k]:.1f}%  "
          f"(+{100*(cov_a[k]-cov_b):.1f} points)")
    print(f"  cells improved by >3 dB: {np.mean(delta > 3):.1%}")

    def img(v):
        o = np.full(len(gok), np.nan); o[gok] = v
        return o.reshape(len(gys), len(gxs))
    ext = [gxs[0], gxs[-1], gys[0], gys[-1]]

    fig, ax = plt.subplots(2, 2, figsize=(12.6, 9.4), constrained_layout=True)
    ax = ax.ravel()
    n1 = Normalize(-120, -50)
    site = (float(S["site_x"]), float(S["site_y"]))

    for a in ax:
        a.set_xticks([]); a.set_yticks([]); a.set_aspect("equal")

    im0 = ax[0].imshow(img(before), origin="lower", extent=ext, norm=n1, cmap="viridis")
    ax[0].contour(img(before), levels=[thr], extent=ext, origin="lower",
                  colors="white", linewidths=1.1)
    ax[0].set_title(f"a  Coverage today — {100*cov_b:.0f}% of cells above "
                    f"{thr:.0f} dBm", loc="left", weight="bold", fontsize=10)
    fig.colorbar(im0, ax=ax[0], shrink=0.85, label="RSRP (dBm)")

    im1 = ax[1].imshow(img(after), origin="lower", extent=ext, norm=n1, cmap="viridis")
    ax[1].contour(img(after), levels=[thr], extent=ext, origin="lower",
                  colors="white", linewidths=1.1)
    ax[1].set_title(f"b  With one {asset} — {100*cov_a[k]:.0f}% "
                    f"(+{100*(cov_a[k]-cov_b):.1f} pts)", loc="left",
                    weight="bold", fontsize=10)
    fig.colorbar(im1, ax=ax[1], shrink=0.85, label="RSRP (dBm)")

    lim = max(float(np.nanpercentile(delta, 99.5)), 1.0)
    im2 = ax[2].imshow(img(delta), origin="lower", extent=ext,
                       norm=TwoSlopeNorm(0, -lim, lim), cmap="RdBu_r")
    ax[2].set_title(f"c  RSRP change — {np.mean(delta>3):.0%} of cells gain >3 dB",
                    loc="left", weight="bold", fontsize=10)
    fig.colorbar(im2, ax=ax[2], shrink=0.85, label="change (dB)")

    sc = ax[3].scatter(cand[:, 0], cand[:, 1], c=100 * (cov_a - cov_b), s=170,
                       cmap="magma", marker="s", edgecolors="none")
    ax[3].scatter(cand[k, 0], cand[k, 1], s=260, facecolors="none",
                  edgecolors="#00d0ff", linewidths=2.2, marker="s")
    ax[3].set_xlim(ext[0], ext[1]); ax[3].set_ylim(ext[2], ext[3])
    ax[3].set_title("d  Coverage gain by candidate location — the siting objective",
                    loc="left", weight="bold", fontsize=10)
    fig.colorbar(sc, ax=ax[3], shrink=0.85, label="coverage gain (points)")

    for a in (ax[0], ax[1], ax[2], ax[3]):
        a.plot(*site, marker="^", ms=11, mfc="#e8453c", mec="white", mew=1.2, zorder=8)
    for a in (ax[1], ax[2]):
        a.plot(cand[k, 0], cand[k, 1], marker="*", ms=17, mfc="#00d0ff",
               mec="white", mew=1.2, zorder=9)

    fig.suptitle(f"Where does one added {asset} help most?  "
                 f"ARA Agronomy Farm, 3.4608 GHz — {watts:g} W, {gdbi:g} dBi, "
                 f"{mast:g} m mast.   Red triangle = existing macro, star = "
                 f"recommended site.", fontsize=10.5, weight="bold")
    fig.savefig(out, dpi=140, bbox_inches="tight", facecolor="white")
    print("wrote", out)


if __name__ == "__main__":
    main()
