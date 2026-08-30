"""The whole model progression on one page, as predicted service surfaces.

Extends scene/compare_surfaces.py, which compared two building sources, to cover every
model in this approach:

  a  OpenStreetMap buildings, ray tracer only          the shipped baseline
  b  Microsoft ML buildings, ray tracer only           commit 06426e8
  c  Microsoft ML buildings + ITU-R P.526 diffraction  current model

and the two deltas that separate them, plus the coverage curve that is the reason any of
it matters for Challenge 3.

Panel f is the decision-relevant one. A ray-traced surface can only report coverage over
the cells it managed to model, and those are systematically the *easy* ones -- so read
coverage off (a) or (b) and it is overstated. Panel c has no such gap.

usage: compare_models.py <osm.npz> <ms.npz> <hybrid.npz> <out.png>
"""
import json
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize, TwoSlopeNorm, LightSource
from matplotlib.gridspec import GridSpec
from PIL import Image

BASE = Path(__file__).resolve().parent
SCENE = BASE.parent / "scene"
VMIN, VMAX = -120.0, -50.0
BLOCK = 2000.0
Image.MAX_IMAGE_PIXELS = None


def load_rt(p):
    """Ray-tracer-only surface: best server, offset fitted on training blocks."""
    d = np.load(p, allow_pickle=True)
    order = [str(t) for t in d["tx_order"]]
    serv = np.array([order.index(str(c)) for c in d["meas_cell"]])
    pg_m = d["meas_pg"][np.arange(len(serv)), serv]
    pg_g = d["grid_pg"].max(axis=1)
    mx, my, rsrp = d["meas_x"], d["meas_y"], d["meas_rsrp"]
    bx, by = np.floor(mx / BLOCK).astype(int), np.floor(my / BLOCK).astype(int)
    test = ((bx + by) % 2 == 1)
    ok = pg_m > 0
    tr, te = ok & ~test, ok & test
    off = float(np.mean(rsrp[tr] - 10 * np.log10(pg_m[tr])))
    pred = 10 * np.log10(np.where(pg_g > 0, pg_g, np.nan)) + off
    img = np.full(len(d["gok"]), np.nan)
    img[d["gok"]] = pred
    pm = 10 * np.log10(np.where(pg_m > 0, pg_m, np.nan)) + off
    res = pm[te] - rsrp[te]
    return dict(img=img.reshape(len(d["gy"]), len(d["gx"])), flat=pred,
                gx=d["gx"], gy=d["gy"], d=d,
                rmse=float(np.sqrt(np.mean(res ** 2))), n=int(te.sum()),
                link=float(np.mean(np.isfinite(pred))))


def load_hybrid(p):
    d = np.load(p, allow_pickle=True)
    img = np.full(len(d["gok"]), np.nan)
    img[d["gok"]] = d["rsrp_mean"]
    return dict(img=img.reshape(len(d["gy"]), len(d["gx"])), flat=d["rsrp_mean"],
                gx=d["gx"], gy=d["gy"], d=d,
                rmse=float(d["heldout_rmse_db"]), n=None, link=1.0)


def main():
    osm, ms, hyb, out = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    A, B, C = load_rt(osm), load_rt(ms), load_hybrid(hyb)
    for nm, X in (("OSM", A), ("MS", B), ("hybrid", C)):
        print(f"  {nm:<7} RMSE {X['rmse']:.2f}  modelled {X['link']:.1%}  "
              f"grid {X['img'].shape}")
    assert A["img"].shape == B["img"].shape == C["img"].shape, "grids differ"

    g = json.loads((SCENE / "georef.json").read_text())
    tb = g["terrain_bbox"]
    dem = np.array(Image.open(SCENE / "dem_3dep.tif"), dtype=float)
    dem = np.where(dem < -1e5, np.nan, dem)
    hs = LightSource(azdeg=315, altdeg=45).hillshade(dem, vert_exag=3.0, dx=7.7, dy=10.3)
    dext = [tb["x0"], tb["x1"], tb["y0"], tb["y1"]]
    ext = [A["gx"][0], A["gx"][-1], A["gy"][0], A["gy"][-1]]
    site = (float(A["d"]["site_x"]), float(A["d"]["site_y"]))

    plt.rcParams.update({"font.size": 9, "axes.titlesize": 9.5, "figure.dpi": 200})
    fig = plt.figure(figsize=(14.5, 8.9))
    gs = GridSpec(2, 3, figure=fig, wspace=0.05, hspace=0.16,
                  left=0.015, right=0.995, bottom=0.085, top=0.9)
    norm = Normalize(VMIN, VMAX)

    def base(ax):
        ax.imshow(hs, extent=dext, origin="upper", cmap="gray", vmin=0, vmax=1.35,
                  alpha=0.55, zorder=0, interpolation="bilinear")
        ax.set_xlim(ext[0], ext[1]); ax.set_ylim(ext[2], ext[3]); ax.set_aspect("equal")
        ax.set_xticks([]); ax.set_yticks([])
        ax.plot(*site, marker="^", ms=10, mfc="#e8453c", mec="white", mew=1.2,
                ls="none", zorder=6)

    panels = [
        (0, "a  OpenStreetMap buildings, ray tracer only", A,
         f"RMSE {A['rmse']:.2f} dB   {A['link']:.0%} of cells modelled"),
        (1, "b  Microsoft ML buildings, ray tracer only", B,
         f"RMSE {B['rmse']:.2f} dB   {B['link']:.0%} of cells modelled"),
        (2, "c  + ITU-R P.526 profile diffraction", C,
         f"RMSE {C['rmse']:.2f} dB   100% of cells modelled"),
    ]
    for k, title, X, sub in panels:
        ax = fig.add_subplot(gs[0, k]); base(ax)
        im = ax.imshow(X["img"], extent=ext, origin="lower", cmap="viridis", norm=norm,
                       alpha=0.9, zorder=3, interpolation="nearest")
        ax.set_title(title, loc="left", weight="bold")
        ax.text(0.015, 0.03, sub, transform=ax.transAxes, fontsize=8, va="bottom",
                bbox=dict(fc="white", ec="#ddd", alpha=0.92, pad=3), zorder=7)

    # --- the two deltas -------------------------------------------------------
    for k, (title, diff, note) in enumerate([
            ("d  Effect of the building source  (b − a)", B["img"] - A["img"],
             "concentrated, not uniform"),
            ("e  Effect of profile diffraction  (c − b)", C["img"] - B["img"],
             "fills every unmodelled cell")]):
        ax = fig.add_subplot(gs[1, k]); base(ax)
        lim = max(np.nanpercentile(np.abs(diff), 99), 0.5)
        im2 = ax.imshow(diff, extent=ext, origin="lower", cmap="RdBu_r",
                        norm=TwoSlopeNorm(0, -lim, lim), alpha=0.92, zorder=3,
                        interpolation="nearest")
        fin = np.isfinite(diff)
        ax.set_title(title, loc="left", weight="bold")
        ax.text(0.015, 0.03,
                f"{100*np.sum(fin & (np.abs(diff) > 1))/max(fin.sum(),1):.0f}% of "
                f"shared cells shift >1 dB\nmedian |change| "
                f"{np.nanmedian(np.abs(diff)):.2f} dB, max {np.nanmax(np.abs(diff)):.0f} dB"
                f"\n{note}",
                transform=ax.transAxes, fontsize=7.5, va="bottom",
                bbox=dict(fc="white", ec="#ddd", alpha=0.92, pad=3), zorder=7)
        if k == 1:
            im2_keep = im2
        else:
            im2_first = im2

    # --- coverage curve: the reason the grey cells matter ---------------------
    ax = fig.add_subplot(gs[1, 2])
    thr = np.arange(-125, -59, 1.0)
    for X, lab, sty in ((A, "a  OSM, ray tracer only", "--"),
                        (B, "b  MS, ray tracer only", "-."),
                        (C, "c  MS + diffraction (complete)", "-")):
        v = X["flat"][np.isfinite(X["flat"])]
        frac = [(v > t).mean() for t in thr]
        ax.plot(thr, np.array(frac) * 100, sty, lw=2 if sty == "-" else 1.5,
                label=lab, color="#1f6f8b" if sty == "-" else None)
    # what the complete surface says about ALL cells, including a/b's blanks
    vC = C["flat"]
    ax.axvline(-100, color="#999", lw=0.8, ls=":")
    ax.set_xlabel("service threshold (dBm)"); ax.set_ylabel("% of cells above threshold")
    ax.set_title("f  Coverage is overstated by the incomplete surfaces",
                 loc="left", weight="bold")
    ax.grid(alpha=0.25); ax.legend(fontsize=7.5, loc="lower left")
    ax.set_xlim(-125, -60); ax.set_ylim(0, 100)
    a100 = (A["flat"][np.isfinite(A["flat"])] > -100).mean() * 100
    c100 = (vC > -100).mean() * 100
    ax.annotate(f"at −100 dBm:\n  (a) {a100:.0f}% of its modelled cells\n"
                f"  (c) {c100:.0f}% of all cells",
                xy=(-100, c100), xytext=(-121, 62), fontsize=7.5,
                bbox=dict(fc="white", ec="#ddd", alpha=0.95, pad=3),
                arrowprops=dict(arrowstyle="->", color="#666", lw=0.8))

    cax = fig.add_axes([0.10, 0.038, 0.26, 0.018])
    cb = fig.colorbar(im, cax=cax, orientation="horizontal")
    cb.set_label("Predicted RSRP (dBm)", fontsize=8); cb.ax.tick_params(labelsize=7.5)
    cax2 = fig.add_axes([0.42, 0.038, 0.20, 0.018])
    cb2 = fig.colorbar(im2_keep, cax=cax2, orientation="horizontal")
    cb2.set_label("change (dB)", fontsize=8); cb2.ax.tick_params(labelsize=7.5)

    fig.suptitle("Predicted service surface, Agronomy Farm — 3 sectors, 3.4608 GHz, "
                 "30 m mast.   Held-out RMSE 8.58 → 8.31 → 7.96 dB, "
                 "and 56% → 100% of cells predicted.",
                 x=0.015, ha="left", weight="bold", fontsize=11, y=0.975)
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    print("wrote", out)


if __name__ == "__main__":
    main()
