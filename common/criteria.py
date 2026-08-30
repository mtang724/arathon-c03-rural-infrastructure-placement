"""
Turning predicted RSRP into the thing a planner actually cares about.

A simulator predicts received power. Nobody wants received power. They want to
know whether a cell has service at all, whether the link is clean, whether it
will carry 25 Mbps. Each of those is a monotone map from predicted RSRP to an
outcome, calibrated on the measurements -- and which one you pick changes the
answer, so all of them are built and the planner chooses.

HOW MUCH IT MATTERS. `terrain-approach/src/service.py` measured exactly this on
the flat model: route demand meeting 10 Mbps is 94.8% at p90, 51.4% on the mean,
29.6% at p50 and 9.1% at p10, and the recommended site moves up to 2.6 km AND
REVERSES DIRECTION -- a reliability target pulls the asset inward, an average
target pushes it out. That machinery never made it into the terrain-aware
planner, which shipped availability only. This module puts it back, and makes it
model-agnostic.

THE ONE RULE THAT MAKES THIS SAFE. Every curve is calibrated against the
PREDICTED RSRP OF THE SIMULATOR THAT WILL READ IT. Fitting a curve on one
model's RSRP and reading it with another's is not a subtlety -- it is a bug this
project has already shipped once. `MODEL.md` records it: the availability curve
was calibrated against the non-terrain fit and read with the terrain fit, up to
6.9 dB apart on distance alone, and the simulator claimed 44.6% of measured
route-km had service where the measurements said 68.0%.

WHAT IS CONDITIONED ON WHAT. Availability, SINR and RSRQ are properties of a
place, so they are regressed on the simulator's PREDICTED RSRP there.
Throughput given a working link is a property of the RADIO, not of the place, so
its conditional distribution is measured against OBSERVED RSRP and only then
composed with the model's own outage probability and shadow fading. Mixing those
two up would let a model's prediction error leak into the rate curve and back
out again as skill.
"""
from __future__ import annotations

import numpy as np
from sklearn.isotonic import IsotonicRegression

from .schema import Criterion, rsrp_grid

QUANTILES = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90)


# ==========================================================================
# Building blocks
# ==========================================================================

def _cells(df, grid_m=200.0, lat0=42.0):
    """200 m cell aggregates.

    Curves are fitted on CELLS rather than rows because sampling density is
    wildly uneven -- the cell containing the tower holds 543 samples while
    far-south cells hold one or two -- so a row-level fit is silently weighted
    toward the well-surveyed region. Each cell then carries its sample count as
    a weight, because the population being scored has a sample-weighted
    availability of 0.58 while the unweighted cell mean is 0.38, and fitting the
    wrong one moved the simulated served route-km from 47.7% to 24.7%.
    """
    ma = grid_m / 111_320.0
    mo = grid_m / (111_320.0 * np.cos(np.radians(lat0)))
    g = df.assign(_gy=np.round(df.lat / ma).astype(int),
                  _gx=np.round(df.lon / mo).astype(int))
    agg = g.groupby(["_gy", "_gx"]).agg(
        lat=("lat", "mean"), lon=("lon", "mean"), n=("outage", "size"),
        avail=("outage", lambda s: 1.0 - s.mean()),
        sinr=("sinr", "median"), rsrq=("rsrq", "median")).reset_index()
    return agg


def _isotonic_on_grid(x, y, w, grid):
    iso = IsotonicRegression(increasing=True, out_of_bounds="clip")
    iso.fit(np.asarray(x, float), np.asarray(y, float),
            sample_weight=None if w is None else np.asarray(w, float))
    return np.maximum.accumulate(iso.predict(grid))


def conditional_rate_quantiles(df, col, grid, bw=6.0, min_n=25):
    """Quantiles of a throughput column at each OBSERVED RSRP, by sliding window.

    A local window rather than a parametric quantile regression: the shape is
    visibly non-linear and there is enough data to read the quantiles directly.
    Each series is made non-decreasing afterwards, for the same reason every
    other curve here is -- more received power cannot mean less throughput.
    """
    d = df[df[col].notna() & df.rsrp.notna()]
    if len(d) < 200:
        return None
    r, u = d.rsrp.to_numpy(float), d[col].to_numpy(float)
    out = {q: np.empty(len(grid)) for q in QUANTILES}
    for i, x in enumerate(grid):
        m = np.abs(r - x) <= bw
        sel = u[m] if m.sum() >= min_n else u[np.argsort(np.abs(r - x))[:40]]
        for q in QUANTILES:
            out[q][i] = np.quantile(sel, q)
    return {q: np.maximum.accumulate(v) for q, v in out.items()}


def experienced_quantile(cq, avail, sigma, q, grid, n_shadow=41, n_levels=101):
    """RSRP -> the q-th percentile of throughput a user actually experiences.

    Three things stand between a predicted RSRP and a delivered rate, and all
    three depend on nothing but that RSRP, which is what makes this one table
    instead of a per-cell Monte Carlo:

      * shadow fading moves the true RSRP around the prediction, sigma dB wide;
      * at the true RSRP the link may be down entirely, with probability
        1 - avail(RSRP) -- an ATOM at zero, not a small rate;
      * given it is up, the rate still has a distribution, which is `cq`.

    The atom is why this cannot be done by interpolating a mean curve. With 90%
    of route passes unavailable more than 10% of the time, the p10 of experienced
    throughput is pinned at zero however fast the link is when it works, and a
    mean curve hides that completely.
    """
    z = np.linspace(-3.0, 3.0, n_shadow)
    wz = np.exp(-0.5 * z ** 2)
    wz /= wz.sum()
    lv = (np.arange(n_levels) + 0.5) / n_levels
    qs = np.array(QUANTILES)
    stack = np.stack([cq[qv] for qv in QUANTILES])          # (nq, ngrid)

    out = np.empty(len(grid))
    for i, r in enumerate(grid):
        idx = np.clip(np.searchsorted(grid, np.clip(r + z * sigma, grid[0],
                                                    grid[-1])), 0, len(grid) - 1)
        vals = np.stack([np.interp(lv, qs, stack[:, j]) for j in idx])  # (nz, nl)
        p_up = float(np.clip(avail[i], 0.0, 1.0))
        v = np.concatenate([[0.0], vals.ravel()])
        w = np.concatenate([[1.0 - p_up],
                            p_up * np.repeat(wz[:, None], n_levels, 1).ravel()
                            / n_levels])
        o = np.argsort(v)
        c = np.cumsum(w[o])
        out[i] = v[o][np.searchsorted(c, q * c[-1])]
    return np.maximum.accumulate(out)


# ==========================================================================
# The criterion set
# ==========================================================================

def build(df, sim, verbose=False) -> dict[str, Criterion]:
    """Every service definition, calibrated against `sim`'s own predicted RSRP.

    Returns a dict keyed by criterion name, ready to drop into a bundle. Any
    criterion whose measurement column is absent or too sparse is skipped rather
    than faked -- a planner offering a throughput target it cannot support would
    be worse than one that does not offer it.
    """
    grid = rsrp_grid()
    agg = _cells(df)
    pred = np.asarray(sim.macro_rsrp(agg.lat.to_numpy(), agg.lon.to_numpy()),
                      float)
    out: dict[str, Criterion] = {}

    # ---- availability ---------------------------------------------------
    avail = np.clip(_isotonic_on_grid(pred, agg.avail.to_numpy(),
                                      agg.n.to_numpy(), grid), 0.0, 1.0)
    out["availability"] = Criterion(
        name="availability", label="Availability", unit="fraction",
        blurb="the cell has a serving cell at all, this fraction of the time",
        value=[round(float(v), 5) for v in avail],
        default_threshold=0.50, threshold_min=0.20, threshold_max=0.95,
        threshold_step=0.05)

    # ---- raw received power ---------------------------------------------
    # The identity map. Trivial, and worth carrying: it is the only criterion
    # with no calibration between the model and the decision, so it isolates
    # the propagation model from every curve fitted on top of it.
    out["rsrp"] = Criterion(
        name="rsrp", label="Received power", unit="dBm",
        blurb="predicted RSRP alone, with no availability curve in between",
        value=[round(float(v), 3) for v in grid],
        default_threshold=-100.0, threshold_min=-120.0, threshold_max=-70.0,
        threshold_step=1.0)

    # ---- link quality ---------------------------------------------------
    for col, key, label, unit, lo, hi, dflt in (
            ("sinr", "sinr", "Link quality (SINR)", "dB", -5.0, 25.0, 3.0),
            ("rsrq", "rsrq", "Link quality (RSRQ)", "dB", -20.0, -5.0, -14.0)):
        v = agg[key]
        ok = v.notna().to_numpy()
        if ok.sum() < 50:
            continue
        curve = _isotonic_on_grid(pred[ok], v.to_numpy(float)[ok],
                                  agg.n.to_numpy()[ok], grid)
        out[f"{key}_db"] = Criterion(
            name=f"{key}_db", label=label, unit="dB",
            blurb=f"median measured {key.upper()} for cells at this predicted RSRP",
            value=[round(float(x), 3) for x in curve],
            default_threshold=dflt, threshold_min=lo, threshold_max=hi,
            threshold_step=1.0)

    # ---- throughput -----------------------------------------------------
    for col, side in (("uplink", "Uplink"), ("downlink", "Downlink")):
        cq = conditional_rate_quantiles(df, col, grid)
        if cq is None:
            continue
        for q, tag, human in ((0.50, "p50", "typical attempt"),
                              (0.10, "p10", "nine attempts in ten")):
            curve = experienced_quantile(cq, avail, sim.sigma_db, q, grid)
            hi = float(np.ceil(max(curve.max(), 1.0)))
            out[f"{col}_{tag}_mbps"] = Criterion(
                name=f"{col}_{tag}_mbps", label=f"{side} ({human})", unit="Mbps",
                blurb=(f"{side.lower()} rate reached by {int(q*100)}% of attempts, "
                       "including the time the link is down entirely"),
                value=[round(float(x), 4) for x in curve],
                default_threshold=min(10.0, max(1.0, round(hi * 0.25))),
                threshold_min=1.0, threshold_max=hi, threshold_step=1.0)
            if verbose:
                print(f"[crit] {col}_{tag}: max {curve.max():.1f} Mbps")

    if verbose:
        print(f"[crit] {len(out)} criteria: {', '.join(out)}")
    return out


__all__ = ["build", "conditional_rate_quantiles", "experienced_quantile",
           "QUANTILES"]
