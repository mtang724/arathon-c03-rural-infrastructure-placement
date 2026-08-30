#!/usr/bin/env bash
# Assemble a standalone zip for someone who wants to run simulations without cloning.
# Includes the measurement data, so the result is Arathon-internal: do not publish it.
set -euo pipefail
cd "$(dirname "$0")"
DATA="${COTS_DATA:-../extracted/COTS_Dataset}"
OUT="${1:-sionna-bundle.zip}"
case "$OUT" in /*) ;; *) OUT="$PWD/$OUT";; esac
[ -f "$DATA/COTS.csv" ] || { echo "COTS.csv not found in $DATA — set COTS_DATA"; exit 1; }

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
B="$TMP/sionna-bundle"; mkdir -p "$B/mitsuba/meshes" "$B/data"
cp scene/*.py "$B/"
cp scene/georef.json scene/dem_3dep.tif "$B/"
cp scene/mitsuba/ames.xml "$B/mitsuba/"
cp scene/mitsuba/meshes/Terrain.ply scene/mitsuba/meshes/ames_osm_buildings.ply "$B/mitsuba/meshes/"
cp RUNNING.md "$B/README.md"
cp coverage_validation.png "$B/" 2>/dev/null || true
cp "$DATA/COTS.csv" "$DATA/Base_Station_Information.yaml" "$B/data/"
(cd "$TMP" && zip -qr "$OUT" sionna-bundle)
echo "wrote $OUT ($(du -h "$OUT" | cut -f1))"
