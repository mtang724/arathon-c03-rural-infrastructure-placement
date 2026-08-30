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
