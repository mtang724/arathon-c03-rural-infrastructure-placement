# Two models of one network — a comparison

**ARATHON Challenge 03** · ARA rural COTS RAN testbed, Ames, Iowa

This repository contains two independent predictions of the same radio network, built from
the same 7,144 measurements by different means:

| | [`terrain-approach/`](terrain-approach/) | [`sionna-approach/`](sionna-approach/) |
|---|---|---|
| method | parametric law **fitted to the measurements** | **ray tracing** over a reconstructed scene |
| core | two-slope path loss, azimuth harmonic, P.526 diffraction, Fresnel clearance | Sionna RT over 30 m terrain + Microsoft ML footprints, 12 sectors, + P.526 profile diffraction |
| fitted constants | 7 | 5 |
| runtime | seconds | ~8 GPU-minutes for a candidate pass |
| planner mode | analytic — a pin can be dropped anywhere | tabulated — snaps to a candidate |

Until `common/` existed they could not be compared: each carried its own splits, demand
grid and planner. Everything below runs through **one contract, one testbench, one
planner**, so the numbers mean the same thing.

Reproduce the whole thing with `python run_pipeline.py`.

---

## 1. Accuracy — identical splits, identical buffering, identical metrics

`common/backtest.py`, RSRP in dB. Lower is better; R² is against the test set's own variance.

| split | terrain-parametric | **sionna-hybrid** | what it tests |
|---|---|---|---|
| in sample | **7.35** (R² +0.803) | 7.61 (R² +0.789) | fit, not generalisation |
| random split | **7.33** (R² +0.802) | 7.59 (R² +0.788) | leaks — samples are 22 m apart |
| **KMeans blocks** | 9.59 (R² +0.171) | **7.95** (R² +0.425) | contiguous regions held out |
| **angular wedges** | 9.81 (R² +0.045) | **7.80** (R² +0.525) | a whole bearing sector held out |

**The fitted law wins where it is fitted and loses where it is not.** That is not a
criticism — it is what a fitted law is. The decisive column is the geographically blocked
one, because Challenge 3's deliverable is the 89% of the area nobody drove.

The stability is the clearer signal:

```
terrain-parametric   7.33  ->  9.59  ->  9.81      degrades by 2.5 dB
sionna-hybrid        7.59  ->  7.95  ->  7.80      moves by 0.4 dB
```

Ray tracing barely notices which rows it was shown. Its five constants are also insensitive
to the training set: a 200 m buffer that removes 19% of training rows moves its RMSE by
less than 0.01 dB.

**A caveat that cuts against the ray tracer.** The shared testbench scores against RSRP
reported by the *Agronomy* serving cell, so the full-network variant (12 sectors, four
sites) is graded on a question it was not asked and reads 9.0–10.0 dB. The row above is the
Agronomy-only variant, which is the comparable one. Both are exposed by
`sionna-approach/adapter.py`; reporting only the flattering number would have been the easy
mistake.

---

## 2. Where they agree — and this matters more than the ranking

Three independent convergences, from opposite directions:

**The mechanism.** `terrain-approach` reasoned from the data to ITU-R P.526 knife-edge
diffraction and first-Fresnel clearance against 3DEP with a 4/3-earth bulge.
`sionna-approach` arrived at exactly the same physics from a residual diagnostic — the ray
tracer over-predicted monotonically with predicted diffraction loss (+2.5 / +4.5 / +7.7 dB
across bands). Two routes, one mechanism.

**Asset power.** `terrain-approach`'s menu uses −20 dB for a donor relay and −26 dB for a
small cell. `sionna-approach` derived −19.2 dB (5 W small cell) and −23.1 dB (2 W repeater)
independently, from ARA's published radio and channel bandwidth ([`DEPLOYMENT.md`](sionna-approach/DEPLOYMENT.md)).

**The decision.** Both find that **power dominates and the brief's asset menu cannot close
the hole.** A macro-class site buys an order of magnitude more coverage than a relay. Two
models that disagree about where to build agree about what to build.

---

## 3. Where they disagree — and it changes the recommendation

Same demand grid, same candidates, same objective, `common/bundle.py`:

| asset | terrain-parametric | sionna-hybrid | they differ by |
|---|---|---|---|
| donor relay | 42.00854, −93.81638 · +0.90% | 41.99420, −93.84865 · **+2.61%** | **3.11 km** |
| small cell | 41.99420, −93.84865 · +0.43% | 41.99420, −93.84865 · **+1.12%** | **0.00 km** |
| macro-class | 41.97955, −93.83471 · +23.76% | 41.96514, −93.80032 · **+39.89%** | **3.26 km** |

They pick the *same* small-cell site and sites 3 km apart for the other two. The ray tracer
predicts 1.7–2.9× larger gains throughout.

The surfaces show why: they differ by **more than 5 dB on 22% of grid cells** despite
matching aggregate metrics, and disagree on headline coverage — 63.1% against 57.8% of
cells above −100 dBm. `sionna-approach` is more pessimistic along the river valleys and
more optimistic near the tower and north-east. See
[`sionna-approach/model_comparison.png`](sionna-approach/model_comparison.png).

**"Tied on RMSE" does not mean "either will do."** For a siting decision the disagreement
is the finding, and it is exactly what the brief's robustness requirement is about.

---

## 4. What each is for

**Use `terrain-approach` when** you need an answer in seconds, a closed form the planner can
evaluate at an arbitrary dropped pin, or a model whose every constant can be defended in a
room. It is also the only one that currently ships the full siting stack.

**Use `sionna-approach` when** the question is about somewhere nobody drove — which is the
whole point of Challenge 3. It generalises 1.6–2.0 dB better across geography, it resolves
individual obstructions rather than a fitted average, and it predicts **100% of grid cells**
where ray tracing alone left 44% unmodelled.

That last point is decision-relevant on its own. Read coverage off the ray-traced surface
before the diffraction correction and 90.6% of *modelled* cells exceed −100 dBm; across
*all* cells it is 57.8%. The blank cells were systematically the bad ones.

**Best available estimate:** the simple average of the two, 7.77 dB against 7.97 and 8.05 on
a common row set. Their residuals correlate at +0.888, so there is little independent
information to pool — and a *fitted* blend does worse than the plain mean, because two
collinear predictors overfit two weights.

---

## 5. What neither has done

- **Uplink thresholds exist but are young.** `common/criteria.py` now calibrates
  availability, SINR, uplink and downlink per simulator, which is the brief's preferred
  definition of underserved. The siting numbers above are on availability.
- **The measurement floor is ~3.4 dB** (`sionna-approach/analysis/error_floor.py`), so both
  models leave ~7 dB of genuine shadow fading unexplained. Four independent attempts to fit
  it — empirical antenna patterns, parametric downtilt, per-sector offsets, gradient
  boosting over every per-path feature — all lost to physics on held-out blocks.
- **Uncertainty is not yet in the ranking.** σ and a 300 m residual correlation length are
  fitted and stored; the Monte Carlo that would say whether a recommendation survives them
  is built in `common/` but not yet reported here.
- **Candidate feasibility is partial.** Road proximity and donor links are handled; power
  and land access are not.
- **`sionna-approach`'s negative control fails mildly.** Research Park serves 0 of 7,144
  rows in the data; the model makes it best-server on 5.54% of measured points.

---

## 6. Reproduce

```bash
python run_pipeline.py              # features -> both simulators -> testbench -> planner
```

Outputs `reports/testbench.json`, one bundle per simulator, and `planner.html` carrying
both. `sionna-approach/simcache/` holds ~30 MB of precomputed ray tracing so the GPU work
does not have to be repeated; its README gives the regeneration command and cost for every
file.
