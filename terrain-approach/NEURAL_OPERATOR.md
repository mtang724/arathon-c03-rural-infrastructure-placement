# A neural operator against the diffraction physics

> **Status.** The framing, the model-by-model verdict (§1), the leakage analysis
> (§4) and the GeNeRT check (§6) are complete and final. The head-to-head
> results table is still computing at the time of writing; `src/fno_compare.py`
> writes it to `reports/fno_compare.json`.

Whether a deep learned model — FNO, TFNO, UNO, SFNO, CoDANO, NeRF2, GeNeRT —
can do the coverage mapping and siting in this project better than the fitted
terrain-aware model in [`MODEL.md`](MODEL.md).

§1 is the part that decides the outcome, and it is about the dataset rather
than the architectures. §4 is the measurement that says how to read any result.

---

## 1. One transmitter is the binding constraint

A neural operator learns a map between **function spaces**. To fit one you need
many `(input function, output function)` pairs. The natural framing for a radio
map is

```
(terrain patch, transmitter position)  ──►  received-power surface
```

and on this dataset that framing has **exactly one training example**, because
there is exactly one serving transmitter. Agronomy Farm serves 3,838 of the
7,144 rows; Curtiss and Wilson appear on ~100–180 sporadic samples each and fit
with R² ≈ 0. There is one input function and one output function. No amount of
architecture fixes a sample size of one.

That single fact disposes of the whole list *in this framing*:

| Model | Verdict in the (terrain, TX) → surface framing |
|---|---|
| **FNO / TFNO / UNO / WNO** in 2-D | n = 1. One input function, one output function. Not viable, whatever the architecture. |
| **NeRF2** | Learns a neural radiance field of the RF environment from many TX or RX positions. We have one TX and receivers confined to roads — a 1-D curve through a 3-D volume. Not viable, and this was argued and rejected earlier in the project on the same grounds. |
| **SFNO** | Spherical harmonics, built for global fields on a sphere. The survey box is 11 × 16 km. Wrong geometry, not a close call — and this `neuraloperator` build does not ship SFNO at all. |
| **CoDANO** | Codomain attention *across several coupled physical variables*. There is one output variable here, and far less data than its capacity would need. |
| **GeNeRT** | A different class of thing entirely — see §7. It needs a semantically labelled 3-D scene and ray-traced channel impulse responses to train on. We have a bare-earth DEM and scalar RSRP. |

Four of these are dead for reasons that no reframing repairs: NeRF2 and GeNeRT
want data we cannot collect from a COTS handset, SFNO wants a sphere, and CoDANO
wants coupled fields we do not have. The **FNO family is different** — it is
starved by the framing, not by the physics — so §2 changes the framing and runs
an FNO inside it.

**What was and was not run.** Only the FNO was trained and evaluated. TFNO, UNO
and a hand-built WNO are implemented at matched width and depth in
[`src/operators.py`](src/operators.py) and are one flag away
(`python src/fno_compare.py --architectures`), but they were not run — each
architecture is about ninety minutes on CPU and there was not time before
submission. What §4 shows is a property of the dataset rather than of the
Fourier basis, so there is little reason to expect a different basis to rescue
it, but that is an argument rather than a measurement and is labelled as one.

"We tried the fashionable thing and the data does not support it" is a result.
It is reported here rather than buried because the alternative — running a
2-D FNO on one example, reporting the training loss, and calling it a coverage
model — would have looked far more impressive and meant nothing.

---

## 2. The framing that *is* well-posed

Stop treating the **area** as the function. Treat the **terrain profile along
each link** as the function.

Every measurement is a link from the fixed tower to one receiver. Sample ground
elevation at 128 points along the great circle between them and you have a
genuine input function on [0, 1]; the received power is the output. That is
**3,838 examples of a real operator**, and it competes head-to-head with the
term it would replace.

The parametric model reduces that whole profile to two scalars before the fit
ever sees it:

```
J(v)   ITU-R P.526 knife-edge loss at the single worst obstruction
F      first-Fresnel clearance at that same point
```

An operator does not have to throw the rest of the profile away. So the question
is sharp, and it is a fair fight:

> **Can a learned operator beat textbook diffraction physics at turning a
> terrain profile into decibels?**

It also plugs into the planner with no new machinery. For a candidate
transmitter, walk the profile to each demand cell and run the network, exactly
where `macro_rsrp()` currently evaluates the diffraction term.

### The trap this experiment is built around

Fresnel clearance is **96.5% correlated with log-distance** in this dataset —
clearance is high near the tower and low far from it. That collinearity already
collapsed the parametric path-loss exponent to **0.53** once, before the terrain
terms were orthogonalised (`MODEL.md` §2.1). A profile sampled on an absolute
horizontal axis *encodes its own length*, so a network handed one will learn
distance, score well, and be measuring the wrong thing.

Three defences, all in the code:

- `profiles.py` normalises every profile to **unit horizontal length**. Distance
  cannot enter through the sampling grid.
- The residual variant is given the profile and nothing else, so it can only
  explain what the distance backbone left behind.
- The end-to-end variant is handed distance **explicitly**, as a channel, so the
  profile is not the only route to it.
- `corr(prediction, log d)` is reported for every model.

Worth noting on its own: the raw obstruction profile is far less
distance-confounded than the engineered feature it competes with.

| Quantity | corr with log-distance |
|---|---|
| Fresnel clearance `F` | **−0.965** |
| P.526 loss `J(v)` | +0.354 |
| max obstruction height along the profile | **+0.293** |
| mean obstruction height along the profile | −0.238 |

---

## 3. What was run

Four models, one control, on **`backtest.py`'s splits, imported rather than
reimplemented** — the same KMeans blocks and angular wedges, the same 200 m
training buffer, the same seed. A comparison on different splits would not be a
comparison.

| | |
|---|---|
| `parametric_terrain` | the shipped model: `fit_with_terrain` + `macro_rsrp` |
| `backbone_no_terrain` | distance + azimuth only, terrain terms deleted — what everything else has to beat |
| `pca_linear_residual` | ridge on the leading 12 principal components of the profile |
| `fno_residual` | **(a)** 1-D FNO on the normalised obstruction profile, predicting the backbone residual |
| `fno_end_to_end` | **(b)** 1-D FNO on the bare ground profile plus explicit distance and bearing channels |
| `fno_shuffled_control` | **(c)** variant (a) with profiles paired to the wrong links |

The backbone is `fit_with_terrain` with the two terrain terms removed and
nothing else changed — same one azimuth harmonic, same dual slope at 3 km, same
near-exponent bound of [1.8, 3.5], same bounded solver. Keeping it identical is
what makes the comparison fair: the parametric terrain terms and the operator
are both asked to improve on the *same* distance law.

`pca_linear_residual` is there because "the neural operator beat the physics"
and "any flexible learner beat the physics" are different claims, and only one
of them justifies reaching for a neural operator.

`fno_shuffled_control` is there because a model can score without using its
input. Whatever the shuffled control achieves is coming from the target
distribution, not from terrain, and any honest reading of variant (a) nets it
off.

---

## 4. The profile is a location fingerprint

Before any results, one measurement decides how they have to be read.

For every one of the 3,838 links, take the nearest *other* link in profile space
— plain L2 distance between the two 128-point profiles — and ask how far away it
is on the ground:

| | |
|---|---|
| Median ground separation of the profile-space nearest neighbour | **12.2 m** |
| 90th percentile | 29.3 m |
| Share within 50 m | **97.2%** |
| Share within 200 m | 99.6% |
| Same statistic for a randomly chosen partner | 5,072 m |

**A terrain profile is very nearly a unique identifier of where the receiver
was.** That is not surprising in hindsight — the profile is a 128-dimensional
descriptor of a specific line across a specific landscape — but it changes what
a good score means.

Consecutive COTS samples are 2.63 s apart, which is metres at driving speed. So
on a random split the same road metre appears in both halves, and a flexible
learner fitted on profiles can reach the answer by looking up its own training
set. It is not learning propagation. It is learning *this survey*.

Two consequences:

- **Any random-split number in this document is uninterpretable as skill**, for
  the neural operator specifically. `MODEL.md` §4 already discounts the random
  split for the parametric model; for a model that consumes a location
  fingerprint the problem is far worse.
- **`backtest.py`'s 200 m training buffer is exactly the right size.** 99.6% of
  profile-space nearest neighbours lie within 200 m, so dropping training rows
  inside that radius of any test row is what severs the lookup.

---

## 6. GeNeRT, checked rather than asserted

GeNeRT was the one name on the list worth checking properly rather than
dismissing from memory, so this section is written from the paper.

**GeNeRT: A Physics-Informed Approach to Intelligent Wireless Channel Modeling
via Generalizable Neural Ray Tracing** — Bian, Tao, Sun and Yu, arXiv
[2506.18295](https://arxiv.org/abs/2506.18295), 2025. It replaces the
deterministic reflection / diffraction / scattering models inside a ray tracer
with learnable modules, using relative geometric features, scatterer semantics
and a Fresnel-inspired polarisation-driven architecture, and it is trained in
three stages: module-wise pre-training, system-wise end-to-end training on
receiver-side channel impulse responses, and fine-tuning on sparse measured
multipath components.

It is a good piece of work and it is at **3.5 GHz**, which is our band. That is
the only thing about it that fits.

| GeNeRT needs | We have |
|---|---|
| A 3-D scene of convex polygonal surfaces with material properties | A **bare-earth** DEM. No buildings, no materials, and vegetation stripped by definition |
| One-hot scatterer **semantic classes** | No semantic layer at all |
| ~27,000 + ~6,087 training samples from **Wireless Insite** ray tracing | No commercial RT licence, and generating them presupposes the scene we do not have |
| Supervision by **channel impulse responses**; fine-tuning on measured **MPCs** | One scalar RSRP per sample. No delay, no angle, no per-path anything |
| Pretrained weights | **None published.** No code release is referenced in the paper |

So GeNeRT is not an alternative to the model in `MODEL.md`. It is a way to make
a *ray tracer* faster and more transferable, and the thing it would accelerate is
[`../sionna-approach/`](../sionna-approach/), not this one. Even there it would
need a semantically labelled scene and a simulator to learn from before it could
start, and the supervision signal it wants — full CIRs — is exactly what a COTS
handset cannot give you.

Reported here because "we could not use it" and "we did not look" are different
statements, and the first one needs the receipts.
