"""
Service definitions -- the one place that answers "what does a cell deliver?"

This module exists because of a finding, not because of tidiness.  The pipeline
originally scored every cell on EXPECTED uplink, (1 - P(outage)) x mean uplink.
Re-running the same optimisation under percentile definitions showed that:

  * route demand meeting 10 Mbps is 94.8% (p90), 51.4% (mean), 29.6% (p50),
    9.1% (p10) -- the same network, the same model, only the statistic changed;
  * the recommended site moves up to 2.6 km, and reverses direction: a
    reliability target pulls the asset INWARD, an average target pushes it out;
  * 90.3% of route passes are unavailable more than 10% of the time, which pins
    their p10 throughput to zero however fast they are when connected.

A number that swings 10x on a choice nobody wrote down is not a result, it is a
hidden assumption.  So the criterion became a parameter, every criterion is
evaluated on every run, and the recommendation now has to survive all of them.

Two families live here:

  THROUGHPUT criteria  -- mean / p50 / p10 / p05 / p90 of experienced uplink,
                          measured against a Mbps target.
  AVAILABILITY         -- P(the cell has service at all), measured against a
                          fraction-of-time target.  Added because the finding
                          above says availability, not speed, is what fails.
"""
from dataclasses import dataclass
from typing import Callable

import numpy as np

from config import (AVAILABILITY_TARGET, DEFAULT_THRESHOLD, QUANTILE_LEVELS,
                    RSRP_GRID_MAX, RSRP_GRID_MIN)

RSRP_GRID = np.arange(RSRP_GRID_MIN, RSRP_GRID_MAX + 1.0, 1.0)


@dataclass
class Criterion:
    name: str
    label: str
    fn: Callable            # rsrp array -> service value per cell
    threshold: float
    unit: str
    blurb: str


# ==========================================================================
# Conditional distribution of uplink given RSRP
# ==========================================================================

def conditional_quantiles(df, qs=QUANTILE_LEVELS, bw=6.0):
    """Empirical quantiles of uplink at each RSRP, by sliding window.

    A local window rather than a parametric quantile regression: the shape is
    visibly non-linear and 2,979 measured points is enough to read the quantiles
    off directly.  Each series is then made non-decreasing, for the same reason
    the mean curve is isotonic -- more received power cannot mean less throughput.
    """
    d = df[df["uplink"].notna() & df["rsrp"].notna()]
    r, u = d["rsrp"].to_numpy(), d["uplink"].to_numpy()
    out = {q: [] for q in qs}
    out["mean"] = []
    for x in RSRP_GRID:
        m = np.abs(r - x) <= bw
        sel = u[m] if m.sum() >= 25 else u[np.argsort(np.abs(r - x))[:40]]
        for q in qs:
            out[q].append(float(np.quantile(sel, q)))
        out["mean"].append(float(sel.mean()))
    return {k: np.maximum.accumulate(np.array(v)) for k, v in out.items()}


def percentile_table(cq, oc, sigma, q, n_shadow=61, n_levels=201):
    """RSRP -> q-th percentile of experienced throughput, as a lookup table.

    The simplification that makes this cheap: outage probability is itself a
    function of predicted RSRP, so the whole experienced distribution -- the
    atom at zero, shadow fading across positions, and conditional scatter at
    fixed RSRP -- depends on nothing but RSRP.  What looks like a per-cell Monte
    Carlo is one 81-row table, built once and interpolated thereafter.

    The mixture has an atom, so it is assembled as an explicit weighted sample:
        weight P(outage)        at 0 Mbps
        weight 1 - P(outage)    spread over shadow x conditional-quantile levels
    """
    z = np.linspace(-3.2, 3.2, n_shadow)
    wz = np.exp(-0.5 * z ** 2); wz /= wz.sum()
    lv = (np.arange(n_levels) + 0.5) / n_levels
    qs = np.array(QUANTILE_LEVELS)
    stack = np.stack([cq[qv] for qv in QUANTILE_LEVELS])

    out = np.empty(len(RSRP_GRID))
    for i, r in enumerate(RSRP_GRID):
        rr = np.clip(r + z * sigma, RSRP_GRID[0], RSRP_GRID[-1])
        idx = np.clip(np.searchsorted(RSRP_GRID, rr), 0, len(RSRP_GRID) - 1)
        vals = np.stack([np.interp(lv, qs, stack[:, j]) for j in idx])
        p_out = float(np.clip(oc.predict([r])[0], 0, 1))
        v = np.concatenate([[0.0], vals.ravel()])
        w = np.concatenate([[p_out], (1 - p_out) * np.repeat(wz[:, None], n_levels, 1).ravel() / n_levels])
        o = np.argsort(v); v, w = v[o], w[o]
        c = np.cumsum(w)
        out[i] = v[np.searchsorted(c, q * c[-1])]
    return np.maximum.accumulate(out)


# ==========================================================================
# The criterion set
# ==========================================================================

def build_criteria(df, pl, iso, oc, threshold=DEFAULT_THRESHOLD):
    """Every service definition the pipeline evaluates, keyed by name."""
    sigma = pl["residual_sd_db"]
    cq = conditional_quantiles(df)
    tables = {q: percentile_table(cq, oc, sigma, q) for q in (0.05, 0.10, 0.50, 0.90)}

    def mean_fn(rs):
        p = np.clip(oc.predict(rs), 0, 1)
        return (1 - p) * np.clip(iso.predict(rs), 0, None)

    def pct_fn(q):
        return lambda rs: np.interp(rs, RSRP_GRID, tables[q])

    def avail_fn(rs):
        return 1.0 - np.clip(oc.predict(rs), 0, 1)

    C = [
        Criterion("mean", "Planning average", mean_fn, threshold, "Mbps",
                  "expected uplink, (1 - P(outage)) x mean rate"),
        Criterion("p50", "Typical attempt", pct_fn(0.50), threshold, "Mbps",
                  "half of attempts do at least this well"),
        Criterion("p10", "90% reliability", pct_fn(0.10), threshold, "Mbps",
                  "nine attempts in ten reach the target"),
        Criterion("p05", "95% reliability", pct_fn(0.05), threshold, "Mbps",
                  "nineteen attempts in twenty reach the target"),
        Criterion("p90", "Best case", pct_fn(0.90), threshold, "Mbps",
                  "the best tenth of attempts"),
        Criterion("availability", "Availability", avail_fn, AVAILABILITY_TARGET, "fraction",
                  "the cell has service at all, this fraction of the time"),
    ]
    return {c.name: c for c in C}, cq, tables


def covered(values, weight, threshold):
    """Demand weight meeting a criterion's threshold."""
    return float((weight * (values >= threshold)).sum())


def availability_passes(rsrp, oc, weight):
    """Expected route passes that get service at all -- the continuous version.

    Reported alongside the thresholded score because it is the number a planner
    can act on: 'this asset restores service to N vehicle-passes that currently
    get nothing', rather than 'N cells crossed an availability line'.
    """
    return float((weight * (1 - np.clip(oc.predict(rsrp), 0, 1))).sum())
