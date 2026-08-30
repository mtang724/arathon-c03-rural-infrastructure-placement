# Rural COTS RAN UE Measurement Dataset

This dataset contains timestamped measurements collected from user equipment
(UE) operating on an ARA commercial off-the-shelf radio access network (COTS RAN)
in a rural setting. The collection route covered approximately five miles
south of the Agronomy Farm base station.

Each record combines geographic position, serving-radio information, radio
quality measurements, latency, and—when available—uplink and downlink test
results. The data can support research on rural coverage, performance
prediction, service-degradation detection, and network planning.

## Dataset file

Recommended filename:

```text
COTS.csv
```

The CSV uses one measurement per row and contains the following columns:

```text
timestamp_local,lat,lon,ping_ms,band,cellid,arfcn,rsrp,sinr,rsrq,uplink,downlink
```

## Collection context

| Attribute | Description |
|---|---|
| Environment | Rural |
| Network | ARA Ericsson COTS RAN |
| Measurement point | UE-side |
| Approximate coverage | Five miles around the base station |
| Example collection date | March 19 and 20, 2026 |
| Time zone in sample | US Central Time |
| Device and modem | Quectel RG530 |
| Throughput-test tool and server | *iperf* and ARA Data center |

The five-mile description should be interpreted as the approximate collection
area or route coverage, not necessarily a complete five-mile-radius survey.

## Schema

| Column | Suggested type | Unit | Description |
|---|---:|---:|---|
| `timestamp_local` | timestamp with time zone | — | Local measurement time; US Central Time. |
| `lat` | float | decimal degrees | UE latitude in WGS 84 coordinates. |
| `lon` | float | decimal degrees | UE longitude in WGS 84 coordinates. |
| `ping_ms` | float | ms | Measured round-trip latency. |
| `band` | string/category | — | Human-readable spectrum-layer label, such as `mid-band`. |
| `cellid` | string | — | Serving-cell identifier. Read as a string to preserve leading zeros. |
| `arfcn` | nullable integer | channel number | Absolute radio-frequency channel number reported by the UE or collection tool. |
| `rsrp` | float | dBm | Reference Signal Received Power; more negative values indicate weaker received power. |
| `sinr` | float | dB | Signal-to-Interference-plus-Noise Ratio; higher values generally indicate a cleaner radio channel. |
| `rsrq` | float | dB | Reference Signal Received Quality; values closer to zero generally indicate better quality. |
| `uplink` | float, nullable | Mbps | Observed uplink test result. Likely a throughput measure, but its unit must be verified. |
| `downlink` | float, nullable | Mbps | Observed downlink test result. Likely a throughput measure, but its unit must be verified. |

## Example record

```csv
timestamp_local,lat,lon,ping_ms,band,cellid,arfcn,rsrp,sinr,rsrq,uplink,downlink
2026-03-19 13:16:24.870373-05:00,42.0205489,-93.7768082,26.0,mid-band,00019C01F,630720.0,-51.0,18,-10,53.8,168.0
```

## Missing values

Some rows may contain radio and latency measurements without uplink or
downlink results. Empty values should be parsed as missing (`NA`/`null`), not
as zero.

Missing active-test results can occur because of out of coverage or software error at the UE.

## Suggested derived features

Useful features that can be calculated from the raw records include:

- Distance from the base station, if its coordinates are available
- Distance and time elapsed between consecutive samples
- Estimated UE speed and stationary/moving status
- Route segment or geographic grid-cell identifier
- Rolling mean, variance, minimum, maximum, and slope for radio measurements
- Uplink-to-downlink ratio for rows containing both test results
- Radio or performance change points along the route
- Distance band, time-of-day group, and collection-run identifier

Derived speed should be treated carefully when timestamps are widely spaced or
GPS positions are noisy.

## Potential research uses

The dataset is suitable for hackathon projects such as:

1. **Predictive rural network digital twin:** Predict latency and throughput at
   unmeasured locations and display prediction uncertainty.
2. **Explainable service-degradation diagnosis:** Identify locations that are
   likely coverage-limited, interference-limited, or affected by non-radio
   constraints.
3. **Proactive connectivity warning:** Predict a latency spike or throughput
   drop from a short history of UE measurements.
4. **Uplink-downlink imbalance analysis:** Determine where uplink service
   becomes limiting while downlink service remains usable.
5. **Infrastructure or measurement placement:** Recommend where an additional
   relay, repeater, small cell, or measurement campaign could provide the most
   benefit.


## Limitations

- UE-side measurements alone cannot conclusively identify congestion,
  scheduling, interference, backhaul, or test-server problems.
- Latency and throughput can depend on the UE, modem state, test server,
  transport protocol, network load, and collection procedure.
- A single route or collection period cannot establish recurring time-of-day
  congestion.
- Results from one cell, device, band, route, or rural site may not generalize
  to other deployments.
- Sparse route measurements do not represent uniform coverage of the entire
  surrounding area.
- The supplied example does not establish the full dataset's row count,
  duration, number of cells, or number of collection runs.


## License

This dataset is provided exclusively for use in the Arathon (AgWireless 2026) while it remains non-public. It may not be copied, redistributed, published, or reused outside the Arathon before its official public release.

Once the dataset is officially made public, it may be reused in accordance with the license and terms accompanying that release. The dataset should not be considered publicly available until an authorized public release location has been announced.