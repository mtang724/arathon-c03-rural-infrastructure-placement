# Experiment log

Auto-generated from `scene/experiments.jsonl` by `scene/summarize_experiments.py`.
Parameters and provenance: [`PARAMETERS.md`](PARAMETERS.md). Narrative: [`REPORT.md`](REPORT.md).

All metrics are on held-out 2 km checkerboard blocks; the `offset` calibration constant is
fitted on the complementary blocks only, so nothing here is in-sample.

**Compare within a block, not down the whole table.** Runs tagged `ground-*`, `tilt-*` and
`curv-*` use an identical 800-row subsample (seed 0), so they are *paired* and their
ordering is meaningful — but their absolute level is ~1.2 dB pessimistic. The same
configuration scores **9.77 dB on 800 rows and 8.58 dB on all rows** (`tilt-0` vs
`full-sample`). Quote absolute numbers from full-sample runs only.

| tag | terrain | ground | h (m) | tilt° | diffr | link | RMSE dB | r | bias dB | offset dB | n test |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `baseline` | Terrain | medium_dry_ground | 30 | 0 | off | 0.83 | **10.24** | 0.736 | +0.84 | 25.8 | 192 |
| `ground-very_dry_ground` | Terrain | very_dry_ground | 30 | 0 | off | 0.84 | **9.68** | 0.770 | +1.32 | 25.6 | 367 |
| `ground-medium_dry_ground` | Terrain | medium_dry_ground | 30 | 0 | off | 0.84 | **9.77** | 0.769 | +1.62 | 26.0 | 367 |
| `ground-wet_ground` | Terrain | wet_ground | 30 | 0 | off | 0.84 | **9.81** | 0.768 | +1.69 | 26.0 | 367 |
| `tilt-0` | Terrain | medium_dry_ground | 30 | 0 | off | 0.84 | **9.77** | 0.769 | +1.62 | 26.0 | 367 |
| `tilt-2` | Terrain | medium_dry_ground | 30 | 2 | off | 0.84 | **9.86** | 0.769 | +1.76 | 26.0 | 367 |
| `tilt-4` | Terrain | medium_dry_ground | 30 | 4 | off | 0.84 | **9.94** | 0.769 | +1.90 | 26.0 | 367 |
| `tilt-6` | Terrain | medium_dry_ground | 30 | 6 | off | 0.84 | **10.04** | 0.769 | +2.03 | 26.0 | 367 |
| `tilt-8` | Terrain | medium_dry_ground | 30 | 8 | off | 0.84 | **10.13** | 0.769 | +2.15 | 26.1 | 367 |
| `tilt-10` | Terrain | medium_dry_ground | 30 | 10 | off | 0.84 | **10.23** | 0.769 | +2.28 | 26.2 | 367 |
| `curv-off` | Terrain3DEP_s3_flat | medium_dry_ground | 30 | 0 | off | 0.88 | **9.95** | 0.767 | +1.68 | 26.0 | 377 |
| `curv-k43` | Terrain3DEP_s3_k1p33333 | medium_dry_ground | 30 | 0 | off | 0.87 | **10.02** | 0.766 | +1.90 | 26.3 | 377 |
| `full-sample` | Terrain | medium_dry_ground | 30 | 0 | off | 0.82 | **8.58** | 0.826 | +1.75 | 26.0 | 1762 |
| `full-diff-d5` | Terrain | medium_dry_ground | 30 | 0 | on | 0.83 | **10.46** | 0.777 | +1.63 | 26.6 | 1777 |
| `h15` | Terrain | medium_dry_ground | 15 | 0 | off | 0.70 | **9.87** | 0.830 | +3.72 | 27.3 | 1521 |
| `full-nodiff-d3` | Terrain | medium_dry_ground | 30 | 0 | off | 0.82 | **8.61** | 0.824 | +1.72 | 26.1 | 1761 |
| `h30` | Terrain | medium_dry_ground | 30 | 0 | off | 0.82 | **8.62** | 0.824 | +1.72 | 26.1 | 1761 |
| `full-diff-d3` | Terrain | medium_dry_ground | 30 | 0 | on | 0.83 | **10.34** | 0.781 | +1.65 | 26.6 | 1776 |
| `h45` | Terrain | medium_dry_ground | 45 | 0 | off | 0.88 | **8.66** | 0.817 | +0.08 | 25.2 | 1862 |
| `full-nodiff-d5` | Terrain | medium_dry_ground | 30 | 0 | off | 0.82 | **8.61** | 0.824 | +1.71 | 26.1 | 1761 |
| `h60` | Terrain | medium_dry_ground | 60 | 0 | off | 0.92 | **9.55** | 0.810 | -0.85 | 24.7 | 1947 |
| `full-diffuse` | Terrain | medium_dry_ground | 30 | 0 | off | 0.82 | **8.61** | 0.824 | +1.72 | 26.1 | 1761 |
| `h90` | Terrain | medium_dry_ground | 90 | 0 | off | 0.95 | **11.32** | 0.785 | -2.06 | 24.4 | 2032 |


## Paired rescoring — the numbers above are NOT comparable across rows

Every RMSE above is computed over whichever receivers that configuration happened to link,
so a run that links *more* receivers is graded on a harder set. `analysis/rescore.py`
rescores on the subset linked by **all** runs, with a −140 dBm sensitivity floor. Three
recorded conclusions do not survive it.

**Solver settings (full sample, 3,838 receivers, common subset 3,152):**

| run | own-set RMSE | **common subset** | link rate |
|---|---|---|---|
| `full-nodiff-d3` | 8.61 | **8.61** | 0.821 |
| `full-diff-d3` | 10.34 | **8.64** | 0.827 |
| `full-nodiff-d5` | 8.61 | **8.61** | 0.822 |
| `full-diffuse` | 8.61 | **8.61** | 0.821 |

Diffraction is **neutral (0.03 dB), not harmful**. The 1.73 dB of apparent damage was 23
extra links scored as numeric predictions. `max_depth` 5 and diffuse scattering both change
nothing.

**Antenna height.** Scored on the common subset the sweep is no longer flat, but the answer
depends on whether diffraction is modelled — because raising the antenna is how a
diffraction-free model sheds missing diffraction loss:

| height | RT only, common subset | **RT + profile diffraction, all 1,688 held-out points** |
|---|---|---|
| 15 m | 9.86 | 8.47 |
| **30 m** | 8.60 | **8.10** |
| 45 m | **7.91** | 8.20 |
| 60 m | 8.00 | 8.50 |
| 90 m | 9.35 | 9.12 |

With the physics present, the optimum returns to **30 m** and the de-clustered column agrees
(8.04 dB). The assumed value was right; it now has a reason.

**Best model.** Ray tracer where it finds a path, ITU-R P.526 profile diffraction where it
does not: **held-out 8.08 dB, r 0.85, on 100% of measured points** versus 8.58 dB on 82%
for the shipped baseline. Three fitted parameters, all on training blocks.
