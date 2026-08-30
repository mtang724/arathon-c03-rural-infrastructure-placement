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
| [`sionna-approach/`](sionna-approach/) | Physics-based ray tracing (Sionna RT) over real terrain and OSM building geometry | Twin built and validated; siting optimisation not started |

Other approaches are being explored in parallel — add a sibling folder and a row here.

## Shared context

- [`COTS_Challenge_3.pdf`](COTS_Challenge_3.pdf) — the challenge brief
- [`Rural_COTS_RAN_Description.pdf`](Rural_COTS_RAN_Description.pdf) — dataset brief

The measurement dataset itself is **not in this repository** — see Licence below.

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
