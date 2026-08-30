#!/usr/bin/env bash
# One-factor-at-a-time sweep. Every run appends a full parameter record to
# experiments.jsonl; see PARAMETERS.md for what each knob means and where it came from.
set -u
cd "$(dirname "$0")"
PY="${PYTHON:-python}"
N="${N_RX:-800}"
run() { $PY experiment.py --n-rx "$N" "$@" 2>&1 | grep -v -i warn; }

echo "### A. ground material (terrain and antenna fixed)"
for m in itu_very_dry_ground itu_medium_dry_ground itu_wet_ground; do
  run --tag "ground-${m#itu_}" --note "soil moisture A/B; March thaw suspected" --ground "$m"
done

echo "### B. mechanical downtilt (ground and terrain fixed)"
for t in 0 2 4 6 8 10; do
  run --tag "tilt-${t}" --note "sector downtilt sweep; unmodelled until now" --downtilt "$t"
done

echo "### C. earth curvature (matched 3DEP meshes, 23x31 m posts)"
run --tag "curv-off" --note "flat projected plane, no horizon"      --terrain Terrain3DEP_s3_flat.ply
run --tag "curv-k43" --note "4/3-earth correction, 8.5 m at 12 km"  --terrain Terrain3DEP_s3_k1p33333.ply
