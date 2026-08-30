#!/usr/bin/env bash
# Heavy runs worth doing on a GPU. Every experiment appends a full parameter record to
# experiments.jsonl; regenerate the results table with summarize_experiments.py.
#
#   ./run_gpu.sh            # default sizes
#   N_RX=4000 RT_CHUNK=16000 ./run_gpu.sh
#
# On CUDA do NOT set DRJIT_LIBLLVM_PATH -- Sionna picks cuda_ad_mono_polarized itself.
# Confirm with:  python -c "import mitsuba as mi; print(mi.variant())"
set -u
cd "$(dirname "$0")"
PY="${PYTHON:-python}"
N="${N_RX:-4000}"           # 4000 = every measured row; the 800-row sweeps are ~1.2 dB pessimistic
CHUNK="${RT_CHUNK:-8000}"   # raise until VRAM complains
export RT_CHUNK="$CHUNK"
run() { $PY experiment.py --n-rx "$N" "$@" 2>&1 | grep -v -i warn; }

echo "=== 0. build the building meshes (footprints are committed; meshes are not) ==="
for h in 3 4 5 6 8; do $PY build_ms_buildings.py $h > /dev/null; done
$PY make_terrain_variants.py 3 0 > /dev/null

echo "=== 1. building height, the one parameter that has moved the needle ==="
for h in 3 4 5 6 8; do
  run --tag "gpu-msh$h" --note "MS footprint extrusion height sweep" --buildings "ms_buildings_h$h.ply"
done

echo "=== 2. antenna height, on the improved scene ==="
# NB: compare on a COMMON linked subset -- taller antennas link more marginal far points
for a in 15 20 25 30 40 50; do
  run --tag "gpu-hant$a" --note "antenna height on MS buildings" --buildings ms_buildings_h4.ply --h-ant "$a"
done

echo "=== 3. re-test the six rejected hypotheses at full sample on the better scene ==="
for m in itu_very_dry_ground itu_medium_dry_ground itu_wet_ground; do
  run --tag "gpu-ground-${m#itu_}" --note "ground permittivity, re-test" --buildings ms_buildings_h4.ply --ground "$m"
done
for t in 0 2 4 6; do
  run --tag "gpu-tilt$t" --note "downtilt, re-test" --buildings ms_buildings_h4.ply --downtilt "$t"
done
run --tag "gpu-maxdepth5" --note "deeper ray bounces" --buildings ms_buildings_h4.ply --max-depth 5
run --tag "gpu-diffuse"   --note "diffuse reflection on" --buildings ms_buildings_h4.ply --diffuse

echo "=== 4. high-resolution service surface (the Challenge-3 deliverable) ==="
# 100 m instead of 200 m -> 4x the grid points. 50 m if VRAM allows.
$PY predict_surface.py mitsuba/ames_ms.xml 30 pred_ms_100m.npz 100
$PY make_figure.py pred_ms_100m.npz ../coverage_validation_hires.png

echo "=== done. summarise with: ==="
echo "  $PY summarize_experiments.py ../RESULTS.md"
