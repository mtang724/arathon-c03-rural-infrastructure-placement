# The backtest testbench

**How to check whether your simulator describes the network that was actually
measured — on the same splits, with the same metrics, as every other model in
this repository.**

If two models are evaluated on different splits they are not being compared,
however carefully each RMSE was computed. That is the entire reason this lives
in `common/` rather than inside one approach.

---

## The 60-second version

```python
import sys; sys.path[:0] = [".", "terrain-approach/src"]
import pandas as pd
from common.backtest import Testbench

df = pd.read_csv("terrain-approach/data/labeled_terrain.csv", dtype={"cellid": str})
tb = Testbench.from_frame(df, serving_site="Agronomy Farm")

report = tb.run({"my-model": my_sim, "terrain-parametric": their_sim},
                out_path="reports/backtest_shared.json")
```

```
simulator                   fit? in_sample random_sp kmeans_on angular_w   agree%   base%
------------------------------------------------------------------------------------------
terrain-parametric           yes      7.35      7.33      9.66      9.78     60.5    63.9

RMSE in dB. Discount the random split — see below. The
geographic splits are the ones that decide anything.
```

Your model needs the two methods in [the contract](README.md#1-the-contract) and
nothing else.

---

## What it asks

Run the simulator **with no added transmitter** and compare it to what the van
recorded. Everything downstream — coverage percentages, siting, the
recommendation — rests on the claim that the model describes the network as it
is today. So that claim gets tested first, separately, and before anything is
built on it.

Two things are measured:

1. **RSRP accuracy.** MAE, RMSE, bias and R², in sample and on three held-out
   schemes.
2. **Service accuracy.** Whether the model gets *service* right, not just
   received power — cell-by-cell agreement and a Brier score, against the base
   rate.

The second is reported because a model can predict power well and still be
useless for planning. In this repository it is the weaker half by a wide margin,
and pretending otherwise would be the easiest way to oversell a result.

---

## The three splits, and why more than one

### `random_split` — report it, then discount it

Consecutive COTS samples are **2.63 s apart**, which is metres apart at driving
speed. A random split therefore tests the model on places it trained on, and the
test set is very nearly the training set.

For a model that consumes any per-location descriptor it is worse than
uninformative. Measured on this dataset: the nearest other link **in terrain
profile space** sits a median of **12.2 m away on the ground**, and 97.2% are
within 50 m. A terrain profile is very nearly a unique identifier of where the
receiver was. So a flexible model fed profiles can answer by looking up its own
training set, score **better than the physics**, and have learned no physics at
all — which is exactly what a 1-D FNO does here.

Keep it in the table as a **contamination gauge**: the gap between it and the
geographic splits is how much your model is memorising.

### `kmeans_on_position` — the harshest

Compact regions. One of them is the near-tower cluster, so holding it out
deletes every sample under ~2 km and forces the distance law to extrapolate
*inward*. Only 8.2% of test points fall inside the training distance range. It
will make a sound model look broken, and that is the point — it measures
extrapolation.

### `angular_wedges` — the fairer one

Bearing sectors. Every wedge spans the full distance range, so distance support
survives; what is held out is a bearing sector, which tests the antenna-pattern
term instead.

**The gap between these two is a finding about this survey's radial geometry,
not about any model.** Report both. Neither is cherry-picked.

### The 200 m buffer

Training rows within 200 m of *any* test row are dropped, so no road segment is
shared across a split. The radius is not arbitrary: 99.6% of profile-space
nearest neighbours lie within 200 m, so this is the distance at which lookup
stops being possible.

---

## Numbers to beat

The fitted physics of [`MODEL.md`](../terrain-approach/MODEL.md), on exactly
these splits:

| Split | MAE | RMSE | R² |
|---|---|---|---|
| In sample | 5.59 dB | 7.35 dB | +0.803 |
| Naive random split | 5.60 dB | 7.33 dB | +0.803 |
| **KMeans blocks** | 7.63 dB | **9.66 dB** | **+0.154** |
| **Angular wedges** | 8.05 dB | 9.78 dB | +0.054 |

Service: **60.5%** cell-by-cell agreement against a **63.9%** base rate, Brier
0.141, on 501 cells with ≥5 samples each.

Beating the KMeans column is the real target. Beating the random split is not an
achievement — see above.

---

## Reading your output

**In-sample much better than held-out.** Normal, and the size of the gap is the
interesting part. If in-sample is 7 dB and KMeans is 20 dB, your model has fitted
the survey rather than the physics.

**Random split much better than held-out geography.** Memorisation. Look at what
per-location information your features carry.

**Held-out R² near zero or negative.** Your model is no better than predicting
the block mean *on that block*. That can still be a real model — the KMeans split
is brutal — but you cannot claim generalisation from it.

**`fitted: no`.** Your `refit` returned `self`. Correct for a ray tracer, wrong
for anything with fitted constants. If you have constants and this says `no`,
your held-out numbers are contaminated and mean nothing.

**Agreement below the base rate.** Your service classifier is worse than
answering "served" every time. Say so; this repository's own model does.

---

## Required columns

`Testbench.from_frame` needs:

| column | |
|---|---|
| `lat`, `lon` | degrees WGS84 |
| `rsrp` | dBm, `NaN` where not measured |
| `dist_m` | metres to the serving site |
| `az_deg` | bearing from the site, degrees from north |
| `outage` **or** `cellid` | `outage` is derived as `cellid.isna() or cellid == "FFFFFFFFF"` |

Optional, and used for extra criteria if present: `uplink`, `downlink`, `sinr`,
`rsrq`, `site`.

**Do not drop rows with missing radio data before handing the frame over.** In
this dataset 2,885 of 7,144 rows (40.4%) report no serving cell. Those are not
missing measurements, they are *measured absences of service* — the exact demand
the challenge asks you to serve. A reflexive `dropna()` deletes every coverage
hole and then reports that coverage is excellent.

---

## Parameters

| | default | |
|---|---|---|
| `N_BLOCKS` | 5 | folds per scheme |
| `BUFFER_M` | 200.0 | training exclusion radius around test rows |
| `RANDOM_SEED` | 42 | KMeans and the random split |
| `min_dist_m` | 30.0 | near-field rows dropped |
| `avail_target` | 0.50 | "has service more often than not" |

**Change none of these when reporting a comparison.** They are shared so that
numbers from different people are commensurable. If you need different settings
for your own investigation, say so explicitly next to the numbers.

---

## Two honest caveats about this harness

**The coverage check evaluates at measured positions, not grid centroids.**
`terrain-approach/src/backtest.py` scores the demand grid's cell centres; this
harness aggregates measurements and scores their mean position, so it does not
depend on any approach's grid builder. Same 501 cells, same base rate (63.87%),
same threshold (−90.05 dBm), and **agreement differs by about 1 pp** (60.5 here,
59.5 there). Neither is wrong; do not mix numbers from the two.

**It does not test the counterfactual.** Every split holds out *measurements of
the existing network*. Nothing here tests whether your model correctly predicts
a transmitter that has never existed, because no such measurement exists. That
is a limit of the data, not of the harness, and it is why the siting comparison
in [PLANNER.md](PLANNER.md) reports **where models disagree** rather than which
one is right.
