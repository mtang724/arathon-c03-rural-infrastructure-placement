# Simulation plan — from a calibrated twin to a siting decision

**ARATHON Challenge 03.** The twin is built and validated ([`README.md`](README.md),
[`HANDOFF.md`](HANDOFF.md)). What is missing is the thing the challenge actually asks for:

> Where would one additional relay, repeater, small cell, or measurement campaign
> deliver the greatest improvement?

This document is the plan for the simulation work that answers it. It is written against
the brief's four success criteria, which are the acceptance tests for everything below:

| The brief asks for | Where it is delivered |
|---|---|
| Before/after route coverage under **explicit service thresholds** | Phase 5 |
| **Robustness to model uncertainty** | Phase 2 (uncertainty model), Phase 5 (Monte Carlo) |
| **Gains per intervention** and sensitivity to placement constraints | Phase 5 |
| A **scenario planner** where judges place assets and see the change | Phase 6 |
| Geographically separated test segments | already in place — 2 km checkerboard |

## The one design decision that shapes everything

The naive reading of "evaluate K candidate sites" is K ray-tracing runs. It is not.
Sionna's `PathSolver` takes **many transmitters in one solve**, so K candidate sites and
M demand points cost *one* chunked pass and produce a dense path-gain matrix

```
G[m, k]   linear path gain from candidate k to demand point m      (M x K)
G0[m, s]  the same for the four existing sites' sectors            (M x 12)
```

Everything downstream — the facility-location objective, the baselines, the Monte Carlo
robustness sweep, and the interactive scenario planner — is arithmetic over `G` and `G0`.
No ray tracing in the loop. **This is what makes an interactive demo possible**, and it is
why the plan front-loads one expensive pass instead of spreading tracing through the
optimisation.

Corollary: candidate generation must happen *before* the expensive pass, and must be
generous, because adding a candidate afterwards costs another pass.

---

## Should we optimise on top of an 8.6 dB model at all?

> **Decided 2026-08-30: no — accuracy work comes first.** There is schedule room, so
> Phase 1 has been expanded into its own plan, [`ACCURACY.md`](ACCURACY.md), and runs
> before Phase 2. The argument below still stands as the *fallback* justification if the
> gap turns out not to be closable — and `ACCURACY.md` §A1 is designed to find that out
> cheaply, before any effort is committed. Phases 2–7 here are unchanged.


`HANDOFF.md` says close the 9 dB gap first, and for an absolute coverage claim that is
right. But the decision this challenge needs is a **ranking of candidate sites**, and a
ranking is far more tolerant of the error we have, for three reasons:

1. The fitted `offset` (EIRP + antenna gain, ~25 dB) is **common-mode**. It shifts every
   candidate's predicted coverage together and largely cancels in a comparison.
2. Most of the residual is **spatially correlated** — terrain and vegetation errors that
   are a property of the location, not of which transmitter illuminates it. Two candidates
   scored over the same demand points inherit the same errors.
3. The remaining risk is exactly what Phase 5's Monte Carlo is for: if the recommended
   site survives resampling under the measured error model, the recommendation is
   defensible *at the stated uncertainty*, which is what the brief asks for.

So: proceed, but only after Phase 1, which buys accuracy improvements that are cheap and
directly load-bearing for siting — and stop there rather than chasing the residual.

---

## Phase 0 — Bring-up  *(blocker)*

Nothing runs on this machine yet.

- `pip install sionna-rt` — **not installed**.
- `COTS.csv` — **not present anywhere under `/nas-data/mt55`**. Needs to land somewhere
  `COTS_DATA` can point at. Every script finds it via that variable.
- No Blender. This matters only for Phase 1's vegetation work, which the plan routes
  around (see below).

**This box is much better suited to the job than the machine the twin was built on**
(2 × RTX A6000, 48 GB each, both idle; 32 cores; 125 GB RAM). Consequences:

- `DRJIT_LIBLLVM_PATH` is irrelevant — Sionna will pick `cuda_ad_mono_polarized`. Assert
  `mi.variant()` at the top of every run script; a silent CPU fallback is the classic way
  to spend an afternoon.
- `RT_CHUNK` goes to 8000+ and the grid goes to 50–100 m.
- Two GPUs means two independent runs via `CUDA_VISIBLE_DEVICES` — use it to run a
  sweep and a surface concurrently, not to try to shard one solve.

*Exit test:* `predict_surface.py mitsuba/ames.xml 30 pred.npz 100` reproduces the shipped
RMSE 8.6 dB / r 0.82 figure on GPU.

---

## Phase 1 — Twin upgrades the siting decision actually needs

> **Superseded in scope by [`ACCURACY.md`](ACCURACY.md).** Items 1.1–1.3 below are still
> required for siting and remain here; the accuracy-driven work (1.4 vegetation, 1.5
> height, plus diffraction, downtilt and the scoring fixes) is planned in detail there.

Scoped deliberately. Each item is here because the optimisation is wrong without it, not
because it would improve RMSE.

### 1.1 All four sites, not just Agronomy  *(required)*

`predict_surface.py` hard-codes `g["sites"]["Agronomy Farm"]` and filters to its three
sectors. That is fine for calibration and wrong for siting: the "before" surface must be
the coverage the **existing network** provides, or every gap Curtiss and Wilson Hall
already fill will be re-filled by our recommendation.

Generalise to all 12 sectors across 4 sites. Azimuths are known for Agronomy (0/115/240)
and consistent for Curtiss; **Wilson Hall's orientation is unknown** (106 samples, one
sector, 3–9 km) — sweep it and pick the azimuth that best reproduces those 106 rows, or
treat it as omni and record that as an assumption.

### 1.2 Use the no-service rows — the single biggest validation win available

42% of rows (3,023) have no serving cell. They have never been fed to the model. They
convert the twin's weakest presentational point into its strongest claim:

- Today panel (b) greys out 43% of cells because no path was traced, and the README has to
  call that "a known gap, not an absence of coverage."
- Place receivers at the 3,023 no-service locations. If the tracer finds no path (or a
  path below the UE's usable floor) at most of them, while finding paths where service was
  reported, then **grey means no service** — a prediction, validated, not a gap.

This gives a proper **coverage classifier**: fit `P(served | predicted RSRP)` as a logistic
on served-vs-not, on the same blocked split. That is the function Phase 2 needs, and it is
only fittable because the no-service rows exist.

*Report:* confusion matrix and AUC on held-out blocks. This is a headline result.

### 1.3 SINR validation — a second, independent axis

With all 12 sectors in the scene, predicted SINR follows from the same `G0`:

```
SINR_pred = PG_serving / (sum of other sectors' PG + N0)
```

`sinr` is measured in the dataset and has never been checked. RSRP validates the *path
loss*; SINR validates the *sector geometry and azimuths*. If SINR correlates and RSRP
does, the twin is right for the right reasons.

Free negative control: **Research Park serves 0 of 7,144 rows.** A model that gives it
usable best-server coverage anywhere the drive went is wrong regardless of its RMSE.
Make this an assertion in the test, not a paragraph in a README.

### 1.4 Vegetation — the leading residual suspect, without Blender

`import_scene.py` sets `forests = vegetation = False`, and `HANDOFF.md` names Iowa
shelterbelts as the leading explanation for the residual. Blender is not on this box, but
it is not needed: follow the pattern `build_terrain_3dep.py` already establishes and write
the mesh directly.

- Pull `landuse=forest`, `natural=wood`, and tree-row ways from `ames.osm` (`clip_osm.py`
  regenerates it from the Geofabrik PBF).
- Extrude each polygon to ~12 m over the terrain surface, write a PLY, add one `<shape>`
  to the Mitsuba XML with `itu_vegetation`.
- Re-run the calibration. Keep only if held-out RMSE improves.

*Timebox this.* If it does not pay, record it in "what has been ruled out" and move on —
the ranking argument above does not depend on it.

### 1.5 Antenna height, settled honestly

The sweep is flat 15→60 m because RMSE is computed on a different receiver subset per
height. Rescore on the **common linked subset** (points linked at every height), as
`RUNNING.md` §5 already says. Two outcomes, both fine: a height becomes identifiable, or
it does not and we state 30 m as a documented assumption with a sensitivity band from
Phase 5.

---

## Phase 2 — From path gain to a service surface

The brief is explicit that Challenge 3 needs "deployment assumptions and uncertainty
clearly stated". This phase is where the assumptions live, so each one gets a named
constant in one config file, not a magic number in a script.

### 2.1 Demand points and their weights

**Demand must not be limited to where the van drove** — that would optimise for the drive
test rather than for the area. Two weightings, reported side by side:

| Weight | Source | What it represents |
|---|---|---|
| **Route** | OSM `highway=*` length per cell, from `ames.osm` | where anyone could be |
| **Drive density** | kernel density of the 7,144 GPS samples | the campaign's own priorities |

The brief says "population or route coverage"; rural Iowa has no useful population raster
at this scale, so road length is the defensible proxy, with drive density as the
sensitivity case.

### 2.2 The service metric — uplink, not downlink

Non-negotiable and already established: DL saturates ~230 Mbps for any SINR > 0, while UL
tracks RSRP hard (Spearman 0.78) over 8–63 Mbps. A DL objective calls everything fine.

Chain, each link fitted on training blocks only:

```
G  ->  RSRP_pred  ->  P(served)          [1.2, logistic]
                  ->  SINR_pred          [1.3]
                  ->  UL_pred            [isotonic or small GBM on (RSRP, SINR)]
```

**Missing UL is not missing-at-random** — it is missing where service failed. Treat UL as
0 at no-service points rather than dropping the row; dropping is what biases a service
surface optimistic in exactly the places this challenge is about.

*Explicit thresholds*, stated up front so the before/after numbers mean something:

- **Underserved**: `P(served) < 0.5` **or** `UL_pred < 10 Mbps`
- **Well served**: `P(served) > 0.9` **and** `UL_pred >= 25 Mbps`

Report every headline number at both thresholds, and show the sweep.

### 2.3 The uncertainty model — a first-class output

Needed twice over: for Phase 5's robustness test and for Phase 6's measurement-campaign
objective. Per demand point:

- **Residual variance** from the blocked held-out residuals, as a function of the features
  that predict error — distance to nearest measurement, number of traced paths, LOS vs
  reflected, terrain roughness along the path.
- **Spatial correlation.** Fit a variogram on the residuals. The correlation length is what
  decides whether errors cancel between candidates; assuming independence would make the
  robustness test dishonestly optimistic.

Output: a per-cell σ map alongside the mean surface, plus the correlation length.

---

## Phase 3 — Candidates and the one expensive pass

### 3.1 Generate candidates *(must be generous — see the design decision above)*

Feasibility is a modelling choice worth making explicit, because "sensitivity to placement
constraints" is a stated evaluation criterion:

- On or within ~100 m of an OSM road (access and power).
- Not inside a building footprint or a water polygon.
- Prefer existing vertical structures — OSM towers, silos, tall farm buildings — as a
  cheaper-deployment tier.
- **Repeater feasibility is a real constraint, not a footnote.** A repeater needs a donor
  link back to Agronomy. `G0` at each candidate's own location gives that link budget for
  free; candidates failing it can host a small cell (needs backhaul) but not a repeater.
  Reporting which asset type each candidate supports is exactly the "limited, defensible
  intervention" framing the brief opens with.

Two tiers: ~100–200 coarse candidates on a ~1 km grid over the underserved region, then
the top ~10 refined on a 250 m grid with three sectors and an azimuth sweep.

### 3.2 The pass

New script, `siting_matrix.py`, structured like `predict_surface.py`:

- Demand points at 100 m over the scene, terrain-following, +1.5 m.
- Candidates as transmitters, omni at first (sector optimisation is Phase 4's job for the
  shortlist only), at a stated height (30 m mast; 10 m for the structure-mounted tier).
- One chunked solve, `RT_CHUNK=8000`, `max_depth=3`, diffraction off.
- Write `G`, `G0`, demand coordinates, weights, and every assumption constant into one
  `.npz`. This file is the interface to everything downstream.

*Cost note:* solve time scales with `n_tx x n_rx`. 200 candidates × 26k demand points is
roughly 200× the shipped run, so expect hours, not minutes, and stage it: validate the
pipeline at 500 m demand spacing and 20 candidates first. Both GPUs can carry independent
candidate batches. Checkpoint per chunk — `predict_surface.py` already writes `.partNNN`
files, keep that.

---

## Phase 4 — The optimisation

Pure numpy over `G` — seconds, not hours.

**Objective (max-coverage facility location, k = 1):**

```
maximise  sum_m w_m * [ served_after(m) ] - sum_m w_m * [ served_before(m) ]
```

where `served_after` uses best-server over existing sectors *plus* the candidate, and `w_m`
is the route weight. With `G` precomputed, k = 1 is an exhaustive scan; k = 2, 3 is greedy
with a lazy-evaluation exact check — worth reporting because diminishing returns per asset
is a genuinely useful planning result.

**Baselines — the brief's testable hypothesis is a comparison, so run the comparators:**

| Baseline | Why it is in the table |
|---|---|
| **Worst single measured point** | the brief names this as the thing to beat |
| Centroid of the largest outage segment | the obvious human heuristic |
| Maximum distance from any existing site | the naive geometric answer |
| Random feasible candidate (distribution over 1,000 draws) | is the optimiser beating chance? |

Report each on the same held-out demand points under the same thresholds.

---

## Phase 5 — Evaluation and robustness

1. **Before/after** covered route-km and covered demand-weight, at both thresholds,
   reported *only on held-out blocks*.
2. **Gain per intervention** — Δ covered route-km, and the same for k = 2, 3.
3. **Monte Carlo robustness.** Resample the RSRP surface from the Phase 2.3 error model
   *with its spatial correlation*, re-run the optimisation, ~500 draws. Report how often
   the recommended site stays in the top 1 / top 5, and a CI on the gain. **If the
   recommendation is not stable under the model's own uncertainty, that is the finding** —
   report it rather than hiding it.
4. **Sensitivity to constraints** — re-solve with mast height 10/20/30 m, with and without
   the repeater donor-link constraint, road-proximity 100 m vs 500 m. A recommendation that
   flips on a constraint choice needs saying so.
5. **Sensitivity to assumptions** — thresholds, route vs drive-density weighting, antenna
   height from 1.5.

---

## Phase 6 — Alternative objective: where to *measure* next

The brief asks for this explicitly and it is the cheapest strong result in the plan,
because Phase 2.3 already built the uncertainty model.

Choose the drive route that maximally reduces model uncertainty: treat the residual field
as a GP with the fitted variogram, and greedily select road segments maximising integrated
variance reduction, subject to a route budget (say 50 km of driving) and connectivity along
the road graph.

The finding to look for: **the best place to measure is not the best place to build.**
Building goes where demand is underserved; measuring goes where the model is *least sure*,
which is typically far out and off the drive route. Two maps side by side make that point
in one glance, and it is a genuinely useful operational recommendation.

---

## Phase 7 — Demo artifact

The brief asks for "a scenario planner where judges place one or more assets and
immediately see estimated coverage, performance, uncertainty, and route-benefit changes."

Because `G` is precomputed, this is achievable as a **self-contained interactive page**:
the candidate grid, its path-gain columns, and the demand weights ship inside the page;
clicking the map snaps to the nearest candidate and recomputes best-server coverage in
the browser. No server, no ray tracing at demo time.

Panels: before/after coverage map · Δ covered route-km · the uncertainty overlay · the
ranked candidate table with asset type (relay / repeater / small cell) and donor-link
status.

*Licence constraint on the demo:* measured coordinates and values are Arathon-only while
non-public. The planner ships **predicted surfaces and candidate geometry only** — no raw
measurement rows — unless the event confirms otherwise.

---

## Order of work, and what blocks what

```
Phase 0  bring-up                    BLOCKED on the dataset
   |
Phase 1  twin upgrades               1.1 and 1.2 are required; 1.4 is timeboxed
   |
Phase 2  service surface + sigma     the assumptions live here
   |
Phase 3  candidates + the big pass   hours of GPU; stage it small first
   |
   +---> Phase 4  optimisation  ---> Phase 5  evaluation ---+
   |                                                        +--> Phase 7  planner
   +---> Phase 6  measurement objective  ---------------------+
```

Phases 4–7 are cheap once Phase 3's matrix exists. **The schedule risk is concentrated in
Phase 3**, so the pipeline gets validated end-to-end at coarse resolution — 500 m demand
spacing, 20 candidates, a deliberately bad service surface — before the full pass is
launched. An end-to-end coarse result is worth more than a perfect Phase 1.

## Open questions

1. **Where is `COTS.csv`?** Nothing proceeds without it.
2. **Asset type.** Does the recommendation need to distinguish relay / repeater / small
   cell, or is "one new site" enough? The plan assumes distinguishing them, since the
   donor-link constraint is nearly free and it strengthens the framing.
3. **Do we own an approach folder beyond `sionna-approach/`?** The top-level README
   anticipates siblings. If a statistical-surface approach also lands, Phases 3–7 are
   surface-agnostic and could consume either — worth keeping the `.npz` interface clean.
