# Terrain-aware empirical propagation and coverage siting

**ARATHON Challenge 03** · a sibling to [`../sionna-approach/`](../sionna-approach/)

Where `sionna-approach/` solves propagation by ray-tracing a reconstructed scene,
this one fits a **parametric propagation law to the measurements themselves** and
adds terrain only where the data says terrain matters. It is cheaper, it runs in
seconds, and it carries a mechanism — so it can answer the counterfactual the
challenge actually asks: *what happens if we put a transmitter over there?*

It also ships the scenario planner, and an honest account of where it breaks.

---

## The short version

**Coverage today** — service available at least half the time — is **44% of
route-km and 37% of area** across the 178 km² survey box.

| Asset | Power vs the tower | Mast | Service radius | Route-km added |
|---|---|---|---|---|
| Donor relay | −20 dB | 10 m | ~520 m | +1.4 |
| Small cell | −26 dB | 10 m | ~256 m | +0.7 |
| **Macro-class** | 0 dB | 37 m | **~5.5 km** | **+28.6** |

**Recommended: 41.97955, −93.83471** — 6.8 km south-west, 37 m mast, on the road
network. Route 44% → **69%**, area 37% → **59%**.

**The brief's menu cannot solve this.** The fitted law is two-slope — n = 1.80
inside 3 km, n = 3.35 beyond — so in the far field every 10 dB lost costs roughly
half the radius. A relay is 20 dB down. A ~520 m bubble against a 9 km hole.

Power is what matters, not height: sweeping the mast from 6 m to 60 m moves the
coverage gain by 3%, while sweeping transmit power from 0 to 26 dB down collapses
it from 0.565 to 0.024. That is a change from what an earlier version of this
model said, and it is the terrain term being fitted properly that changed it.

**Why the holes are where they are.** Between 2 and 6 km from the tower, a
Fresnel-obstructed cell is **2.25–2.39× more likely** to have no service than a
clear cell the same distance out (p < 10⁻⁷). Past 6 km the link budget has
already run out and terrain stops mattering. Bare line of sight is blocked on
only 13% of links, but **46% intrude on the first Fresnel zone** — the holes are
grazing paths, not blocked ones.

---

## Read this before quoting a number

`src/backtest.py` runs the simulator with **no added unit** and compares it to
what the van actually recorded. It calls the shipped model rather than
reimplementing it, so what is tested is what ships.

| RSRP | MAE | RMSE | R² |
|---|---|---|---|
| In sample | 5.59 dB | **7.35 dB** | +0.803 |
| Naive random split | 5.60 dB | 7.33 dB | +0.803 |
| **Held out — KMeans blocks** | 7.63 dB | **9.66 dB** | **+0.154** |
| **Held out — angular wedges** | 8.05 dB | 9.78 dB | +0.054 |

Two blocking schemes are reported because on this dataset they measure different
things. The survey is radial around one tower, so geography and the covariates
are nearly the same variable, and any contiguous region held out is also a slice
of covariate space. KMeans carves out the near-tower cluster and forces
log-distance to extrapolate inward; angular wedges keep every distance but hold
out a bearing sector, testing the antenna term instead. Neither is cherry-picked.

**Availability is still the weak link:**

| | |
|---|---|
| Observed route-km served | **68.0%** |
| Simulated | **47.7%** |
| Cell-by-cell agreement | **59.5%** against a **63.9%** base rate |
| Brier score | 0.148 |

So: **received power we predict to 7.35 dB RMSE and it generalises. Whether a
given cell has service, we still do not beat "always say served."**

| Claim | Status |
|---|---|
| Dead spots at 2–6 km are terrain | **holds** |
| Service radii, the power law, device ranking | **holds** — geometry from a validated law |
| "44% now → 69% after" | **indicative only** |
| The site, to within 2 km | **holds** — 98–100% of shadow-fading draws |

Full account in [`MODEL.md`](MODEL.md) §4.

## Running it

The dataset is **not in this repository**. Point at it the same way
`sionna-approach/` does:

```bash
export COTS_DATA=/path/to/COTS_Dataset      # or drop it in terrain-approach/data/
pip install pandas numpy scikit-learn scipy pyyaml rasterio python-pptx
pip install torch neuraloperator          # only for the neural-operator comparison
```

Terrain: two USGS 3DEP 1/3 arc-second tiles, `USGS_13_n42w094.tif` and
`USGS_13_n43w094.tif` (~866 MB the pair), into `data/`. Get them from
[The National Map](https://apps.nationalmap.gov/downloader/) for bbox
`41.9225, −93.8921 → 42.0492, −93.6588`. They are gitignored — public data,
regenerable, and far past GitHub's file limit.

```bash
python run_all.py                        # features → model → optimise → planner
python src/propagation.py                # mosaic + clip the 3DEP tiles
python src/backtest.py                   # the honesty check above
python src/make_deck.py                  # six-slide deck
```

The neural-operator comparison is deliberately **not** in `run_all.py` — it
trains 48 networks and takes about an hour and a half on CPU:

```bash
python src/profiles.py                   # cache one terrain profile per link
python src/operators.py                  # check the db4 basis, size the four models
python src/fno_compare.py                # the comparison in NEURAL_OPERATOR.md
python src/fno_compare.py --capacity     # the same, with a much larger network
python src/fno_compare.py --architectures  # FNO vs TFNO vs UNO vs WNO
```

Then open `planner.html`.

---

## The tool

The planner now lives at the repository root — [`../planner.html`](../planner.html),
built by `common/build_planner.py` — and is parameterised over the simulator, the
service criterion (availability, RSRP, SINR, RSRQ, uplink/downlink p50 and p10)
and the route-versus-area weighting, re-solving the siting for whatever
combination you pick.

> `terrain-approach/planner.html` is the older single-model page. Its four
> analysis tabs have not been ported yet, but **its numbers are superseded**: its
> JavaScript carries an incomplete copy of the fitted constants and is optimistic
> for a new node by a mean of 5.95 dB, RMS 8.37 dB. See [`MODEL.md`](MODEL.md) §5.

Either way it is one self-contained HTML file — no server, no install, no network.
It carries the terrain grid at 31 m posts and runs the whole chain in JavaScript,
so a pin dropped anywhere gets a genuine prediction rather than a stored lookup.

Four tabs, one per thing the brief asks a team to demonstrate:

| Tab | |
|---|---|
| **Thresholds** | before/after at four explicit service definitions at once |
| **Robustness** | 150 fresh shadow-fading draws, run live, with the gain distribution |
| **Gains** | per device class at your location, and per successive installation |
| **Sensitivity** | gain swept against mast height and transmit power |

---

## Layout

This approach exposes its models to the repository-wide tools through
[`src/adapter.py`](src/adapter.py) — see [`../common/README.md`](../common/README.md).
Both the shared backtest testbench and the shared planner run on them:

```bash
python -c "import sys; sys.path[:0]=['..','src']; ..."   # see common/BACKTEST.md
```

```
src/
  adapter.py           the two models, behind the shared simulator contract
  config.py            every tunable assumption, one file
  features.py          COTS.csv → labelled frame (three service states)
  propagation.py       3DEP mosaic, Fresnel zone, ITU-R P.526 diffraction
  model.py             path-loss and isotonic service curves
  coverage_terrain.py  terrain-aware siting, the main solver
  profiles.py          per-link terrain profiles on a unit-length axis
  operators.py         FNO / TFNO / UNO / WNO at matched width and depth
                       (the wavelet transform is built and checked here)
  fno_compare.py       neural operators vs the diffraction physics
  robustness.py        path-specific shadow fading, four correlation models
  backtest.py          the zero-intervention check
  build_coverage_planner.py + planner_tpl.py   the tool
  make_deck.py         the six-slide deck
web/
  eda_template.html        the exploratory write-up, __DATA__ injected at build
  analysis_template.html   the full analysis write-up
  build_eda.py             injects reports/eda.json into the template
  test_js.py               runs a page's JavaScript under QuickJS against a DOM
                           shim — catches runtime errors before they blank a page
reports/               fitted constants and model summaries
data/                  regenerated locally, never committed
MODEL.md               the maths, in full
NEURAL_OPERATOR.md     the deep-learning comparison, and why most of it cannot work

planner.html           the scenario planner — open it directly
coverage_view.html     terrain + coverage, no dependencies
coverage_map.html      the same over satellite tiles; open from disk
survey_extent.html     the survey box and every measurement
ARA_Challenge3.pptx    six slides, native charts throughout
```

### What is and is not committed

**Committed**: source, the document templates, `MODEL.md`, and the model-summary
reports — fitted constants, siting results, robustness, backtest.

**Never committed**: `data/` and the measurement-bearing reports
(`eda.json`, `analysis.json`, `percentiles.json`). They carry measurement values
and coordinates, which the root `.gitignore` keeps out until ARA publishes, and
the two USGS tiles are 450 MB and 416 MB besides.

**Committed as a documented exception**: the four HTML tools and the deck. Each
embeds all 7,144 measurement positions, so they fall under the same policy even
though they are the deliverables. The repository is private and they are the
things a reader actually needs, so they are in — the `.gitignore` marks the block
to restore if that judgement changes.

Everything in either excluded category is rebuilt by the commands above.
