"""
Every tunable assumption in the project lives here, in one file.

The challenge brief says the planning result is only credible "provided deployment
assumptions and uncertainty are clearly stated". Scattering magic numbers through
the code makes that impossible, so every physical and methodological constant is
declared here with the reason it has the value it does.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _find_dataset():
    """Locate COTS.csv. Override with COTS_DATA=/path/to/dir.

    Same convention as sionna-approach/ so both approaches read the dataset from
    wherever it actually lives. It is deliberately not in the repository -- see
    the licence note in the root README.
    """
    import os
    env = os.environ.get("COTS_DATA")
    if env and (Path(env) / "COTS.csv").exists():
        return Path(env)
    here = Path(__file__).resolve().parent
    cands = [here.parent / "data", here.parent.parent / "COTS_Dataset"]
    cands += [p / "extracted" / "COTS_Dataset" for p in here.parents]
    cands += [p / "COTS_Dataset" for p in here.parents]
    for c in cands:
        if (c / "COTS.csv").exists():
            return c
    raise SystemExit("COTS.csv not found. Set COTS_DATA=/path/to/COTS_Dataset")


DATASET = _find_dataset()
DATA = ROOT / "data"
REPORTS = ROOT / "reports"

# --------------------------------------------------------------------------
# Radio / geometry
# --------------------------------------------------------------------------

# NR-ARFCN 630720 -> 3000 + 0.015 * (630720 - 600000) MHz.  Band n78, TDD.
# TDD matters: uplink and downlink use the SAME frequency, so path loss is
# reciprocal.  That is what licenses us to predict UPLINK quality from a
# DOWNLINK measurement (RSRP).  On an FDD band this step would be invalid.
CARRIER_MHZ = 3460.8

# The site that actually serves this campaign.  Curtiss and Wilson appear on
# ~100-180 sporadic samples each and fit with R^2 ~ 0 (see reports/pathloss.json),
# so they are excluded from modelling and reported as incidental.
SERVING_SITE = "Agronomy Farm"

# --------------------------------------------------------------------------
# Asset assumptions.  Stated as EIRP DEFICIT relative to the macro, in dB,
# because that is the only form the data can support: we never observe the
# macro's absolute EIRP, but a new node that is X dB weaker simply shifts the
# fitted RSRP-vs-distance curve down by X dB.  See model.py::predict_rsrp_from.
# --------------------------------------------------------------------------
ASSETS = {
    # Donor-fed repeater: cheap, no backhaul trench, but it can only rebroadcast
    # a signal it can still hear -- hence DONOR_RSRP_MIN.
    "relay": {
        "label": "Donor-fed relay",
        "eirp_deficit_db": 20.0,     # ~43 dBm EIRP vs an assumed ~63 dBm macro
        "needs_donor": True,
        "donor_rsrp_min": -95.0,     # dBm at the relay site; below this there is
                                     # nothing worth repeating
    },
    # Small cell: independent transmitter, needs real backhaul (fibre or fixed
    # wireless), so no donor constraint but a much higher siting cost.
    "smallcell": {
        "label": "Backhauled small cell",
        "eirp_deficit_db": 26.0,     # ~37 dBm EIRP
        "needs_donor": False,
        "donor_rsrp_min": None,
    },
}

# Below this received power we treat the cell as out of service entirely.
# Cross-checked against the data: the 8-13 km distance band has median RSRP
# -100 dBm and 65% of samples reporting no serving cell at all.
RSRP_SERVICE_EDGE_DBM = -108.0

# --------------------------------------------------------------------------
# Grid and demand
# --------------------------------------------------------------------------
# 200 m chosen from the measured sampling density: it yields 931 occupied cells
# at ~7.7 samples each.  100 m gives 1887 cells but many singletons; 500 m
# collapses the structure we are trying to find.
GRID_M = 200

# We only claim knowledge of the corridor we actually drove.  Cells further than
# this from any measurement are not predicted and not shown -- painting the whole
# county would be a fabrication.
CORRIDOR_M = 350

# Service thresholds in Mbps.  25 is the FCC's broadband uplink-adjacent figure;
# 5 and 10 bracket what a field sensor / imagery upload realistically needs.
UPLINK_THRESHOLDS = [5.0, 10.0, 25.0]
DEFAULT_THRESHOLD = 10.0

# --------------------------------------------------------------------------
# Service DEFINITION -- which statistic of the throughput distribution counts.
#
# This is a parameter rather than a constant because measuring it showed the
# answer swings on it: route demand meeting 10 Mbps is 94.8% at p90, 51.4% on
# the mean, 29.6% at p50 and 9.1% at p10, and the recommended site moves up to
# 2.6 km between them.  A choice that large cannot sit unwritten inside a
# helper function.
#
# The headline default is p50 rather than the mean.  IsotonicRegression
# minimises squared error, so the mean curve sits above the median on a
# right-skewed throughput distribution -- reporting it flatters the network.
# p10 is not the default either: with 90% of passes outage-limited it is nearly
# degenerate as an objective.  p50 is the honest middle, and every criterion is
# reported on every run regardless.
HEADLINE_CRITERION = "p50"
CRITERIA_SWEEP = ["p90", "mean", "p50", "p10", "p05", "availability"]

# Availability target: the fraction of time a cell must have service at all.
# 0.9 matches the p10 throughput criterion -- a cell out more than 10% of the
# time has a p10 of zero no matter how fast it is when connected.
AVAILABILITY_TARGET = 0.90

# Grid over which the RSRP -> service lookup tables are built.
RSRP_GRID_MIN, RSRP_GRID_MAX = -125.0, -44.0
QUANTILE_LEVELS = [0.05, 0.10, 0.25, 0.50, 0.75, 0.90]

# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------
# Consecutive samples are 2.63 s apart -- metres apart at driving speed.  A random
# split therefore tests the model on places it already trained on.  We hold out
# whole spatial blocks AND drop any training row within BUFFER_M of a test row.
N_SPATIAL_BLOCKS = 5
BUFFER_M = 200.0
RANDOM_SEED = 42

# --------------------------------------------------------------------------
# Optimisation
# --------------------------------------------------------------------------
CANDIDATE_SPACING_M = 250.0   # candidates snap to the driven route: rural siting
                              # follows roads, right-of-way and existing poles
N_SITES = 3                   # solve for k = 1..3
N_ROBUSTNESS_DRAWS = 200      # re-solve the placement this many times against
                              # samples from the model's own predictive band
