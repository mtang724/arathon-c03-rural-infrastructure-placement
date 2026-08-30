# Simulation cache

Everything expensive this approach has computed, so it never has to be recomputed.
**Not in git** — these are derived from the measurement dataset, which is Arathon-only
while non-public, and several exceed sensible repository sizes. Regeneration commands are
given for every file, so a fresh clone can rebuild the lot.

Total ~30 MB. Wall-clock to regenerate from scratch: ~25 minutes on one RTX A6000.

**What is tracked and what is not.** The expensive artifacts carry no measurement values
or coordinates and ARE in git, so nobody repeats the GPU work: `siting/` (465 GPU-seconds
plus 110 CPU-seconds), `surfaces/surface_h37.npz` and `surface_hybrid.npz`, and
`dem10.npz`. The per-run dumps in `runs/`, the raw pre-hybrid surfaces, and `features/`
carry `meas_lat` / `meas_lon` / `meas_rsrp` — and `all_sites_h37.npz` also carries
`meas_sinr`, `meas_uplink` and `meas_downlink` — so they stay out under the dataset policy
in the root README. They are also the cheapest to rebuild, about 25 s each.

## `surfaces/` — predicted service surfaces on the 100 m grid (26,055 cells)

| file | what | regenerate |
|---|---|---|
| `pred_h30_100m.npz` | OSM buildings, 30 m mast, ray tracer only | `predict_surface.py mitsuba/ames.xml 30 <out> 100` (185 s) |
| `surf_ms.npz` | MS ML buildings, 30 m mast, ray tracer only | `predict_surface.py mitsuba/ames_ms.xml 30 <out> 100` (28 s) |
| `surf_ms_h37.npz` | MS ML buildings, 36.576 m mast | `predict_surface.py mitsuba/ames_ms.xml 36.576 <out> 100` (28 s) |
| `surface_hybrid.npz` | **hybrid surface, 30 m** — mean, sigma, all fitted constants | `analysis/make_surface.py surf_ms.npz <out>` |
| `surface_h37.npz` | **hybrid surface, 36.576 m — the current model** | `analysis/make_surface.py surf_ms_h37.npz <out>` |

`surface_h37.npz` is the interface everything downstream consumes: `rsrp_mean`,
`rsrp_sigma`, `grid_lat`/`grid_lon`, `corr_len_m`, and every fitted constant.

## `runs/` — per-experiment receiver dumps (3,838 measured points, per-sector path gain)

`h15/h30/h45/h60/h90` (height sweep), `full-nodiff-d3`, `full-diff-d3`, `full-nodiff-d5`,
`full-diffuse` (solver sweep), `msbld` (MS buildings), `ms_h37` (MS + 120 ft).

Regenerate any with `scene/experiment.py --tag <t> --n-rx 5000 --dump <out.npz> [flags]`,
~25 s each on GPU. These are what `analysis/rescore.py` needs to compare configurations
on a common linked subset.

## `features/` — per-path terrain features from the 3DEP DEM

`feat_h15..h90.npz`, `feat_ms.npz`, `feat_ms_h37.npz`, `terrain_features.npz`. Deygout
diffraction loss, Fresnel clearance, roughness, LOS flag. CPU-only, ~20 s each:
`analysis/terrain_features.py <run.npz> <out.npz>`. The tower height changes the LOS line,
so these are height-specific.

## `siting/` — the candidate pass (the expensive one)

| file | what |
|---|---|
| `siting_G.npz` | **G[26055, 140]** — path gain from 70 candidate sites x 2 mast heights to every demand cell, plus candidate coordinates |
| `siting_J.npy` | J[26055, 70] — Deygout diffraction loss on each candidate-to-cell path |
| `siting_results.json` | coverage before/after per asset class and threshold |

`siting_G.npz` is 465 s of GPU and `siting_J.npy` ~110 s of CPU. Regenerate both with
`analysis/siting.py <before.npz> mitsuba/ames_ms.xml <prefix> 2000` — it reuses either
cache if present, so deleting one file rebuilds only that one.

**This matrix is the point.** Every siting question — ranking candidates, before/after
maps, asset-class comparison, the Monte Carlo robustness sweep, an interactive planner —
is arithmetic over `G` and needs no further ray tracing.

## `dem10.npz`

`../../terrain-approach/`'s DEM cache, in the format its `propagation.DEM` expects, built
from `scene/dem_3dep.tif` (same 1/3 arc-second data, same grid). Its own `build_dem()`
needs `USGS_13_*.tif` tiles that are not in the repo. Copy to
`terrain-approach/data/dem10.npz` to run that pipeline.
