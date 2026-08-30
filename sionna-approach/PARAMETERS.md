# Parameter registry

Every quantity the propagation model depends on, with its **provenance** — whether it was
measured from the data, recovered by inference, assumed, fitted, or ruled out by experiment.
The point is that no number in a report should be untraceable.

Machine-readable run log: [`scene/experiments.jsonl`](scene/experiments.jsonl), one JSON
record per run containing the complete parameter set plus results. Regenerate the results
table with `python scene/summarize_experiments.py`.

Provenance keys — **M** measured in the dataset · **I** inferred from the data ·
**A** assumed · **F** fitted · **X** tested and found not to matter ·
**P** published by ARA or the vendor (see [`DEPLOYMENT.md`](DEPLOYMENT.md)).

## Radio

| Parameter | Value | Prov. | Source / evidence |
|---|---|---|---|
| Carrier frequency | 3.4608 GHz | **M** | NR-ARFCN 630720, single-valued across all 7,144 rows. This is the **SSB** position, not the carrier centre — see [`DEPLOYMENT.md`](DEPLOYMENT.md) |
| Channel bandwidth | 100 MHz (273 PRB, 3,276 subcarriers) | **P** | ARA n77 allocation 3.45–3.55 GHz, arXiv:2408.00913 Table 1 |
| Radio unit | Ericsson AIR 6419, 64T64R, 192 elements/sector | **P** | arXiv:2408.00913 §3.1 |
| Wavelength | 8.67 cm | **M** | derived |
| Band | mid-band, single layer | **M** | `band` column is single-valued |
| Serving site | Agronomy Farm | **M** | serves 3,838 of 4,121 served rows |
| Sector azimuths | 0° / 115° / 240° compass | **I** | cell-ID suffix `00B`/`015`/`01F`; each wins a clean contiguous bearing arc, handover boundaries at the predicted bisectors |
| Sector mapping | `00019C00B`→0°, `00019C015`→115°, `00019C01F`→240° | **I** | as above |
| EIRP + antenna gain | ~25–26 dB (absorbed constant) | **F** | fitted per run as `offset`; never fitted on test blocks |
| Per-RE EIRP at boresight | 34.0 dBm (= `offset` + 8.0 dB) | **F/P** | decomposition of the fitted constant; **corroborated** — implies a carrier-total SSB EIRP of 69.2 dBm, 9.8 dB below the AIR 6419's rated 79 dBm peak beam. See [`DEPLOYMENT.md`](DEPLOYMENT.md) |
| Configured TX power | ~128 W per sector | **P?** | ARA new-user training session, unverified. Implies an 18.1 dBi SSB beam gain, ~6 dB below the array's ~24 dBi peak |
| Antenna height AGL | 30 m | **I** | **now identifiable.** Scored on a common receiver set with profile diffraction modelled, RMSE minimises at 30 m (8.10 dB; 15/45/60/90 m give 8.47/8.20/8.50/9.12) and the de-clustered column agrees. Without diffraction the optimum shifts to 45 m — raising the antenna is how the model sheds missing diffraction loss. Not published by ARA. Agronomy and Curtiss are **poles**, Wilson Hall and Research Park **rooftops**, so one height for all four sites is still wrong |
| Mechanical downtilt | 0° | **X** | 0–10° sweep: monotonically *worse*, 9.77 → 10.3 dB. **Now explained**: a 192-element 64T64R sweeps a *set* of SSB beams over elevation, so there is no single boresight to tilt — the model shape is wrong, not the angle. See [`DEPLOYMENT.md`](DEPLOYMENT.md) |
| TX pattern | `tr38901` | **A** | Sionna built-in, 8.0 dB boresight gain (measured by integrating over the sphere). The real unit is a 192-element array, so the SSB *beam set* is the right object to model |
| RX pattern | isotropic | **A** | UE antenna unknown |
| Polarization | V | **A** | not reported by the UE |
| UE height AGL | 1.5 m | **A** | vehicle-mounted |

## Scene geometry

| Parameter | Value | Prov. | Source / evidence |
|---|---|---|---|
| Extent | 41.9200–42.0500 N, −93.8950–−93.6250 E | **A** | contains all 7,144 rows + all four sites, ~1.7 km pad |
| Scene size | 22.4 × 14.5 km | — | derived |
| Projection | spherical transverse Mercator, R = 6378137, k = 1 | **M** | Blosm's own projection; round-trips to 1e-10 m |
| Origin | 41.98499870300293, −93.7599983215332 | **M** | `scene["lat"]`/`["lon"]` after import |
| Height offset | 262 m | **M** | `Terrain["height_offset"]`; terrain z is relative |
| Terrain source | AWS skadi 1 arc-second (~30 m) | **A** | Blosm default |
| Terrain resolution | 30 m posts | **X** | 10 m 3DEP scores 9.14 vs 8.99 dB — **no gain for 18× the geometry** |
| Earth curvature | **not modelled** | **X** | 4/3-earth correction (8.5 m at 12 km): 10.02 vs 9.95 dB — marginally *worse*. Physically right (link rate 0.88→0.87 as distant receivers drop below the horizon) but swamped by 94 m of terrain relief |
| Buildings | 10,357 from Microsoft ML footprints | **M** | OSM has only 6 within 2 km of the site; see below |
| Building height | 4 m uniform | **F** | Microsoft footprints carry no height; 4-6 m fits, 10 m is clearly too tall |
| Vegetation | **excluded** | **X** | real but small — see below |
| Water bodies | excluded | **A** | 172 `natural=water` available, untested |
| Silos / grain bins | excluded | **A** | 29 `man_made=silo` tagged; metal, untested |

## Materials

| Parameter | Value | Prov. | Source / evidence |
|---|---|---|---|
| Terrain | `itu_medium_dry_ground` | **X** | very_dry / medium_dry / wet span only **0.13 dB** (9.68 / 9.77 / 9.81) — soil moisture is not the answer |
| Buildings | `itu_concrete` | **A** | rural farmsteads are really wood and metal; untested |

Sionna has **no vegetation ITU material** (list: marble, concrete, wood, metal, brick,
glass, floorboard, ceiling_board, chipboard, plasterboard, plywood, very_dry_ground,
medium_dry_ground, wet_ground). Note `itu_wood` is dry lumber for walls, **not foliage** —
using it for trees would be badly wrong.

## Solver

| Parameter | Value | Prov. | Source / evidence |
|---|---|---|---|
| `max_depth` | 3 | **X** | **tested:** depth 5 is identical to depth 3 (8.61 dB both, full sample). Deeper bounces find nothing |
| LOS | on | **A** | |
| Specular reflection | on | **A** | |
| Sionna UTD diffraction | off | **X** | **neutral, not harmful — earlier finding retracted.** Full sample on GPU, scored on the common linked subset: 8.64 dB on vs 8.61 dB off. The recorded 1.7 dB of damage was 23 extra links being graded as numeric predictions with no sensitivity floor. Left off only because it costs time and buys nothing; the profile method below is what actually pays |
| Diffuse reflection | off | **X** | **tested:** identical to baseline (8.61 dB). No effect |
| Refraction | off | **A** | untested |
| `synthetic_array` | true | **A** | single-element arrays |
| Receiver chunk size | 800 (`RT_CHUNK`) | **A** | CPU-tuned; 8000 works on an A6000 (29,893 rx in 184 s) |
| **Profile diffraction** | ITU-R P.526 knife-edge, Deygout, 4/3 earth | **F** | **the one correction that transferred.** Held-out 9.09 → 8.08 dB *and* coverage 82% → 100% of measured points, r 0.70 → 0.85. Fitted alpha 0.33–0.86 on the Deygout loss (P.526 de-rates Deygout for multiple edges, so alpha < 1 is expected). `analysis/terrain_features.py`, `analysis/fit_residual.py` |
| Measurement error floor | 3.4 ± 0.5 dB | **M** | two independent estimators, `analysis/error_floor.py`. ~3 dB of it is positioning, not the receiver (stationary re-samples give 0.97 dB) |

## Evaluation protocol

| Parameter | Value | Prov. | Rationale |
|---|---|---|---|
| Split | 2 km checkerboard blocks | **A** | brief requires geographically separated test segments; samples are ~22 m apart so a random split leaks |
| Calibration | `offset` fitted on train blocks only | — | test metrics are genuinely out-of-sample |
| Sample size | 800 rows per run | **A** | speed; worth raising on GPU |
| Seed | 0 | — | same subsample across runs so comparisons are paired |
| Metrics | RMSE, r, bias, MAE on test blocks | — | RMSE is the headline |

**Do not compare RMSE across antenna heights.** A taller antenna links more receivers, and
the extra ones are marginal far-out points that predict badly, so lower heights score better
partly by being graded on an easier subset. Compare on a common linked subset.

## Scene validation against aerial imagery

`scene/verify_orientation.py` runs five independent checks designed to fail loudly on a
flip, mirror or axis swap rather than degrade quietly. All pass:

| check | result |
|---|---|
| Coordinate handedness | east → +x (8272 m per 0.1°), north → +y (11132 m). **PASS** |
| Base-station relative geometry | all six pairwise distances within **0.11%** of great-circle truth |
| Terrain vs an independent DEM read | mean error **+0.04 m**, std 1.16 m, r = 0.9973. N–S flipped would give r = 0.38, E–W flipped r = −0.42 |
| Measured sector bearings (data only) | `015` at 116.6° (assumed 115), `01F` at 233.9° (assumed 240) |
| **Predicted best server vs measured serving cell** | **97.1% agreement** over 3,156 points against 33% chance |

The last is the strongest: it couples geometry, projection and antenna azimuth in one
number, and any mirror or rotation would drive it toward chance.

Two caveats it surfaced:

- **A 0.11% scale inflation.** Blosm's projection uses the WGS84 semi-major axis
  (6,378,137 m) as a spherical radius, while true distances use the mean radius
  (6,371,000 m). Every scene distance is therefore 0.112% long — 13 m over 12 km.
  Negligible for RF, but it is a systematic bias, not noise.
- **Sector `00019C00B`'s azimuth is uncertain.** Its measured bearings have a circular mean
  of 317°, not the assumed 0°. With only 170 samples, one-sided coverage of the arc cannot
  be distinguished from a genuinely different azimuth. The model still agrees with the
  network on 86.5% of those points, versus 100% and 96.7% for the other two sectors.

## OSM building coverage is the weak input, not the terrain

Verified against USGS NAIP imagery (`scene/verify_vs_aerial.py`, figure
`scene_validation.png`):

- **6 OSM buildings exist in the 2×2 km box around Agronomy Farm.** The imagery shows
  dozens of large agricultural sheds, grain bins and the ISU research complex.
- **365 of 10,063 buildings (3.6%) sit in the rural western half** of the extract; 96.4%
  are in Ames and on the ISU campus to the east — where almost no measurements were taken.
- Whether those six land on real roofs **cannot be determined** — six polygons, 93% of the
  masked pixels belonging to one dark-roofed school, give no alignment signal either way.
  An earlier claim here that they "land squarely on real roofs" was eyeballed and is
  withdrawn.

Buildings are therefore close to absent along the measured rural route.

### Fixed with Microsoft ML footprints — and it is the only thing that has helped

Microsoft's US Building Footprints are extracted from imagery rather than contributed by
volunteers, so rural coverage does not depend on mapper attention.

| source | 2x2 km box | rural half | whole extract |
|---|---|---|---|
| OpenStreetMap | 6 | 365 | 10,063 |
| **Microsoft ML** | **37** | **2,167** | 10,357 |

Held out on the full sample, this is the **largest single improvement measured so far** —
roughly twice any other change tried:

| buildings | RMSE | r | link rate |
|---|---|---|---|
| OSM (baseline) | 8.58 dB | 0.826 | 0.82 |
| **Microsoft, 4 m** | **8.29 dB** | **0.832** | 0.80 |
| Microsoft, 6 m | 8.32 dB | 0.831 | 0.79 |
| Microsoft, 10 m | 9.32 dB | 0.787 | 0.77 |

**Alignment measured, not eyeballed** (`scene/check_alignment.py`). Cross-correlating the
footprints against imagery contrast over a shift grid gives a sharp peak for the Microsoft
set at **+2 m East, 0 m North**:

| E-W shift (m) | -10 | -6 | -2 | 0 | +2 | +6 | +10 |
|---|---|---|---|---|---|---|---|
| contrast (grey levels) | 1.3 | 2.5 | 5.5 | 8.1 | **10.2** | 5.9 | 3.8 |

Collapsing to background by +/-10 m means this is a genuine peak, not a plateau. A 2 m
residual is an order of magnitude below the terrain post spacing (23-31 m), smaller than the
uncertainty on the fitted building height, and shifts shadowing geometry by under 0.1 deg at
1-12 km. **It does not hurt.**

This also re-validates the pipeline more strongly than the earlier eyeball did: the
Microsoft footprints pass through the identical projection and mesh-export chain, so a 2 m
alignment is independent confirmation that projection and export are correct.

The same test on OpenStreetMap gives a flat profile (2.3-2.9 across +/-10 m) with no peak,
but with six polygons dominated by one low-contrast building that is an inconclusive sample,
not evidence of error.

Two caveats. **Link rate falls** from 0.82 to 0.80 as extra buildings occlude more paths, so
the test sets differ slightly (1,762 vs 1,718 points) and the comparison is not perfectly
paired. And **height is a free parameter** — the footprints carry none. 4-6 m fits best,
which is plausible for single-storey rural buildings, but 10 m is clearly too tall, so this
is fitted rather than known. Regenerate with `build_ms_buildings.py <height>`.

## What has been ruled out

Six hypotheses for the ~9 dB residual, tested and rejected. Full run log in
[`RESULTS.md`](RESULTS.md) and `scene/experiments.jsonl`.

1. **Terrain resolution** — 10 m DEM: no gain (9.14 vs 8.99 dB).
2. ~~**Diffraction** — actively harmful~~ **RETRACTED.** Neutral (8.64 vs 8.61 dB) once
   scored on a common linked subset. The apparent harm was a scoring defect, and adding
   diffraction *as profile physics* is the single biggest improvement found so far.
3. **Soil moisture / ground permittivity** — 0.13 dB across the full range
   (very_dry 9.68 / medium_dry 9.77 / wet 9.81).
4. **Mechanical downtilt** — monotonically harmful, 9.77 dB at 0° to 10.23 dB at 10°.
   Whatever the real sectors do, adding tilt to this model only makes it worse.
5. **Earth curvature** — 0.07 dB, wrong direction.
6. **Vegetation** — real, dose-responsive, but tiny in aggregate. Model over-predicts by
   **+4.5 dB** on paths crossing woodland (clean dose-response: −0.4 dB open → +4.2 dB at
   50–150 m of wooded path → +5.9 dB at 150–300 m). But only **9.2% of paths** cross
   woodland, so a perfect correction buys **+0.09 dB** of overall RMSE.
   The fitted loss, 0.021 dB/m, is ~10× below ITU-R P.833's 0.2–0.3 dB/m for bare
   deciduous — consistent with rays passing *above* the canopy for most of a long path,
   entering it only near the receiver. Reproduce with `scene/veg_diagnostic.py`.

**Vegetation still matters for Challenge 3 even though it barely moves RMSE.** The model
over-predicts precisely in wooded areas, so it will call coverage adequate where it is not —
and those are exactly the locations a placement optimiser should be considering.

## Where the residual probably is

Not in any of the above. **Six independent geometric and material hypotheses each moved the
error by ≲0.15 dB**, which is itself the most informative result in this table. Remaining
candidates, untested:

- ~~**The antenna**~~ — **tested and rejected three ways.** A free-form empirical gain
  table over elevation/azimuth *anti-transfers* across blocks (held-out 8.61 → 9.41 dB,
  and the fitted correction correlates **negatively** with the residual it should remove,
  at every resolution from 2 to 20 bins). A parametric 3GPP elevation pattern is worse at
  every beamwidth tried (8.28 → 9.8–10.8 dB). Per-sector offsets span only 1.6 dB and do
  not transfer. See `analysis/fit_pattern.py`.
- **Gradient boosting over all per-path features** also loses to 3 parameters of physics:
  blocked-CV RMSE 8.43 dB vs 7.48 dB for physics alone, rejected before touching the test
  set. It reaches 5.3 dB on training data and carries none of it across a block boundary.
  See `analysis/fit_ml.py`.
- **Irreducible shadow fading.** Log-normal shadowing in rural environments is typically
  6–10 dB, and the residual is ~8–9 dB. **But the measurement floor has now been measured
  and it is only 3.4 ± 0.5 dB** (`analysis/error_floor.py`, [`ACCURACY.md`](ACCURACY.md)
  §A1), leaving ~7.9 dB model-attributable. Shadow fading is spatially structured physics,
  not measurement noise, so "near the floor" is not supported.
  If so, the productive move is to model the *distribution* (predict a mean plus an
  uncertainty band) rather than chase the mean — which is also what Challenge 3 asks for,
  since it wants placement robust to model uncertainty.
