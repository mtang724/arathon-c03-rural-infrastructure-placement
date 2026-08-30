"""Side-by-side of the two predicted service surfaces, plus their difference.

The difference panel is the point: it shows *where* replacing the building source changed
the prediction, which is more informative than the 0.29 dB headline because the change is
concentrated rather than uniform.

usage: compare_surfaces.py <old.npz> <new.npz> <out.png>
"""
import sys, json, math
import numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize, TwoSlopeNorm, LightSource
from matplotlib.gridspec import GridSpec
from pathlib import Path
from PIL import Image

BASE = Path(__file__).resolve().parent
OLD, NEW, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
VMIN, VMAX = -120.0, -50.0
BLOCK = 2000.0

def load(p):
    d = np.load(BASE / p, allow_pickle=True)
    order = [str(t) for t in d["tx_order"]]
    serv = np.array([order.index(str(c)) for c in d["meas_cell"]])
    pg_m = d["meas_pg"][np.arange(len(serv)), serv]
    pg_g = d["grid_pg"].max(axis=1)
    mx, my, rsrp = d["meas_x"], d["meas_y"], d["meas_rsrp"]
    bx = np.floor(mx / BLOCK).astype(int); by = np.floor(my / BLOCK).astype(int)
    test = ((bx + by) % 2 == 1); ok = pg_m > 0
    tr, te = ok & ~test, ok & test
    off = float(np.mean(rsrp[tr] - 10 * np.log10(pg_m[tr])))
    pred_g = 10 * np.log10(np.where(pg_g > 0, pg_g, np.nan)) + off
    img = np.full(len(d["gok"]), np.nan); img[d["gok"]] = pred_g
    img = img.reshape(len(d["gy"]), len(d["gx"]))
    pm = 10 * np.log10(np.where(pg_m > 0, pg_m, np.nan)) + off
    res = pm[te] - rsrp[te]
    return dict(img=img, gx=d["gx"], gy=d["gy"], d=d, off=off,
                rmse=float(np.sqrt(np.mean(res ** 2))),
                corr=float(np.corrcoef(pm[te], rsrp[te])[0, 1]),
                n=int(te.sum()), link=float(ok.mean()))

A, B = load(OLD), load(NEW)
print(f"old  RMSE {A['rmse']:.2f}  r {A['corr']:.3f}  link {A['link']:.2f}  n {A['n']}")
print(f"new  RMSE {B['rmse']:.2f}  r {B['corr']:.3f}  link {B['link']:.2f}  n {B['n']}")

g = json.load(open(BASE / "georef.json")); tb = g["terrain_bbox"]
Image.MAX_IMAGE_PIXELS = None
dem = np.array(Image.open(BASE / "dem_3dep.tif"), dtype=float)
dem = np.where(dem < -1e5, np.nan, dem)
hs = LightSource(azdeg=315, altdeg=45).hillshade(dem, vert_exag=3.0, dx=7.7, dy=10.3)
dext = [tb["x0"], tb["x1"], tb["y0"], tb["y1"]]
ext = [A["gx"][0], A["gx"][-1], A["gy"][0], A["gy"][-1]]
site = (float(A["d"]["site_x"]), float(A["d"]["site_y"]))

plt.rcParams.update({"font.size": 9, "axes.titlesize": 10, "figure.dpi": 200})
fig = plt.figure(figsize=(14.5, 5.4))
gs = GridSpec(1, 3, figure=fig, wspace=0.06, left=0.02, right=0.99, bottom=0.14, top=0.85)
norm = Normalize(VMIN, VMAX)

def base(ax):
    ax.imshow(hs, extent=dext, origin="upper", cmap="gray", vmin=0, vmax=1.35,
              alpha=0.55, zorder=0, interpolation="bilinear")
    ax.set_xlim(ext[0], ext[1]); ax.set_ylim(ext[2], ext[3]); ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    ax.plot(*site, marker="^", ms=11, mfc="#e8453c", mec="white", mew=1.2, ls="none", zorder=6)

ax0 = fig.add_subplot(gs[0]); base(ax0)
im = ax0.imshow(A["img"], extent=ext, origin="lower", cmap="viridis", norm=norm,
                alpha=0.9, zorder=3, interpolation="nearest")
ax0.set_title(f"a  OpenStreetMap buildings — RMSE {A['rmse']:.2f} dB", loc="left", weight="bold")

ax1 = fig.add_subplot(gs[1]); base(ax1)
ax1.imshow(B["img"], extent=ext, origin="lower", cmap="viridis", norm=norm,
           alpha=0.9, zorder=3, interpolation="nearest")
ax1.set_title(f"b  Microsoft ML buildings — RMSE {B['rmse']:.2f} dB", loc="left", weight="bold")

ax2 = fig.add_subplot(gs[2]); base(ax2)
diff = B["img"] - A["img"]
lim = np.nanpercentile(np.abs(diff), 99)
im2 = ax2.imshow(diff, extent=ext, origin="lower", cmap="RdBu_r",
                 norm=TwoSlopeNorm(0, -lim, lim), alpha=0.92, zorder=3, interpolation="nearest")
chg = np.isfinite(diff) & (np.abs(diff) > 1.0)
ax2.set_title("c  Difference — where the new buildings matter", loc="left", weight="bold")
ax2.text(0.015, 0.03, f"{100*chg.sum()/np.isfinite(diff).sum():.0f}% of cells shift by >1 dB\n"
                      f"median |change| {np.nanmedian(np.abs(diff)):.2f} dB, "
                      f"max {np.nanmax(np.abs(diff)):.0f} dB",
         transform=ax2.transAxes, fontsize=8, va="bottom",
         bbox=dict(fc="white", ec="#ddd", alpha=0.92, pad=3))

cax = fig.add_axes([0.13, 0.075, 0.30, 0.024])
cb = fig.colorbar(im, cax=cax, orientation="horizontal")
cb.set_label("Predicted RSRP (dBm)", fontsize=8); cb.ax.tick_params(labelsize=7.5)
cax2 = fig.add_axes([0.70, 0.075, 0.24, 0.024])
cb2 = fig.colorbar(im2, cax=cax2, orientation="horizontal")
cb2.set_label("change, new − old (dB)", fontsize=8); cb2.ax.tick_params(labelsize=7.5)

fig.suptitle("Effect of replacing the building source on the predicted service surface "
             "— Agronomy Farm, 3 sectors, 3.4608 GHz",
             x=0.02, ha="left", weight="bold", fontsize=11, y=0.965)
fig.savefig(BASE.parent / OUT, bbox_inches="tight", facecolor="white")
print("wrote", OUT)
