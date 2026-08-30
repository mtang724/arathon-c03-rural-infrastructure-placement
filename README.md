# Data-driven rural infrastructure placement

**ARATHON CHALLENGE 03** · AgWireless '26 / Rural Connectivity Research

> Where would one additional relay, repeater, small cell, or measurement campaign
> deliver the greatest improvement?

Given a UE drive test that covers roughly 7% of a rural service area near Ames, Iowa, the
challenge is to move from *describing* weak service to *recommending* a limited, defensible
intervention: predict performance where nothing was measured, then choose where one
additional asset does the most good.

## Approaches

Each approach lives in its own folder and can be read and run independently.

| Folder | Approach | Status |
|---|---|---|
| [`sionna-approach/`](sionna-approach/) | Physics-based ray tracing (Sionna RT) over real terrain and OSM building geometry | Twin validated at 8.58 dB RMSE on held-out blocks — [report](sionna-approach/REPORT.md). Siting optimisation not started |

Other approaches are being explored in parallel — add a sibling folder and a row here.

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

## Licence

The measurement dataset is **Arathon-only while non-public**. It may not be copied,
redistributed or published before ARA's official release. It is excluded from this
repository by `.gitignore`, along with derived files that carry measurement values or
coordinates. Keep this repository private.

Scene geometry derives from **OpenStreetMap (© OpenStreetMap contributors, ODbL)** and NASA
SRTM / Mapzen terrain tiles; USGS 3DEP elevation is public domain. Attribute these in any
published figure.
