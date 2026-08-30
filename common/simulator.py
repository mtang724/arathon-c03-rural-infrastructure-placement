"""
The simulator contract.

Everything in this repository that predicts radio -- a fitted path-loss law, a
ray tracer, a neural operator -- can be reduced to two questions:

    what does the EXISTING network deliver at this point?
    what would a NEW transmitter deliver at this point?

That is the whole interface. It was not designed up front; it is what
`terrain-approach/src/siting_compare.py` turned out to need in order to run two
completely different models through one siting pipeline, so it is the smallest
thing that is known to be sufficient.

    class MySimulator:
        info = SimulatorInfo(name="my-model", label="My model",
                             approach="my-approach")
        sigma_db = 7.3

        def macro_rsrp(self, lat, lon): ...
        def node_rsrp(self, tx_lat, tx_lon, agl_m, eirp_deficit_db, lat, lon): ...

Implement those, and every tool here works on your model: the backtest harness,
the bundle builder, and the planner.

REFITTING, AND THE MODELS THAT CANNOT.

`refit(train)` is how the backtest harness asks for a copy of your model fitted
on a subset of the measurements. It matters because a model with fitted
constants must be refitted inside every cross-validation fold or the held-out
score is contaminated.

A model with NO fitted constants -- a ray tracer working from a scene and
physics -- has nothing to refit, and should return `self`. That is not a
loophole. The harness records `fitted_on_rows = 0`, reports the model as
unfitted, and notes that no leakage is possible, which is a genuinely stronger
position than a fitted model can claim. What it must not do is quietly refit
nothing while reporting itself as fitted.

UNITS AND CONVENTIONS, so that two models mean the same thing by the same word:

  lat, lon           degrees, WGS84, numpy arrays of equal length
  RSRP               dBm, per demand point, numpy float array
  agl_m              antenna height above GROUND LEVEL at the transmitter, m
  eirp_deficit_db    how many dB BELOW the existing macro this node radiates.
                     Never absolute EIRP -- the macro's EIRP is not observed
                     anywhere in this dataset, so absolute power is not a
                     quantity any model here is entitled to claim.
  sigma_db           standard deviation of YOUR model's residual against the
                     measurements. The robustness analysis draws shadow fading
                     from it, so borrowing another model's sigma would let a
                     worse fit inherit a tighter uncertainty band.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np

from .schema import SimulatorInfo


@runtime_checkable
class Simulator(Protocol):
    """What every model in this repository must look like from outside."""

    info: SimulatorInfo
    sigma_db: float

    def macro_rsrp(self, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
        """RSRP in dBm from the EXISTING serving macro at each point.

        This is the counterfactual baseline: what the network delivers today,
        before anything is built. It must include whatever the existing site
        has that a new node would not -- sector pattern, mast height, power.
        """

    def node_rsrp(self, tx_lat: float, tx_lon: float, agl_m: float,
                  eirp_deficit_db: float, lat: np.ndarray,
                  lon: np.ndarray) -> np.ndarray:
        """RSRP in dBm from a NEW omnidirectional node at (tx_lat, tx_lon).

        Called once per candidate site, so it should be vectorised over the
        demand points rather than over sites.
        """

    def refit(self, train) -> "Simulator":
        """A copy of this model fitted only on `train`, or self if nothing fits.

        `train` is a pandas frame of measurements with the same columns as the
        full set. See the module docstring on unfitted models.
        """


class Unfitted:
    """Mixin for models with no fitted constants. See the module docstring."""

    def refit(self, train):
        return self


def describe(sim) -> str:
    i = sim.info
    how = ("nothing fitted -- physics only" if i.fitted_on_rows == 0
           else f"fitted on {i.fitted_on_rows:,} rows")
    return f"{i.label} [{i.name}] from {i.approach}, {how}, sigma {sim.sigma_db:.2f} dB"


def check(sim, lat, lon) -> None:
    """Fail loudly, here, rather than subtly three stages downstream.

    Every check is something that has gone wrong in this repository or would be
    invisible if it did: shapes that silently broadcast, a model that returns
    linear watts because it forgot to convert, a node that ignores its EIRP
    deficit and makes a relay look like a macro.
    """
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    m = np.asarray(sim.macro_rsrp(lat, lon), float)
    if m.shape != lat.shape:
        raise TypeError(f"{sim.info.name}.macro_rsrp returned {m.shape} for "
                        f"{lat.shape} points")
    if not np.all(np.isfinite(m)):
        raise ValueError(f"{sim.info.name}.macro_rsrp returned non-finite values")
    if m.min() > 0 or m.max() > 0:
        raise ValueError(f"{sim.info.name}.macro_rsrp looks like it is not in "
                         f"dBm (range {m.min():.1f}..{m.max():.1f})")

    a = np.asarray(sim.node_rsrp(lat[0], lon[0], 36.576, 0.0, lat, lon), float)
    b = np.asarray(sim.node_rsrp(lat[0], lon[0], 36.576, 20.0, lat, lon), float)
    if a.shape != lat.shape:
        raise TypeError(f"{sim.info.name}.node_rsrp returned {a.shape} for "
                        f"{lat.shape} points")
    d = np.median(a - b)
    if not np.isclose(d, 20.0, atol=0.5):
        raise ValueError(
            f"{sim.info.name}.node_rsrp ignores eirp_deficit_db: a 20 dB deficit "
            f"moved the median prediction by {d:.2f} dB. A deficit is a constant "
            "offset on the prediction; a relay that radiates like a macro will "
            "sail through siting and be wrong on site.")
    if sim.sigma_db <= 0:
        raise ValueError(f"{sim.info.name}.sigma_db must be positive")


__all__ = ["Simulator", "SimulatorInfo", "Unfitted", "describe", "check"]
