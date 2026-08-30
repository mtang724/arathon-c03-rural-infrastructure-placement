"""
Where service is wanted, and where a transmitter is allowed to go.

Neither of these depends on a propagation model, so both live here rather than
inside one approach. Two models that score against different demand grids or
search different candidate sets are not being compared, however carefully their
RMSEs were computed.

DEMAND, TWO LAYERS.

  ROUTE-KM  is de-duplicated, and that is not a detail. The van drove some roads
            on all four runs, so summing GPS steps gives 277 km for what is
            really 116.7 km of distinct road -- a 2.4x overcount concentrated
            exactly on the well-surveyed roads near the tower, which would tilt
            every siting decision inward. Counting distinct 25 m sub-cells
            recovers the true length.

  AREA      is uniform over the bounding box, and is the counterweight to the
            fact that route density measures the SURVEY rather than the
            population. The van avoided the deepest holes; area demand does not.

CANDIDATES are on-route (access, right-of-way and power are evidenced by the
fact that a vehicle got there) plus a coarse off-route lattice, and anything
closer than 400 m to the existing macro is dropped as pointless.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

GRID_M = 200.0
SUB_M = 25.0                  # sub-cell size for de-duplicating road length
LAT0 = 42.0
W_ROUTE, W_AREA = 0.70, 0.30

# The brief's menu, plus one class deliberately outside it. A 520 m relay cannot
# fill a 9 km hole, and the honest comparison is what it would actually take.
ASSETS = {
    "relay": {"label": "Donor-fed relay", "deficit": 20.0, "agl": 10.0,
              "donor_min": -95.0},
    "smallcell": {"label": "Backhauled small cell", "deficit": 26.0, "agl": 10.0,
                  "donor_min": None},
    "macro": {"label": "Macro-class site", "deficit": 0.0, "agl": 36.576,
              "donor_min": None},
}

EARTH_R = 6_371_000.0


def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = (np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2)
         * np.sin(np.radians(np.asarray(lon2) - np.asarray(lon1)) / 2) ** 2)
    return 2 * EARTH_R * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def _steps(grid_m):
    return (grid_m / 111_320.0,
            grid_m / (111_320.0 * np.cos(np.radians(LAT0))))


def build_grid(df, grid_m=GRID_M) -> pd.DataFrame:
    """One grid over the survey box carrying both demand layers."""
    ma, mo = _steps(grid_m)
    sa, so = _steps(SUB_M)
    d = df.assign(sy=np.round(df.lat / sa).astype(int),
                  sx=np.round(df.lon / so).astype(int),
                  gy=np.round(df.lat / ma).astype(int),
                  gx=np.round(df.lon / mo).astype(int))
    rk = (d.drop_duplicates(["sy", "sx"]).groupby(["gy", "gx"]).size()
          .mul(SUB_M / 1000.0).rename("route_km"))

    gy = np.arange(int(np.floor(df.lat.min() / ma)),
                   int(np.ceil(df.lat.max() / ma)) + 1)
    gx = np.arange(int(np.floor(df.lon.min() / mo)),
                   int(np.ceil(df.lon.max() / mo)) + 1)
    GY, GX = np.meshgrid(gy, gx, indexing="ij")
    cells = pd.DataFrame({"gy": GY.ravel(), "gx": GX.ravel()})
    cells["lat"] = cells.gy * ma
    cells["lon"] = cells.gx * mo
    cells["area_km2"] = (grid_m / 1000.0) ** 2
    cells = cells.merge(rk.reset_index(), on=["gy", "gx"], how="left")
    cells["route_km"] = cells.route_km.fillna(0.0)
    return cells.reset_index(drop=True)


def build_candidates(df, cells, macro_lat, macro_lon, donor_rsrp_fn=None,
                     spacing_m=400.0, offroute_m=600.0,
                     min_from_macro_m=400.0) -> pd.DataFrame:
    """On-route sites plus an off-route lattice.

    `donor_rsrp_fn(lat, lon) -> dBm` is the received power AT the candidate from
    the existing macro. A donor-fed relay can only rebroadcast a signal it can
    still hear, so this is what makes the relay class feasibility-limited rather
    than merely weak. Pass None and every candidate is treated as feasible.
    """
    pts = df[["lat", "lon"]].dropna().to_numpy()
    keep, kl, ko = [pts[0]], [pts[0][0]], [pts[0][1]]
    for p in pts[1:]:
        if haversine_m(p[0], p[1], np.array(kl), np.array(ko)).min() > spacing_m:
            keep.append(p)
            kl.append(p[0])
            ko.append(p[1])
    on = pd.DataFrame(keep, columns=["lat", "lon"])
    on["kind"] = "on-route"

    ma, mo = _steps(GRID_M)
    step = max(1, int(round(offroute_m / GRID_M)))
    g = cells[(cells.gy % step == 0) & (cells.gx % step == 0)]
    keepo = [(r.lat, r.lon) for r in g.itertuples()
             if haversine_m(r.lat, r.lon, on.lat.to_numpy(),
                            on.lon.to_numpy()).min() > offroute_m * 0.6]
    off = pd.DataFrame(keepo, columns=["lat", "lon"])
    off["kind"] = "off-route"

    cand = pd.concat([on, off], ignore_index=True)
    cand["d_macro"] = haversine_m(cand.lat, cand.lon, macro_lat, macro_lon)
    cand = cand[cand.d_macro > min_from_macro_m].reset_index(drop=True)
    cand["donor_rsrp"] = (np.full(len(cand), 0.0) if donor_rsrp_fn is None
                          else donor_rsrp_fn(cand.lat.to_numpy(),
                                             cand.lon.to_numpy()))
    return cand


class Scorer:
    """The objective: a weighted blend of route-km and area, each normalised.

    Weights are arguments rather than constants because the planner exposes them
    as a slider. Route 0.70 / area 0.30 is a default, not a finding.
    """

    def __init__(self, cells, w_route=W_ROUTE, w_area=W_AREA):
        self.rk = cells.route_km.to_numpy(float)
        self.ar = cells.area_km2.to_numpy(float)
        self.tot_rk = float(self.rk.sum())
        self.tot_ar = float(self.ar.sum())
        self.w_route, self.w_area = w_route, w_area

    def parts(self, covered):
        return float(self.rk[covered].sum()), float(self.ar[covered].sum())

    def __call__(self, covered):
        km, ar = self.parts(covered)
        return self.w_route * km / self.tot_rk + self.w_area * ar / self.tot_ar


def greedy(base_r, R, thr, scorer, k=3):
    """Max-coverage by greedy selection.

    Coverage is submodular, so greedy is within 1 - 1/e (about 63%) of optimal,
    needs no solver, and runs in milliseconds -- which is what lets the same
    routine run live in a browser for any criterion, threshold and weighting the
    user picks.
    """
    cur = base_r.copy()
    base = scorer(cur >= thr)
    chosen, gains = [], []
    for _ in range(k):
        best, bg, br = None, 1e-12, None
        for i in range(len(R)):
            nr = np.maximum(cur, R[i])
            s = scorer(nr >= thr) - base
            if s > bg:
                best, bg, br = i, s, nr
        if best is None:
            break
        chosen.append(int(best))
        cur = br
        gains.append(float(bg))
    return chosen, gains


__all__ = ["GRID_M", "SUB_M", "W_ROUTE", "W_AREA", "ASSETS", "build_grid",
           "build_candidates", "Scorer", "greedy", "haversine_m"]
