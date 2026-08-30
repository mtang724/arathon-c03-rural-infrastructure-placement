# Data request to ARA

**ARATHON Challenge 03 — Data-driven rural infrastructure placement**

What we would ask for, ranked by how much it would change our results. Ordering is based on
measured evidence, not guesswork: see [`REPORT.md`](REPORT.md) for the experiments behind
each justification.

## Why more of the same data is not the ask

The current campaign is **repeatable to ~2 dB**. Across 255 locations revisited on separate
drive runs with the same serving cell, RSRP agrees to a 2.1 dB standard deviation (3.0 dB
median range); within-run, within-25 m spread is also 2.1 dB.

Our model's error against those measurements is **8.58 dB**. The gap between 2 dB of
measurement repeatability and 8.6 dB of model error is **systematic and spatially
deterministic** — it is not noise, and it is not temporal variation. Six geometric and
material hypotheses have each failed to explain it (terrain resolution, diffraction, ground
permittivity, downtilt, earth curvature, vegetation), each moving RMSE by ≤0.15 dB.

That points at the transmitter, which is the largest object in the model we know almost
nothing about. Hence the ordering below.

---

## Tier 1 — would directly attack the 8.6 dB error

### 1. Antenna and sector configuration, per cell

For each of the twelve cells (`00019400B` … `0001A001F`):

- **Antenna model / part number** — so we can obtain the real radiation pattern instead of
  the generic `tr38901` we currently substitute
- **Height above ground level** of the antenna centre
- **Azimuth** (we infer 0° / 115° / 240° at Agronomy from bearing analysis — please confirm)
- **Mechanical downtilt** and **electrical downtilt** separately
- **Antenna gain** (dBi)
- **Transmit power / EIRP** per sector

*Why:* antenna height is currently **not identifiable** from the data — model error is flat
from 15 m to 60 m — and EIRP plus antenna gain are collapsed into a single fitted constant
(~26 dB) that absorbs whatever is wrong. Nothing else on this list is worth as much.

### 2. Reference-signal configuration

- **SSB transmit power** and periodicity, numerology, channel bandwidth
- How **RSRP, RSRQ and SINR** are computed and quantised by the UE or collection tool

*Why:* RSRP is defined per resource element on the SSB. Without SSB power we cannot convert
modelled path gain into absolute RSRP except through a fitted offset. Separately, `rsrq` in
the dataset has a standard deviation of only 1.2 dB with half its mass in [−11, −10], which
suggests heavy quantisation or a non-standard definition — we would like to know which.

---

## Tier 2 — would unlock validation we currently cannot perform

### 3. Neighbour-cell measurements

RSRP/RSRQ of **non-serving** cells, not only the serving cell.

*Why:* we can currently only validate the model where a cell *won* the handover competition,
which is a badly biased sample — every validation point is one where our predicted-strongest
cell also happened to be the measured-strongest. Neighbour reports would let us validate the
three-sector pattern directly, and would turn **Research Park** — which serves 0 of 7,144
rows — from an untested negative control into a real one.

### 4. Timing relationship between radio samples and throughput tests

Were the `iperf` uplink/downlink tests concurrent with the radio measurement in the same row,
or interleaved? What was the test duration and direction order?

*Why:* it determines whether throughput can legitimately be regressed on the RSRP in the same
row, which every service-surface model here assumes.

---

## Tier 3 — needed to make "underserved" mean the right thing

Uplink is the binding constraint in this dataset: downlink saturates near 230 Mbps for any
SINR > 0, while uplink tracks RSRP hard across 8–63 Mbps.

### 5. UE power headroom reports and UE transmit power

*Why:* this distinguishes a UE that is **power-limited** (a coverage problem, fixed by a
relay) from one that is **scheduling- or interference-limited** (not fixed by a relay). That
distinction determines whether the challenge's recommended intervention is even the right
kind of intervention.

### 6. Uplink MCS, PRB allocation and BLER

### 7. UE antenna gain, mounting height and orientation on the vehicle

---

## Tier 4 — network-side context

### 8. Per-cell PRB utilisation and connected-user counts during the campaign

*Why:* the dataset documentation states that UE-side measurements alone cannot separate
congestion, scheduling, interference and backhaul effects. A single load counter would.

### 9. Backhaul capacity and utilisation per site

---

## Tier 5 — required before any placement recommendation is operational

The challenge asks where one additional asset should go. Without a feasible set, that
optimisation is unconstrained and its answer is not actionable.

### 10. Siting constraints

- Where **grid power** and **fibre or backhaul** are available
- **Existing structures** that could host a relay — grain legs, silos, water towers, barns,
  existing poles — with heights
- **Land access / easement** constraints, and any exclusion zones

### 11. Deployment economics

Relative cost and lead time for each asset class the brief names (relay, repeater, small
cell, measurement campaign), plus the coverage or capacity each is expected to deliver.

*Why:* the brief asks which intervention "delivers the greatest improvement". Without
relative costs, the four asset types cannot be compared and the answer defaults to whichever
has the largest coverage footprint.

---

## Tier 6 — would test our specific open hypotheses

### 12. A repeat drive in a leafed-out season

*Why:* the campaign is 19–20 March, pre-planting, bare deciduous. We measure a real
vegetation effect — the model over-predicts by +4.5 dB on paths crossing woodland, with a
clean dose-response — but it affects only 9.2% of paths in March. A July repeat would show
whether that becomes a first-order effect in leaf, and whether the same recommendation holds
across seasons.

### 13. Static long-dwell measurements at a handful of fixed points

*Why:* several minutes stationary at known coordinates would separate fast fading from
shadowing cleanly and give an independent estimate of the measurement floor, rather than the
~2 dB we infer from opportunistic revisits.

### 14. Ground truth for the four sites' surroundings

Whether the immediate surroundings of each site changed between March 2026 and now — our
OpenStreetMap extract is a current snapshot, roughly five months newer than the campaign.
