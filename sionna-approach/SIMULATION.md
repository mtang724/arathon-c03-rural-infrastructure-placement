# How the Sionna simulation works

**ARATHON Challenge 03** · ARA rural COTS RAN testbed, Ames, Iowa

A complete account of the ray-tracing pipeline: what it computes, why each stage exists,
what is measured versus assumed, and what it costs. Companion documents:
[`DEPLOYMENT.md`](DEPLOYMENT.md) for the published radio specifications,
[`PARAMETERS.md`](PARAMETERS.md) for every constant with provenance,
[`RESULTS.md`](RESULTS.md) for the experiment log, and
[`../COMPARISON.md`](../COMPARISON.md) for how it compares to the fitted approach.

---

## 0. The problem, in one paragraph

A UE drive test recorded 7,144 samples around one base station. That covers about 11% of
the service area. Challenge 3 asks where one additional asset would help most, which
requires knowing service quality in the **other 89%** — where there is no measurement to
interpolate from. A statistical model can only interpolate; a physical model can
extrapolate, because it computes what the terrain does to a radio wave rather than what
the data did near a road. That is the case for ray tracing here, and the reason the
evaluation is always on *geographically disjoint* held-out blocks.

---

## 1. The pipeline at a glance

```
  OpenStreetMap ──┐
  Microsoft ML    ├──► scene (Mitsuba XML + PLY meshes)  ──┐
  3DEP / SRTM   ──┘                                        │
                                                           ▼
  Base_Station_Information.yaml ──► 12 transmitters ──► SIONNA RT (GPU)
                                                           │
                                        path gain G[rx, tx] per sector
                                                           │
  USGS 3DEP DEM ──► terrain profile ──► ITU-R P.526 ──► diffraction loss J
                                                           │
                                                           ▼
                              HYBRID  =  tracer where it found a path
                                         free space − αJ where it did not
                                                           │
                        COTS.csv (train blocks only) ──► 5 fitted constants
                                                           │
                                                           ▼
                                     service surface  (26,055 cells, 100 m)
                                        + σ = 7.5 dB, correlation length 300 m
                                                           │
                    ┌──────────────────────┴──────────────────────┐
                    ▼                                             ▼
        siting matrix G[26055, 140]                  common/ simulator contract
        70 candidates × 2 mast heights               → shared testbench, planner
```

Every stage is reproducible; `simcache/README.md` gives the command and cost for each.

---

## 2. Stage 1 — building the scene

Ray tracing needs geometry. The scene is **22.4 × 14.5 km**, large enough to contain all
7,144 measurements and all four base stations with ~1.7 km of padding.

| layer | source | size |
|---|---|---|
| terrain | SRTM/Mapzen 1 arc-second (~30 m posts) | 457,310 vertices, 455,868 faces |
| buildings | **Microsoft ML footprints** (`ms_buildings_h4.ply`) | ~2,200 in the rural half |
| materials | `itu_medium_dry_ground`, `itu_concrete` | Sionna built-ins |

**Why Microsoft footprints and not OpenStreetMap.** OSM is volunteer-mapped, so rural
coverage is poor: only **6 OSM buildings** exist in the 2 × 2 km box around the serving
site, and 3.6% of the extract lay in the rural half where the measurements are. Microsoft's
ML-extracted footprints raise that to 37 and 2,167. The substitution is worth **0.3 dB**,
roughly twice any other single scene change tested.

**Terrain resolution is not the limit.** USGS 3DEP at 1/3 arc-second (10 m posts, 8.2M
triangles) scores 9.14 dB against the 30 m mesh's 8.99 dB — no gain for 18× the geometry.
The 30 m mesh is used.

### Georeferencing is verified, not assumed

Everything downstream depends on lat/lon → scene-XY being exact. The projection is a
spherical transverse Mercator, `radius = 6378137`, `k = 1`, centred on
41.98499870 N, 93.75999832 W, and it is checked three ways:

- forward/inverse round-trip on the 3,838 known measurement coordinates: **2.4 × 10⁻⁹ m**
- all 7,144 rows fall inside the terrain footprint; all four sites resolve onto the surface
- the model's predicted best-serving sector matches the network's actual serving sector on
  **97.1% of 3,156 points** against 33% chance — a single number that couples projection,
  geometry and antenna azimuth, and that any mirror or rotation would destroy

Constants live in `scene/georef.json`; nothing re-derives them.

---

## 3. Stage 2 — the radio configuration

| quantity | value | provenance |
|---|---|---|
| carrier | 3.4608 GHz, λ = 8.67 cm | measured — NR-ARFCN 630720, single-valued |
| channel | **100 MHz**, 273 PRB, 3,276 subcarriers | published — ARA n77 3.45–3.55 GHz |
| radio | Ericsson AIR 6419, 64T64R, 192 elements/sector | published — arXiv:2408.00913 |
| sites | 4, three sectors each = **12 transmitters** | `Base_Station_Information.yaml` |
| azimuths | 0° / 115° / 240° compass | inferred — each cell-ID suffix wins a clean bearing arc |
| mast | **36.576 m** (120 ft) | external, from `terrain-approach` |
| TX pattern | `tr38901`, **8.0 dB** boresight | measured by integrating over the sphere |
| RX | isotropic, 1.5 m AGL | assumed |

A subtlety worth knowing: **3460.8 MHz is the SSB frequency, not the carrier centre.** A
100 MHz carrier centred there would fall outside ARA's 3.45–3.55 GHz allocation, and
3460.8 = 3000 + 320 × 1.44 sits exactly on the NR SSB sync raster. Immaterial for
propagation, but it is what makes the 3,276-subcarrier count correct.

**Transmit power is not fitted blind.** The traced path gain already contains the
`tr38901` gain, so the calibration constant should equal *per-RE EIRP minus that gain*.
Solving gives a per-RE EIRP of **34.0 dBm**, i.e. a carrier-total SSB EIRP of 69.2 dBm —
9.8 dB below the AIR 6419's rated 79 dBm peak beam, exactly the margin expected between a
broadcast beam and a coherent data beam. This is the only check of the model's **absolute**
scale; everything else is relative. See [`DEPLOYMENT.md`](DEPLOYMENT.md).

---

## 4. Stage 3 — what Sionna actually computes

Sionna RT 2.0.1 on Mitsuba 3.8.0 / Dr.Jit 1.3.1, variant `cuda_ad_mono_polarized`.
`PathSolver` shoots rays from each transmitter and finds propagation paths to each
receiver.

```python
paths = solver(scene, max_depth=3, los=True, specular_reflection=True,
               diffuse_reflection=False, refraction=False,
               diffraction=False, synthetic_array=True)
a, _ = paths.cir(normalize_delays=False, out_type="numpy")
pg = np.sum(np.abs(a) ** 2, axis=(1, 3, 4, 5))       # [n_rx, n_tx] linear path gain
```

`a` is the complex channel impulse response indexed
`[rx, rx_ant, tx, tx_ant, path, time]`; summing |a|² over paths and antennas gives the
linear path gain per receiver–transmitter pair, which is the only quantity used downstream.

### Solver settings, and why

| setting | value | evidence |
|---|---|---|
| `max_depth` | 3 | depth 5 is **identical** (8.61 dB both) — deeper bounces find nothing |
| specular reflection | on | — |
| diffuse reflection | off | **tested: identical** to baseline |
| tracer diffraction | off | **tested: neutral**, 8.64 vs 8.61 dB on a common subset |
| `synthetic_array` | true | single-element arrays |

**`PathSolver` must be chunked.** Cost scales far worse than linearly in receiver count:
800 receivers solve in 15 s on CPU, but a single 15,742-receiver call ran 30 minutes
without finishing. Chunking keeps each solve in the linear regime. `RT_CHUNK` sets the
size — 800 suits CPU, 8000 suits a 48 GB GPU.

### Measured cost on one RTX A6000

| job | size | time |
|---|---|---|
| service surface, 3 sectors | 29,893 rx | 28 s |
| all 12 sectors + every measured row | 34,357 rx × 12 tx | 270 s |
| **siting pass** | 26,055 rx × **140 tx** | **465 s** |

---

## 5. Stage 4 — the diffraction correction, and why it is the main result

### The problem the tracer has

With LOS and specular reflection only, a receiver whose direct path is blocked by terrain
gets either *nothing* or whatever reflected path happens to exist off a distant hillside.
At 3.46 GHz over 10 km with 98 m of relief, rural NLOS is **terrain-diffraction dominated**,
so neither answer is right. The symptoms were measurable:

| | LOS | NLOS |
|---|---|---|
| traced-path rate | 98.9% | **62.4%** |
| bias | −2.62 dB | **+3.77 dB** |
| correlation | 0.761 | **0.416** |

and the bias grew monotonically with how much diffraction loss the physics predicted:
**+2.53 → +4.52 → +7.68 dB** across bands. The tracer over-predicts exactly where terrain
should be attenuating.

### The fix: profile diffraction, not mesh diffraction

Rather than turning on Sionna's UTD edge diffraction — which operates on triangle
boundaries of a faceted DEM — the correction works on the **elevation profile**, which is
what ITM/Longley-Rice and ITU-R P.1812 do. For each transmitter–receiver pair:

1. sample the USGS 3DEP DEM along the great circle, **256 points**
2. add the 4/3-earth curvature bulge, `d₁d₂ / (2 k R)`
3. compute clearance against the first Fresnel ellipsoid,
   `F₁ = √(λ d₁ d₂ / d)` — 14.7 m at the midpoint of a 10 km link here
4. convert to the Fresnel–Kirchhoff parameter `ν = h √(2/λ · (1/d₁ + 1/d₂))`
5. single-edge loss by the ITU-R P.526 approximation
   `J(ν) = 6.9 + 20 log₁₀(√((ν−0.1)² + 1) + ν − 0.1)` for ν > −0.78
6. **Deygout** recursion: principal edge, then one level on each sub-path

This is pure numpy over a raster — thousands of profiles per second, no GPU.

### Combining the two

```
                ⎧ 10·log₁₀(pg_traced) + offset_LOS/NLOS − α·J     where the tracer has a path
  RSRP_pred  =  ⎨
                ⎩ 20·log₁₀(λ/4πd)     + offset_freespace − α'·J    where it does not
```

The second branch is not a fallback. On the points the tracer cannot link at all it scores
**6.86 dB RMSE — better than the traced branch's 8.39** — because a shadowed path is
better described by profile physics than by an arbitrary reflection.

**A control worth knowing:** free space − αJ *alone*, with no ray tracing whatsoever,
scores 8.94 dB against the tracer's 8.61. The tracer still earns its keep — the hybrid
beats profile-physics-only by 0.55 dB — but only in combination.

---

## 6. Stage 5 — calibration: five constants, fitted honestly

| constant | value | meaning |
|---|---|---|
| `los_offset_db` | 28.09 | EIRP + antenna gain, LOS links |
| `nlos_offset_db` | 25.57 | same, NLOS links — 2.5 dB lower, i.e. the tracer over-predicts there |
| `alpha_linked` | 0.639 | weight on Deygout loss for traced links |
| `fs_offset_db` | 24.32 | offset for the free-space branch |
| `alpha_unlinked` | 0.350 | weight on Deygout loss for the free-space branch |

**α < 1 is what physics expects, not a fudge.** Deygout over-predicts loss when several
edges contribute, and ITU-R P.526 applies its own empirical de-rating for exactly that.

### The evaluation protocol

Consecutive drive samples are ~22 m apart, so a random train/test split leaks badly. The
brief requires geographically separated test segments, so points are assigned to a **2 km
checkerboard**; constants are fitted on one colour and every reported metric is computed on
the other. The shared testbench in `common/` adds two harder schemes — contiguous KMeans
blocks and angular wedges — plus a 200 m buffer that drops training rows near any test row.

The five constants are insensitive to which rows they see: **that buffer removes 19% of the
training set and moves RMSE by less than 0.01 dB.** That insensitivity is why the model
transfers.

---

## 7. Stage 6 — the service surface

`analysis/make_surface.py` applies the hybrid to a 100 m grid: **26,055 cells**, each with a
predicted RSRP, a σ, and the terrain features behind it.

| | ray tracer alone | **hybrid** |
|---|---|---|
| cells with a prediction | 60.9% | **100%** |
| held-out RMSE | 8.68 dB | **7.96 dB** |
| correlation | 0.709 | **0.856** |

**The blank cells were systematically the bad ones**, which matters more than the RMSE.
Read coverage off the ray-traced surface and 86.9% of *modelled* cells exceed −100 dBm;
across *all* cells it is **57.0%**. A siting optimiser run on the partial surface would have
been choosing against a map that hid the holes it was meant to fill.

### Uncertainty is a first-class output

- **σ = 7.5 dB, constant.** A heteroscedastic model was fitted and **rejected**: the best
  feature correlates with |residual| at only r = 0.06, and its log-likelihood was worse.
- **Calibrated on held-out blocks:** z sd 1.08, |z| > 2 on 3.4% against a 4.6% target.
- **Correlation length 300 m**, from the variogram of standardised residuals. Errors within
  that range do *not* cancel, so any Monte Carlo must sample correlated fields rather than
  per-cell noise.

That calibration is also the evidence that a heavier generative model is not warranted: a
Gaussian random field with three numbers already produces a well-calibrated ensemble.

---

## 8. Stage 7 — siting: one solve, then arithmetic

The naive reading of "evaluate K candidate sites" is K ray-tracing runs. It is not.
`PathSolver` takes **many transmitters in one solve**, so `analysis/siting.py` places 70
candidates × 2 mast heights = 140 transmitters and solves once against all 26,055 demand
cells, producing

```
G[26055, 140]      path gain, every candidate to every demand cell
J[26055, 70]       diffraction loss on each candidate-to-cell path
```

Everything downstream — ranking candidates, before/after maps, asset-class comparison,
robustness sweeps, an interactive planner — is arithmetic over `G` with **no further ray
tracing**. That is what makes a live demo possible.

**Asset power comes from the link budget, not assumption.** With an isotropic TX pattern the
traced gain carries no antenna gain, so each class needs exactly its per-RE EIRP:

| asset | power, gain, mast | per-RE EIRP | coverage above −100 dBm |
|---|---|---|---|
| — | current network | — | 57.0% |
| relay/repeater | 2 W, 13 dBi, 10 m | 10.9 dBm | 60.6% (+3.6) |
| small cell | 5 W, 13 dBi, 10 m | 14.8 dBm | 63.0% (+6.0) |
| macro-class | 128 W, 18.1 dBi, 36.6 m | 34.0 dBm | **87.4% (+30.3)** |

The macro-class constant reproduces the independently fitted 34.0 dBm — the link budget and
the drive-test calibration agree.

---

## 9. Stage 8 — plugging into the shared platform

`adapter.py` exposes the model behind `common/`'s two-method contract, so the shared
testbench, bundle builder and planner all run on it unchanged.

```python
class SionnaHybridSimulator:
    def macro_rsrp(self, lat, lon): ...        # what the existing network delivers
    def node_rsrp(self, tx_lat, tx_lon, agl_m, eirp_deficit_db, lat, lon): ...
    def refit(self, train): ...                # the five constants, per CV fold
```

**Tabulated, not analytic.** There is no closed form for a ray tracer, so `macro_rsrp` reads
the precomputed 100 m grid and interpolates, using the exact traced value where a query
lands on a measured point. `node_rsrp` *is* analytic — free space minus the same fitted
P.526 loss — because the contract calls it per candidate at arbitrary coordinates and a
scene solve per call would make the planner unusable.

Two variants are exposed. The **full network** (12 sectors) is the siting baseline; the
**Agronomy-only** variant is the one comparable to models that only model the serving site,
since the testbench scores against RSRP from the Agronomy serving cell.

---

## 10. What has been tested and ruled out

Physics that did **not** help, each tested on held-out blocks:

| hypothesis | result |
|---|---|
| finer DEM (10 m 3DEP) | 9.14 vs 8.99 dB — no gain for 18× geometry |
| Sionna UTD diffraction | **neutral** (8.64 vs 8.61) on a common linked subset |
| `max_depth` 5 | identical |
| diffuse scattering | identical |
| ground permittivity | 0.13 dB across the full ITU range |
| earth curvature term | 0.07 dB, wrong direction |
| vegetation | real (+4.5 dB on wooded paths) but only 9.2% of paths → +0.09 dB |

Fitting that did **not** help — this is the more interesting list:

| attempt | result |
|---|---|
| empirical antenna pattern (elevation/azimuth lookup) | **anti-transfers**: 8.61 → 9.41 dB, and the correction correlates *negatively* with the residual it should remove, at every resolution from 2 to 20 bins |
| parametric 3GPP elevation pattern | worse at every beamwidth (8.28 → 9.8–10.8 dB) |
| per-sector offsets | span only 1.6 dB, do not transfer |
| gradient boosting, all per-path features, blocked CV | **8.43 dB vs 7.48 for physics alone** — rejected before touching the test set; reaches 5.3 dB on train and carries none of it across a block boundary |
| heteroscedastic σ | worse log-likelihood than a constant |

**The pattern is the finding.** On this dataset extra model capacity buys training fit and
loses held-out performance. Five parameters of the right mechanism beat every flexible model
tried.

---

## 11. How good is it, and how good could it be?

| | RMSE | note |
|---|---|---|
| **measurement floor** | **3.4 ± 0.5 dB** | two independent estimators, `analysis/error_floor.py` |
| current model, held-out | **7.96 dB** | r 0.856, 100% of cells |
| shared testbench, KMeans blocks | 7.95 dB | vs 9.59 for the fitted approach |
| shared testbench, angular wedges | 7.80 dB | vs 9.81 |

The floor was measured, not assumed: de-clustered cross-run repeat passes give 3.14 dB and
the cross-run variogram nugget 3.63 dB. About 3 dB of it is **positioning**, not the
receiver — stationary re-samples at the same spot give only 0.97 dB — so map-matching the
GPS track to road centrelines would genuinely lower it.

So ~7 dB of the residual is real, spatially-structured shadow fading. It is not measurement
noise, and eleven separate attempts above show it is not reachable by fitting. The correct
response is to **characterise** it (§7) rather than chase it.

---

## 12. Running it

```bash
conda activate sionna                 # sionna-rt 2.0.1, CUDA
cd sionna-approach/scene

# service surface
RT_CHUNK=8000 python predict_surface.py mitsuba/ames_ms.xml 36.576 out.npz 100

# whole network, 12 sectors, every measured row
python ../analysis/predict_all_sites.py mitsuba/ames_ms.xml 36.576 all.npz 100

# hybrid surface + figure
python ../analysis/make_surface.py out.npz surface.npz surface.png

# siting: one pass, then arithmetic
python ../analysis/siting.py surface.npz mitsuba/ames_ms.xml siting 2000
python ../analysis/siting_figure.py surface.npz siting "macro-class" out.png -100

# everything, both approaches, one planner
cd ../.. && python run_pipeline.py
```

`simcache/` holds ~30 MB of precomputed output so none of the GPU work must be repeated;
its README gives the regeneration command and cost per file. Full rebuild ≈ 25 GPU-minutes.

---

## 13. Limitations, stated plainly

- **Antenna is the largest unmodelled object.** The real unit is a 192-element array that
  sweeps a *set* of SSB beams; the model uses one `tr38901` element. Three attempts to fit
  the difference all failed to transfer, so this is a known gap rather than a fixable one
  with this data.
- **Wilson Hall's azimuths are assumed** — 106 samples on one sector cannot determine them.
- **Research Park is a failing negative control.** It serves 0 of 7,144 rows in the data;
  the model makes it best-server on **5.54%** of measured points.
- **Building heights are fitted, not known** — Microsoft footprints carry none.
- **Water bodies and grain bins are excluded.** Metal silos are strong specular scatterers
  at 8.7 cm.
- **One site, one season.** Agronomy serves 3,838 of 4,121 served rows; the campaign is two
  days in March, pre-planting. Nothing here establishes seasonal behaviour.
- **Uncertainty is computed but not yet propagated** into the siting ranking.
