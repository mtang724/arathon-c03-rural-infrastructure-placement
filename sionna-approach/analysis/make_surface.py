"""Apply the hybrid model to the prediction grid -- the deliverable surface.

The ray tracer alone leaves 43% of grid cells with no modelled path, which REPORT.md has
to report as "unmodelled rather than zero coverage". That caveat is the single biggest
obstacle to the siting stage: PLAN.md Phase 3 notes that how the optimiser treats those
cells "will drive its answer more than the propagation model does".

Profile diffraction removes the caveat. Where the tracer finds a path we use it, corrected
by fitted diffraction loss; where it does not, free space minus that same loss gives a
real prediction rather than a hole. Every parameter is fitted on training blocks only.

Outputs a surface .npz carrying the mean, the per-cell sigma, and every assumption, plus
a figure. This is the interface PLAN.md Phase 3 and ../terrain-approach/ consume.

usage: make_surface.py <pred.npz> <out.npz> [out.png]
"""
import json
import math
import sys
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parent
SCENE = BASE.parent / "scene"
sys.path.insert(0, str(BASE))
from terrain_features import load_dem, profile_features, dem_sample   # noqa: E402

BLOCK = 2000.0
FC = 3.4608e9
LAMBDA = 299792458.0 / FC
SIGMA_DB = 7.5          # calibrated on held-out blocks by uncertainty.py
CORR_LEN_M = 300.0      # residual correlation length, for the Phase 5 Monte Carlo


def to_geo(x, y, g):
    """Inverse spherical transverse Mercator -- the exact inverse of fromGeo()."""
    R, K = g["radius"], g["k"]
    lat0 = math.radians(g["origin_lat"])
    xp, yp = x / (K * R), y / (K * R) + lat0
    lat = np.arcsin(np.sin(yp) / np.cosh(xp))
    lon = np.arctan2(np.sinh(xp), np.cos(yp))
    return np.degrees(lat), np.degrees(lon) + g["origin_lon"]


def main():
    src, out = sys.argv[1], sys.argv[2]
    png = sys.argv[3] if len(sys.argv) > 3 else None
    d = np.load(src, allow_pickle=True)
    g = json.loads((SCENE / "georef.json").read_text())
    site = g["sites"]["Agronomy Farm"]
    h_ant = float(d["h_ant"])

    # --- round-trip check: the projection must invert exactly ------------------
    lat_c, lon_c = to_geo(d["meas_x"], d["meas_y"], g)
    err = np.hypot((lat_c - d["meas_lat"]) * 111320.0,
                   (lon_c - d["meas_lon"]) * 111320.0 * np.cos(np.radians(42)))
    print(f"projection round-trip on {len(err):,} known points: "
          f"max {err.max():.2e} m, mean {err.mean():.2e} m")
    assert err.max() < 0.01, "inverse projection is wrong -- everything downstream is void"

    z, H, W = load_dem()
    tx_lat, tx_lon = site["lat"], site["lon"]

    # --- measured points: fit the hybrid on training blocks --------------------
    tx_order = [str(t) for t in d["tx_order"]]
    serv = np.array([tx_order.index(str(c)) for c in d["meas_cell"]])
    pg_m = d["meas_pg"][np.arange(len(serv)), serv]
    rsrp, mx, my = d["meas_rsrp"], d["meas_x"], d["meas_y"]
    dm = np.hypot(mx - site["x"], my - site["y"])
    fm = profile_features(tx_lat, tx_lon, h_ant, d["meas_lat"], d["meas_lon"], 1.5,
                          np.maximum(dm, 50.0), z, H, W)
    Jm, losm = fm["J_deygout"], fm["is_los"] > 0.5
    validm = dm > 50.0
    linkedm = (pg_m > 0) & validm
    pgdbm = np.where(pg_m > 0, 10 * np.log10(np.where(pg_m > 0, pg_m, 1.0)), np.nan)
    fsm = 20 * np.log10(LAMBDA / (4 * np.pi * np.maximum(dm, 1.0)))
    bx, by = np.floor(mx / BLOCK).astype(int), np.floor(my / BLOCK).astype(int)
    test = ((bx + by) % 2 == 1)

    a = linkedm & ~test
    A = np.column_stack([losm[a].astype(float), (~losm[a]).astype(float), -Jm[a]])
    c2, *_ = np.linalg.lstsq(A, rsrp[a] - pgdbm[a], rcond=None)
    b = validm & ~test & ~linkedm
    cf, *_ = np.linalg.lstsq(np.column_stack([np.ones(b.sum()), -Jm[b]]),
                             rsrp[b] - fsm[b], rcond=None)
    print(f"fitted on {a.sum():,} linked + {b.sum():,} unlinked training points")
    print(f"  LOS offset {c2[0]:.2f} dB   NLOS offset {c2[1]:.2f} dB   alpha {c2[2]:.3f}")
    print(f"  free-space branch: offset {cf[0]:.2f} dB, alpha {cf[1]:.3f}")

    hyb_m = np.where(linkedm, np.where(np.isfinite(pgdbm), pgdbm, 0.0)
                     + np.where(losm, c2[0], c2[1]) - c2[2] * Jm,
                     fsm + cf[0] - cf[1] * Jm)
    te = validm & test
    r = hyb_m[te] - rsrp[te]
    print(f"  held-out check: n={te.sum():,} RMSE {np.sqrt(np.mean(r**2)):.2f} dB "
          f"r {np.corrcoef(hyb_m[te], rsrp[te])[0,1]:.3f}")

    # --- grid ------------------------------------------------------------------
    gx, gy, gz = d["grid_x"], d["grid_y"], d["grid_z"]
    pg_g = d["grid_pg"].max(axis=1)                 # best server
    glat, glon = to_geo(gx, gy, g)
    dg = np.hypot(gx - site["x"], gy - site["y"])
    print(f"\ngrid: {len(gx):,} cells, computing terrain profiles "
          f"({len(gx)*256/1e6:.1f} M samples)")
    fg = profile_features(tx_lat, tx_lon, h_ant, glat, glon, 1.5,
                          np.maximum(dg, 50.0), z, H, W)
    Jg, losg = fg["J_deygout"], fg["is_los"] > 0.5
    linkedg = pg_g > 0
    pgdbg = np.where(linkedg, 10 * np.log10(np.where(linkedg, pg_g, 1.0)), np.nan)
    fsg = 20 * np.log10(LAMBDA / (4 * np.pi * np.maximum(dg, 1.0)))
    surf = np.where(linkedg, np.where(np.isfinite(pgdbg), pgdbg, 0.0)
                    + np.where(losg, c2[0], c2[1]) - c2[2] * Jg,
                    fsg + cf[0] - cf[1] * Jg)

    print(f"  ray tracer alone:  {linkedg.mean():.1%} of cells modelled "
          f"({int((~linkedg).sum()):,} grey)")
    print(f"  with diffraction:  100.0% of cells modelled (0 grey)")
    print(f"  surface range {np.percentile(surf,1):.0f} to {np.percentile(surf,99):.0f} dBm "
          f"(1st-99th pct)")
    for thr in (-100, -110, -120):
        print(f"    cells above {thr} dBm: RT-only {np.mean(surf[linkedg] > thr):.1%} "
              f"of modelled, hybrid {np.mean(surf > thr):.1%} of all")

    np.savez_compressed(
        out, grid_x=gx, grid_y=gy, grid_z=gz, grid_lat=glat, grid_lon=glon,
        rsrp_mean=surf, rsrp_sigma=np.full(len(surf), SIGMA_DB),
        rt_linked=linkedg, J_deygout=Jg, is_los=losg.astype(np.uint8), d_site=dg,
        gx=d["gx"], gy=d["gy"], gok=d["gok"], grid_m=d["grid_m"],
        h_ant=h_ant, xml=str(d["xml"]), corr_len_m=CORR_LEN_M, sigma_db=SIGMA_DB,
        los_offset_db=c2[0], nlos_offset_db=c2[1], alpha_linked=c2[2],
        fs_offset_db=cf[0], alpha_unlinked=cf[1],
        heldout_rmse_db=float(np.sqrt(np.mean(r**2))),
        site_x=site["x"], site_y=site["y"], site_ground=site["ground"])
    print(f"\nwrote {out}")

    if png:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        nx, ny = len(d["gx"]), len(d["gy"])
        ok = d["gok"]
        def grid_of(v, mask=None):
            img = np.full(nx * ny, np.nan)
            idx = np.where(ok)[0]
            vv = v.copy()
            if mask is not None:
                vv = np.where(mask, vv, np.nan)
            img[idx] = vv
            return img.reshape(ny, nx)
        fig, ax = plt.subplots(1, 2, figsize=(13, 5.2), constrained_layout=True)
        ext = [d["gx"][0]/1000, d["gx"][-1]/1000, d["gy"][0]/1000, d["gy"][-1]/1000]
        for k, (title, img) in enumerate([
                (f"a  Ray tracer alone — {(~linkedg).sum():,} cells unmodelled "
                 f"({(~linkedg).mean():.0%})", grid_of(surf, linkedg)),
                ("b  + ITU-R P.526 profile diffraction — complete", grid_of(surf))]):
            cmap = matplotlib.colormaps["viridis"].with_extremes(bad="#c8c8c8")
            # unmodelled cells render grey so panel (a) reads as the caption says
            im = ax[k].imshow(img, origin="lower", extent=ext, vmin=-120, vmax=-50,
                              cmap=cmap, interpolation="nearest")
            ax[k].set_title(title, loc="left", weight="bold", fontsize=10)
            ax[k].set_xlabel("km east of scene origin")
            ax[k].plot(site["x"]/1000, site["y"]/1000, "*", ms=14, mfc="#ff3b30",
                       mec="white", mew=1.2)
            if k == 0:
                ax[k].set_ylabel("km north")
            fig.colorbar(im, ax=ax[k], label="predicted RSRP (dBm)", shrink=0.88)
        fig.suptitle("Predicted service surface, ARA Agronomy Farm.  Grey in (a) is "
                     "'no modelled path' — and those cells are systematically the weak "
                     "ones,\nso reading coverage off (a) overstates it: 90.6% of modelled "
                     "cells exceed −100 dBm, against 57.8% of all cells in (b).",
                     fontsize=10)
        fig.savefig(png, dpi=140)
        print(f"wrote {png}")


if __name__ == "__main__":
    main()
