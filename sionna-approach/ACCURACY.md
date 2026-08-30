# Closing the gap — plan for the propagation model

**Decision (2026-08-30):** accuracy work comes before the siting optimisation. There is
time, and a tighter model makes every number in [`PLAN.md`](PLAN.md) defensible on its own
terms rather than merely survivable under a robustness test. `PLAN.md` Phases 2–7 are
unchanged and still consume whatever surface this work produces.

Current state: **held-out RMSE 8.6 dB, r = 0.82, bias +1.7 dB** on spatially disjoint 2 km
blocks. Ruled out already: finer DEM. *Not* actually ruled out: diffraction — see below.

---

## 0. A finding already in hand: the diffraction result was a scoring artifact

Before planning anything I re-ran the diffraction comparison on this box (GPU, 628
receivers on terrain, 0.5–10 km, identical geometry both ways). The conclusion in
`HANDOFF.md` — "diffraction makes the fit worse, leave it off" — does not survive.

| measurement | value |
|---|---|
| Path-gain change on links that exist **both** ways | **−0.06 dB mean, 0.44 dB std** |
| Links added by diffraction | 70 (72.5% → 83.8% linked) |
| Those added links, vs free space | **−72.6 dB** |
| Predicted RSRP of added links (offset +25 dB) | median **−164.7 dBm** |
| Added links below the 3GPP RSRP floor (−156 dBm) | **50 of 70** |
| Added links a UE could plausibly report (> −120 dBm) | **2 of 70** |

Diffraction does essentially nothing to the predictions that matter (0.06 dB). All of the
8.99 → 11.71 dB RMSE degradation came from **newly added links that are 70+ dB below free
space** — signals no UE could ever detect, scored as if they were numeric predictions
against real measured RSRP. A handful of 50 dB residuals is all it takes.

So the real defect is not in the physics, it is in the scoring: **`calibrate.py` has no
receiver sensitivity floor.** Any predicted level below what a UE can decode must be
treated as *no service*, not as a number to regress against. That single fix is A3 below,
and it invalidates or changes several recorded conclusions.

Two consequences worth stating plainly:

1. The same critique the handoff correctly makes about the **antenna-height** sweep
   ("not apples-to-apples — a taller antenna links more receivers") applies to the
   diffraction rows and was not applied there. Every conclusion drawn from a comparison
   with a differing `linked` count needs re-deriving. In the 2×2 table the diffraction-off
   best rows are at h=15 and the diffraction-on best rows at h=60, so those cells differ in
   *two* variables at once.
2. Sionna's edge diffraction over a tessellated DEM puts shadowed points 72.6 dB below
   free space. Real terrain-diffracted paths at these ranges sit more like 20–40 dB below.
   So the tessellation diagnosis in the handoff was right about there being an artifact —
   it was just the wrong sign of conclusion. The mechanism is under-predicting badly, which
   is B2 below.

*Sanity check that the scale is trustworthy:* on links found without diffraction, path gain
sits **+5.0 dB above free space**, consistent with tr38901 boresight gain minus
off-boresight rolloff. The model is physically sane on the links it finds. The problem is
the links it does not find, and how the ones it invents are scored.

---

## 1. What "closed" means

Setting a target honestly, because "close the 9 dB gap" has no natural endpoint:

- Published rural drive-test accuracy for ITM / Longley-Rice class models is **8–12 dB**.
  Well-calibrated ray tracing over real terrain reaches **6–9 dB**.
- We are at 8.6 dB, i.e. already at the good end of the statistical-model band and the poor
  end of the ray-tracing band.
- **Target: 6–7 dB held-out, and a model that knows when it does not know.**

But the ceiling is set by the data, not by us, and nobody has measured it. Hence A1.

---

## Stage A — Instrument before optimising

Nothing in Stage B is worth doing until these three are done. All are cheap; A1 needs no
ray tracing at all.

### A1. Measure the irreducible error floor  *(do this first — it may end the project)*

> **ANSWERED 2026-08-30: sigma_floor = 3.4 +- 0.5 dB. The gate is passed — continue.**
> `analysis/error_floor.py`. Two independent estimators agree: de-clustered cross-run
> repeat passes extrapolated to zero separation give **3.14 dB**, and the cross-run
> variogram nugget on detrended RSRP gives **3.63 dB**. Against the twin's 8.58 dB that
> leaves **7.9 dB model-attributable and ~5 dB of RMSE headroom**, so Stage B is justified.
>
> Two qualifications. **The floor is mostly positioning, not physics:** stationary
> re-samples (same spot, same run) give only **0.97 dB**, so ~3 dB enters through not
> knowing where the UE was — GPS plus micro-siting. Map-matching the track to the OSM road
> centreline would remove the cross-track component and genuinely lower the floor. And it
> is a floor for *position-only* models: heading (UE inside a vehicle), speed and time of
> day are derivable from the track and may predict part of it.
>
> **De-clustering was essential.** 601 of 4,121 served samples sit in 6 cells of 20 m, one
> 369 deep — the van parks. Naive radius-pair counting weights those ~n² and reports one
> parking spot's stationary repeatability (it gave 1.8 dB, with a discontinuity at 15 m).
> All cross-run estimates draw one sample per (cell, run), averaged over 25 draws.
>
> This also contradicts the closing claim in [`REPORT.md`](REPORT.md) that the deterministic
> model is near the floor of what the geometry can explain. The *measurement* floor is
> 3.4 dB. Shadow fading is spatially structured physics, not measurement noise.

If two passes over the same road disagree by 8 dB, then an 8.6 dB model is *already at the
noise floor* and every day spent on Stage B is wasted. Nobody has checked.

Two estimators, both from `COTS.csv` alone:

- **Repeat-pass reproducibility.** There are 4 runs over 276 km with overlap. Where two
  runs pass within 10 m on the same serving sector, take the RSRP difference. If those
  differences have std σ_d, each measurement carries noise σ_d/√2 — and **that is the best
  RMSE any position-only model can achieve.**
- **Short-lag variogram nugget.** Consecutive samples are ~22 m apart. Fit a variogram of
  RSRP against separation and read the nugget at zero lag. It absorbs receiver noise,
  small-scale fading, and GPS error together.

*Output:* one number, σ_floor, and the realistic target becomes `sqrt(σ_floor² + σ_model²)`.
Report it in the README next to the RMSE — it reframes 8.6 dB from "mediocre" to
"n dB from the achievable limit", which is a far stronger claim either way.

### A2. Decompose the residual  *(the highest-information hour available)*

Every result so far is a scalar RMSE from a one-parameter-at-a-time sweep. No one has
plotted the residual against anything. Structure in any of these names the mechanism:

| Residual plotted against | What structure would mean |
|---|---|
| **Elevation angle** from the tower, `atan((h_tx − h_rx)/d)` | antenna **downtilt / vertical pattern** wrong — see B3 |
| log₁₀(distance) | path-loss exponent wrong, or tilt aliasing into range |
| Azimuth offset from sector boresight | horizontal pattern or azimuth error |
| Fresnel-zone clearance along the profile | diffraction modelling error — see B2 |
| LOS vs reflected-only, and number of traced paths | mechanism coverage |
| Run ID, time of day, speed | measurement-side artifacts |
| **Spatially, as a map** | clusters localise the cause — overlay on aerial imagery and look for shelterbelts |

Also stratify RMSE by distance band and by LOS/NLOS. A model at 8.6 dB overall might be
4 dB LOS and 14 dB NLOS, and that decomposition alone would say where the entire budget
should go.

### A3. Fix the scoring  *(prerequisite for trusting any Stage B result)*

- **Sensitivity floor.** Predictions below a UE-detectable level are "no service", never a
  regression target. Set the floor from the data — the minimum reported RSRP — and treat
  everything below it as a classification outcome. This is what section 0 demands.
- **Common linked subset.** Any two configurations get compared only on receivers linked in
  both. Retro-fit this and re-derive the height and diffraction conclusions.
- **Censoring.** Serving rows are a *truncated* sample: at long range the UE only holds the
  cell where the fade was favourable, so measured RSRP is biased high exactly where the
  model is worst. This is a plausible source of the reported **+1.7 dB bias**. Fit with a
  censored (Tobit) likelihood using the 3,023 no-service rows as left-censored
  observations, rather than dropping them.
- **Per-sector offsets.** One global `offset` assumes three identical sectors. Fit three and
  look at the spread; more than ~3 dB apart means an azimuth or pattern problem, not an
  EIRP one.
- **Report more than RMSE.** MAE, bias, correlation, the residual *distribution* (Gaussian
  or heavy-tailed?), and stratified breakdowns. Heavy tails point at outliers with a cause.

---

## Stage B — Mechanisms, ranked by expected value

Order reflects expected dB per hour, and A2 may reorder it. Each is accepted only on
**held-out** improvement under the A3 scoring.

### B1. Re-test diffraction properly  *(near-zero cost, conclusion already suspect)*

With the sensitivity floor and common-subset scoring in place, re-run the 2×2. Section 0
predicts diffraction will be neutral-to-positive rather than catastrophic. Cost on this
box: 1.7 s per 628-receiver solve. This is an afternoon, not a project.

### B2. Hybrid RT + profile diffraction  *(the likely main event)*

Physics says rural NLOS at 3.46 GHz over 10 km with 94 m of relief is **terrain-diffraction
dominated**. Sionna's mesh-edge diffraction puts those points 72.6 dB down — far too deep —
because it diffracts off triangle boundaries rather than off the real terrain profile.

The standard fix is to leave the mesh alone and work on the **elevation profile**, which is
what ITM/Longley-Rice and ITU-R P.1812 do:

1. Sample terrain elevation along the TX→RX great circle from `dem_3dep.tif` (already in
   `scene/`), ~100 points per profile.
2. Apply 4/3-earth curvature (bulge = d₁d₂/2kR).
3. Find obstructions against the first Fresnel ellipsoid — 14.7 m radius at the midpoint of
   a 10 km link at this frequency.
4. Multi-knife-edge loss by **Deygout** (principal edge, then recurse), each edge via the
   ITU-R P.526 approximation `J(ν) ≈ 6.9 + 20log₁₀(√((ν−0.1)²+1) + ν − 0.1)` for ν > −0.78,
   with `ν = h√(2/λ · (1/d₁ + 1/d₂))`.
5. **Combine:** use the ray tracer where it finds a real path (LOS + specular, where it is
   already +5.0 dB vs free space and trustworthy), and free-space-plus-diffraction-loss
   where it does not.

This is pure numpy over a raster — thousands of profiles per second, no GPU — and it can be
applied as a **post-process to existing `.npz` output**. It targets exactly the two known
holes: the 6–27% of measured points with no traced path, and the 43% of grid cells that are
currently grey. Those grey cells become predictions instead of a caveat, which matters
directly for `PLAN.md` Phase 3.

### B3. Antenna pattern and downtilt

`tr38901` is a generic 3GPP pattern at zero tilt. The real unit is an Ericsson 3.5 GHz
radio, and **electrical downtilt of 2–6° is standard**. Tilt produces a systematic
*distance-dependent* bias that a single scalar `offset` cannot absorb — it can only average
it out, inflating RMSE at both ends of the range.

A2's residual-vs-elevation-angle plot reads this off directly. Then fit tilt as a free
parameter, jointly with height (they are correlated — which is *why* height came out
unidentifiable: at zero assumed tilt, height changes almost nothing about the far-field
elevation angle).

Note the RSRP is measured on SSB beams, which are broader than the data beams on a massive-
MIMO unit; the SSB beam set is the right thing to model, not a single narrow beam.

### B4. Vegetation

Named as the leading suspect in `HANDOFF.md`; ranked below B2/B3 here because sections 0
and A2 give more specific evidence for those. Blender is **not** needed — follow the
pattern `build_terrain_3dep.py` already sets: pull `landuse=forest`, `natural=wood` and
tree-row ways from `ames.osm`, extrude to ~12 m over the terrain, write a PLY, add one
`<shape>` to the XML with `itu_vegetation`. Timebox it; keep only on held-out improvement.

### B5. Ground material and roughness

`itu_medium_dry_ground` for **March in Iowa, post-thaw** is likely wrong — wet ground has
much higher permittivity and reflects more strongly, changing the two-ray interference
pattern. One-line sweep across the ITU ground types. Separately, specular reflection off
smooth mesh facets over a ploughed field is unphysical; test `diffuse_reflection=True` with
a scattering coefficient.

---

## Stage C — Whatever is left becomes the uncertainty model

The residual never reaches zero, and `PLAN.md` Phase 2.3 needs it characterised anyway:
per-cell σ as a function of distance / clearance / path count, plus the variogram
correlation length that decides whether errors cancel between candidate sites. **Stage A's
diagnostics are exactly the inputs that model needs**, so this work is not lost even if the
gap refuses to close.

---

## Order, cost, and what blocks what

```
A1  error floor          CPU, minutes      needs COTS.csv only     <-- may end the project
A2  residual decomp      1 GPU run + plots needs COTS.csv + scene
A3  scoring fixes        rewrite scoring   needs COTS.csv
     |
B1  re-test diffraction  seconds per solve       <-- conclusion already suspect
B2  hybrid diffraction   numpy, no GPU           <-- likely main event
B3  pattern + downtilt   GPU sweep
B4  vegetation           OSM -> PLY, timeboxed
B5  material + roughness one-line sweeps
     |
C   uncertainty model    feeds PLAN.md Phase 2.3
```

**Do not run Stage B before A1.** If the noise floor is 7 dB, the correct decision is to
stop, write it up as a finding, and spend the time on the siting problem instead.

## Environment status

- ✅ **Sionna RT 2.0.1 installed** in a dedicated `sionna` conda env (base untouched —
  `sionna-rt` pins mitsuba 3.8.0 / drjit 1.3.1 and base holds torch 2.5.1).
  Activate with `conda activate sionna`.
- ✅ **GPU backend confirmed**: `mi.variant()` → `cuda_ad_mono_polarized`. No
  `DRJIT_LIBLLVM_PATH` needed. 628 receivers solve in **0.3 s** without diffraction, 1.7 s
  with — versus ~15 s for 800 on the original CPU box. Sweeps that were an afternoon are
  now a coffee break, so prefer dense sweeps over clever one-at-a-time ones.
- ✅ Committed scene loads and traces correctly; materials resolve to
  `itu_medium_dry_ground` / `itu_concrete`.
- ⚠️ Env has **numpy 2.4.6 / pandas 3.0.5**, much newer than the scripts were written
  against. Expect minor API friction on first run.
- ⛔ **`COTS.csv` is not on this machine.** A1, A2 and A3 are all blocked on it. This is the
  only thing standing between here and starting.
