"""Clip the Iowa PBF to the Challenge-3 scene extent, writing reference-complete OSM XML.

Two streaming passes so we never need a whole-state node-location index:
  pass 1  node ids whose lat/lon fall in the bbox
  pass 2  ways referencing any of those nodes, then relations touching either;
          BackReferenceWriter pulls in every node a written way still needs.
"""
import os
from pathlib import Path

# Paths resolve relative to this script so the tree can be moved or cloned anywhere.
BASE = str(Path(__file__).resolve().parent)
import sys, osmium

W, S, E, N = -93.8950, 41.9200, -93.6250, 42.0500
SRC = f"{BASE}/iowa-latest.osm.pbf"
DST = f"{BASE}/ames.osm"

inside = set()
for n in osmium.FileProcessor(SRC).with_filter(osmium.filter.EntityFilter(osmium.osm.NODE)):
    if W <= n.location.lon <= E and S <= n.location.lat <= N:
        inside.add(n.id)
print(f"pass 1: {len(inside):,} nodes inside extent", flush=True)

kept_ways = set()
nw = nr = 0
with osmium.BackReferenceWriter(DST, ref_src=SRC, overwrite=True) as writer:
    for o in osmium.FileProcessor(SRC):
        if o.is_node():
            if o.id in inside:
                writer.add(o)
        elif o.is_way():
            if any(r.ref in inside for r in o.nodes):
                writer.add(o); kept_ways.add(o.id); nw += 1
        else:
            hit = any((m.type == 'n' and m.ref in inside) or
                      (m.type == 'w' and m.ref in kept_ways) for m in o.members)
            if hit:
                writer.add(o); nr += 1
print(f"pass 2: {nw:,} ways, {nr:,} relations written", flush=True)
