# The real deployment — published specifications and what the fit implies

The measurement dataset contains no transmit power, no bandwidth, no antenna model and no
tower height, so the twin absorbs all of them into one fitted constant (`offset` ≈ 26 dB,
see [`PARAMETERS.md`](PARAMETERS.md)). ARA publishes enough to recover most of them.

This document records what is externally established, what remains unknown, and what the
fitted constant decomposes into once the published numbers are applied. The arithmetic is
reproducible with [`analysis/link_budget.py`](analysis/link_budget.py).

Provenance keys extend those in `PARAMETERS.md`: **P** published by ARA or the vendor ·
**M** measured in the dataset · **I** inferred · **A** assumed · **F** fitted.

## Sources

- [ARA deployment page](https://arawireless.org/deployment/) — site list and site types
- [ARA capabilities](https://arawireless.readthedocs.io/en/latest/overview/ara_capabilities.html)
  — equipment inventory
- [ARA infrastructure](https://arawireless.readthedocs.io/en/latest/overview/ara_infrastructure.html)
  — band and array size
- Kumar et al., *Design and Implementation of ARA Wireless Living Lab for Rural Broadband
  and Applications*, [arXiv:2408.00913](https://arxiv.org/pdf/2408.00913) — Table 1 and §3.1
- Ericsson AIR 6419 product information (vendor spec sheets, secondary sources) — power and
  EIRP ratings

## What ARA publishes

| Quantity | Value | Prov. | Source |
|---|---|---|---|
| Radio unit | **Ericsson AIR 6419**, three per site | **P** | arXiv §3.1; capabilities page |
| Baseband | Ericsson Baseband 6647 gNB | **P** | capabilities page |
| Band | n77, **3.45–3.55 GHz** | **P** | infrastructure page; arXiv Table 1 |
| Channel bandwidth | **100 MHz** | **P** | arXiv Table 1 (AraMIMO-c) |
| Array | **192 antenna elements per sector**, 64T64R | **P** | arXiv §3.1 |
| Cell coverage | 8.5+ km | **P** | arXiv Table 1 — dataset shows Agronomy serving to 10.9 km |
| Sites | Agronomy Farm (**pole**), Curtiss Farm (**pole**), Wilson Hall (**rooftop**), Research Park (**rooftop**) | **P** | deployment page |
| Sectors per site | 3 | **P** | three AIR 6419 per site; matches the three cell IDs per site in `Base_Station_Information.yaml` |
| AIR 6419 rated max output | up to 320 W | **P** | vendor |
| AIR 6419 rated peak EIRP | 79 dBm | **P** | vendor (fully coherent data beam) |

### Still not published anywhere

- **Antenna height AGL** at any site. The paper says heights were "carefully chosen through
  coverage simulations and field testing" and gives no numbers.
- **Configured transmit power.** Reported as **~128 W** in an ARA new-user COTS training
  session (recollection, unverified — treat as **P?**). Consistent with the fit; see below.
- Downtilt, SSB beam-set configuration, per-sector azimuths.

### The `arfcn` column is the SSB frequency, not the carrier centre

The dataset reports NR-ARFCN 630720 → 3460.8 MHz. A 100 MHz carrier centred there would
span 3410.8–3510.8 MHz, which falls outside ARA's 3.45–3.55 GHz allocation, so it cannot be
the carrier centre. And 3460.8 = 3000 + 320 × 1.44 lands exactly on the NR SSB sync raster
(GSCN 7819). So the UE is reporting the **SSB position**; the carrier is the full
3.45–3.55 GHz block, centred near 3500 MHz.

Immaterial for propagation — 1.1% in frequency — but it is what makes the 273-PRB
subcarrier count below correct, and it explains an otherwise impossible-looking number.

## Decomposing the fitted constant

RSRP is power per **resource element**, so a total carrier power only meets the fitted
offset after division by the subcarrier count:

```
offset  = EPRE + G_real - G_model
EPRE    = P_total_dBm - 10*log10(N_subcarriers)
N_sc    = 273 PRB x 12 = 3276          (100 MHz at 30 kHz SCS, TS 38.101-1 Table 5.3.2-1)
G_model = 8.0 dB
```

`G_model` is **measured, not assumed**: integrating Sionna's `tr38901` element over the
sphere gives peak |F|² = 6.3096 → 8.0 dB boresight gain (and 9.83 dBi max directivity — the
pattern carries 1.8 dB of embedded loss). This is the gain already inside the traced path
gain, so it must be subtracted.

### The identifiable quantity

The fit constrains the **sum** `EPRE + G_real`, and cannot separate power from antenna
gain. That costs nothing, because the sum is exactly what a coverage prediction consumes:

| Quantity | Value |
|---|---|
| Per-RE EIRP at boresight, `offset + G_model` | **34.0 dBm** |
| Carrier-total SSB EIRP, `+ 10log10(3276)` | **69.2 dBm** |
| AIR 6419 rated peak EIRP | 79.0 dBm |
| → broadcast beam sits below the peak coherent beam by | **9.8 dB** |

A broadened SSB broadcast beam running ~10 dB below the unit's peak steered data beam is
the expected order of magnitude. **This is the first check of the twin's absolute scale** —
every previous result was relative, with `offset` free to absorb any error. Two independent
quantities, a nameplate power and a constant fitted from drive-test residuals, agree.

### The power / gain split

Each row is a consistent reading of the same measurement; the data cannot choose between
them, but all three are physically sensible. Peak array gain is ~24 dBi (the vendor's own
79 dBm EIRP at 320 W).

| P_total | dBm | EPRE dBm | implied SSB beam gain | below 24 dBi peak |
|---|---|---|---|---|
| **128 W** (reported) | 51.07 | 15.92 | **18.1 dBi** | −5.9 dB |
| 200 W | 53.01 | 17.86 | 16.1 dBi | −7.8 dB |
| 320 W (rated max) | 55.05 | 19.90 | 14.1 dBi | −9.9 dB |

## Consequences

### 1. The downtilt result is explained, and the fix changes shape

[`RESULTS.md`](RESULTS.md) records downtilt as monotonically harmful (9.77 dB at 0° →
10.23 dB at 10°), which is odd, since real sector antennas are tilted. The array explains it:
a 64T64R AIR 6419 with 192 elements does not have one boresight. It sweeps a **set of SSB
beams** across elevation, and the UE reports whichever beam is strongest. There is no single
downtilt to fit, so applying a mechanical tilt to one `tr38901` element is the wrong model
*shape*, not a badly chosen parameter value.

This reframes the antenna work in [`ACCURACY.md`](ACCURACY.md) §B3: model the SSB beam set,
or fit an empirical gain surface `g(elevation, azimuth-offset)` from training-block
residuals, rather than fitting a tilt angle. Expect the empirical pattern to look like an
*envelope* over beams — broader in elevation than any single element.

### 2. Antenna height must differ by site

[`PLAN.md`](PLAN.md) §1.1 generalises the surface to all 12 sectors. The 30 m assumption
comes from Agronomy Farm, which is a **pole**. Wilson Hall and Research Park are
**rooftops** — building height plus a short mast. Applying 30 m uniformly would misplace two
of the four sites in the "before" surface, which is the baseline every siting gain is
measured against.

### 3. Candidate assets need their own offsets

The siting pass in [`PLAN.md`](PLAN.md) §3.2 places candidate transmitters and states no
power, which silently scores every candidate as a 128 W AIR 6419 with an 18 dBi array. The
challenge asks about relays, repeaters and small cells, which are 19–37 dB weaker:

| Asset | EIRP dBm | vs macro | `offset` to use |
|---|---|---|---|
| Existing macro (AIR 6419) | 69.2 | — | 26.0 |
| Small cell, 5 W, 13 dBi | 50.0 | −19.2 | 6.8 |
| Repeater output, 2 W, 13 dBi | 46.0 | −23.1 | 2.9 |
| Small cell, 250 mW, 8 dBi | 32.0 | −37.2 | −11.2 |

Using the macro's 26 dB for a small cell overstates its coverage by 19–37 dB, which would
dominate any ranking of candidate sites.

### 4. Height may now be identifiable

Height reads as unidentifiable partly because `offset` is free to absorb any scale error.
With EIRP pinned by the nameplate power and antenna gain constrained to a plausible array
range, `offset` is no longer free — so residual scale error has to be geometric. Fitting
height with `offset` **fixed** is a far better-posed problem than the flat sweep in
[`RESULTS.md`](RESULTS.md), and it is cheap.

## Reproduce

```bash
python analysis/link_budget.py 26.0        # the decomposition above
```
