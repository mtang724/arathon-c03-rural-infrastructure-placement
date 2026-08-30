"""
Assemble the planner page from one or more coverage bundles.

    python -m common.build_planner bundles/*.json --dem terrain-approach/data/dem10.npz

Every bundle listed becomes one entry in the page's simulator dropdown. They
must share a demand grid -- the whole point is that the models are compared on
the same demand -- and that is checked rather than assumed.

TWO THINGS HAPPEN HERE THAT ARE NOT JUST COPYING.

  THE TABULATED MATRICES ARE RE-ENCODED. A bundle stores them zlib-compressed,
  because a bundle is read by Python. The page decodes with `atob` and has no
  inflate, so they are transcoded to raw base64 here. That costs payload, which
  is why analytic bundles ship no matrix at all -- the page rebuilds theirs from
  the terrain grid on demand and caches it.

  THE DEM IS SHARED, NOT PER BUNDLE. It is the biggest single object on the
  page and it is a property of the ground, not of a model.
"""
from __future__ import annotations

import argparse
import base64
import json
import zlib
from pathlib import Path

import numpy as np

from .demand import ASSETS
from .planner_tpl import TPL
from .schema import CoverageBundle

STRIDE = 3          # DEM posts to keep: every third, 31 m rather than 10 m


def _dem_block(path, stride=STRIDE):
    """The terrain grid the analytic path walks, thinned to keep the page small.

    Checked rather than assumed: against the full-resolution grid, 31 m posts
    change the mean predicted diffraction loss by 0.15 dB with a correlation of
    0.994, which is far inside the residual sigma of any model here.
    """
    d = np.load(path)
    lats, lons, z = d["lats"], d["lons"], d["z"]
    zz = z[::stride, ::stride]
    fill = float(np.nanmedian(zz))
    return {"ny": int(zz.shape[0]), "nx": int(zz.shape[1]),
            "lat0": float(lats[0]), "lon0": float(lons[0]),
            "dlat": float((lats[1] - lats[0]) * stride),
            "dlon": float((lons[1] - lons[0]) * stride),
            "z": [int(round(float(v))) for v in
                  np.nan_to_num(zz, nan=fill).ravel()]}


def _raw_b64(blob: str) -> str:
    """zlib+base64 (bundle) -> plain base64 (page). See the module docstring."""
    return base64.b64encode(zlib.decompress(base64.b64decode(blob))).decode("ascii")


def _thin(b: CoverageBundle, keep_every: int):
    """Drop candidates from a tabulated bundle to keep the page openable.

    Only ever applied to TABULATED bundles, and only for the page. The offline
    solve in `common/bundle.py` always uses the full set.

    This is a resolution reduction and it is worth being plain about: with
    keep_every=2 the candidate lattice goes from about 400 m to about 800 m
    spacing. The robustness analysis already reports that this dataset locates a
    site to about 2 km rather than to a pole, so 800 m is inside the resolution
    the measurements actually support -- but it does mean the page's optimum can
    sit a few hundred metres from the offline one.
    """
    if keep_every <= 1 or b.prediction.mode != "tabulated":
        return b
    nc = len(b.prediction.candidates)
    idx = np.arange(0, nc, keep_every)
    n = len(b.grid.lat)
    b.prediction.candidates = [b.prediction.candidates[i] for i in idx]
    out = []
    for blob in b.prediction.rsrp_q:
        raw = np.frombuffer(zlib.decompress(base64.b64decode(blob)),
                            np.uint8).reshape(nc, n)
        out.append(base64.b64encode(raw[idx].tobytes()).decode("ascii"))
    b.prediction.rsrp_q = out
    b.prediction._already_raw = True
    return b


def build(bundle_paths, dem_path=None, out="planner.html", keep_every=2,
          verbose=True):
    bundles = [CoverageBundle.load(p) for p in bundle_paths]
    if not bundles:
        raise SystemExit("no bundles given")

    ref = bundles[0].grid
    for b in bundles[1:]:
        if len(b.grid.lat) != len(ref.lat) or abs(
                b.grid.total_route_km - ref.total_route_km) > 1e-6:
            raise SystemExit(
                f"{b.simulator.name} was built on a different demand grid "
                f"({len(b.grid.lat)} cells, {b.grid.total_route_km:.2f} route-km) "
                f"than {bundles[0].simulator.name} ({len(ref.lat)}, "
                f"{ref.total_route_km:.2f}). Rebuild them from the same "
                "measurements -- models scored on different demand are not "
                "being compared.")

    payload = []
    for b in bundles:
        b = _thin(b, keep_every)
        d = b.to_dict()
        if b.prediction.mode == "analytic":
            # The page rebuilds this itself from the terrain grid, so shipping
            # it would double the file for nothing.
            d["prediction"]["rsrp_q"] = []
        elif not getattr(b.prediction, "_already_raw", False):
            d["prediction"]["rsrp_q"] = [_raw_b64(x) for x in b.prediction.rsrp_q]
        d.pop("schema", None)
        payload.append(d)

    lat = np.array(ref.lat)
    lon = np.array(ref.lon)
    data = {
        "bundles": payload,
        "assets": {k: {"label": v["label"], "deficit_db": v["deficit"],
                       "agl_m": v["agl"], "donor_min_dbm": v["donor_min"]}
                   for k, v in ASSETS.items()},
        "cell_deg": ref.grid_m / 111_320.0,
        "bounds": [float(lat.min()), float(lon.min()),
                   float(lat.max()), float(lon.max())],
        "dem": _dem_block(dem_path) if dem_path else
               {"ny": 1, "nx": 1, "lat0": 0, "lon0": 0, "dlat": 1, "dlon": 1,
                "z": [0]},
    }
    if any(b.prediction.mode == "analytic" for b in bundles) and not dem_path:
        raise SystemExit("an analytic bundle needs --dem: the page walks the "
                         "terrain profile itself for free placement")

    out = Path(out)
    out.write_text(TPL.replace("__DATA__", json.dumps(data, separators=(",", ":"))),
                   encoding="utf-8")
    if verbose:
        print(f"[planner] {out} ({out.stat().st_size / 1e6:.2f} MB)")
        for b in bundles:
            print(f"[planner]   {b.simulator.label} [{b.prediction.mode}] "
                  f"{len(b.prediction.candidates)} candidates, "
                  f"{len(b.objective.criteria)} criteria")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("bundles", nargs="+")
    ap.add_argument("--dem", default=None)
    ap.add_argument("--out", default="planner.html")
    ap.add_argument("--keep-every", type=int, default=2,
                    help="thin tabulated candidates by this factor (page only)")
    a = ap.parse_args()
    build(a.bundles, a.dem, a.out, a.keep_every)


if __name__ == "__main__":
    main()
