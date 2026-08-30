"""
Stage 8b -- terrain-aware propagation.

Replaces the straight-line "does the ground poke through" test with the physics
that actually governs a grazing path at 3.46 GHz:

  * EARTH CURVATURE. Over a 10 km path the k=4/3 effective-earth bulge is 1.47 m
    at mid-path. The obstructions found with the coarse DEM had a median height
    of 1.5 m, so ignoring curvature was not a rounding error -- it was the same
    size as the effect being measured.

  * FIRST FRESNEL ZONE. A link does not need bare line of sight, it needs
    clearance of the Fresnel ellipsoid. At this carrier the F1 radius is 10.4 m
    at mid-path on a 5 km link and 14.0 m on a 9 km link, which is why 1/3
    arc-second posts (10.3 x 7.7 m) are the right resolution and 1 m would be
    oversampling something the radio integrates over anyway.

  * KNIFE-EDGE DIFFRACTION. ITU-R P.526 J(v) for the worst obstruction on the
    path, which converts geometry into decibels instead of a boolean.

The output is a set of per-link terrain features that get added to the fitted
path-loss model to see how much of its 9.2 dB residual they absorb.
"""
import numpy as np
import rasterio
from rasterio.windows import from_bounds

from config import DATA

C_LIGHT = 299_792_458.0
CARRIER_HZ = 3_460_800_000.0
LAMBDA = C_LIGHT / CARRIER_HZ          # 0.0867 m
K_EARTH = 4.0 / 3.0
R_EARTH = 6_371_000.0
R_EFF = K_EARTH * R_EARTH              # 8,494 km

TX_AGL = 36.576                        # 120 ft, as specified
RX_AGL = 1.8                           # roof-mounted vehicle antenna


# ==========================================================================
# DEM
# ==========================================================================

def build_dem(pad_deg=0.02, verbose=True):
    """Mosaic the 3DEP tiles, clip to the survey box, cache as dem10.npz."""
    import glob
    import pandas as pd
    from config import DATASET
    df = pd.read_csv(DATASET / "COTS.csv")
    w, e = df.lon.min() - pad_deg, df.lon.max() + pad_deg
    s, n = df.lat.min() - pad_deg, df.lat.max() + pad_deg

    tifs = sorted(glob.glob(str(DATA / "USGS_13_*.tif")))
    if not tifs:
        raise SystemExit("no USGS_13_*.tif in data/")

    lat0 = lon0 = res = None
    tiles = []
    for f in tifs:
        with rasterio.open(f) as r:
            b = r.bounds
            if not (b.left < e and b.right > w and b.bottom < n and b.top > s):
                continue
            win = from_bounds(w, s, e, n, r.transform).round_offsets().round_lengths()
            a = r.read(1, window=win, boundless=True, fill_value=np.nan).astype("float32")
            a[a <= -9999] = np.nan
            t = r.window_transform(win)
            tiles.append((a, t))
            res = abs(t.a)
    # common grid
    tops = [t.f for _, t in tiles]
    lefts = [t.c for _, t in tiles]
    top, left = max(tops), min(lefts)
    H = int(round((top - s) / res)); W = int(round((e - left) / res))
    out = np.full((H, W), np.nan, "float32")
    for a, t in tiles:
        r0 = int(round((top - t.f) / res)); c0 = int(round((t.c - left) / res))
        h, wd = a.shape
        r1, c1 = min(H, r0 + h), min(W, c0 + wd)
        if r1 <= r0 or c1 <= c0:
            continue
        blk = out[r0:r1, c0:c1]
        src = a[:r1 - r0, :c1 - c0]
        out[r0:r1, c0:c1] = np.where(np.isnan(blk), src, blk)

    lats = top - (np.arange(H) + 0.5) * res      # descending
    lons = left + (np.arange(W) + 0.5) * res
    np.savez_compressed(DATA / "dem10.npz", lats=lats, lons=lons, z=out, res_deg=res)
    if verbose:
        ok = out[~np.isnan(out)]
        print(f"[dem] mosaic {H} x {W} @ {res*111320:.1f} m lat / "
              f"{res*111320*np.cos(np.radians(42)):.1f} m lon")
        print(f"[dem] lat {lats.min():.5f}..{lats.max():.5f}  "
              f"lon {lons.min():.5f}..{lons.max():.5f}")
        print(f"[dem] elevation {ok.min():.1f}..{ok.max():.1f} m "
              f"(relief {ok.max()-ok.min():.1f} m), {int(np.isnan(out).sum())} nodata")
    return out


class DEM:
    def __init__(self, path=None):
        d = np.load(path or (DATA / "dem10.npz"))
        self.lats, self.lons, self.z = d["lats"], d["lons"], d["z"]
        self.dlat = self.lats[1] - self.lats[0]      # negative (descending)
        self.dlon = self.lons[1] - self.lons[0]

    def at(self, la, lo):
        """Bilinear ground elevation, metres AMSL."""
        fi = np.clip((np.asarray(la) - self.lats[0]) / self.dlat, 0, len(self.lats) - 1.001)
        fj = np.clip((np.asarray(lo) - self.lons[0]) / self.dlon, 0, len(self.lons) - 1.001)
        i0, j0 = fi.astype(np.int32), fj.astype(np.int32)
        ti, tj = fi - i0, fj - j0
        z = self.z
        return ((1 - ti) * (1 - tj) * z[i0, j0] + ti * (1 - tj) * z[i0 + 1, j0]
                + (1 - ti) * tj * z[i0, j0 + 1] + ti * tj * z[i0 + 1, j0 + 1])


# ==========================================================================
# Link geometry
# ==========================================================================

def knife_edge_db(v):
    """ITU-R P.526 single knife-edge diffraction loss J(v), dB."""
    v = np.asarray(v, float)
    out = np.zeros_like(v)
    m = v > -0.78
    vm = v[m] - 0.1
    out[m] = 6.9 + 20.0 * np.log10(np.sqrt(vm * vm + 1.0) + vm)
    return np.maximum(out, 0.0)


def link_features(dem, tx_lat, tx_lon, rx_lat, rx_lon,
                  tx_agl=TX_AGL, rx_agl=RX_AGL, nseg=160, chunk=20000):
    """Terrain features for TX -> each RX point.

    Returns dict of arrays: fresnel_frac (min clearance as a fraction of F1,
    negative when the ground is inside the line), diff_db (knife-edge loss),
    clear_m (min metric clearance), and blocked (bare LOS test).
    """
    rx_lat = np.atleast_1d(np.asarray(rx_lat, float))
    rx_lon = np.atleast_1d(np.asarray(rx_lon, float))
    n = len(rx_lat)
    ff = np.empty(n); dd = np.empty(n); cc = np.empty(n)
    f = np.linspace(0.0, 1.0, nseg)[None, :]
    tx_z = float(dem.at(tx_lat, tx_lon)) + tx_agl

    for a in range(0, n, chunk):
        b = min(n, a + chunk)
        la = rx_lat[a:b][:, None]; lo = rx_lon[a:b][:, None]
        # total path length (m) for this chunk
        dtot = _hav(tx_lat, tx_lon, rx_lat[a:b], rx_lon[a:b])[:, None]
        pl = tx_lat + (la - tx_lat) * f
        po = tx_lon + (lo - tx_lon) * f
        g = dem.at(pl.ravel(), po.ravel()).reshape(pl.shape)

        rx_z = dem.at(rx_lat[a:b], rx_lon[a:b]) + rx_agl
        line = tx_z + (rx_z[:, None] - tx_z) * f

        d1 = dtot * f
        d2 = dtot - d1
        # effective-earth bulge lifts the ground relative to the straight line
        bulge = d1 * d2 / (2.0 * R_EFF)
        gg = g + bulge

        clear = line - gg                       # +ve = clear
        F1 = np.sqrt(np.maximum(LAMBDA * d1 * d2 / np.maximum(dtot, 1.0), 1e-9))
        with np.errstate(divide="ignore", invalid="ignore"):
            frac = clear / F1                   # clearance in Fresnel radii
        frac[:, 0] = np.inf; frac[:, -1] = np.inf   # endpoints are not obstacles

        ff[a:b] = np.nanmin(frac, axis=1)
        cc[a:b] = np.nanmin(np.where(np.isfinite(frac), clear, np.inf), axis=1)
        # v = -sqrt(2) * (clearance / F1); obstruction is positive v
        v = -np.sqrt(2.0) * frac
        dd[a:b] = knife_edge_db(np.nanmax(v, axis=1))

    return {"fresnel_frac": ff, "diff_db": dd, "clear_m": cc, "blocked": cc < 0}


def _hav(la1, lo1, la2, lo2):
    p1, p2 = np.radians(la1), np.radians(la2)
    a = (np.sin((p2 - p1) / 2) ** 2
         + np.cos(p1) * np.cos(p2) * np.sin(np.radians(np.asarray(lo2) - lo1) / 2) ** 2)
    return 2 * R_EARTH * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


if __name__ == "__main__":
    build_dem()
