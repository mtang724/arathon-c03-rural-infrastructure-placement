# Filling a rural coverage map with ray tracing

**ARATHON Challenge 03 — Data-driven rural infrastructure placement**
Technical report · ARA rural COTS RAN testbed, Ames, Iowa

---

## Summary

A UE drive test around the ARA testbed produced 7,144 measurements covering about 11% of
the service area. Challenge 03 asks where one additional relay would help most, which
requires knowing service quality in the other 89%.

We built a geometric digital twin — real terrain and 10,079 OpenStreetMap buildings — and
ray-traced it with Sionna RT. On measurements held out in geographically disjoint blocks the
twin predicts RSRP with **RMSE 8.58 dB, r = 0.83**, and produces a continuous service
surface over the unmeasured area.

The more useful result is negative. **Six independent hypotheses for the residual error
were tested and rejected, each moving RMSE by ≤0.15 dB**: terrain resolution, diffraction,
ground permittivity, antenna downtilt, earth curvature, and vegetation. The residual sits
at 8–9 dB, in the established range of log-normal shadow fading for rural environments
(6–10 dB).

Crucially, that residual is **not** measurement noise. The campaign is repeatable to ~2 dB
(§2.1), so the remaining 8.6 dB is systematic and spatially deterministic — recoverable in
principle, but not by any scene refinement we tried. The evidence points instead at the
transmitter, whose pattern, height, tilt and EIRP are all unknown and currently absorbed
into one fitted scalar. See [`DATA_REQUEST.md`](DATA_REQUEST.md).

![Measured, predicted and held-out validation](coverage_validation.png)

*(a) the drive test, following the Iowa section-road grid. (b) the ray-traced fill.
(c) held-out validation: the calibration constant is fitted only on the complementary
checkerboard of 2 km blocks.*

---

## 1. Method

### 1.1 Scene

A 22.4 × 14.5 km scene containing all 7,144 measurements and all four base stations, with
~1.7 km of padding. Terrain from 1 arc-second elevation tiles (457,310 vertices); buildings
from OpenStreetMap (10,079 footprints, 95,427 faces). Exported to Mitsuba and loaded into
Sionna RT 2.0.1 with ITU radio materials.

Georeferencing was verified rather than assumed: the projection (spherical transverse
Mercator, k = 1, centred on 41.98499870 N, 93.75999832 W) round-trips to 1e-10 m, all 7,144
measurement rows fall inside the terrain footprint, and all four base stations resolve onto
the terrain surface at plausible elevations.

### 1.2 Radio configuration

Carrier 3.4608 GHz (NR-ARFCN 630720, single-valued across the dataset). The serving site,
Agronomy Farm, is a standard three-sector installation: the cell-ID suffixes `00B`/`015`/
`01F` each win a clean contiguous arc of bearings with handover boundaries at the predicted
bisectors, giving azimuths of **0° / 115° / 240°** compass.

Antenna height, tilt, pattern and EIRP are not in the dataset. EIRP and antenna gain are
absorbed into a single fitted constant (~26 dB). Height is asserted at 30 m because it is
**not identifiable** — see §3.3.

### 1.3 Evaluation protocol

Consecutive samples are ~22 m apart, so a random split leaks badly. Following the challenge
brief's requirement for geographically separated test segments, points are assigned to a
**2 km checkerboard**; the calibration constant is fitted on one colour and all reported
metrics are computed on the other. No test block influences any fitted quantity.

---

## 2. Results

Held-out performance of the best configuration (30 m terrain, LOS + specular, `max_depth` 3,
no diffraction, 30 m antenna, no downtilt):

| metric | value |
|---|---|
| Test RMSE | **8.58 dB** |
| Test correlation | **0.826** |
| Test bias | +1.75 dB |
| Held-out points | 1,762 |
| Link rate | 0.82 |

57% of grid cells in the mapped area receive a modelled path. The remainder are reported as
unmodelled rather than as zero coverage — an important distinction, and a known limitation
(§4).

---

### 2.1 The scene is not flipped

Five independent orientation checks pass (`scene/verify_orientation.py`). The decisive one:
the model's predicted best-serving sector matches the sector the network actually used on
**97.1% of 3,156 points**, against 33% chance. That single number couples projection,
geometry and antenna azimuth, and any mirror or rotation would collapse it. Terrain matches
an independent DEM read to +0.04 m mean error (r = 0.9973), where a north–south flip would
give r = 0.38.

Validation against USGS NAIP aerial imagery (`scene_validation.png`) exposes a separate
problem: **only 6 OSM buildings exist in the 2×2 km box around the serving site**, and just
3.6% of the extract's 10,063 buildings lie in the rural half where the measurements are —
so buildings were effectively unmodelled along the measured route. §2.2 replaces them.

### 2.2 Replacing the building source is the one change that helped

Microsoft's US Building Footprints are ML-extracted from imagery, so rural coverage does not
depend on volunteer mapping. Substituting them raises building counts within 2 km of the
serving site from **6 to 37**, and across the rural half from **365 to 2,167**.

| buildings | RMSE | r | link rate |
|---|---|---|---|
| OpenStreetMap | 8.58 dB | 0.826 | 0.82 |
| **Microsoft ML, 4 m** | **8.29 dB** | **0.832** | 0.80 |
| Microsoft ML, 10 m | 9.32 dB | 0.787 | 0.77 |

Footprint alignment was measured rather than assumed: cross-correlating against imagery
contrast gives a sharp peak at **+2 m East**, collapsing to background by +/-10 m
(`scene/check_alignment.py`). That residual is an order of magnitude below the terrain post
spacing and shifts shadowing by under 0.1 deg at these ranges, so it does not hurt. It is
also independent confirmation of the projection chain, since these footprints pass through
the same export path as everything else.

**+0.29 dB, roughly twice any other single change tested** — and the only one to improve
correlation as well. Compare `scene_validation.png` with `scene_validation_ms.png`.

Recomputing the full service surface gives **8.27 dB** (r = 0.832) against the OSM scene's
8.58 dB. The change is **concentrated, not uniform**: 7% of grid cells shift by more than
1 dB, median absolute change 0.10 dB, maximum 27 dB — see `surface_comparison.png`. That
pattern is what a building-driven effect should look like, and it matters for Challenge 3,
since a 27 dB local change can move a cell across a service threshold even though the map
as a whole barely moves.

Two honest caveats: link rate falls from 0.82 to 0.80 as the extra buildings occlude more
paths, so the test sets are not identical (1,763 vs 1,722 points); and building height is
fitted, not known, since the footprints carry none.

That the *only* effective fix was better input data rather than better physics is consistent
with §3 — and it suggests the next gains lie in what the scene contains, not in how it is
traced.

### 2.3 The measurement floor is ~2 dB

The campaign comprises four drive runs. 255 locations were revisited on *separate* runs with
the same serving cell:

| comparison | spread |
|---|---|
| Across separate runs, same 25 m cell and serving cell | 2.1 dB std, 3.0 dB median range |
| Within a single run, same 25 m cell | 2.1 dB std |

This bounds what any model could achieve, and it is far below our 8.58 dB error. The
implication is important: **the model's error is systematic and location-specific, not
random**. Repeat visits to the same place see the same value. Whatever we are missing is a
fixed property of the geometry or the transmitter, not fading that averages away — so it is
recoverable, given the right inputs.

## 3. What does not explain the residual

Each row is a controlled, one-factor-at-a-time comparison. Full run log in
[`RESULTS.md`](RESULTS.md); every parameter with provenance in
[`PARAMETERS.md`](PARAMETERS.md).

| Hypothesis | Test | Result |
|---|---|---|
| Terrain resolution | 30 m vs 10 m USGS 3DEP (8.2M triangles) | 8.99 → 9.14 dB — **no gain for 18× the geometry** |
| Diffraction | UTD on / off, both meshes | 9.0 → 10.6–11.7 dB — **actively harmful** |
| Ground permittivity | very dry / medium dry / wet | 9.68 / 9.77 / 9.81 dB — **0.13 dB across the full range** |
| Mechanical downtilt | 0° → 10° | 9.77 → 10.23 dB, monotonic — **harmful** |
| Earth curvature | 4/3-earth, 8.5 m at 12 km | 9.95 → 10.02 dB — **0.07 dB, wrong direction** |
| Vegetation | woodland along path vs residual | real but **+0.09 dB** if perfectly corrected |

### 3.1 Diffraction fails for a diagnosable reason

Enabling UTD diffraction degrades the fit on both meshes, and degrades it *less* on the
finer one (10.6 dB vs 11.7 dB). That ordering is the signature of a tessellation artifact
rather than physics: a faceted DEM presents every triangle boundary as a candidate
diffracting edge with an unphysically large dihedral angle, and refining the mesh shallows
those angles. Diffraction should be restricted to building edges before being used at all.

### 3.2 Vegetation is real, and almost irrelevant

Testing woodland *along the transmitter-to-receiver path* (not merely near the receiver)
gives a clean dose-response:

| woodland crossed | n | mean residual |
|---|---|---|
| none | 2,865 | −0.41 dB |
| 0–50 m | 41 | −0.13 dB |
| 50–150 m | 165 | **+4.23 dB** |
| 150–300 m | 51 | **+5.86 dB** |
| >300 m | 34 | +5.58 dB |

The effect survives controlling for distance (+4.8 dB within the 6–12 km band alone), so the
physics is confirmed: the model over-predicts where it ignores trees. But only **9.2% of
paths cross woodland**, so a perfect correction improves overall RMSE by 0.09 dB.

Two details worth recording. The fitted loss, 0.021 dB/m, is roughly **10× below** ITU-R
P.833's 0.2–0.3 dB/m for bare deciduous — consistent with the ray riding above the canopy
for most of a long path and entering it only near the receiver. And Sionna provides **no
vegetation ITU material**; `itu_wood` is dry lumber for walls, not foliage, and using it for
trees would be badly wrong.

**This still matters for the placement decision.** The model over-predicts precisely in
wooded areas, so it will report adequate coverage where there is none — exactly the
locations a placement optimiser should be considering.

### 3.3 Antenna height is not identifiable

RMSE is flat from 15 m to 60 m in every configuration tested. Note that RMSE is **not
comparable across heights**: a taller antenna links more receivers, and the additional ones
are marginal far-out points that predict poorly, so lower heights score better partly by
being graded on an easier subset. Any conclusion about height needs a common linked subset.

---

### 2.4 What the headline number does and does not cover

Every RMSE here is on **RSRP in dBm**, serving cell only — the quantity the ray tracer
natively produces, and the most favourable one available. Chaining to uplink, the metric a
placement decision needs, gives r = 0.332 and 29.7 Mbps RMSE. A control feeding the same
curve *measured* RSRP reaches only r = 0.565, so the RSRP->uplink mapping is a larger
limitation than the propagation model.

More seriously, **the validation set excludes the underserved**. The 3,023 rows (42%) with
no serving cell carry no RSRP and are dropped before scoring, so the model is validated
where the network already works. Of the 1,225 points reaching the uplink evaluation, 20
(1.6%) fall below 10 Mbps, and the model's recall on identifying them is **0.00**.

The 8.27 dB is real, but it licenses less than it appears to. Closing this needs a
validation path built on coverage *classification* — does a location have any serving cell —
rather than RSRP regression on the subset where one already does.

## 4. Limitations

- **43% of mapped cells have no modelled path**, and 6–27% of points where the UE genuinely
  reported RSRP receive no traced path. These are model failures, not coverage holes, and
  the figure distinguishes them.
- **The antenna is the largest unmodelled object.** Real sector pattern, electrical tilt and
  EIRP are unknown and collapsed into one scalar; `tr38901` may simply be the wrong pattern.
- **Building height is fitted, not known.** Microsoft footprints carry no height; 4 m fits
  best and 10 m clearly does not. Real rural buildings vary from 4 m sheds to 25 m grain
  bins, so a uniform height is a real approximation.
- **Vegetation is still absent.** Aerial imagery shows tree lines and shelterbelts that
  neither building source records.
- **Water bodies (172) and grain bins (29 tagged) are excluded** and untested. Metal silos
  are strong specular scatterers at 8.7 cm.
- **The sweep in §3 used 800 sampled rows per run.** Those runs are *paired* (identical
  subsample, seed 0), so the ordering is valid, but their absolute level is ~1.2 dB
  pessimistic: the same configuration scores 9.77 dB on the 800-row subsample and 8.58 dB on
  all rows. Absolute numbers should be quoted from full-sample runs only.
- **One site, one season.** Agronomy Farm serves 3,838 of 4,121 served rows; the campaign is
  two days in March, pre-planting. Nothing here establishes seasonal or multi-site
  behaviour.

---

## 5. What we would do next

1. **Request the antenna specifications.** Given that measurements repeat to 2 dB while the
   model errs by 8.6 dB, the missing information is systematic, and the transmitter is the
   largest thing we do not know. Pattern, height, tilt and EIRP are all currently collapsed
   into one fitted constant. [`DATA_REQUEST.md`](DATA_REQUEST.md) ranks this and everything
   else worth asking ARA for.
2. **Predict a distribution, not a mean.** Whatever the residual turns out to be, the
   surface should carry an uncertainty band and placement should optimise expected coverage
   under it. The challenge explicitly asks for robustness to model uncertainty, so this
   converts a limitation into the required deliverable.
3. **Define "underserved" on uplink.** Downlink saturates near 230 Mbps for any SINR > 0
   while uplink tracks RSRP hard across 8–63 Mbps. A downlink-based objective would call
   almost everywhere adequate.
4. **Treat unmodelled cells as unknown, not as zero.** With 43% of cells lacking a path, the
   optimiser's treatment of them will drive its answer more than the propagation model does.
5. **Use Research Park as a negative control.** It serves 0 of 7,144 rows. Any model
   predicting usable coverage from it is wrong regardless of its fit at Agronomy.
6. **Validate on the no-service rows.** Reframe scoring as coverage classification so the
   42% of locations with no serving cell enter the evaluation instead of being dropped.
   Without this, no placement recommendation is backed by a measured error.
7. **Re-run the sweep at full sample size on a GPU.** Every rejection in §3 rests on paired
   800-row runs.

---

## 6. Reproducibility

Every run appends a complete record — all parameters, all results, git SHA, Mitsuba variant
— to `scene/experiments.jsonl`. [`RESULTS.md`](RESULTS.md) is generated from it.
[`PARAMETERS.md`](PARAMETERS.md) tags every model quantity as measured, inferred, assumed,
fitted, or ruled out.

```bash
pip install sionna-rt
cd scene
python experiment.py --tag mytest --n-rx 4000     # one configuration
./run_experiments.sh                              # the full sweep in §3
python veg_diagnostic.py                          # the vegetation analysis in §3.2
```

The 30 m Mitsuba scene is committed, so this runs on a fresh clone with no Blender and no
downloads. Setup details and coordinate conventions: [`RUNNING.md`](RUNNING.md).

**Data.** The measurement dataset is Arathon-only while non-public and is not in this
repository. Scene geometry derives from OpenStreetMap (© OpenStreetMap contributors, ODbL)
and NASA SRTM / Mapzen terrain tiles; USGS 3DEP elevation is public domain.
