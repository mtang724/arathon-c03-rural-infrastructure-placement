# The model, the maths, and the tool

How the ARA Challenge 3 simulator works, what it predicts well, and — measured
rather than asserted — where it fails.

> **Read this first.** The propagation half of this model is sound: **RMSE
> 7.35 dB in sample and 9.66 dB held out by geography, R² +0.15**, with a
> two-slope exponent of 1.80 near / 3.35 far. The availability half is weak:
> asked whether a given 200 m cell has service it scores **59.5%** against a
> base rate of **63.9%**. The device comparison and the siting logic rest on the
> first half. The absolute coverage percentages inherit the second. Treat ratios
> as findings and percentages as indicative.

---

## 1. What the simulator is

A function from a **transmitter** (position, mast height, radiated power) and a
**receiver location** to a predicted service outcome, fitted entirely on the
7,144-row COTS measurement file plus a USGS terrain model.

```
(lat, lon, mast height, EIRP)  ─┐
                                ├──►  RSRP  ──►  availability  ──►  covered?
(demand cell lat, lon)         ─┘
```

Three things make it a *model* rather than an interpolation, which matters
because the question is counterfactual — what happens if we add a transmitter
that has never existed:

1. **It is a physical law with fitted constants**, not a memorised surface. A
   gradient booster trained on `(lat, lon) → service` has nothing to say about a
   transmitter it never saw. A path-loss law does: a node radiating X dB below
   the macro sits X dB lower on the same curve at every distance.
2. **Terrain enters through geometry**, so a new site is evaluated on what it can
   actually see, not just how far away it is.
3. **Mast height is a variable**, so raising an antenna changes which terrain it
   clears — the mechanism that dominates in rolling farmland.

---

## 2. The maths

### 2.1 Path loss

Received power in dBm at distance `d` metres from the serving site:

```
RSRP(d, φ, J) = b₀ + b₁·log₁₀(d)
                + a₁cos φ + a₂sin φ + a₃cos 2φ + a₄sin 2φ      (antenna pattern)
                + b_J · J(v)                                    (terrain)
```

`φ` is the bearing from the tower to the receiver. Fitted by ordinary least
squares on 3,838 samples where Agronomy Farm was the serving site:

| Term | Fitted value | Meaning |
|---|---|---|
| `b₀` | **−21.71 dBm** | intercept at 1 m |
| `b₁` | **−18.00 dB/decade** | near exponent **n = 1.80** (bounded) |
| `b_dual` | **−15.53** | adds beyond 3 km ⇒ far exponent **n = 3.35** |
| `a₁, a₂` | −4.88, +2.51 | one azimuth harmonic |
| `b_J` | **−0.73 dB per dB** | diffraction, orthogonalised |
| `b_F` | **+7.33** | Fresnel clearance, orthogonalised |
| residual σ | **7.35 dB** | shadow fading |

**Four choices here were forced by the backtest, not chosen for elegance:**

**One azimuth harmonic, not two.** Two fit the three-sector beam beautifully in
sample and fall apart on a held-out bearing sector. This was the single largest
win.

**A dual slope breaking at 3 km** — the standard two-ray treatment, and the fit
lands on textbook rural values.

**Both terrain terms orthogonalised against log-distance.** Fresnel clearance is
**96.5% correlated** with log-distance — clearance is high near the tower and low
far from it — so a free coefficient on it absorbs the distance effect and leaves
an exponent of **0.53**, which is not a propagation law, it is distance wearing a
hat. Removing the collinear part lets each term carry only what distance does not
already explain.

**The near exponent bounded at 1.8.** Costs 0.08 dB of RMSE and buys a model
whose constants can be defended in a room.

**Why the azimuth terms exist.** Fitting `RSRP` on log-distance alone returns
**n = 1.68** — propagation *better than free space*, which is impossible. The van
drove along and across the sector boresight, so the beam shape was being absorbed
into the distance term. Two Fourier harmonics of bearing give the pattern
somewhere to live and free the exponent to mean what it should.

**Why the two-slope shape is the check that matters.** A single exponent has to
average the near field and the far field into one number, and it landed at 2.40 —
a value that is right nowhere. Splitting at 3 km gives 1.80 inside and 3.35
outside, which is what rural propagation actually looks like: close to free space
near the tower, steepening sharply once the ground and the horizon start to bite.

### 2.2 Terrain: Fresnel, curvature, diffraction

For every link the path is sampled at 160 points and three corrections applied.

**Effective-earth curvature.** With `k = 4/3`, `R_eff = 8,494 km`, the ground
bulges above the straight line by

```
h_bulge(d₁, d₂) = d₁·d₂ / (2·R_eff)
```

which is 1.47 m at mid-path on a 10 km link. Not negligible — the obstructions
found here have a *median height of 1.5 m*, so ignoring curvature would have been
the same size as the effect being measured.

**First Fresnel zone.** The radius at a point splitting the path into `d₁` and
`d₂`:

```
F₁ = √(λ·d₁·d₂ / d)          λ = c/f = 8.67 cm at 3460.8 MHz
```

10.4 m at mid-path on a 5 km link, 14.0 m on a 9 km link. **This sets the
required terrain resolution**: 1/3 arc-second posts (10.3 × 7.7 m) match the
Fresnel radius, and 1-metre data would resolve detail 10× finer than the radio
can respond to.

**Knife-edge diffraction (ITU-R P.526).** With clearance `h` (negative when the
ground intrudes), the Fresnel–Kirchhoff parameter and loss are

```
v = −√2 · (h / F₁)

J(v) = 6.9 + 20·log₁₀( √((v−0.1)² + 1) + v − 0.1 )     for v > −0.78
     = 0                                                otherwise
```

The `v > −0.78` cutoff is exactly the classical **0.6 F₁ clearance rule**:
`0.78/√2 = 0.55`. The worst `v` along the path is taken as the single controlling
edge.

**The finding this produced.** Bare line of sight is blocked on only **13%** of
links, but **46%** intrude on the first Fresnel zone. The holes are *grazing*
paths, not blocked ones — which is why a naive LOS test finds nothing. Holding
distance constant, a Fresnel-obstructed cell is:

| Ring | Odds ratio for outage | p |
|---|---|---|
| 2–4 km | **2.25** | 7.7 × 10⁻⁸ |
| 4–6 km | **2.39** | 5.5 × 10⁻¹² |
| 6–8 km | 0.83 | 0.07 (ns) |
| 8–13 km | 0.97 | 0.89 (ns) |

**Between 2 and 6 km the dead spots are terrain. Past 6 km the link budget has
already run out and terrain no longer discriminates.**

The fitted `b_J = −1.90` rather than the physical −1.0 says single-knife-edge
**under-predicts** real loss — expected, since actual paths have multiple edges
and the bare-earth DEM strips the tree lines that sit on those same ridges.

### 2.3 Availability

Isotonic (monotone) regression of observed service rate on predicted RSRP,
fitted on 200 m cell aggregates:

```
A(RSRP) = isotonic_increasing( P(cell has a serving cell) )
covered ⟺ A(RSRP_best) ≥ t          default t = 0.50
```

Monotone by construction because more received power cannot mean less service,
and fitted on **cells rather than rows** because sampling density is wildly
uneven — the cell containing the tower holds 543 samples while far-south cells
hold one or two, so a row-level fit is silently weighted toward the good region.

**This is the weak link, and §4 measures how weak.**

### 2.4 Adding a transmitter

The counterfactual is one line. A new omnidirectional node with EIRP `Δ` dB below
the macro delivers

```
RSRP_new(cell) = b₀ + b₁·log₁₀(d_new) − Δ + b_J·J(v_new)
```

where `d_new` and `J(v_new)` are recomputed from the new site's position and mast
height. A cell then takes the best server available to it:

```
RSRP_best = max( RSRP_macro , RSRP_new )
```

so adding a transmitter can only help, and before/after are computed by identical
code — which is what makes the **delta** meaningful even where the absolute level
is not.

**Service radius.** Setting `RSRP = threshold` and solving:

```
r(Δ) = 10^((b₀ − Δ − RSRP_thr) / (−b₁))
```

At 19.49 dB/decade, **every 6 dB lost halves the radius and quarters the area**:

| Δ | Radius | Area vs a macro |
|---|---|---|
| 0 dB (macro) | 5,523 m | 1.000× |
| 20 dB (relay) | 520 m | **0.0089×** |
| 26 dB (small cell) | 256 m | **0.0022×** |

### 2.5 The objective

Demand is a 200 m grid over the 189 km² box, carrying two layers:

```
score = 0.70 · (route-km covered / 116.7) + 0.30 · (area covered / 189.2)
```

**Route-km is de-duplicated.** The van drove some roads on all four runs, so
summing GPS steps gives 277 km for what is really **116.7 km** of distinct road.
Counting distinct 25 m sub-cells recovers the true length.

Solved greedily. Coverage is submodular, so greedy is within `1 − 1/e ≈ 63%` of
optimal, needs no solver, and runs in milliseconds — which is what lets the same
routine run live in the browser.

### 2.6 Uncertainty

Shadow fading is a property of the **path**, not the location. Two transmitters
at different bearings look through different terrain, so their fades are only
partly shared:

```
S_t(c) = √ρ · Common(c) + √(1−ρ) · Own_t(c)
ρ(θ)   = ρ₀ · exp(−θ / θ_c)        ρ₀ = 0.60, θ_c = 45°
```

`θ` is the angle the two paths subtend at the receiver; median ρ works out at
0.22. An earlier version added the *same* draw to both transmitters, which made
their errors cancel and reported 100% confidence for a site that beats its
runner-up by 0.5%. Under the corrected model:

| Shadow model | Exact site | ≤2 km |
|---|---|---|
| ρ = 1 (the old, over-confident one) | 25% | 100% |
| ρ = 0.5 constant | 13% | 100% |
| **ρ(θ) angular — default** | **12%** | **97%** |
| ρ = 0 independent | 10% | 98% |

**We know the right 2 km, not the right pole**, and that survives every fading
assumption.

---

## 3. What it concludes

Coverage today, at "available at least half the time": **44% of route-km,
37% of area**.

| Asset | Power | Mast | Radius | Route-km added | Area added |
|---|---|---|---|---|---|
| Donor relay | −20 dB | 10 m | ~520 m | +1.4 | +0.5 km² |
| Small cell | −26 dB | 10 m | ~256 m | +0.7 | +0.1 km² |
| **Macro-class** | 0 dB | 37 m | ~5.5 km | **+28.6** | **+42.6 km²** |

Recommended: **41.97955, −93.83471**, 6.8 km south-west, 37 m mast, on the road
network. Route 44% → **69%**, area 37% → **59%**.

**Power dominates height, and by more than the earlier model said.** Sweeping the
mast from 6 m to 60 m moves the gain by 3% (0.548 → 0.567); sweeping power from
0 to 26 dB down collapses it from 0.565 to 0.024. Fitting the terrain term
properly is what changed this — the previous −1.90 dB/dB diffraction coefficient
was absorbing distance effects and inflating the apparent value of mast height.

**The brief's menu — relay, repeater, small cell — is built to fill small gaps
inside served areas. This is a 9 km hole with one tower 9.5 km from its far
edge.** No device on that menu can reach it.

---

## 4. Where it fails — measured, not asserted

`src/backtest.py` runs the simulator with **no added unit** and compares it to
what the van recorded. It calls the shipped `fit_with_terrain` / `macro_rsrp`
rather than reimplementing them.

### RSRP: now generalises

| Split | MAE | RMSE | R² |
|---|---|---|---|
| In sample | 5.59 dB | 7.35 dB | +0.803 |
| Naive random split | 5.60 dB | 7.33 dB | +0.803 |
| **Held out — KMeans blocks** | 7.63 dB | **9.66 dB** | **+0.154** |
| **Held out — angular wedges** | 8.05 dB | 9.78 dB | +0.054 |

The earlier form of this model scored **RMSE 12.48 dB and R² −0.651** on the same
KMeans split — worse than predicting the block mean. The changes in §2.1 took
**23% off the RMSE and moved R² from −0.65 to +0.15.**

Note that the random split now reproduces the in-sample figure almost exactly
(7.33 vs 7.35). That is not the model being good; it is samples 2.6 s apart being
metres apart, so the test set is the training set. The honest numbers are the
held-out rows.

**Two blocking schemes, because they measure different things.** The survey is a
radial pattern around one tower, so geography and the covariates are nearly the
same variable, and any contiguous region held out is also a slice of covariate
space:

- **KMeans on position** carves compact regions. One is the near-tower cluster,
  so holding it out deletes every sample under ~2 km and forces log-distance to
  extrapolate inward. Harshest, and least like deployment.
- **Angular wedges** cut bearing sectors. Distance support survives; what is held
  out is a bearing sector, testing the antenna term instead.

The gap between them is a finding about the survey geometry, not about the model.

### Availability: still barely beats guessing

Classifying 501 cells (≥5 samples each) as served or not:

| | |
|---|---|
| Observed route-km served | **68.0%** |
| Simulated | **47.7%** |
| Cell-by-cell agreement | **59.5%** |
| Base rate — always say "served" | **63.9%** |
| Brier score | **0.148** (was 0.183) |

Calibration is now close in the bins that matter — predicted 0.84 against
observed 0.84, predicted 0.59 against 0.67 — and the Brier score improved, but
the classifier still does not beat the base rate.

**One fix that did help.** The availability curve was fitted unweighted over
cells, so the sparse far-south cells (one or two samples each, mean availability
0.38) dominated a fit that is scored on a population whose sample-weighted
availability is 0.58. Weighting each cell by its sample count moved the simulated
figure from 24.7% to 47.7% and the Brier score from 0.176 to 0.141.

### Why the ceiling is low

| Source | Share of outage variance |
|---|---|
| **Where** it was (cell mean) | **71.4%** |
| Which run it was | 5.3% |

Location dominates, so a spatial model *should* do well — we are simply not
capturing it. Predicted RSRP correlates with observed availability at about
+0.35. Real availability carries far more spatial structure than a smooth
function of distance, bearing and diffraction can express: sector boundaries,
handover behaviour, specific dead pockets.

And some of it is irreducible. Of 87 cells measured on two or more runs, **21%
flip** between mostly-served and mostly-dead. Run 1 saw 90% availability; run 3,
over largely the same roads, saw 46%.

### An earlier bug the backtest caught

The availability curve was calibrated against `rsrp_omni(distance)` from the
*non-terrain* fit but read with RSRP from the *terrain* fit — up to 6.9 dB apart
on distance alone, far more on obstructed cells. Fixed, and it did **not** rescue
the availability step, which is how we know the weakness is structural rather
than a coding error.

### What this means for the conclusions

| Claim | Status |
|---|---|
| Dead spots at 2–6 km are terrain | **Holds** — odds ratios 2.25–2.39, p < 10⁻⁷ |
| Two-slope exponent, service radii, the power law | **Holds** — RMSE 9.66 dB held out, R² +0.15 |
| Relay and small cell cannot reach; a macro can | **Holds** — a ratio, from geometry |
| "44% covered now, 69% after" | **Indicative only** |
| The site, to within 2 km | **Holds** — 98–100% of draws across all four fading models |

## 5. The tool

> **Superseded.** The tool is now [`../planner.html`](../planner.html), built by
> `common/build_planner.py`, and it is parameterised over the simulator, the
> service criterion and the route/area weighting rather than fixed to
> availability at 50%. `terrain-approach/planner.html` is kept only for its four
> analysis tabs, which have not been ported. **Do not quote its numbers** — see
> the correction below.

**A correction.** This section used to claim that `terrain-approach/planner.html`
tracks the offline optimiser to about 1%. That was true when it was written and
stopped being true when the model gained its dual slope, Fresnel term and
orthogonalisation offsets: the page's JavaScript carries a hand-copied subset of
the fitted constants and was never updated, so it still evaluates

```
b0 + slope*log10(d) - deficit + b_diff * J(v)
```

while `rsrp_from_node` evaluates that plus `b_dual*dual` and `b_fres*fres`, both
orthogonalised. Measured over four candidate sites and all 4,731 demand cells,
the page is **optimistic by a mean of 5.95 dB, RMS 8.37 dB, up to 31 dB** — which
is larger than the model's own 7.35 dB residual σ. Nothing detected it because
nothing checked that the copy was complete.

The replacement carries every coefficient the declared formula family requires,
and `common/schema.py::validate` refuses a bundle that does not. Against Python
on the same candidate and cells it agrees to **mean −0.07 dB, RMS 1.34 dB,
correlation 0.994, with zero service disagreements** over 300 cells; what remains
is the 31 m versus 10 m DEM stride, which is the 0.994 figure below.

**It recomputes.** The page carries the 3DEP terrain grid at 31 m posts and runs
the entire chain in JavaScript — path profile, earth bulge, Fresnel radius,
P.526 loss, RSRP, availability, threshold. A pin dropped anywhere gets a genuine
prediction, not a nearest-neighbour lookup. 31 m rather than 10 m posts costs
0.15 dB of mean diffraction error (correlation 0.994), checked rather than
assumed.

**Controls.** Asset class (relay / small cell / macro), mast height 6–60 m,
transmit power 0–34 dB below the tower, service threshold 20–90% availability.
Click the map to place, drag to pan, scroll to zoom.

**Four analysis tabs**, one per requirement in the brief:

| Tab | What it does |
|---|---|
| **Thresholds** | before/after at four explicit service definitions at once |
| **Robustness** | 150 fresh shadow-fading draws, run live on the placed site, with the gain distribution |
| **Gains** | per device class at your location, and the marginal gain of the 1st/2nd/3rd installation |
| **Sensitivity** | gain swept against mast height and transmit power |

It warns when a relay is placed somewhere with no usable donor link, using the
same diffraction physics as everything else rather than distance alone.

### Pipeline

```
python run_all.py            # features → model → optimise → planner, ~2.5 min
python src/backtest.py       # the honesty check in §4
python src/make_deck.py      # the six-slide deck
```

| Stage | Reads | Writes |
|---|---|---|
| `features.py` | `COTS.csv` | `labeled.csv` |
| `terrain.py` / `propagation.py` | 3DEP tiles | `dem10.npz`, `labeled_terrain.csv` |
| `coverage_terrain.py` | labelled + DEM | `coverage_terrain.json` |
| `robustness.py` | " | `robustness.json` |
| `backtest.py` | " | `backtest.json` |
| `build_coverage_planner.py` | all of the above | `planner.html` |

`src/config.py` holds every tunable assumption; nothing is hard-coded elsewhere.

---

## 6. Assumptions that are not measurements

- **Macro EIRP is never observed.** Relay at −20 dB and small cell at −26 dB are
  assumptions; real repeaters may sit 20–40 dB down. The relay figure is
  *generous*. The small cell being weaker than the relay is arguably backwards —
  a small cell is a real base station — but swapping them changes nothing, since
  both are 15–25× short on radius.
- **Tower height** 120 ft was supplied; **sector azimuths** were not, so the
  antenna pattern is fitted rather than known.
- **Demand is where the van drove.** Route density measures the survey, not the
  population, and the van avoided the deepest holes. A uniform-weight sensitivity
  is reported alongside.
- **The DEM is bare earth**, so vegetation is stripped. Collection ran 19–20
  March: pre-emergence, leaf-off. This is a **best-case foliage condition** and
  the measured deficit is a floor.
- **One UE, one modem, one band, two days, four runs, one serving site.** UE-side
  data cannot separate congestion, interference, backhaul or scheduling, so every
  conclusion here is coverage- and power-limited only.
