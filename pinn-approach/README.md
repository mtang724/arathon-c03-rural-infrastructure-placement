# `pinn-approach/` — a physics-informed neural network, and why it loses

**Replication of ReVeal (IEEE DySPAN 2025) and ReVeal-MT (arXiv 2512.04100) —
from the group that runs ARA — on the COTS drive test.**

> **Read this first.** This model is **third of three** on the splits that
> decide anything, and it is in the repository because the *reasons* are
> measurable and transferable, not because it wins. If you want a coverage
> surface, use `terrain-approach/` or `sionna-approach/`.

## Where it lands

`common/backtest.py`, identical splits, 200 m buffer, RMSE in dB. The two
right-hand columns are the ones that decide anything.

| model | in sample | random split | **KMeans blocks** | **angular wedges** |
|---|---|---|---|---|
| sionna-hybrid (Agronomy) | 7.61 | 7.59 | **7.95** | **7.80** |
| terrain-parametric | 7.35 | 7.33 | **9.59** | **9.81** |
| sionna-hybrid (full network) | 9.02 | 9.01 | 9.97 | 8.86 |
| terrain-fno | 7.26 | 7.52 | 14.04 | 11.47 |
| **reveal-mt-pinn** | **5.63** | 5.92 | 15.83 | 15.09 |

**Best of all five in sample by 1.6 dB, last on both geographic splits.**

Read it beside `terrain-fno`, which landed independently. Both neural models
show the same signature — strong in sample, collapsing on geography — from
completely different architectures: a 1-D FNO over terrain profiles, and a
physics-informed MLP over position. Neither beats the fitted physics where the
challenge is decided. **Two architectures, one conclusion**, which is a much
stronger statement than either could make alone.

The random-split column is a **contamination gauge, not a score**. We "win" it
because position is the model's entire input, so it can answer by looking up its
own training set. `BACKTEST.md` warns about exactly this; ReVeal is the extreme
case of it, and `NEURAL_OPERATOR.md` §4 measures why.

Its service classifier scores **58.9% against a 63.9% base rate** — below the
base rate, i.e. worse than answering "served" every time. `terrain-approach`
reports the same failure at 60.5%; ours is slightly worse.

The random-split column is a **contamination gauge, not a score**. We "win" it
because position is the model's entire input, so it can answer by looking up its
own training set. `BACKTEST.md` warns about exactly this; ReVeal is the extreme
case of it.

## What the method is

Input `(lat, lon)`, output RSRP. A 3 × 304 MLP over a parametric multi-transmitter
path-loss law (paper eqns 9–14):

```
a_i(x,y) = (1/10)·( EIRP_i + G_i(bearing) − 10·η·log10(r_i/d0) + Z(x,y) )
RSRP     = 10·log10( Σ_i 10^a_i )
```

The physics loss asks the predicted field's Laplacian to match the observed
field's, which works because **log-distance path loss is harmonic in 2-D**: the
Laplacian of log(r) is zero, so the transmitter cancels out of the constraint
entirely and the method needs no transmitter location or power.

Sanity checks that it learns real physics rather than memorising — both were
**free** parameters: fitted per-sector EIRP lands at 46.9–50.0 dBm, and the
path-loss exponent at **η = 2.39** against a measured log-distance exponent of
**2.44**.

## Four findings, all measured

**1. The published ReLU activation makes the physics loss a mathematical no-op.**
A ReLU network is piecewise *linear* in its input, so its second derivative is
exactly zero almost everywhere: the predicted Laplacian is identically 0 and the
physics term contributes no gradient at all. Measured — mean |∇²|: **0.000e+00**
(ReLU) against **1.66e-02** (SiLU). Both papers specify ReLU in Table II. This
module uses SiLU; `--act relu` reproduces the published choice.

**2. The PDE term is close to unobservable from a drive test.** `∇²P_obs` is
undefined for scattered points and neither paper says how it was computed. A
local quadratic fit — the obvious choice — returns sd **1.25e+02 dB/m²** where
the physically possible scale is **1.6e-06**: too large by eight orders of
magnitude, because road neighbourhoods are near-collinear (condition number
median 2.3e+04) and a 6-term 2-D quadratic is unidentifiable on them. Binning to
a grid and using a 5-point stencil fixes the conditioning but not the supply: a
cell needs all four neighbours populated, and on a road network that yields **at
most 17 usable collocation points out of 4,121 measurements**. No λ > 0 improved
held-out error, so this ships at **λ = 0**. ReVeal sampled a 2-D *area* via the
Local Pivotal Method; a route samples a curve, and second derivatives across a
curve are unobservable.

**3. An unbounded field extrapolates to +395 dBm.** On a held-out bearing wedge
the original model predicted received power greater than the power transmitted,
while scoring 7.5 dB on its own training rows in the same fold — an MLP over
(x, y) has no constraint outside the convex hull of its training data. The fix
is `Z = z0 + Z_MAX·tanh(net/Z_MAX)`: a free scalar offset absorbing the
unobserved EIRP, plus a ±20 dB bounded spatial variation that is genuinely
shadowing. Clamping the *sum* instead does not work — unbounded, Z spans −120 to
−43 dB, so a ±25 dB clamp saturates 100% of points and in-sample RMSE goes
6.94 → 44.39 dB. `z0` also needs a data-driven init and its own dB-scale
learning rate; at the network's it moves too slowly to converge and the fit
stays broken at 35 dB. Bounded, the model predicts −120…−47 dBm across the whole
demand grid.

**4. Giving it terrain makes it worse.** The obvious remedy was that it flies
blind while `terrain-approach` is *handed* P.526 knife-edge loss and Fresnel
clearance. Supplying both, orthogonalised against log-distance:

| model | 800 m segments | KMeans | angular wedges |
|---|---|---|---|
| log-distance control (4 constants) | 14.18 | 28.61 | 14.97 |
| PINN, position only | **12.90** | 23.49 | **14.23** |
| PINN + terrain | 17.55 | **22.35** | 15.32 |

Worse on two of three. The reason is the one this repository already documents:
the terrain features are **themselves a location fingerprint**. The nearest
neighbour in (J, Fresnel-v) space sits a median of **137 m** away on the ground,
44% within 50 m, against 5,071 m for a random partner. Handing them over adds
memorisation capacity, not physics — and the 200 m buffer exists to defeat
memorisation. (`terrain-approach/NEURAL_OPERATOR.md` §4 measures the same thing
for full 128-point profiles: median 12.2 m, 97.2% within 50 m.)

Our feature values agree with this repository's published correlations against
log-distance — J **+0.346** against **+0.354**, Fresnel v **+0.931** against
**+0.965** — so the two codebases compute the same physics and the disagreement
is about the model, not a bug on either side.

## Why this is worth keeping

`NEURAL_OPERATOR.md` argues from the dataset that learned coverage models cannot
work here: one transmitter, R² ≈ 0 for the other sites. This reaches the same
conclusion from a different direction — a *physics-informed* network, from the
group that runs the testbed, on their own data — and adds a sharper statement of
why: **every input you can give it is also a location label**, so more
information makes memorisation easier rather than physics easier.

It also earns a place in the planner's *"compare every simulator"* view. A third
method sharing no physics with either of the others makes the disagreement
between models more informative, and this repository already treats that
disagreement as the finding.

## Running it

```bash
python -c "import sys; sys.path[:0]=['.','pinn-approach/src']; \
           import run_bench" # contract check + full testbench
```

Needs `torch` (CUDA optional). The measurement frame is built from the shared
labelled features; **blank `cellid` must be normalised to NaN first** — 2,885 of
7,144 no-service rows carry a blank *string*, and `Testbench.from_frame` derives
outage as `cellid.isna() | cellid.eq("FFFFFFFFF")`, which silently misses every
one of them and reports a 99.8% base rate instead of 63.9%.

## Files

```
src/adapter.py           the model behind common/'s simulator contract
src/adapter_terrain.py   the terrain-fed variant (finding 4)
src/run_bench.py         contract check + full testbench
```
