"""
Stage 14a -- terrain profiles as input FUNCTIONS.

A neural operator learns a map between function spaces, so before one can be
trained the data has to be posed as (input function, output value) pairs. The
framing that works on this dataset is NOT "terrain map -> coverage surface":
there is exactly one serving transmitter, so that framing has exactly one
training example. It is "terrain profile along the link -> received power",
which has 3,838.

For each measurement, ground elevation is sampled at NPROF points along the
great circle from the tower to the receiver, and the same geometry that
propagation.link_features() uses -- k=4/3 earth bulge, the transmitter and
receiver antenna heights -- is applied so that the profile the operator sees is
the profile the physics sees.

Two representations are cached, because the two experiments need different ones:

  obstruction (`hb`)  ground + earth bulge - the straight TX-RX line, in metres.
      Positive means terrain intrudes on the optical path. This is the quantity
      P.526 reduces to a single scalar v at the worst point; handing the whole
      function to a network is precisely the comparison being made.

  ground (`grel`)     bare ground elevation relative to the transmitter's own
      ground level, in metres. No line subtracted, so nothing about the link
      geometry is baked in.

THE HORIZONTAL AXIS IS NORMALISED TO [0, 1] IN BOTH. That is deliberate and it
is the whole reason this file exists separately from the model code. Fresnel
clearance in this dataset is 96.5% correlated with log-distance, and a profile
sampled on an absolute axis encodes its own length; a network handed one will
learn distance, score well, and be measuring the wrong thing. Distance is
supplied to the operator explicitly, as a channel, or not at all -- never
smuggled in through the sampling grid.
"""
import numpy as np
import pandas as pd

from config import DATA, SERVING_SITE
from features import load_sites
from propagation import DEM, R_EFF, RX_AGL, TX_AGL, _hav

NPROF = 128


def profiles(dem, tx_lat, tx_lon, rx_lat, rx_lon, tx_agl=TX_AGL, rx_agl=RX_AGL,
             nprof=NPROF, chunk=4000):
    """Terrain profiles for TX -> each RX, sampled on a normalised [0,1] axis.

    Returns (hb, grel, dist_m):
        hb    (n, nprof)  ground + bulge - LOS line, metres, +ve = obstruction
        grel  (n, nprof)  ground - TX ground elevation, metres
        dist  (n,)        great-circle path length, metres
    """
    rx_lat = np.atleast_1d(np.asarray(rx_lat, float))
    rx_lon = np.atleast_1d(np.asarray(rx_lon, float))
    n = len(rx_lat)
    hb = np.empty((n, nprof), np.float32)
    gr = np.empty((n, nprof), np.float32)
    f = np.linspace(0.0, 1.0, nprof)[None, :]
    tx_g = float(dem.at(tx_lat, tx_lon))
    tx_z = tx_g + tx_agl
    dist = _hav(tx_lat, tx_lon, rx_lat, rx_lon)

    for a in range(0, n, chunk):
        b = min(n, a + chunk)
        la = rx_lat[a:b][:, None]
        lo = rx_lon[a:b][:, None]
        dtot = dist[a:b][:, None]
        g = dem.at((tx_lat + (la - tx_lat) * f).ravel(),
                   (tx_lon + (lo - tx_lon) * f).ravel()).reshape(b - a, nprof)
        rx_z = dem.at(rx_lat[a:b], rx_lon[a:b]) + rx_agl
        line = tx_z + (rx_z[:, None] - tx_z) * f
        d1 = dtot * f
        bulge = d1 * (dtot - d1) / (2.0 * R_EFF)
        hb[a:b] = (g + bulge) - line
        gr[a:b] = g - tx_g
    return hb, gr, dist


def build(verbose=True):
    """Cache profiles for every modelled row, in the row order the model uses."""
    dem = DEM()
    df = pd.read_csv(DATA / "labeled_terrain.csv", dtype={"cellid": str})
    r = (df[df.site.eq(SERVING_SITE) & df.rsrp.notna() & (df.dist_m > 30)]
         .copy().reset_index(drop=True))
    sites, _ = load_sites()
    tl, to = sites[SERVING_SITE]
    hb, gr, dist = profiles(dem, tl, to, r.lat.to_numpy(), r.lon.to_numpy())

    np.savez_compressed(
        DATA / "profiles.npz", hb=hb, grel=gr, dist_m=dist.astype(np.float32),
        lat=r.lat.to_numpy(np.float32), lon=r.lon.to_numpy(np.float32),
        az_deg=r.az_deg.to_numpy(np.float32), rsrp=r.rsrp.to_numpy(np.float32),
        diff_db=r.diff_db.to_numpy(np.float32),
        fresnel_frac=r.fresnel_frac.to_numpy(np.float32))
    if verbose:
        obs = (hb > 0).any(axis=1)
        print(f"[prof] {len(r):,} links x {NPROF} points, "
              f"{np.corrcoef(np.log10(dist), hb.max(axis=1))[0,1]:+.3f} "
              f"corr(log d, max obstruction)")
        print(f"[prof] {100*obs.mean():.1f}% of links have terrain above the "
              f"line somewhere; max intrusion {hb.max():.1f} m")
        print(f"[prof] wrote data/profiles.npz")
    return hb, gr, dist


if __name__ == "__main__":
    build()
