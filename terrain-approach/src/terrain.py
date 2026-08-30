"""
Stage 8a -- fetch a terrain model for the survey area and cache it.

Source: USGS NED 10 m (the 3DEP product) via api.opentopodata.org, which needs
no API key. The public instance allows 100 locations per call and about one call
per second, so the grid spacing below is a deliberate compromise: 100 m posts
cover the box in ~180 calls and a few minutes, and at 3.46 GHz over kilometre-
scale paths the features that actually shadow a link -- ridge lines and creek
valleys -- are hundreds of metres wide. Finer posts would cost 100x the calls
and change no line-of-sight verdict.

Writes data/dem.npz: a regular lat/lon grid of ground elevation in metres.
"""
import json
import time
import urllib.error
import urllib.request

import numpy as np
import pandas as pd

from config import DATA, DATASET

URL = "https://api.opentopodata.org/v1/ned10m"
POST_M = 100.0        # grid spacing
MARGIN_M = 1500.0     # so paths that leave the box still land on real ground
BATCH = 100           # locations per request (API maximum)
PAUSE = 1.05          # seconds between calls (API allows ~1/s)


def _fetch(batch, tries=4):
    q = "|".join(f"{a:.6f},{b:.6f}" for a, b in batch)
    for k in range(tries):
        try:
            with urllib.request.urlopen(f"{URL}?locations={q}", timeout=45) as r:
                d = json.loads(r.read().decode())
            if d.get("status") == "OK":
                return [None if x["elevation"] is None else float(x["elevation"])
                        for x in d["results"]]
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError):
            pass
        time.sleep(2.0 * (k + 1))
    return [None] * len(batch)


def build(verbose=True):
    df = pd.read_csv(DATASET / "COTS.csv")
    mlat = POST_M / 111_320.0
    mlon = POST_M / (111_320.0 * np.cos(np.radians(42.0)))
    pad_lat = MARGIN_M / 111_320.0
    pad_lon = MARGIN_M / (111_320.0 * np.cos(np.radians(42.0)))

    lats = np.arange(df.lat.min() - pad_lat, df.lat.max() + pad_lat + mlat, mlat)
    lons = np.arange(df.lon.min() - pad_lon, df.lon.max() + pad_lon + mlon, mlon)
    LA, LO = np.meshgrid(lats, lons, indexing="ij")
    pts = list(zip(LA.ravel(), LO.ravel()))
    n = len(pts)
    if verbose:
        print(f"[terrain] grid {len(lats)} x {len(lons)} = {n:,} posts at {POST_M:.0f} m")
        print(f"[terrain] {int(np.ceil(n/BATCH))} API calls, ~{n/BATCH*PAUSE/60:.1f} min")

    out = np.full(n, np.nan)
    t0 = time.time()
    for i in range(0, n, BATCH):
        vals = _fetch(pts[i:i + BATCH])
        for j, v in enumerate(vals):
            if v is not None:
                out[i + j] = v
        if verbose and (i // BATCH) % 20 == 0:
            done = min(i + BATCH, n)
            print(f"[terrain]   {done:>6}/{n}  ({100*done/n:5.1f}%)  "
                  f"{time.time()-t0:5.0f}s elapsed", flush=True)
        time.sleep(PAUSE)

    Z = out.reshape(LA.shape)
    miss = int(np.isnan(Z).sum())
    DATA.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(DATA / "dem.npz", lats=lats, lons=lons, z=Z,
                        post_m=POST_M, source="USGS NED 10m via opentopodata")
    if verbose:
        ok = Z[~np.isnan(Z)]
        print(f"[terrain] done in {(time.time()-t0)/60:.1f} min, {miss} missing posts")
        print(f"[terrain] elevation {ok.min():.1f} to {ok.max():.1f} m "
              f"(relief {ok.max()-ok.min():.1f} m), median {np.median(ok):.1f} m")
        print(f"[terrain] wrote {DATA/'dem.npz'}")
    return Z


if __name__ == "__main__":
    build()
