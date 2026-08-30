# Where to build — and how much that depends on what you assumed

**ARATHON Challenge 03.** The brief asks for "sensitivity to placement constraints". A
single recommended latitude and longitude does not answer that, because a recommendation is
a function of five choices and the data hands us none of them:

| choice | options swept |
|---|---|
| **model** | ray-traced (`sionna-hybrid`) · fitted parametric (`terrain-parametric`) |
| **asset** | donor relay (−20 dB, 10 m) · small cell (−26 dB, 10 m) · macro-class (0 dB, 36.6 m) |
| **criterion** | availability · uplink p50 · uplink p10 · raw RSRP |
| **threshold** | 2–3 levels per criterion |
| **weighting** | route 0.7/area 0.3 · route only · area only |

`common/recommend.py` sweeps all of them — **198 combinations** — on one shared demand grid
(4,731 cells) and one shared candidate set (627 sites), so any difference between models is
the models and not their bookkeeping. Reproduce with
`python compare_recommendations.py`.

---

## 1. The headline: the *definition* of service matters more than the model

| varying… | comparisons | median move | p90 |
|---|---|---|---|
| **criterion** | 12 | **4.24 km** | 11.66 km |
| **asset** | 171 | **3.35 km** | 7.73 km |
| model | 81 | 2.06 km | 4.56 km |
| threshold | 162 | 1.28 km | 5.72 km |
| weighting | 180 | 1.21 km | 5.15 km |

Changing what counts as "service" — availability against uplink throughput — moves the
recommended site **twice as far as changing the propagation model**. Two teams could run
identical physics and land 4 km apart purely by defining underserved differently.

That reorders the priorities. Weeks of propagation modelling narrowed the model term to
2 km; the criterion term is larger and was chosen, not measured. **It should be argued for
explicitly in the write-up, not defaulted.**

---

## 2. Do the two models agree?

81 questions where both models were asked exactly the same thing:

| | |
|---|---|
| identical site (< 500 m) | **12%** |
| within 2 km | **48%** |
| median separation | **2.06 km** |
| 90th percentile | 4.56 km |

Under the default weighting:

| asset | criterion | terrain-parametric | sionna-hybrid | apart |
|---|---|---|---|---|
| macro | availability ≥ 0.5 | 41.9795, −93.8347 · **+23.8%** | 41.9651, −93.8003 · **+39.9%** | 3.26 km |
| macro | uplink p50 ≥ 10 Mbps | 41.9871, −93.8365 · +19.7% | 41.9709, −93.8002 · +39.4% | 3.50 km |
| relay | availability ≥ 0.5 | 42.0085, −93.8164 · +0.9% | 41.9942, −93.8487 · +2.6% | 3.11 km |
| relay | uplink p50 ≥ 10 Mbps | 41.9942, −93.8487 · +0.5% | 41.9942, −93.8487 · +2.6% | **0.00 km** |
| small cell | availability ≥ 0.5 | 41.9942, −93.8487 · +0.4% | 41.9942, −93.8487 · +1.1% | **0.00 km** |

They sometimes pick the *identical* candidate and sometimes sites 3.5 km apart. Two
systematic differences run through all of it:

- **The baseline differs.** `terrain-parametric` says 42.6% of weighted demand is served
  today; `sionna-hybrid` says 36.8%. A 5.8-point disagreement about the *present* propagates
  into every gain figure.
- **The ray tracer is consistently more optimistic about new assets** — 1.7× on the macro,
  2.9× on the relay. It resolves individual obstructions rather than a fitted average, so a
  candidate on a local high point is credited for it.

The worst disagreements (up to 13.6 km) are all **relay under area-only weighting**, which
is the least constrained question in the sweep: a −20 dB asset covers so little that
almost any placement scores nearly the same, so the optimum is nearly arbitrary and small
model differences decide it. That is a property of the question, not a fault in either model.

---

## 3. Where both models agree the asset menu runs out

At a demanding bar — **availability ≥ 0.9**, threshold −71.7 dBm — `terrain-parametric`
finds that **no placement of a relay or a small cell adds any coverage anywhere**. Gain is
exactly zero for all 627 candidates under every weighting. `sionna-hybrid`, whose calibrated
threshold is −77.1 dBm, finds a marginal +0.7% for a relay.

Both agree on the substance: **the brief's relay/repeater/small-cell menu cannot deliver
high-availability service in this geography.** Only the macro-class asset moves the number
(+3.1% to +13.4% at that bar; +23.8% to +39.9% at availability ≥ 0.5).

This is the third independent route to the same conclusion — a fitted law, a ray tracer,
and a link-budget decomposition from ARA's published radio specifications all say **power
dominates**.

---

## 4. The most-supported location

**41.97955, −93.83471** — about 6.8 km south-west of Agronomy Farm.

It is within 2 km of the site chosen by **93 of 180 (52%)** achievable parameter
combinations, across both models, all three assets, four criteria and three weightings. It
is also `terrain-approach`'s independently shipped recommendation.

That is the honest form of the answer: not "this is the optimum", but *this is the location
that survives the widest range of defensible assumptions.* Under half of the sweep something
else wins, and the ray-traced model's own macro pick sits 3.3 km away.

---

## 5. How to read this

**A single recommendation is not a defensible output here.** The right claim is bounded:

> Under a route-weighted availability criterion at 50%, a macro-class site near
> 41.98, −93.83 adds 24–40 points of covered demand depending on which propagation model you
> believe. A relay or small cell adds under 3 points under any assumption, and nothing at
> all at a 90% availability bar. The recommendation is stable to threshold and weighting
> (~1.2 km), moderately sensitive to the model (~2 km), and most sensitive to how service is
> defined (~4 km).

**What would tighten it.** The uncertainty model exists — σ = 7.5 dB with a 300 m
correlation length — but is not yet propagated into this sweep. Resampling correlated
shadow-fading fields and re-running the greedy would say how often each site stays on top,
which converts "52% of parameter combinations" into a probability. That is the last
substantive gap between this and what the brief asks for.

---

## 6. Reproduce

```bash
python compare_recommendations.py --out reports/recommendations.json
```

~9 minutes, dominated by one node surface per model per mast height (627 candidates ×
4,731 cells). Everything after that is arithmetic, which is why sweeping 198 combinations
is free. Outputs `reports/recommendations.{json,csv}`.
