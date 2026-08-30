# Data-driven rural infrastructure placement

**ARATHON CHALLENGE 03** · AgWireless '26 / Rural Connectivity Research

> Where would one additional relay, repeater, small cell, or measurement campaign
> deliver the greatest improvement?

Given a UE drive test that covers roughly 7% of a rural service area near Ames, Iowa, the
challenge is to move from *describing* weak service to *recommending* a limited, defensible
intervention: predict performance where nothing was measured, then choose where one
additional asset does the most good.

## The shared platform

[`common/`](common/) is what makes the approaches comparable rather than merely
adjacent: one simulator contract, one backtest testbench, one planner.

| | |
|---|---|
| [`common/README.md`](common/README.md) | the contract — two methods, and your model works with every tool here |
| [`common/BACKTEST.md`](common/BACKTEST.md) | the testbench — identical splits, buffer, seed and metrics for every model |
| [`common/PLANNER.md`](common/PLANNER.md) | the planner — every simulator, every service definition, every weighting, re-solved live |

`common/` never imports an approach; approaches import `common` and expose their
models through it. Adding a new approach therefore touches no existing one.
[`terrain-approach/src/adapter.py`](terrain-approach/src/adapter.py) is the
reference implementation, with one analytic model and one tabulated model that
share nothing except the interface.

## Approaches

Each approach lives in its own folder and can be read and run independently.

| Folder | Approach | Status |
|---|---|---|
| [`sionna-approach/`](sionna-approach/) | Physics-based ray tracing (Sionna RT) over real terrain and OSM building geometry | Twin validated at 8.58 dB RMSE on held-out blocks — [report](sionna-approach/REPORT.md). Siting optimisation not started |
| [`terrain-approach/`](terrain-approach/) | Two-slope path-loss law fitted to the measurements, plus ITU-R P.526 terrain diffraction; greedy coverage siting | Propagation validated at **7.35 dB RMSE in sample, 9.66 dB held out by geography (R² +0.15)**. Siting solved, scenario planner shipped. Availability step remains weak — see [README](terrain-approach/README.md) |

Other approaches are being explored in parallel — add a sibling folder, a row here, and an
adapter implementing [the shared contract](common/README.md#1-the-contract).

## The terrain approach

Where `sionna-approach/` solves propagation by ray-tracing a reconstructed scene, this one
fits a parametric law to the measurements and adds terrain only where the data says terrain
matters. It runs in seconds and it carries a mechanism, so it can answer the counterfactual
the brief actually asks — *what happens if we put a transmitter over there?*

**Model** — two-slope log-distance path loss, n = 1.80 inside 3 km and 3.35 beyond, with one
azimuth harmonic for the three-sector beam. Terrain enters as ITU-R P.526 knife-edge
diffraction and first-Fresnel clearance, computed against USGS 3DEP 1/3 arc-second elevation
with a 4/3-earth bulge correction, and both orthogonalised against log-distance so they
cannot absorb the exponent. Availability is a sample-weighted isotonic curve on predicted
RSRP. Siting is a greedy maximum-coverage solve over 4,731 demand cells weighted 70%
route-km and 30% area.

**Validation** — 7.35 dB RMSE in sample, **9.66 dB held out by geography (R² +0.15)**. Two
blocking schemes are reported rather than one, because on a radial single-tower survey each
cut tests a different extrapolation; see the note in the shared facts below.

**What it concludes** — 44% of route-km has service today. One macro-class site at
41.97955, −93.83471 takes that to 69% and area coverage from 37% to 59%. A donor relay adds
1.4 route-km and a small cell 0.7, because a 20 dB power deficit costs an order of magnitude
of radius. **The brief's menu does not contain an asset that can fill a 9 km hole**, and
saying so is the finding rather than a failure to find one.

**Where it fails** — the availability step. Asked whether a given 200 m cell has service,
the model scores 59.5% against a 63.9% base rate. Received power it predicts well; service
state it does not. Read the ratios, not the absolute percentages —
[`terrain-approach/MODEL.md`](terrain-approach/MODEL.md) §4 is the full account, including
two bugs the backtest caught.

**Deliverables** — [`planner.html`](planner.html) at the repository root is the
parameterised planner: pick the simulator, the service definition (availability, RSRP, SINR,
RSRQ, or uplink/downlink throughput percentiles), the target, and the route-versus-area
weighting, and it re-solves the siting live. Three buttons sweep each of those axes and
report how far the recommended site moves. Alongside it, three map views and a six-slide
deck built from native PowerPoint objects.

> The older single-model page has been **deleted**. Its JavaScript evaluated an
> incomplete form of the fitted model — missing the dual slope, the Fresnel term and the
> orthogonalisation offsets — leaving it optimistic for a new node by a mean of 5.95 dB,
> RMS 8.37 dB. Its four analysis tabs have not been ported and are outstanding. See
> [`common/PLANNER.md`](common/PLANNER.md).

## Shared context

- [`COTS_Challenge_3.pdf`](COTS_Challenge_3.pdf) — the challenge brief
- [`Rural_COTS_RAN_Description.pdf`](Rural_COTS_RAN_Description.pdf) — dataset brief

The measurement dataset itself is **not in this repository** — see Licence below.

### Which columns are actually useful

Measured from the file, not assumed. Verdicts are for modelling service quality and siting;
an approach with a different objective may weigh them differently.

| column | verdict | evidence |
|---|---|---|
| `lat`, `lon` | **essential** | position; everything geometric depends on them |
| `rsrp` | **essential** | 5.91 bits over 82 levels, std 16.8 dB; best predictor of uplink (rho 0.78) |
| `cellid` | **essential** | 6 distinct values; identifies the serving sector, and its *null* state is the Challenge-3 signal |
| `timestamp_local` | **essential** | segments the 4 runs, enables leak-free splits, gives the ~2 dB repeatability floor |
| `uplink` | **high** | the binding constraint; "underserved" must be defined on it |
| `sinr` | **moderate, untapped** | 4.71 bits over 45 levels, rho 0.57 with uplink; the route to validating interference |
| `downlink` | **low** | useful as a contrast - saturates, rho only 0.34, which is what proves uplink binds |
| `ping_ms` | **low** | rho -0.16 Pearson, **-0.02 Spearman** with uplink - essentially decoupled from radio |
| `rsrq` | **near-zero** | **1.45 bits** over 12 levels, std 1.22 dB; its apparent correlation is co-variation with RSRP |
| `band` | **zero** | 1 unique value across all 7,144 rows |
| `arfcn` | **zero as a feature** | 2 values (`630720`, `-1`) - but decodes to 3.4608 GHz, which is foundational |

Three things that table does not show:

- **`arfcn` is worthless per row and critical once.** It sets the carrier frequency, hence
  wavelength, Fresnel radii and every material property in a physical model.
- **The most valuable content is the missingness.** 42% of rows have no valid serving cell,
  and those are exactly the locations Challenge 3 exists to fix. Any pipeline starting with
  `dropna()` deletes the answer.
- **Derived features beat most raw columns.** Distance to the serving site correlates -0.78
  with RSRP; bearing from the site recovers the sector azimuths; run ID enables the
  repeatability estimate. All three outrank `ping_ms`, `rsrq`, `band` and `arfcn` combined.

### Defining "underserved" — the choice that decides the answer

Candidate definitions barely overlap, so they are not competing thresholds for one thing;
they are different failure modes needing different interventions.

| definition | % of route | *additional* to no-service |
|---|---|---|
| **no serving cell** | **42.3%** | - |
| `sinr < 0` | 15.9% | **1,115 locations** |
| `uplink < 10 Mbps` | 6.1% | **381 locations** |
| `ping > 100 ms` | 3.6% | 187 |
| `rsrp < -110 dBm` | 2.3% | 143 |
| `downlink < 10 Mbps` | 0.6% | 16 |

- **no serving cell** -> coverage failure; a relay fixes this
- **served but low uplink** -> power- or capacity-limited; a relay probably fixes this
- **served, decent RSRP, negative SINR** -> interference-limited; **a relay does not fix
  this and may make it worse**

Folding that third group into "underserved" leads to recommending an asset that adds to the
interference. `sinr` is the parameter that prevents it, and nothing here has used it yet.

Uplink degradation with distance is monotonic and is the quantitative case for intervening:

| distance from Agronomy | median uplink | p10 | below 10 Mbps |
|---|---|---|---|
| 0-2 km | 62.9 Mbps | 31.5 | 0.4% |
| 4-6 km | 31.5 | 10.5 | 9.4% |
| 6-8 km | 15.5 | 2.3 | **30.7%** |
| 8-12 km | 10.5 | 1.6 | **42.4%** |

**Route importance.** 11.9% of 100 m cells were driven on 2+ separate runs, and they contain
33% of all samples - a weak but usable proxy for the route weighting the brief asks for.

### Facts about the data worth not rediscovering

- **42% of rows have no serving cell** (`cellid` null, or `FFFFFFFFF` with `arfcn = -1`).
  Those rows are a no-service state, not missing data, and they are the strongest signal in
  the dataset. A naive `dropna()` throws away exactly what the challenge is about.
- **`sinr` and `rsrq` load as object dtype** — 11 rows contain a literal `'-'`. Always
  `pd.to_numeric(..., errors='coerce')`.
- **Uplink is the binding constraint, not downlink.** Downlink saturates ~230 Mbps for any
  SINR > 0; uplink tracks RSRP hard and spans 8–63 Mbps. Define "underserved" on uplink, or
  a downlink-based objective will call everything fine.
- **Missing uplink/downlink is not missing-at-random** — it is missing exactly where
  service failed, which biases a service surface optimistic in the places that matter most.
- **Consecutive samples are ~22 m apart**, so a random train/test split leaks badly. The
  brief requires geographically separated test segments: split by spatial block or by run.
- Only 4 of 12 cells ever serve, and **Research Park serves 0 of 7,144 rows** — a free
  negative control for any propagation model.
- **Terrain shadowing dominates between 2 and 6 km and is irrelevant beyond it.** A
  Fresnel-obstructed cell is 2.25–2.39× more likely to have no serving cell than a clear cell
  the same distance out (p < 10⁻⁷); past 6 km the link budget has already gone and the effect
  vanishes. Bare line-of-sight is the wrong test — only 13% of links are geometrically
  blocked, but **46% intrude on the first Fresnel zone**. The holes are grazing paths.
- **Spatial cross-validation needs care on a radial survey.** Geography and the model's
  covariates are nearly the same variable here, so a contiguous held-out region is also a
  held-out slice of covariate space. KMeans on position carves out the near-tower cluster and
  leaves only **8.2%** of test points inside the training distance range — it measures
  extrapolation, not generalisation, and it will make a sound model look broken. Angular
  wedges keep 90% and hold out a bearing sector instead.
- **Fresnel clearance is 96.5% correlated with log-distance.** Fit it as a free term and it
  absorbs the distance effect, collapsing the path-loss exponent to 0.53. Orthogonalise
  terrain features against log-distance before fitting.
- **Terrain relief across the survey box is 98 m**, which is more than enough to shadow a
  link at 3.46 GHz from a 120 ft mast. The first Fresnel radius is 10–14 m at mid-path, which
  is what makes 1/3 arc-second (~10 m) the right DEM resolution and 1 m an oversample.

## Licence

The measurement dataset is **Arathon-only while non-public**. It may not be copied,
redistributed or published before ARA's official release. It is excluded from this
repository by `.gitignore`, along with derived files that carry measurement values or
coordinates. Keep this repository private.

Scene geometry derives from **OpenStreetMap (© OpenStreetMap contributors, ODbL)** and NASA
SRTM / Mapzen terrain tiles; USGS 3DEP elevation is public domain. Attribute these in any
published figure.
