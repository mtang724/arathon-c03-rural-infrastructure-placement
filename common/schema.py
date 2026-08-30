"""
The coverage bundle: one file format every simulator in this repository emits
and every tool in this repository consumes.

WHY THIS EXISTS. The planner used to be wired directly to one approach's fitted
constants, hand-copied into a dictionary. When that approach's model gained a
dual slope, a Fresnel term and two orthogonalisation offsets, the dictionary was
not updated and nothing complained -- the page kept evaluating the old formula
and was optimistic by a mean of 5.95 dB, RMS 8.37 dB, against the very optimiser
it claimed to track. That is larger than the model's own residual sigma.

The fix is not "remember to update the dictionary". It is to make the FORMULA
FAMILY part of the contract and to VALIDATE that a bundle carries every
coefficient that family needs. A bundle that cannot drive its own declared
formula is rejected here, at build time, instead of quietly mispredicting in a
browser.

TWO PREDICTION MODES, because two very different kinds of model have to fit.

  ANALYTIC   The simulator declares a formula family and its coefficients. A
             consumer evaluates that formula live, so a pin can be dropped
             anywhere. Fitted path-loss models work this way.

  TABULATED  The simulator precomputes RSRP from a fixed candidate list to every
             demand cell. A consumer snaps a dropped pin to the nearest
             candidate. This is the only mode available to a model that cannot
             be reduced to a closed form -- a ray tracer, or a neural operator --
             and the snap distance is reported so nobody mistakes the resolution
             they are getting.

THE OBJECTIVE IS PART OF THE BUNDLE, NOT OF THE PLANNER.

Everything a simulator predicts is RSRP. Everything a PLANNER wants to know is
something else: is there service at all, is the link clean enough, will it carry
25 Mbps. Each of those is a monotone map from predicted RSRP to an outcome,
calibrated on the measurements -- so the bundle carries a SET of them and the
consumer picks.

This is not a nicety. `terrain-approach/src/service.py` measured what happens
when the criterion changes: route demand meeting 10 Mbps is 94.8% at p90, 51.4%
on the mean, 29.6% at p50 and 9.1% at p10, and the recommended site moves up to
2.6 km and reverses direction -- a reliability target pulls the asset inward, an
average target pushes it out. A number that swings tenfold on a choice nobody
wrote down is a hidden assumption, not a result. The same applies to the
route/area split, which is why the weights travel in the bundle as defaults
rather than living as constants in one approach's config.
"""
from __future__ import annotations

import base64
import json
import zlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

SCHEMA = "arathon.coverage/1"

# Every criterion curve is carried on this grid. Fixed, and fine, on purpose:
# an early planner exported the availability curve coarsely, inverted it in
# JavaScript at a different resolution from the Python, and disagreed with the
# optimiser by 3% on the service threshold. Same grid on both sides or the two
# will differ, and the difference will be invisible.
RSRP_MIN, RSRP_MAX, RSRP_STEP = -140.0, -30.0, 0.05


def rsrp_grid() -> np.ndarray:
    return np.arange(RSRP_MIN, RSRP_MAX, RSRP_STEP)


# ==========================================================================
# Formula families
# ==========================================================================
#
# A family is a NAME plus the exact set of coefficients needed to evaluate it.
# Adding one here is a deliberate act: every consumer that claims to support the
# family must implement it, and `validate` holds bundles to the list.

FAMILIES: dict[str, tuple[str, ...]] = {
    # terrain-approach/src/coverage_terrain.py :: rsrp_from_node / macro_rsrp
    #   RSRP = b0 + slope*log10(d) + b_dual*max(0, log10(d) - log10(break_m))
    #          + az[0]*cos(phi) + az[1]*sin(phi)             (macro only)
    #          + b_diff*(J(v) - orth_diff[0] - orth_diff[1]*log10(d))
    #          + b_fres*(clip(F, -3, 3) - orth_fres[0] - orth_fres[1]*log10(d))
    #          - eirp_deficit_db
    "two_slope_terrain/1": (
        "b0", "slope", "b_dual", "break_m", "az", "b_diff", "b_fres",
        "orth_diff", "orth_fres", "lambda_m", "tx_agl_m", "rx_agl_m",
        "k_earth", "sigma_db"),
    # A single power law. For smoke tests, and for anyone starting from scratch.
    #   RSRP = b0 + slope*log10(d) - eirp_deficit_db
    "log_distance/1": ("b0", "slope", "sigma_db"),
}


class BundleError(ValueError):
    """A bundle that would mispredict if it were shipped."""


# ==========================================================================
# Pieces
# ==========================================================================

@dataclass
class SimulatorInfo:
    """Who produced this, and what it is entitled to claim."""

    name: str                      # machine key, unique across the repo
    label: str                     # what a human sees in the planner
    approach: str                  # the directory it came from
    version: str = "1"
    notes: str = ""
    sigma_db: float = 0.0          # residual spread, for the fading draws
    fitted_on_rows: int = 0        # 0 means nothing was fitted -- see backtest
    carrier_mhz: float = 3460.8


@dataclass
class DemandGrid:
    """Where service is wanted and how much it is worth. Model independent."""

    grid_m: float
    lat: list[float]
    lon: list[float]
    route_km: list[float]
    area_km2: float                # per cell; the grid is regular
    total_route_km: float
    total_area_km2: float


@dataclass
class Criterion:
    """One monotone map from predicted RSRP to a service outcome.

    `value` is sampled on the shared RSRP grid and must be non-decreasing --
    more received power cannot mean less service, and a consumer inverts the
    curve by scanning it, which is only well defined if it is monotone.

    `direction` is always "increasing" today. It exists so that a future
    criterion which gets WORSE with power (interference-limited load, say) has
    somewhere to declare itself rather than being silently inverted.
    """

    name: str
    label: str
    unit: str                      # "fraction" | "Mbps" | "dBm" | "dB"
    blurb: str
    value: list[float]
    default_threshold: float
    threshold_min: float
    threshold_max: float
    threshold_step: float
    direction: str = "increasing"


@dataclass
class Objective:
    """What counts as served, and what the coverage score is worth.

    The weights are DEFAULTS, not constants. A consumer is expected to let the
    user move them, because the answer moves with them and the brief asks for
    deployment assumptions to be stated rather than buried.
    """

    criteria: dict[str, Criterion]
    default_criterion: str
    rsrp_grid: list[float]
    w_route: float = 0.70
    w_area: float = 0.30


@dataclass
class Prediction:
    """How a consumer turns a proposed transmitter into RSRP per demand cell."""

    mode: str                                     # "analytic" | "tabulated"
    family: str | None = None                     # analytic only
    coefficients: dict[str, Any] = field(default_factory=dict)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    agl_m: list[float] = field(default_factory=list)
    rsrp_q: list[str] = field(default_factory=list)   # one blob per agl_m
    q_scale: float = 0.25
    q_offset: float = -150.0
    terrain: dict[str, Any] | None = None         # optional DEM, analytic mode


# ==========================================================================
# Quantisation, for the tabulated mode
# ==========================================================================

def pack_rsrp(a: np.ndarray, scale: float = 0.25, offset: float = -150.0) -> str:
    """Quantise a candidate x cell RSRP matrix into one compressed blob.

    0.25 dB steps over a 64 dB span: 0.07 dB RMS quantisation error, two orders
    of magnitude below the residual sigma of any model here, against 11.9 MB of
    float32 that nobody wants to open in a browser. Values below the span clip,
    and clipping only ever happens far below any service threshold.
    """
    q = np.clip(np.round((np.asarray(a, np.float64) - offset) / scale), 0, 255)
    return base64.b64encode(
        zlib.compress(q.astype(np.uint8).tobytes(), 6)).decode("ascii")


def unpack_rsrp(blob: str, shape: tuple[int, int], scale: float = 0.25,
                offset: float = -150.0) -> np.ndarray:
    raw = zlib.decompress(base64.b64decode(blob))
    return (np.frombuffer(raw, np.uint8).reshape(shape).astype(np.float32)
            * scale + offset)


# ==========================================================================
# The bundle
# ==========================================================================

@dataclass
class CoverageBundle:
    simulator: SimulatorInfo
    grid: DemandGrid
    objective: Objective
    baseline_rsrp_dbm: list[float]
    prediction: Prediction
    assets: dict[str, dict[str, Any]] = field(default_factory=dict)
    solution: dict[str, Any] = field(default_factory=dict)
    macro: dict[str, float] = field(default_factory=dict)
    schema: str = SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, path: str | Path) -> Path:
        validate(self)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), separators=(",", ":")),
                        encoding="utf-8")
        return path

    @staticmethod
    def load(path: str | Path) -> "CoverageBundle":
        return from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    # ------------------------------------------------------------ helpers --
    def threshold_dbm(self, criterion: str | None = None,
                      target: float | None = None) -> float:
        """The RSRP at which a criterion first reaches its target.

        The one inversion in the whole system. Consumers must implement exactly
        this scan -- first grid point at or above the target -- or they will
        disagree with the optimiser about which cells are served.
        """
        c = self.objective.criteria[criterion or self.objective.default_criterion]
        t = c.default_threshold if target is None else target
        v = np.asarray(c.value)
        ok = np.where(v >= t)[0]
        return float(np.asarray(self.objective.rsrp_grid)[ok[0]]) if len(ok) \
            else float("inf")


def from_dict(d: dict[str, Any]) -> CoverageBundle:
    obj = d["objective"]
    b = CoverageBundle(
        simulator=SimulatorInfo(**d["simulator"]),
        grid=DemandGrid(**d["grid"]),
        objective=Objective(
            criteria={k: Criterion(**v) for k, v in obj["criteria"].items()},
            default_criterion=obj["default_criterion"],
            rsrp_grid=obj["rsrp_grid"],
            w_route=obj.get("w_route", 0.70), w_area=obj.get("w_area", 0.30)),
        baseline_rsrp_dbm=d["baseline_rsrp_dbm"],
        prediction=Prediction(**d["prediction"]),
        assets=d.get("assets", {}),
        solution=d.get("solution", {}),
        macro=d.get("macro", {}),
        schema=d.get("schema", SCHEMA))
    validate(b)
    return b


def validate(b: CoverageBundle) -> None:
    """Refuse a bundle that could not drive its own declared formula.

    Every check corresponds to a way a planner has actually been wrong here, or
    could silently be wrong:

      * a missing coefficient means the consumer substitutes a default and
        evaluates a different model from the one that was fitted;
      * arrays of different lengths mean cells and predictions are paired by
        accident;
      * a criterion that never reaches its target gives an infinite threshold,
        so every cell reads as unserved -- which looks like a bad model rather
        than a bad export;
      * a non-monotone curve cannot be inverted by scanning, which is how every
        consumer inverts it.
    """
    if b.schema != SCHEMA:
        raise BundleError(f"schema {b.schema!r}, expected {SCHEMA!r}")

    n = len(b.grid.lat)
    for nm, arr in (("grid.lon", b.grid.lon), ("grid.route_km", b.grid.route_km),
                    ("baseline_rsrp_dbm", b.baseline_rsrp_dbm)):
        if len(arr) != n:
            raise BundleError(f"{nm} has {len(arr)} entries, grid.lat has {n}")

    o = b.objective
    if o.default_criterion not in o.criteria:
        raise BundleError(f"default_criterion {o.default_criterion!r} is not "
                          f"among {sorted(o.criteria)}")
    if abs(o.w_route + o.w_area - 1.0) > 1e-9:
        raise BundleError("objective weights must sum to 1")
    ng = len(o.rsrp_grid)
    for k, c in o.criteria.items():
        if len(c.value) != ng:
            raise BundleError(f"criterion {k!r} has {len(c.value)} values for "
                              f"{ng} grid points")
        if np.any(np.diff(c.value) < -1e-9):
            raise BundleError(f"criterion {k!r} must be non-decreasing in RSRP; "
                              "consumers invert it by scanning")
        if max(c.value) < c.default_threshold:
            raise BundleError(
                f"criterion {k!r} never reaches its default threshold "
                f"{c.default_threshold} (max {max(c.value):.3g} {c.unit}). Its "
                "threshold would be infinite and every cell would read as "
                "unserved. Check the curve was fitted against THIS simulator's "
                "own predicted RSRP.")

    p = b.prediction
    if p.mode == "analytic":
        if p.family not in FAMILIES:
            raise BundleError(
                f"unknown family {p.family!r}. Known: {sorted(FAMILIES)}. Add it "
                "to FAMILIES here AND implement it in every consumer before "
                "declaring it.")
        missing = [k for k in FAMILIES[p.family] if k not in p.coefficients]
        if missing:
            raise BundleError(
                f"family {p.family!r} needs coefficients {missing} and the "
                "bundle does not carry them. A consumer would substitute a "
                "default and quietly evaluate a different model.")
    elif p.mode == "tabulated":
        if not p.candidates:
            raise BundleError("tabulated mode with no candidates")
        if len(p.rsrp_q) != len(p.agl_m):
            raise BundleError("tabulated mode needs one packed matrix per mast "
                              f"height: {len(p.rsrp_q)} blobs, "
                              f"{len(p.agl_m)} heights")
    else:
        raise BundleError(f"prediction.mode {p.mode!r} must be 'analytic' or "
                          "'tabulated'")

    if b.simulator.sigma_db <= 0:
        raise BundleError("simulator.sigma_db must be positive -- the robustness "
                          "tab draws shadow fading from it")


__all__ = ["SCHEMA", "FAMILIES", "RSRP_MIN", "RSRP_MAX", "RSRP_STEP",
           "rsrp_grid", "BundleError", "SimulatorInfo", "DemandGrid",
           "Criterion", "Objective", "Prediction", "CoverageBundle",
           "from_dict", "validate", "pack_rsrp", "unpack_rsrp"]
