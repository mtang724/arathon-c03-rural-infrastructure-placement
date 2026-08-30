"""
This approach's models, wrapped in the repository-wide simulator contract.

`common/` never imports an approach. An approach imports `common` and exposes
its models here, which is what lets a new approach be added without touching an
existing one. If you are writing a new approach, copy the shape of this file --
it is the reference implementation of `common.simulator.Simulator`.

Two models live here:

  ParametricSimulator   the fitted two-slope law with P.526 diffraction and
                        Fresnel clearance. Analytic: it can be reduced to a
                        closed form, so the planner can evaluate it anywhere.

  OperatorSimulator     the distance-and-azimuth backbone plus a neural operator
                        on the terrain profile. Tabulated: there is no closed
                        form to hand a browser, so the planner works from a
                        precomputed candidate grid.

The two are what makes the abstraction worth having -- they share nothing except
this interface, and every tool in the repo runs on both.
"""
import numpy as np

from common.schema import SimulatorInfo
from config import SERVING_SITE
from coverage_terrain import (DUAL_BREAK_M, fit_with_terrain, macro_rsrp,
                              rsrp_from_node)
from features import haversine_m, load_sites
from propagation import (CARRIER_HZ, C_LIGHT, K_EARTH, RX_AGL, TX_AGL, DEM,
                         link_features)


def _bearing_rad(tl, to, lat, lon):
    return np.arctan2(
        np.sin(np.radians(lon - to)) * np.cos(np.radians(lat)),
        np.cos(np.radians(tl)) * np.sin(np.radians(lat))
        - np.sin(np.radians(tl)) * np.cos(np.radians(lat))
        * np.cos(np.radians(lon - to)))


class ParametricSimulator:
    """The shipped model of MODEL.md, behind the shared interface."""

    def __init__(self, df, dem=None, pl=None):
        self.df, self.dem = df, dem if dem is not None else DEM()
        self.pl = pl if pl is not None else fit_with_terrain(df)
        self.sigma_db = float(self.pl["sigma"])
        self.info = SimulatorInfo(
            name="terrain-parametric",
            label="Fitted physics (two-slope + P.526)",
            approach="terrain-approach",
            notes=("Two-slope path loss with an azimuth harmonic, ITU-R P.526 "
                   "knife-edge diffraction and first-Fresnel clearance, both "
                   "orthogonalised against log-distance."),
            sigma_db=self.sigma_db, fitted_on_rows=int(self.pl["n"]))

    def macro_rsrp(self, lat, lon):
        return macro_rsrp(self.pl, self.dem, np.asarray(lat), np.asarray(lon))

    def node_rsrp(self, tx_lat, tx_lon, agl_m, eirp_deficit_db, lat, lon):
        lat, lon = np.asarray(lat), np.asarray(lon)
        F = link_features(self.dem, tx_lat, tx_lon, lat, lon, tx_agl=agl_m)
        d = haversine_m(tx_lat, tx_lon, lat, lon)
        return rsrp_from_node(self.pl, d, F["diff_db"], eirp_deficit_db,
                              F["fresnel_frac"])

    def refit(self, train):
        return ParametricSimulator(train, self.dem)

    # ------------------------------------------------------------------ --
    def bundle_prediction(self):
        """The analytic half of a coverage bundle.

        Every coefficient the declared family needs, taken straight from the
        fitted object rather than retyped. That is the point: the planner used
        to carry a hand-copied subset of these and evaluated a different model
        from the optimiser -- optimistic by a mean of 5.95 dB -- because nothing
        checked that the copy was complete. `common.schema.validate` now does.
        """
        pl = self.pl
        return "two_slope_terrain/1", {
            "b0": float(pl["b0"]), "slope": float(pl["slope"]),
            "b_dual": float(pl["b_dual"]), "break_m": float(pl["break_m"]),
            "az": [float(v) for v in pl["az"]],
            "b_diff": float(pl["b_diff"]), "b_fres": float(pl["b_fres"]),
            "orth_diff": [float(v) for v in pl["orth_diff"]],
            "orth_fres": [float(v) for v in pl["orth_fres"]],
            "lambda_m": float(C_LIGHT / CARRIER_HZ),
            "tx_agl_m": float(TX_AGL), "rx_agl_m": float(RX_AGL),
            "k_earth": float(K_EARTH), "sigma_db": self.sigma_db}


class OperatorSimulator:
    """Distance-and-azimuth backbone plus a neural operator on the profile.

    Same division of labour as the parametric model: the macro carries the
    azimuth harmonic because it is sectorised, a new omni node does not, and
    everything terrain comes from the network instead of from the two textbook
    terms. There is no closed form, so this one is TABULATED in a bundle.
    """

    def __init__(self, df, dem=None, arch="fno", epochs=None, verbose=True,
                 rows=None):
        from fno_compare import (EPOCHS, _data, backbone_pred, fit_backbone,
                                 train_operator)
        from profiles import profiles
        self._profiles = profiles
        self._bp = backbone_pred
        self.df = df
        self.dem = dem if dem is not None else DEM()
        self.arch = arch
        self.epochs = EPOCHS if epochs is None else epochs
        D = _data()
        self._D = D
        # `rows` are POSITIONS into the cached profile array, which is built in
        # exactly the row order _data() produces. common.backtest hands back
        # `rows.iloc[tr]`, whose index is those positions, so a fold can be
        # turned back into profiles without recomputing any terrain.
        idx = np.arange(len(D["y"])) if rows is None else np.asarray(rows)
        self.c = fit_backbone(D["ld"][idx], D["az"][idx], D["y"][idx])
        res = D["y"][idx] - backbone_pred(self.c, D["ld"][idx], D["az"][idx])
        self.net = train_operator(D["Xa"][idx], res, self.epochs, arch=arch)
        self.sigma_db = float((res - self.net(D["Xa"][idx])).std())
        self.sites = load_sites()[0]
        self.info = SimulatorInfo(
            name=f"terrain-{arch}",
            label=f"{arch.upper()} on the terrain profile",
            approach="terrain-approach",
            notes=("Distance and azimuth backbone; the terrain term is a 1-D "
                   f"{arch.upper()} over the 128-point path profile, on a "
                   "unit-length axis so path length cannot leak in."),
            sigma_db=self.sigma_db, fitted_on_rows=int(len(idx)))

    def _terrain_db(self, tx_lat, tx_lon, agl, lat, lon, chunk=20000):
        out = np.empty(len(lat), np.float32)
        for a in range(0, len(lat), chunk):
            b = min(len(lat), a + chunk)
            hb, _, _ = self._profiles(self.dem, tx_lat, tx_lon, lat[a:b],
                                      lon[a:b], tx_agl=agl)
            out[a:b] = self.net(hb[:, None, :].astype(np.float32))
        return out

    def macro_rsrp(self, lat, lon):
        lat, lon = np.asarray(lat, float), np.asarray(lon, float)
        tl, to = self.sites[SERVING_SITE]
        d = haversine_m(tl, to, lat, lon)
        return (self._bp(self.c, np.log10(np.clip(d, 30, None)),
                         _bearing_rad(tl, to, lat, lon))
                + self._terrain_db(tl, to, TX_AGL, lat, lon))

    def node_rsrp(self, tx_lat, tx_lon, agl_m, eirp_deficit_db, lat, lon):
        lat, lon = np.asarray(lat, float), np.asarray(lon, float)
        d = haversine_m(tx_lat, tx_lon, lat, lon)
        ld = np.log10(np.clip(d, 30.0, None))
        dual = np.maximum(0.0, ld - np.log10(DUAL_BREAK_M))
        return (self.c[0] + self.c[1] * ld + self.c[4] * dual - eirp_deficit_db
                + self._terrain_db(tx_lat, tx_lon, agl_m, lat, lon))

    def refit(self, train):
        """Retrain backbone and operator on one fold.

        `common.backtest` passes `rows.iloc[tr]`, and its `rows` are filtered in
        the same order as the cached profiles, so the frame's index IS the set
        of positions to train on. That is asserted rather than trusted: if the
        two ever drift apart, every held-out number would be computed against
        the wrong terrain and still look plausible.

        Each call trains a network, so a full three-split backtest is roughly
        fifteen network fits. `src/fno_compare.py` does the same thing with the
        controls attached and is the place to get publishable numbers.
        """
        idx = np.asarray(train.index)
        n = len(self._D["y"])
        if idx.max() >= n or not np.allclose(
                train.rsrp.to_numpy(), self._D["y"][idx]):
            raise RuntimeError(
                "the fold's rows do not line up with the cached profiles -- "
                "rebuild data/profiles.npz with src/profiles.py, and check the "
                "Testbench row filter still matches fno_compare._data()")
        return OperatorSimulator(self.df, self.dem, self.arch, self.epochs,
                                 rows=idx)


def simulators(df, dem=None, archs=()):
    """Every model this approach offers, keyed by its bundle name."""
    dem = dem if dem is not None else DEM()
    out = {"terrain-parametric": ParametricSimulator(df, dem)}
    for a in archs:
        s = OperatorSimulator(df, dem, arch=a)
        out[s.info.name] = s
    return out
