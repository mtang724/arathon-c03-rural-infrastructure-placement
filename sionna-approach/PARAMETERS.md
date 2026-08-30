# Parameter registry

Every quantity the propagation model depends on, with its **provenance** — whether it was
measured from the data, recovered by inference, assumed, fitted, or ruled out by experiment.
The point is that no number in a report should be untraceable.

Machine-readable run log: [`scene/experiments.jsonl`](scene/experiments.jsonl), one JSON
record per run containing the complete parameter set plus results. Regenerate the results
table with `python scene/summarize_experiments.py`.

Provenance keys — **M** measured in the dataset · **I** inferred from the data ·
**A** assumed · **F** fitted · **X** tested and found not to matter.

## Radio

| Parameter | Value | Prov. | Source / evidence |
|---|---|---|---|
| Carrier frequency | 3.4608 GHz | **M** | NR-ARFCN 630720, single-valued across all 7,144 rows |
| Wavelength | 8.67 cm | **M** | derived |
| Band | mid-band, single layer | **M** | `band` column is single-valued |
| Serving site | Agronomy Farm | **M** | serves 3,838 of 4,121 served rows |
| Sector azimuths | 0° / 115° / 240° compass | **I** | cell-ID suffix `00B`/`015`/`01F`; each wins a clean contiguous bearing arc, handover boundaries at the predicted bisectors |
| Sector mapping | `00019C00B`→0°, `00019C015`→115°, `00019C01F`→240° | **I** | as above |
| EIRP + antenna gain | ~25–26 dB (absorbed constant) | **F** | fitted per run as `offset`; never fitted on test blocks |
| Antenna height AGL | 30 m | **A** | **not identifiable** — flat from 15 to 60 m in every configuration |
| Mechanical downtilt | 0° | **X** | 0–10° sweep: monotonically *worse*, 9.77 → 10.3 dB |
| TX pattern | `tr38901` | **A** | Sionna built-in; real sector panel unknown |
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
| Buildings | 10,079 from OSM | **M** | OSM extract |
| Building heights | Blosm defaults | **A** | only 665 of 10,079 carry `building:levels`, 443 carry `height` |
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
| `max_depth` | 3 | **A** | untested against 2 or 5 |
| LOS | on | **A** | |
| Specular reflection | on | **A** | |
| Diffraction | **off** | **X** | on: 11.7 dB (30 m mesh), 10.6 dB (10 m mesh) vs 9.0 dB off. Tessellated DEM offers every triangle boundary as a spurious diffracting edge; hurts less on finer mesh, which is the artifact signature |
| Diffuse reflection | off | **A** | untested |
| Refraction | off | **A** | untested |
| `synthetic_array` | true | **A** | single-element arrays |
| Receiver chunk size | 800 (`RT_CHUNK`) | **A** | CPU-tuned; raise on GPU |

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

## What has been ruled out

Six hypotheses for the ~9 dB residual, tested and rejected. Full run log in
[`RESULTS.md`](RESULTS.md) and `scene/experiments.jsonl`.

1. **Terrain resolution** — 10 m DEM: no gain (9.14 vs 8.99 dB).
2. **Diffraction** — actively harmful on tessellated terrain.
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

- **The antenna** — real sector pattern, electrical tilt and EIRP are all unknown and
  currently absorbed into one scalar. `tr38901` may simply be the wrong pattern.
- **Irreducible shadow fading.** Log-normal shadowing in rural environments is typically
  6–10 dB, and the residual is ~8–9 dB. A deterministic ray tracer over 30 m terrain and
  default building heights may already be near the floor of what this geometry can explain.
  If so, the productive move is to model the *distribution* (predict a mean plus an
  uncertainty band) rather than chase the mean — which is also what Challenge 3 asks for,
  since it wants placement robust to model uncertainty.
