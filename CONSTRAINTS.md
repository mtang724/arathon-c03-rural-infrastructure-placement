# Placement constraints

**ARATHON Challenge 03** · sensitivity of the siting recommendation to where an asset can
actually be built

The measurement campaign says where service is poor. It says nothing about where a relay
may legally or practically go, and ARA has not supplied utility or land records (see
[`sionna-approach/DATA_REQUEST.md`](sionna-approach/DATA_REQUEST.md)). Without a feasible
set, the optimiser answers an easier question than the one the brief asks.

[`planner_constrained.html`](planner_constrained.html) adds one. The original
[`planner.html`](planner.html) is untouched.

## The layers

Five open-data proxies, derived from OpenStreetMap and building footprints over the scene
extent. **They are evidence, not permission** — a power tower in OSM implies a distribution
line nearby, not an interconnection agreement.

| layer | proxy | features |
|---|---|---|
| Grid power | `power=tower\|pole\|line\|minor_line\|substation` | 1,057 |
| Land access | any mapped `highway=*` | 81,471 |
| Existing structure | building footprint, silo, mast, tower | 109,018 |
| Backhaul | distance to an existing base station | 4 |
| Water (exclusion) | `natural=water`, riverbank | 4,834 |

How far the 627 candidate sites sit from each:

| layer | p10 | median | p90 |
|---|---|---|---|
| Grid power | 276 m | 1,624 m | 3,957 m |
| Land access | 11 m | 96 m | 499 m |
| Existing structure | 47 m | 230 m | 549 m |
| Backhaul | 2,285 m | 5,453 m | 9,156 m |
| Water | 304 m | 1,262 m | 2,535 m |

## The result: constraints relocate the answer without costing coverage

Sweeping the grid-power requirement, everything else held at default:

| power within | feasible sites | score cost | recommendation moves |
|---|---|---|---|
| 6 km | 312 of 627 | 0.000 | 0 m |
| **1 km** | 134 | **−0.062** | **11.1 km** |
| 500 m | 79 | −0.063 | 9.4 km |
| 300 m | 48 | −0.064 | 9.8 km |
| 150 m | 30 | −0.064 | 9.8 km |

**Requiring grid power within 1 km moves the recommended site 11.1 km while costing 0.062
of a 0.248 gain — a quarter of the benefit, for a completely different location.**

That is the substantive finding. There is no single best place to put a relay; there is a
broad plateau of near-equivalent radio outcomes, and which one you pick is decided by
buildability, not by propagation. It also means a recommendation quoted without its
constraint set is close to meaningless — the model will happily nominate a spot in the
middle of a field 4 km from the nearest pole.

It compounds with the robustness result already in
[`terrain-approach/reports/robustness.json`](terrain-approach/reports/robustness.json),
where the optimiser reproduces its exact pick in only 10% of Monte Carlo draws and needs a
3 km radius to reach 99%. Two independent analyses agree the answer is a *neighbourhood*,
not a pin.

## Honest limits

- **The power layer reads pessimistically.** OSM maps transmission towers well and rural
  distribution poorly; real Iowa section roads carry distribution that is simply not in the
  data. Treat the feasible counts as a lower bound.
- **No land ownership, easement, zoning or environmental screen.** "Land access" is road
  proximity, which is a construction-access proxy, not a legal one.
- **Backhaul is distance to an existing site**, not a fibre map.
- Ways are represented by their vertices, so a distance is to the nearest mapped vertex
  rather than the nearest point on a segment. OSM segments here are short enough that this
  is well inside the honesty of the proxy.

Every one of these is fixed by data ARA can supply; the request is already written.

## Reproducing

```bash
python common/constraints.py                       # inventory the layers
python common/build_planner_constrained.py         # -> planner_constrained.html
```

The builder reads the existing `planner.html`, augments each candidate with its distance to
every layer, and grafts on the panel. It never writes to the original.
