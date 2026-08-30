# Data-driven rural infrastructure placement

**ARATHON CHALLENGE 03** · AgWireless '26 / Rural Connectivity Research

> Where would one additional relay, repeater, small cell, or measurement campaign
> deliver the greatest improvement?

A van drove roughly 7% of a rural service area near Ames, Iowa and recorded 7,144
measurements. This repository turns that into a recommendation: predict service where nobody
drove, then choose where one additional asset does the most good — and say honestly how much
that answer depends on what you assumed.

---

## What we found

**Coverage today is 44% of route-km and 37% of area** (service available at least half the
time, across the 178 km² survey box).

**One macro-class site at 41.97955, −93.83471 takes that to 69% and 59%** — 6.8 km
south-west, 37 m mast, on the road network.

**The brief's asset menu cannot solve this.** A donor relay adds 1.4 route-km and a small
cell 0.7, against the macro's 28.6. The fitted law is two-slope — n = 1.80 inside 3 km, 3.35
beyond — so in the far field the 20–26 dB deficit of a relay costs more range than a lower
mast can recover. Saying so is a finding, not a failure to answer.

**Optimising beats the naive baseline the brief names**, in 8 of 8 configurations, by a
median factor of **1.52×**. The brief's suggested baseline — "the single worst measured
point" — is itself decent, landing at the 90th percentile of random placement, which is why
beating it is worth measuring rather than assuming.

**But what you call "service" matters more than which physics you use.** Sweeping 198
combinations of model, asset, criterion, threshold and weighting:

| varying… | median move in the recommended site |
|---|---|
| **criterion** (availability vs uplink) | **4.24 km** |
| asset class | 3.35 km |
| **propagation model** | **2.06 km** |
| threshold | 1.28 km |
| route/area weighting | 1.21 km |

Weeks of propagation modelling narrowed the model term to 2 km. The criterion term is twice
that, and it was *chosen*, not measured.

**And buildability decides among near-equivalent sites.** Requiring grid power within 1 km
moves the recommendation **11.1 km** while costing a quarter of the benefit. Independently,
a 200-draw Monte Carlo reproduces the exact pick in only 10% of draws and needs a **3 km**
radius to reach 99%. Two analyses, one conclusion: **the answer is a neighbourhood, not a
pin.**

---

## Try it

The deliverable is an interactive planner. No build step — open the file.

| | |
|---|---|
| [`planner.html`](planner.html) | four simulators, eight service definitions, three asset classes, live before/after, an optimiser and three sensitivity sweeps |
| [`planner_constrained.html`](planner_constrained.html) | the same, plus five open-data siting constraints and the cost of respecting them — see [CONSTRAINTS.md](CONSTRAINTS.md) |

To rebuild everything from the measurements:

```bash
pip install numpy scipy pandas scikit-learn rasterio   # + torch for pinn-approach
python run_pipeline.py               # features → simulators → testbench → bundles → planner
```

Roughly 3.5 minutes. Approaches whose dependencies are absent are skipped with a message,
and their committed bundles are carried, so a machine without `torch` or a GPU still gets a
complete planner.

---

## The four deliverables

| The brief asks for | Answered in |
|---|---|
| Before/after coverage under explicit service thresholds | The planner's live before/after; [terrain-approach/README.md](terrain-approach/README.md) |
| Robustness to model uncertainty | [`reports/robustness.json`](terrain-approach/reports/robustness.json) — 200-draw Monte Carlo; [`sionna-approach/analysis/uncertainty.py`](sionna-approach/analysis/uncertainty.py) |
| Gains per intervention, and sensitivity to placement constraints | [RECOMMENDATIONS.md](RECOMMENDATIONS.md) — the 198-combination sweep; [CONSTRAINTS.md](CONSTRAINTS.md) — five open-data constraint layers |
| A scenario planner judges can click | [`planner.html`](planner.html), [`planner_constrained.html`](planner_constrained.html) |

---

## Approaches

Four independent models of the same network, each in its own folder, each runnable alone.
All four are in the planner's dropdown.

| Folder | Method | Held out by geography | Verdict |
|---|---|---|---|
| [`sionna-approach/`](sionna-approach/) | Ray tracing (Sionna RT) over reconstructed terrain and building geometry, plus ITU-R P.526 profile diffraction | **7.95 / 7.80 dB** | **Most stable.** Barely notices which rows it was shown — 7.6 → 8.0 dB from in-sample to held-out |
| [`terrain-approach/`](terrain-approach/) | Two-slope path-loss law fitted to the measurements, with P.526 diffraction and Fresnel clearance | 9.66 / 9.78 dB | Wins where it is fitted (7.33 dB), degrades 2.5 dB off it. Ships the siting solver and the planner |
| [`pinn-approach/`](pinn-approach/) | Physics-informed network (ReVeal / ReVeal-MT, DySPAN'25) | 15.83 / 15.09 dB | **Last on geography.** Best in sample (5.63 dB). Kept for the diagnosis, not the accuracy |
| `terrain-fno` (in [`terrain-approach/`](terrain-approach/)) | Fourier neural operator on the terrain profile | 13.13 / 11.66 dB | **Indistinguishable from its own shuffled control** (13.16 / 11.67), and from the backbone with terrain deleted (13.11 / 11.55). The operator extracts nothing from the profile |

**The pattern is the result, and the controls are what make it readable.** A 128-point
terrain profile is very nearly a unique location fingerprint — its nearest neighbour in
profile space sits a median 12.2 m away on the ground, and 97.2% are within 50 m. So on a
random split a flexible learner reaches the answer by looking up its own training set rather
than learning propagation, which is why the random-split column is uninterpretable for these
two models and why the testbench applies a 200 m training buffer.

The FNO experiment shipped the control that proves it: `fno_residual` scores 13.13 dB on
KMeans blocks, its **shuffled control** — the same model fed profiles paired with the wrong
links — scores 13.16, and the backbone with terrain terms deleted scores 13.11. Three ways
of saying the operator extracted nothing from the terrain.
[NEURAL_OPERATOR.md](terrain-approach/NEURAL_OPERATOR.md) predicted this before running it;
[pinn-approach/README.md](pinn-approach/README.md) diagnoses the same failure independently.

**Read the splits, not the headline.** A random split leaks badly — consecutive samples are
22 m apart. Only the geographically blocked columns speak to the 89% of the area nobody
drove, which is the entire deliverable.

---

## How it fits together

[`common/`](common/) is what makes the approaches comparable rather than merely adjacent:
one simulator contract, one testbench, one planner. `common/` never imports an approach;
approaches import `common` and expose their models through it, so adding one touches no
existing one.

| | |
|---|---|
| [`common/README.md`](common/README.md) | the contract — implement two methods and every tool here works with your model |
| [`common/BACKTEST.md`](common/BACKTEST.md) | identical splits, buffer, seed and metrics for every model |
| [`common/PLANNER.md`](common/PLANNER.md) | every simulator, service definition and weighting, re-solved live |

[`terrain-approach/src/adapter.py`](terrain-approach/src/adapter.py) is the reference
implementation, with one analytic and one tabulated model sharing nothing but the interface.

**Two bundle directories exist, and both are read.** `reports/bundle_<name>.json` is written
by `common/bundle.py`; `bundles/<name>.json` is committed by hand for models whose
dependencies are not installed everywhere. `run_pipeline.py` scans both and dedupes on the
simulator's name. Globbing only the first silently dropped a model from the planner once.

---

## Documentation

**Start here** — [COMPARISON.md](COMPARISON.md), the two headline models on one testbench ·
[RECOMMENDATIONS.md](RECOMMENDATIONS.md), where to build and what it depends on ·
[CONSTRAINTS.md](CONSTRAINTS.md), where an asset can actually go.

| Approach | Documents |
|---|---|
| Ray tracing | [README](sionna-approach/README.md) · [SIMULATION.md](sionna-approach/SIMULATION.md) how the pipeline works · [REPORT.md](sionna-approach/REPORT.md) results · [PARAMETERS.md](sionna-approach/PARAMETERS.md) every parameter with provenance · [RESULTS.md](sionna-approach/RESULTS.md) run log · [RUNNING.md](sionna-approach/RUNNING.md) setup incl. GPU · [DATA_REQUEST.md](sionna-approach/DATA_REQUEST.md) what to ask ARA for |
| Terrain | [README](terrain-approach/README.md) · [MODEL.md](terrain-approach/MODEL.md) · [NEURAL_OPERATOR.md](terrain-approach/NEURAL_OPERATOR.md) |
| PINN | [README](pinn-approach/README.md) |

---

## About the data

`extracted/COTS_Dataset/COTS.csv` — 7,144 UE measurements, 19–20 March 2026, Quectel RG530
on an ARA Ericsson COTS RAN. Twelve columns; four carry most of the value.

| column | verdict | evidence |
|---|---|---|
| `lat`, `lon` | **essential** | position |
| `rsrp` | **essential** | 5.91 bits over 82 levels; best predictor of uplink (ρ 0.78). Every RMSE here is on this |
| `cellid` | **essential** | serving sector — and its *null* state is the Challenge-3 signal |
| `timestamp_local` | **essential** | segments the 4 runs, enables leak-free splits, gives the ~2 dB repeatability floor |
| `uplink` | **high** | the binding constraint |
| `sinr` | **moderate, untapped** | the only way to tell interference-limited from coverage-limited |
| `downlink` | low | saturates; ρ 0.34 — which is what proves uplink binds |
| `ping_ms` | low | ρ −0.02 Spearman with uplink |
| `rsrq` | near-zero | 1.45 bits over 12 levels |
| `band`, `arfcn` | zero as features | single-valued — but `arfcn` decodes to 3.4608 GHz, which is foundational |

### Traps worth not rediscovering

- **42% of rows have no serving cell.** They are a measured *absence* of service, not
  missing data, and they are the locations the challenge exists to fix. A pipeline starting
  with `dropna()` deletes the answer.
- **`sinr` and `rsrq` load as object dtype** — 11 rows contain a literal `'-'`.
- **`cellid = FFFFFFFFF` with `arfcn = -1`** is a no-service sentinel that still carries RSRP.
- **Consecutive samples are ~22 m apart**, so a random split leaks. Split by spatial block or
  by run; the testbench uses a 200 m training buffer.
- **Missing uplink/downlink is not missing-at-random** — it is missing exactly where service
  failed, which biases a service surface optimistic where it matters most.
- **Uplink is the binding constraint.** Downlink saturates near 230 Mbps for any SINR > 0.
  A downlink-based objective declares the network healthy everywhere — it finds 43 bad rows
  in the whole dataset, against 3,023 with no service at all.
- **Only 4 of 12 cells ever serve, and Research Park serves 0 of 7,144 rows** — a free
  negative control for any propagation model.

### The measurement floor is ~2 dB

255 locations were revisited on separate runs with the same serving cell; RSRP agrees to
2.1 dB. Model error is 7.8–9.8 dB, so the gap is **systematic and spatially deterministic**,
not noise — recoverable in principle, though six scene refinements failed to recover it.

---

## Licence

The measurement dataset is **Arathon-only while non-public** and may not be redistributed
before ARA's official release. This repository is private; see the note in `.gitignore` for
what that governs.

Scene geometry derives from **OpenStreetMap (© OpenStreetMap contributors, ODbL)**,
Microsoft US Building Footprints (ODbL), NASA SRTM / Mapzen terrain tiles, and USGS 3DEP
elevation and NAIP imagery (public domain). Attribute these in any published figure.
