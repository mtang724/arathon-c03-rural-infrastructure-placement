"""Figure: sparse drive-test measurements -> ray-traced RSRP surface -> blocked validation.

The argument the figure has to make is that filling the map is legitimate, so the three
panels share one color scale and one set of axes, and panel (c) scores only points in
spatial blocks withheld from the calibration.

usage: make_figure.py <pred.npz> <out.png>
"""
import os
from pathlib import Path

# Paths resolve relative to this script so the tree can be moved or cloned anywhere.
BASE = str(Path(__file__).resolve().parent)
import sys, json, numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LightSource, Normalize
from matplotlib.gridspec import GridSpec
from PIL import Image

NPZ, OUT = sys.argv[1], sys.argv[2]
BLOCK = 2000.0
VMIN, VMAX = -120.0, -50.0          # dBm, shared by every panel

d = np.load(NPZ, allow_pickle=True)
tx_order = list(d["tx_order"])
meas_pg, grid_pg = d["meas_pg"], d["grid_pg"]
mx, my, rsrp = d["meas_x"], d["meas_y"], d["meas_rsrp"]

# serving-cell path gain at measured points; best-server on the grid
serv = np.array([tx_order.index(c) for c in d["meas_cell"]])
pg_m = meas_pg[np.arange(len(serv)), serv]
pg_g = grid_pg.max(axis=1)

# ---- blocked split: checkerboard of 2 km blocks, so test points are geographically
# ---- separated from the points that set the calibration constant
bx = np.floor(mx / BLOCK).astype(int); by = np.floor(my / BLOCK).astype(int)
test = ((bx + by) % 2 == 1)
ok = pg_m > 0
train_m, test_m = ok & ~test, ok & test
offset = float(np.mean(rsrp[train_m] - 10 * np.log10(pg_m[train_m])))   # EIRP + gains, fitted on TRAIN only

pred_m = 10 * np.log10(np.where(pg_m > 0, pg_m, np.nan)) + offset
pred_g = 10 * np.log10(np.where(pg_g > 0, pg_g, np.nan)) + offset
res = pred_m[test_m] - rsrp[test_m]
rmse, corr, bias = np.sqrt(np.mean(res**2)), np.corrcoef(pred_m[test_m], rsrp[test_m])[0, 1], res.mean()
print(f"offset {offset:.1f} dB | test n={test_m.sum()} RMSE {rmse:.2f} dB corr {corr:.3f} bias {bias:+.2f}")

# ---- hillshade for geographic context -------------------------------------
g = json.load(open(f"{BASE}/georef.json")); tb = g["terrain_bbox"]
Image.MAX_IMAGE_PIXELS = None
dem = np.array(Image.open(f"{BASE}/dem_3dep.tif"), dtype=float)
dem = np.where(dem < -1e5, np.nan, dem)
hs = LightSource(azdeg=315, altdeg=45).hillshade(dem, vert_exag=3.0, dx=7.7, dy=10.3)
dem_extent = [tb["x0"], tb["x1"], tb["y0"], tb["y1"]]

gx, gy, gok = d["gx"], d["gy"], d["gok"]
grid_img = np.full(len(gok), np.nan); grid_img[gok] = pred_g
grid_img = grid_img.reshape(len(gy), len(gx))
gext = [gx[0], gx[-1], gy[0], gy[-1]]
xlim, ylim = (gx[0], gx[-1]), (gy[0], gy[-1])

plt.rcParams.update({"font.size": 9, "axes.titlesize": 10, "figure.dpi": 200,
                     "axes.spines.top": False, "axes.spines.right": False})
fig = plt.figure(figsize=(13.5, 4.9))
gs = GridSpec(1, 3, figure=fig, width_ratios=[1, 1, 0.78], wspace=0.26,
              left=0.045, right=0.985, bottom=0.13, top=0.86)
norm = Normalize(VMIN, VMAX)

def basemap(ax):
    ax.imshow(hs, extent=dem_extent, origin="upper", cmap="gray",
              vmin=0, vmax=1.35, alpha=0.55, zorder=0, interpolation="bilinear")
    ax.set_xlim(*xlim); ax.set_ylim(*ylim); ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values(): s.set_visible(True); s.set_color("#bbb"); s.set_linewidth(0.6)
    ax.plot(d["site_x"], d["site_y"], marker="^", ms=11, mfc="#e8453c", mec="white",
            mew=1.2, ls="none", zorder=6)
    ax.annotate("Agronomy Farm", (d["site_x"], d["site_y"]), xytext=(9, 9),
                textcoords="offset points", fontsize=8, color="#111", zorder=7,
                bbox=dict(fc="white", ec="none", alpha=0.75, pad=1.4))

def scalebar(ax, km=5):
    x0, y0 = xlim[1] - km * 1000 - 900, ylim[0] + 900
    ax.plot([x0, x0 + km * 1000], [y0, y0], color="#111", lw=2.4, zorder=8,
            solid_capstyle="butt")
    ax.text(x0 + km * 500, y0 + 260, f"{km} km", ha="center", fontsize=7.5, zorder=8)

# (a) measured -------------------------------------------------------------
axA = fig.add_subplot(gs[0, 0]); basemap(axA)
axA.scatter(mx, my, c=rsrp, cmap="viridis", norm=norm, s=2.4, lw=0, zorder=4)
cell_frac = 100 * len(set(zip((mx // 200).astype(int), (my // 200).astype(int)))) / \
            (np.ceil((xlim[1]-xlim[0])/200) * np.ceil((ylim[1]-ylim[0])/200))
axA.set_title("a  Measured — what the drive test gives us", loc="left", weight="bold")
axA.text(0.015, 0.025, f"{len(mx):,} samples on roads\n{cell_frac:.0f}% of 200 m cells visited",
         transform=axA.transAxes, fontsize=7.8, va="bottom",
         bbox=dict(fc="white", ec="#ddd", alpha=0.9, pad=3))
scalebar(axA)

# (b) predicted ------------------------------------------------------------
axB = fig.add_subplot(gs[0, 1]); basemap(axB)
im = axB.imshow(grid_img, extent=gext, origin="lower", cmap="viridis", norm=norm,
                alpha=0.88, zorder=3, interpolation="nearest")
axB.set_title("b  Predicted — ray tracing fills the gaps", loc="left", weight="bold")
filled = 100 * np.isfinite(grid_img).sum() / grid_img.size
axB.text(0.015, 0.025, f"{int(d['grid_m'])} m cells, terrain-following\n"
                       f"{filled:.0f}% of cells have a modelled path",
         transform=axB.transAxes, fontsize=7.8, va="bottom",
         bbox=dict(fc="white", ec="#ddd", alpha=0.9, pad=3))
scalebar(axB)

cax = fig.add_axes([0.355, 0.075, 0.20, 0.022])
cb = fig.colorbar(im, cax=cax, orientation="horizontal")
cb.set_label("RSRP (dBm)", fontsize=8); cb.ax.tick_params(labelsize=7.5)

# (c) blocked validation ---------------------------------------------------
axC = fig.add_subplot(gs[0, 2])
axC.scatter(rsrp[test_m], pred_m[test_m], s=9, lw=0, alpha=0.22, color="#2b6a8f",
            rasterized=True, zorder=3)
lo, hi = VMIN, VMAX
axC.plot([lo, hi], [lo, hi], color="#e8453c", lw=1.4, zorder=5)
axC.plot([lo, hi], [lo + 10, hi + 10], color="#e8453c", lw=0.8, ls=":", zorder=5)
axC.plot([lo, hi], [lo - 10, hi - 10], color="#e8453c", lw=0.8, ls=":", zorder=5)
axC.set_xlim(lo, hi); axC.set_ylim(lo, hi); axC.set_aspect("equal")
axC.set_xlabel("Measured RSRP (dBm)"); axC.set_ylabel("Predicted RSRP (dBm)")
axC.set_title("c  Held-out blocks — is the fill trustworthy?", loc="left", weight="bold")
axC.grid(alpha=0.18, lw=0.5)
axC.text(0.03, 0.97, f"n = {test_m.sum():,}  (2 km blocks, unseen)\n"
                     f"RMSE  {rmse:.1f} dB\nr  {corr:.2f}\nbias  {bias:+.1f} dB",
         transform=axC.transAxes, va="top", fontsize=8.5,
         bbox=dict(fc="white", ec="#ddd", pad=4))
axC.text(0.97, 0.06, "dotted = ±10 dB", transform=axC.transAxes, ha="right",
         fontsize=7.5, color="#e8453c")

fig.suptitle(f"Filling the rural coverage map: {int(d['h_ant'])} m antenna, 3 sectors, "
             f"3.4608 GHz — calibration constant fitted on spatially disjoint blocks",
             x=0.045, ha="left", fontsize=10.5, weight="bold", y=0.975)
fig.savefig(OUT, bbox_inches="tight", facecolor="white")
print("wrote", OUT)
