# The planner

**One page. Every simulator, every service definition, every weighting — and it
re-solves the siting for whatever combination you dial in.**

```bash
python -m common.build_planner bundles/*.json \
       --dem terrain-approach/data/dem10.npz --out planner.html
```

Open `planner.html`. No server, no install, no network.

---

## What it is for

The old planner answered one question: *given availability at 50%, where should
the macro go?* That is one cell of a large table, and the repository's own
measurements say the rest of the table is not flat — changing the service
definition moves the recommended site by **up to 2.6 km and reverses its
direction**: a reliability target pulls the asset inward, an average-throughput
target pushes it out.

So the planner is parameterised on the four things that actually move the
answer:

| Control | |
|---|---|
| **Simulator** | which propagation model drives everything |
| **Criterion** | availability · RSRP · SINR · RSRQ · uplink p50/p10 · downlink p50/p10 |
| **Target** | the threshold on that criterion |
| **Route/area weight** | what the coverage score is actually worth |

plus asset class, mast height and transmit power.

Three buttons answer the question directly:

- **Sweep every criterion** — the best site under each service definition, and
  how far each sits from the first.
- **Sweep the route/area weight** — the same across weightings from pure area to
  pure route.
- **Compare every simulator** — the same across every bundle on the page.

If the recommended site barely moves across all three, the recommendation is
robust and you can say so with evidence. If it moves kilometres, that is the
finding, and burying it under one default would have been the mistake.

---

## How it re-solves so fast

The optimiser searches 627 candidates against 4,731 demand cells. Evaluating
that analytically in a browser is about three million path profiles **per
solve** — far too slow to be interactive. So the candidate × cell RSRP matrix is
computed once and reused for every criterion, threshold and weighting.

Where that matrix comes from depends on the bundle:

**Analytic bundles** (a fitted model with a closed form) ship **no matrix at
all**. The page carries the terrain grid at 31 m posts and builds the matrix
itself on first use, with a progress readout, then caches it. Cost: a few
seconds once, and zero payload. In exchange you get free placement — a pin
dropped anywhere gets a genuine prediction, not a lookup.

**Tabulated bundles** (a ray tracer, a neural operator — anything with no closed
form) carry the matrix. A dropped pin **snaps to the nearest candidate** and the
page tells you how far it moved it. To keep the file openable, the page thins
the candidate lattice by a factor of 2 (`--keep-every`), taking it from about
400 m to about 800 m spacing. That is inside the resolution these measurements
actually support — the robustness analysis locates a site to about 2 km, not to
a pole — but it does mean the page's optimum can sit a few hundred metres from
the offline one. The offline solve in `common/bundle.py` always uses the full
set.

---

## The formula family, and the bug it exists to prevent

An analytic bundle declares a **family** — a named formula plus the exact list
of coefficients needed to evaluate it — and the page implements families by
name.

This is not ceremony. The previous planner carried a hand-copied subset of its
model's constants. When the model gained a dual slope, a Fresnel term and two
orthogonalisation offsets, the copy was not updated and nothing complained. The
page evaluated the old formula and was **optimistic by a mean of 5.95 dB, RMS
8.37 dB, up to 31 dB** — larger than the model's own 7.35 dB residual σ — while
claiming to track the optimiser to 1%.

Now `common/schema.py::validate` refuses a bundle that cannot drive its own
declared formula, at build time.

**If you add a family**, add it to `schema.FAMILIES` *and* implement it in
`planner_tpl.py`, in the same commit. A family listed but not implemented is the
same bug wearing a different hat.

---

## Reading the page

**Map.** Green cells are served before anything is built; blue are the ones your
placement fixes; red stay unserved. Amber dot is the existing macro.

**Before → after.** Route-km, area, the weighted score, and how many currently
unserved cells the placement fixes.

**Service test: RSRP ≥ *x* dBm.** The criterion and target, inverted to a
received-power cut. This is the one inversion in the whole system — first grid
point at or above the target — and Python and JavaScript scan the *same*
0.05 dB grid. They disagreed once, at different resolutions, and produced a
3% difference in the service threshold.

**Model panel.** Every coefficient actually in use. If a number here does not
match your fitted model, the bundle is stale.

---

## Verifying a build

```bash
python -m common.test_js planner.html
```

Runs the page's JavaScript under QuickJS against a DOM shim. It catches the
failure that matters — an exception partway through initialisation that leaves
the lower half of the page blank while the top looks fine — and lists element
ids the script wants that the markup does not define.

To exercise the optimiser itself, not just page load:

```bash
python -m common.test_js planner.html --call "(function(){matCache={};var o='none';
  matrix(nearestAgl(),function(M){solve(M,1,function(p){
    o=JSON.stringify(B().prediction.candidates[p[0].i]);});});return o;})()"
```

This is slow under QuickJS — it is an interpreter doing what a JIT does in
seconds — but it is the check that the in-browser solve agrees with the offline
one. **It does not render**, so it cannot tell you the map is upside down. A
pass means "the page will load", not "the page is correct".

---

## What is not carried over

The single-model page it replaces had four analysis tabs — thresholds, live
robustness draws, per-asset gains, and a mast/power sensitivity sweep — that this
page does not yet have. That page has been deleted rather than deprecated,
because it evaluated the **incomplete** formula described above; the tabs are a
backlog item and should be rebuilt against the bundle, not resurrected.
