"""Per-path terrain features from the 3DEP DEM, and the LOS/NLOS diagnostic.

Motivation. The twin traces LOS + specular reflection only, with no diffraction. Where
terrain blocks the direct path the tracer either returns nothing (18% of measured points,
silently dropped from every metric) or returns whatever reflected path happens to exist --
off a distant hillside, at an essentially arbitrary level -- when the true field there is
terrain-diffracted. At 3.46 GHz over 10 km with 98 m of relief, rural NLOS is
diffraction-dominated, so those predictions may be close to uninformative.

That is testable: split the existing residual by LOS/NLOS computed from the terrain profile.
If the model is tight on LOS and wide on NLOS, the entire error budget lives in NLOS and
the fix is per-path diffraction physics, not a fitted correction of tower geometry.

Everything here is numpy over a raster -- no ray tracing, no GPU.

Features per measurement (all path-specific, hence expected to transfer across blocks):
  nu_max          Fresnel-Kirchhoff parameter at the principal edge
  J_deygout       multi-knife-edge diffraction loss, ITU-R P.526 + Deygout recursion
  clear_ratio     minimum clearance as a fraction of the first Fresnel radius
  frac_blocked    fraction of the profile above the line of sight
  n_edges         number of samples breaking the 0.6 F1 criterion
  rough_m         standard deviation of terrain elevation along the path
  rx_exposure     receiver elevation minus mean elevation within 500 m
  is_los          clearance exceeds 0.6 F1 everywhere (the standard LOS criterion)

usage: terrain_features.py <pred.npz> [out.npz]
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

BASE = Path(__file__).resolve().parent
SCENE = BASE.parent / "scene"

W, S, E, N = -93.8950, 41.9200, -93.6250, 42.0500     # dem_3dep.tif bounds
FC = 3.4608e9
LAMBDA = 299792458.0 / FC
K_EARTH = 4.0 / 3.0
R_EARTH = 6371000.0
N_SAMP = 256                      # profile samples per path
Image.MAX_IMAGE_PIXELS = None


def load_dem():
    z = np.array(Image.open(SCENE / "dem_3dep.tif"), dtype=np.float64)
    h, w = z.shape
    return z, h, w


def dem_sample(z, h, w, lat, lon):
    """Bilinear sample of the DEM at (lat, lon) arrays of any shape."""
    fy = (N - lat) / (N - S) * h - 0.5
    fx = (lon - W) / (E - W) * w - 0.5
    fy = np.clip(fy, 0, h - 1.001)
    fx = np.clip(fx, 0, w - 1.001)
    y0, x0 = np.floor(fy).astype(int), np.floor(fx).astype(int)
    ty, tx = fy - y0, fx - x0
    return ((1 - ty) * ((1 - tx) * z[y0, x0] + tx * z[y0, x0 + 1])
            + ty * ((1 - tx) * z[y0 + 1, x0] + tx * z[y0 + 1, x0 + 1]))


def knife_edge_db(nu):
    """ITU-R P.526 single knife-edge diffraction loss J(nu), dB."""
    out = np.zeros_like(nu)
    m = nu > -0.78
    n = nu[m] - 0.1
    out[m] = 6.9 + 20 * np.log10(np.sqrt(n * n + 1) + n)
    return np.maximum(out, 0.0)


def profile_features(lat_tx, lon_tx, h_tx_agl, lat_rx, lon_rx, h_rx_agl, d_h, z, h, w):
    """Vectorised terrain profiles for every TX->RX pair."""
    n = len(lat_rx)
    t = np.linspace(0.0, 1.0, N_SAMP)[None, :]                 # [1, M]
    lat = lat_tx + (lat_rx[:, None] - lat_tx) * t
    lon = lon_tx + (lon_rx[:, None] - lon_tx) * t
    zp = dem_sample(z, h, w, lat, lon)                          # [n, M] terrain

    d = d_h[:, None]
    d1 = t * d                                                  # [n, M]
    d2 = d - d1
    # 4/3-earth: add the curvature bulge to the terrain rather than bending the ray
    bulge = d1 * d2 / (2.0 * K_EARTH * R_EARTH)
    z_eff = zp + bulge

    z_tx = zp[:, 0] + h_tx_agl
    z_rx = zp[:, -1] + h_rx_agl
    z_los = z_tx[:, None] + (z_rx - z_tx)[:, None] * t          # straight line TX->RX

    clear = z_los - z_eff                                       # >0 means clear
    with np.errstate(divide="ignore", invalid="ignore"):
        f1 = np.sqrt(LAMBDA * d1 * d2 / d)                      # first Fresnel radius
        nu = -clear * np.sqrt(2.0 / LAMBDA * (1.0 / d1 + 1.0 / d2))
    nu[:, 0] = nu[:, -1] = -10.0                                # endpoints are not edges
    f1[:, 0] = f1[:, -1] = np.nan

    interior = slice(1, N_SAMP - 1)
    nu_max = np.nanmax(nu[:, interior], axis=1)
    i_pr = np.nanargmax(nu[:, interior], axis=1) + 1

    with np.errstate(invalid="ignore"):
        ratio = clear[:, interior] / f1[:, interior]
    clear_ratio = np.nanmin(ratio, axis=1)
    frac_blocked = np.mean(clear[:, interior] < 0, axis=1)
    n_edges = np.sum(ratio < 0.6, axis=1)
    rough_m = np.std(zp[:, interior], axis=1)

    # Deygout: principal edge, then one level of recursion on each sub-path
    J = knife_edge_db(nu_max)
    J_sub = np.zeros(n)
    for k in range(n):
        p = i_pr[k]
        for a, b in ((1, p), (p + 1, N_SAMP - 1)):
            if b - a >= 2:
                seg = nu[k, a:b]
                if np.isfinite(seg).any():
                    J_sub[k] += knife_edge_db(np.array([np.nanmax(seg)]))[0]
    J_deygout = J + J_sub
    is_los = clear_ratio > 0.6
    return dict(nu_max=nu_max, J_principal=J, J_deygout=J_deygout,
                clear_ratio=clear_ratio, frac_blocked=frac_blocked,
                n_edges=n_edges.astype(float), rough_m=rough_m,
                is_los=is_los.astype(float))


def main():
    npz_path = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else str(BASE / "terrain_features.npz")
    d = np.load(npz_path, allow_pickle=True)
    g = json.loads((SCENE / "georef.json").read_text())
    site = g["sites"]["Agronomy Farm"]
    h_ant = float(d["h_ant"])

    z, h, w = load_dem()
    lat_rx, lon_rx = d["meas_lat"], d["meas_lon"]
    mx, my = d["meas_x"], d["meas_y"]
    d_h = np.hypot(mx - site["x"], my - site["y"])

    print(f"DEM {z.shape}, relief {z.max()-z.min():.1f} m")
    print(f"{len(lat_rx):,} measured points, "
          f"{N_SAMP} profile samples each ({len(lat_rx)*N_SAMP/1e6:.1f} M samples)")

    keep = d_h > 50.0          # a profile is meaningless at the tower base
    f = profile_features(site["lat"], site["lon"], h_ant,
                         lat_rx, lon_rx, 1.5, np.maximum(d_h, 50.0), z, h, w)

    # receiver terrain exposure: elevation relative to its 500 m neighbourhood
    zr = dem_sample(z, h, w, lat_rx, lon_rx)
    px = (E - W) / w * 111320.0 * math.cos(math.radians(42.0))
    rad = max(int(round(500.0 / px)), 1)
    from scipy.ndimage import uniform_filter
    zbar = uniform_filter(z, size=2 * rad + 1, mode="nearest")
    f["rx_exposure"] = zr - dem_sample(zbar, h, w, lat_rx, lon_rx)
    f["d_h"] = d_h
    f["valid"] = keep.astype(float)

    np.savez_compressed(out, **f)
    print(f"wrote {out}")

    # ---------------- diagnostic: is the error concentrated in NLOS? -----------
    tx_order = [str(t) for t in d["tx_order"]]
    serv = np.array([tx_order.index(str(c)) for c in d["meas_cell"]])
    pg = d["meas_pg"][np.arange(len(serv)), serv]
    rsrp = d["meas_rsrp"]
    ok = (pg > 0) & keep
    pgdb = np.where(pg > 0, 10 * np.log10(np.where(pg > 0, pg, 1)), np.nan)
    off = float(np.mean(rsrp[ok] - pgdb[ok]))
    res = pgdb + off - rsrp

    los = f["is_los"] > 0.5
    print("\n" + "=" * 74)
    print("DIAGNOSTIC -- where does the error actually live?")
    print("=" * 74)
    print(f"  traced-path rate:  LOS {np.mean(pg[keep & los] > 0):.1%} "
          f"({int((keep & los).sum()):,} pts)   "
          f"NLOS {np.mean(pg[keep & ~los] > 0):.1%} "
          f"({int((keep & ~los).sum()):,} pts)")
    print(f"\n  {'stratum':<28}{'n':>7}{'RMSE':>8}{'bias':>8}{'sd':>8}{'r':>8}")
    for name, m in (("LOS (clearance > 0.6 F1)", ok & los),
                    ("NLOS", ok & ~los)):
        if m.sum() < 10:
            continue
        r = res[m]
        print(f"  {name:<28}{int(m.sum()):>7}{np.sqrt(np.mean(r**2)):>8.2f}"
              f"{r.mean():>8.2f}{r.std():>8.2f}"
              f"{np.corrcoef(pgdb[m], rsrp[m])[0,1]:>8.3f}")

    print(f"\n  by diffraction loss J_deygout (dB):")
    Jd = f["J_deygout"]
    edges = [-0.01, 0.01, 5, 10, 20, 30, 1e9]
    for k in range(len(edges) - 1):
        m = ok & (Jd > edges[k]) & (Jd <= edges[k + 1])
        if m.sum() < 10:
            continue
        r = res[m]
        print(f"    {edges[k]:>6.0f}..{edges[k+1]:<7.0f} n={int(m.sum()):>5}  "
              f"RMSE {np.sqrt(np.mean(r**2)):>6.2f}  bias {r.mean():>+7.2f}  "
              f"sd {r.std():>6.2f}")
    print("\n  If NLOS is both wider AND biased, the tracer is not merely imprecise")
    print("  there -- it is answering a question it cannot answer without diffraction.")


if __name__ == "__main__":
    main()
