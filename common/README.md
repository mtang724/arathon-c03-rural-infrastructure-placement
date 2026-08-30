# `common/` — the shared platform

Every simulator in this repository predicts the same thing from the same
measurements. This directory is what lets them be **compared** rather than each
shipping its own numbers in its own format.

Three tools, one contract:

| | |
|---|---|
| **[The contract](#1-the-contract)** | `simulator.py` — two methods. Implement them and everything below works on your model. |
| **[The backtest testbench](BACKTEST.md)** | `backtest.py` — identical splits, identical metrics, for every model. |
| **[The planner](PLANNER.md)** | `build_planner.py` — one page, every simulator, every objective, live re-optimisation. |

`common/` **never imports an approach.** Approaches import `common` and expose
their models. Keeping the dependency one-way is what lets a new approach be
added without touching an existing one.

---

## Why this exists

Two failures motivated it, and both are worth knowing before you trust anything
here.

**The planner and the optimiser drifted apart.** The planner carried its model's
constants in a hand-copied dictionary. When the model gained a dual slope, a
Fresnel term and two orthogonalisation offsets, the dictionary was not updated
and nothing complained. The page kept evaluating the old formula and was
optimistic by a **mean of 5.95 dB, RMS 8.37 dB, up to 31 dB** — larger than the
model's own 7.35 dB residual σ — against the very optimiser it claimed to track
to 1%. The fix is not vigilance. It is that a bundle now declares its **formula
family**, `schema.validate` refuses a bundle that does not carry every
coefficient that family needs, and the consumer implements the family by name.

**A curve was fitted on one model's RSRP and read with another's.** Up to 6.9 dB
apart on distance alone. It made the simulator claim 44.6% of measured route-km
had service where the measurements said 68.0%. So: every criterion is calibrated
against the predicted RSRP of the simulator that will read it, and nothing is
shared between simulators except the demand grid and the measurements.

---

## 1. The contract

```python
from common.schema import SimulatorInfo

class MySimulator:
    info = SimulatorInfo(name="my-model", label="My model",
                         approach="my-approach", sigma_db=7.3)
    sigma_db = 7.3

    def macro_rsrp(self, lat, lon):
        """dBm from the EXISTING serving macro at each point."""

    def node_rsrp(self, tx_lat, tx_lon, agl_m, eirp_deficit_db, lat, lon):
        """dBm from a NEW omni node at (tx_lat, tx_lon)."""

    def refit(self, train):
        """A copy fitted only on `train`. Return `self` if nothing fits."""
```

That is the whole interface. It was not designed up front — it is what turned
out to be sufficient to run two completely unrelated models through one siting
pipeline, so it is the smallest thing known to work.

### Units, so two models mean the same thing by the same word

| | |
|---|---|
| `lat`, `lon` | degrees WGS84, numpy arrays of equal length |
| return value | **dBm**, one per input point, same shape |
| `agl_m` | antenna height above **ground level at the transmitter**, metres |
| `eirp_deficit_db` | dB **below the existing macro**. Never absolute EIRP — the macro's EIRP is not observed anywhere in this dataset, so no model here is entitled to claim absolute power. |
| `sigma_db` | standard deviation of **your** model's residual against the measurements. The robustness analysis draws shadow fading from it, so borrowing another model's σ would let a worse fit inherit a tighter uncertainty band than it earned. |

### Check it before you trust it

```python
from common.simulator import check, describe
check(my_sim, df.lat.to_numpy()[:200], df.lon.to_numpy()[:200])
print(describe(my_sim))
```

`check` catches the things that are otherwise invisible until three stages
downstream: a shape that silently broadcasts, a model returning linear watts
because it forgot to convert, and — the one that actually bites — a `node_rsrp`
that **ignores its EIRP deficit**. A relay that radiates like a macro sails
through siting and is wrong on site.

### Models with nothing to fit

A ray tracer working from a scene and physics has no fitted constants, so
`refit` returns `self`. That is not a loophole: the testbench records
`fitted: false`, reports it, and notes that no leakage is possible — a
genuinely **stronger** position than a fitted model can claim. Its in-sample and
held-out columns should agree; if they do not, something else is wrong.

---

## 2. The bundle

One JSON file per simulator. It is what the planner reads, and what you hand
someone who wants your results without your code.

```python
from common.bundle import build
build(my_sim, df, macro_lat, macro_lon, out="bundles/my-model.json")
```

That single call builds the shared demand grid and candidate set, asks your
model for the baseline, calibrates every service criterion against **your**
model's RSRP, precomputes RSRP from every candidate to every demand cell, and
solves the greedy siting. See [`schema.py`](schema.py) for the format.

### Two prediction modes

**`analytic`** — your model declares a formula family and its coefficients, and
the planner evaluates it live, so a pin dropped anywhere gets a genuine
prediction. Add an optional method:

```python
def bundle_prediction(self):
    return "two_slope_terrain/1", {...every coefficient the family lists...}
```

Families live in `schema.FAMILIES`. **Adding one is a deliberate act**: every
consumer that claims to support a family must implement it, and `validate` holds
your bundle to the coefficient list. If your model does not fit an existing
family, add yours to `FAMILIES` *and* implement it in `planner_tpl.py`, in the
same commit.

**`tabulated`** — you omit `bundle_prediction` and the bundle carries a
precomputed candidate × cell matrix. This is the only mode available to a model
with no closed form — a ray tracer, a neural operator. The planner snaps a
dropped pin to the nearest candidate and says how far it moved it.

Either way the optimiser works identically, because the optimiser only ever
searches the candidate set.

---

## 3. Worked example — adding `sionna-approach`

```python
# sionna-approach/src/adapter.py
import numpy as np
from common.schema import SimulatorInfo
from common.simulator import Unfitted

class SionnaSimulator(Unfitted):          # ray tracing: nothing is fitted
    def __init__(self, scene, calib_db):
        self.scene = scene
        self.offset = calib_db            # one scalar tying it to observed RSRP
        self.sigma_db = 8.1               # measured, not guessed
        self.info = SimulatorInfo(
            name="sionna-rt", label="Sionna ray tracing",
            approach="sionna-approach", sigma_db=8.1, fitted_on_rows=0,
            notes="Path gain from a reconstructed OSM + 3DEP scene.")

    def macro_rsrp(self, lat, lon):
        return self.scene.path_gain_db(self.macro_tx, lat, lon) + self.offset

    def node_rsrp(self, tx_lat, tx_lon, agl_m, eirp_deficit_db, lat, lon):
        tx = self.scene.transmitter(tx_lat, tx_lon, agl_m)
        return (self.scene.path_gain_db(tx, lat, lon) + self.offset
                - eirp_deficit_db)
```

Then:

```bash
python -c "
import sys; sys.path[:0]=['.','sionna-approach/src']
import pandas as pd
from adapter import SionnaSimulator
from common.bundle import build
from common.simulator import check
df = pd.read_csv('.../labeled.csv')
sim = SionnaSimulator(...)
check(sim, df.lat.to_numpy()[:200], df.lon.to_numpy()[:200])
build(sim, df, 42.0206, -93.7768, out='bundles/sionna-rt.json')"

python -m common.build_planner bundles/*.json --dem terrain-approach/data/dem10.npz
```

Your model is now a dropdown entry in the planner, sitting beside every other
model, scored on the same demand grid with the same optimiser.

**Reference implementation:** [`terrain-approach/src/adapter.py`](../terrain-approach/src/adapter.py)
has two — one analytic (fitted physics) and one tabulated (a neural operator).
They share nothing except this interface, which is the point.

---

## 4. What is shared, and what is deliberately not

**Shared, so that a comparison is a comparison:**
the demand grid and its de-duplicated route-km; the candidate set; the greedy
solver; the asset class definitions; the backtest splits, buffer and seed; the
RSRP grid every criterion curve is sampled on.

**Not shared, on purpose:**
every criterion curve (calibrated per simulator, against its own RSRP), and
`sigma_db` (each model's own residual spread). Sharing either would let one
model borrow another's calibration.

---

## 5. Files

```
schema.py          the bundle format, the formula families, and validate()
simulator.py       the contract, plus check() and describe()
demand.py          demand grid, candidates, scorer, greedy solver
criteria.py        RSRP -> availability / SINR / RSRQ / throughput curves
bundle.py          build(): one simulator in, one bundle out
backtest.py        the testbench                    -> BACKTEST.md
selftest.py        reproduce published reference numbers, or fail loudly
build_planner.py   assemble the page from bundles   -> PLANNER.md
planner_tpl.py     the page itself
test_js.py         run a generated page under QuickJS before shipping it
deckkit.py         native-PowerPoint drawing kit (no images, all vector)
make_deck.py       the project deck; one slide per simulator, reserved until built
```

## 6. Running

`common/` needs the repository root on `sys.path`, and an approach's `src/` if
you are using its adapter:

```bash
python -c "import sys; sys.path[:0]=['.', 'terrain-approach/src']; ..."
```

Dependencies: `numpy`, `pandas`, `scikit-learn`. `test_js.py` also needs
`quickjs`. Nothing here needs `torch` unless the adapter you load does.
