"""This approach's model, behind the repository-wide simulator contract.

`common/` never imports an approach; an approach imports `common` and exposes its models
here. See `terrain-approach/src/adapter.py` for the reference implementation.

One model lives here.

  SionnaHybridSimulator   ray tracing over a reconstructed scene (terrain + Microsoft ML
                          building footprints, all four sites, twelve sectors) corrected
                          by ITU-R P.526 profile diffraction where the tracer finds no
                          path. Five fitted constants; the rest is geometry.

TABULATED, NOT ANALYTIC. There is no closed form for a ray tracer, so `macro_rsrp` reads a
precomputed 100 m grid of traced path gain and interpolates, using the exact traced value
where the query lands on a measured point. That is a model output at a measured location,
not a measurement, so it leaks nothing -- and the five constants are refitted per fold by
`refit`.

NEW NODES ARE ANALYTIC. `node_rsrp` cannot ray-trace: the contract calls it once per
candidate at arbitrary coordinates, and a scene solve per call would make the planner
unusable. It uses free space minus the same fitted P.526 diffraction loss, which is not a
fallback but a measured-good predictor in its own right -- on the points where the tracer
finds no path at all it scores 6.86 dB RMSE, better than the traced branch's 8.39.

EIRP CONVENTION. The contract's `eirp_deficit_db` is dB below the existing macro. This
model knows the macro's absolute per-RE EIRP (34.0 dBm, decomposed in DEPLOYMENT.md from
ARA's published radio and bandwidth), so a deficit maps to an absolute level directly.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / "analysis"))

from common.schema import SimulatorInfo                      # noqa: E402
from terrain_features import load_dem, profile_features      # noqa: E402

FC = 3.4608e9
LAMBDA = 299792458.0 / FC
MACRO_EIRP_PER_RE_DBM = 34.0        # DEPLOYMENT.md: offset 26.0 + tr38901 boresight 8.0
SURFACE = BASE / "simcache" / "surfaces" / "all_sites_h37.npz"
SNAP_M = 5.0                        # use the exact traced value within this radius


class _Interp:
    """Bilinear interpolation over the regular scene-XY grid, NaN outside."""

    def __init__(self, gx, gy, gok, values):
        self.gx, self.gy = gx, gy
        img = np.full(len(gok), np.nan)
        img[gok] = values
        self.img = img.reshape(len(gy), len(gx))
        self.dx = gx[1] - gx[0]
        self.dy = gy[1] - gy[0]

    def __call__(self, x, y):
        fx = np.clip((x - self.gx[0]) / self.dx, 0, len(self.gx) - 1.001)
        fy = np.clip((y - self.gy[0]) / self.dy, 0, len(self.gy) - 1.001)
        i0, j0 = fy.astype(int), fx.astype(int)
        ty, tx = fy - i0, fx - j0
        A = self.img
        v = ((1 - ty) * (1 - tx) * A[i0, j0] + (1 - ty) * tx * A[i0, j0 + 1]
             + ty * (1 - tx) * A[i0 + 1, j0] + ty * tx * A[i0 + 1, j0 + 1])
        # a NaN corner (off-terrain) falls back to the nearest finite cell
        bad = ~np.isfinite(v)
        if bad.any():
            v[bad] = A[np.clip(i0[bad], 0, A.shape[0] - 1),
                       np.clip(j0[bad], 0, A.shape[1] - 1)]
        return v


class SionnaHybridSimulator:
    """Ray tracing + ITU-R P.526 profile diffraction, behind the shared contract."""

    def __init__(self, train=None, path=SURFACE, _shared=None, only_site=None):
        """`only_site` restricts best-server to one site's sectors.

        The full network (all four sites, twelve sectors) is what a siting baseline
        needs -- otherwise gaps Curtiss and Wilson Hall already fill get re-filled by
        our recommendation. But the shared testbench scores against RSRP reported by
        the Agronomy serving cell, so a best-server-over-twelve prediction is graded on
        a question it was not asked. Both are exposed, and both are reported.
        """
        self.only_site = only_site
        d = np.load(path, allow_pickle=True)
        self.path = path
        g = json.loads((BASE / "scene" / "georef.json").read_text())
        self.g = g
        self.lat0r = math.radians(g["origin_lat"])
        self.lon0, self.R, self.K = g["origin_lon"], g["radius"], g["k"]

        if _shared is None:
            z, H, W = load_dem()
            gx, gy, gok = d["gx"], d["gy"], d["gok"]
            grid_x, grid_y = d["grid_x"], d["grid_y"]
            order = [str(t) for t in d["tx_order"]]
            sites = [str(s) for s in d["sites"]]
            prefix = {"Agronomy Farm": "00019C", "Curtiss Farm": "000194",
                      "Research Park": "000198", "Wilson Hall": "0001A0"}
            site_of_tx = np.array([next(s for s in sites
                                        if order[i].startswith(prefix[s]))
                                   for i in range(len(order))])
            # best server over all twelve sectors, and which SITE won
            keep_tx = (np.array([True] * len(order)) if only_site is None
                       else site_of_tx == only_site)
            gpg = d["grid_pg"][:, keep_tx]
            sub = site_of_tx[keep_tx]
            gbest_sub = gpg.argmax(axis=1)
            gbest = np.where(keep_tx)[0][gbest_sub]
            gval = gpg.max(axis=1)
            # diffraction loss to each site, on the grid
            glat, glon = self._to_geo(grid_x, grid_y)
            Jg = {}
            for s in sites:
                sx, sy = g["sites"][s]["x"], g["sites"][s]["y"]
                dh = np.maximum(np.hypot(grid_x - sx, grid_y - sy), 50.0)
                f = profile_features(g["sites"][s]["lat"], g["sites"][s]["lon"],
                                     float(d["h_ant"]), glat, glon, 1.5, dh, z, H, W)
                Jg[s] = f["J_deygout"]
            gsite = np.array([sites.index(s) for s in site_of_tx[gbest]])
            gJ = np.choose(gsite, [Jg[s] for s in sites])
            # distance to the site that WINS, not to the nearest one: with twelve
            # sectors across four sites those differ, and the free-space reference
            # must match the transmitter the prediction is about
            gd = np.choose(gsite, [np.hypot(grid_x - g["sites"][s]["x"],
                                            grid_y - g["sites"][s]["y"]) for s in sites])
            _shared = dict(z=z, H=H, W=W, sites=sites, site_of_tx=site_of_tx,
                           order=order, Jg=Jg,
                           I_pg=_Interp(gx, gy, gok, np.where(gval > 0,
                                        10 * np.log10(np.where(gval > 0, gval, 1)), np.nan)),
                           I_lk=_Interp(gx, gy, gok, (gval > 0).astype(float)),
                           I_J=_Interp(gx, gy, gok, gJ),
                           I_d=_Interp(gx, gy, gok, gd))
        self.S = _shared
        self.tree = cKDTree(np.column_stack([d["meas_x"], d["meas_y"]]))
        order_all = [str(x) for x in d["tx_order"]]
        pref = {"Agronomy Farm": "00019C", "Curtiss Farm": "000194",
                "Research Park": "000198", "Wilson Hall": "0001A0"}
        kt = (np.ones(len(order_all), bool) if only_site is None
              else np.array([o.startswith(pref[only_site]) for o in order_all]))
        self.mpg = d["meas_pg"][:, kt]
        self.mx, self.my = d["meas_x"], d["meas_y"]
        self.mlat, self.mlon = d["meas_lat"], d["meas_lon"]
        self.mrsrp = d["meas_rsrp"]
        self.mserved = d["meas_served"]
        self._fit(train)

        self.info = SimulatorInfo(
            name="sionna-hybrid" + ("" if only_site is None else "-agronomy"),
            label=("Ray tracing + P.526 profile diffraction"
                   + ("" if only_site is None else " (Agronomy only)")),
            approach="sionna-approach",
            notes=("Sionna RT over 30 m terrain and Microsoft ML building footprints, "
                   "all four sites and twelve sectors at 36.576 m, corrected by ITU-R "
                   "P.526 knife-edge diffraction (Deygout, 4/3-earth) on the 3DEP "
                   "profile where the tracer finds no path."),
            sigma_db=self.sigma_db, fitted_on_rows=int(self.n_fit))

    # ------------------------------------------------------------ geometry --
    def _from_geo(self, lat, lon):
        lat = np.radians(np.asarray(lat, float))
        lon = np.radians(np.asarray(lon, float) - self.lon0)
        B = np.sin(lon) * np.cos(lat)
        return (0.5 * self.K * self.R * np.log((1 + B) / (1 - B)),
                self.K * self.R * (np.arctan(np.tan(lat) / np.cos(lon)) - self.lat0r))

    def _to_geo(self, x, y):
        xp, yp = x / (self.K * self.R), y / (self.K * self.R) + self.lat0r
        return (np.degrees(np.arcsin(np.sin(yp) / np.cosh(xp))),
                np.degrees(np.arctan2(np.sinh(xp), np.cos(yp))) + self.lon0)

    # --------------------------------------------------------------- fit ----
    def _components(self, lat, lon):
        """Traced path gain (dB), linked flag and diffraction loss at any point."""
        x, y = self._from_geo(lat, lon)
        dist, idx = self.tree.query(np.column_stack([x, y]), k=1)
        snap = dist < SNAP_M
        pgdb = self.S["I_pg"](x, y)
        linked = self.S["I_lk"](x, y) > 0.5
        if snap.any():                      # exact traced value where we have one
            v = self.mpg[idx[snap]].max(axis=1)
            with np.errstate(divide="ignore"):
                pgdb[snap] = np.where(v > 0, 10 * np.log10(np.where(v > 0, v, 1)), np.nan)
            linked[snap] = v > 0
        J = self.S["I_J"](x, y)
        d = np.maximum(self.S["I_d"](x, y), 50.0)
        linked &= np.isfinite(pgdb)
        return np.where(np.isfinite(pgdb), pgdb, 0.0), linked, J, d

    def _fit(self, train):
        """Refit the five constants. `train` is a measurement frame or None."""
        if train is None or not len(train):
            lat, lon, rsrp = self.mlat, self.mlon, self.mrsrp
            keep = np.isfinite(rsrp) & self.mserved.astype(bool)
        else:
            lat = train["lat"].to_numpy(); lon = train["lon"].to_numpy()
            rsrp = train["rsrp"].to_numpy()
            keep = np.isfinite(rsrp)
        lat, lon, rsrp = np.asarray(lat)[keep], np.asarray(lon)[keep], rsrp[keep]
        pgdb, linked, J, d = self._components(lat, lon)
        fs = 20 * np.log10(LAMBDA / (4 * np.pi * d))
        far = d > 50.0
        A = np.column_stack([linked[far].astype(float), (~linked[far]).astype(float),
                             -J[far]])
        rhs = rsrp[far] - np.where(linked[far], pgdb[far], fs[far])
        c, *_ = np.linalg.lstsq(A, rhs, rcond=None)
        self.c_lk, self.c_un, self.alpha = float(c[0]), float(c[1]), float(c[2])
        pred = np.where(linked, pgdb + self.c_lk, fs + self.c_un) - self.alpha * J
        self.sigma_db = float(np.std(pred[far] - rsrp[far]))
        self.n_fit = int(far.sum())

    # ------------------------------------------------------ the contract ----
    def macro_rsrp(self, lat, lon):
        pgdb, linked, J, d = self._components(np.asarray(lat), np.asarray(lon))
        fs = 20 * np.log10(LAMBDA / (4 * np.pi * d))
        return np.where(linked, pgdb + self.c_lk, fs + self.c_un) - self.alpha * J

    def node_rsrp(self, tx_lat, tx_lon, agl_m, eirp_deficit_db, lat, lon):
        lat, lon = np.asarray(lat, float), np.asarray(lon, float)
        x, y = self._from_geo(lat, lon)
        tx, ty = self._from_geo(np.array([tx_lat]), np.array([tx_lon]))
        d = np.maximum(np.hypot(x - tx[0], y - ty[0]), 30.0)
        f = profile_features(tx_lat, tx_lon, agl_m, lat, lon, 1.5, d,
                             self.S["z"], self.S["H"], self.S["W"])
        fs = 20 * np.log10(LAMBDA / (4 * np.pi * d))
        return fs + (MACRO_EIRP_PER_RE_DBM - eirp_deficit_db) - self.alpha * f["J_deygout"]

    def refit(self, train):
        return SionnaHybridSimulator(train, path=self.path, _shared=self.S,
                                     only_site=self.only_site)


def simulators(df=None):
    """Every model this approach exposes, for the shared tools.

    The Agronomy-only variant exists for comparability with models that only model
    the serving site; the full-network one is the siting baseline.
    """
    return [SionnaHybridSimulator(df, only_site="Agronomy Farm"),
            SionnaHybridSimulator(df)]
