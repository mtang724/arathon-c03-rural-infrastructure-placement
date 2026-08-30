# Handoff — ARA Rural COTS RAN digital twin (Blender + Blosm + Sionna)

## Goal

Arathon / AgWireless '26 **Challenge 3: data-driven rural infrastructure placement.**
Use Sionna RT over an OSM/terrain scene of the ARA testbed area (Ames, Iowa) to fill the
gaps in the measured dataset — predict coverage where no measurements exist — then solve
a facility-location problem for where one additional relay/small cell would help most.

Current step: calibrating the ray tracer against the measurements. The scene is built,
georeferenced, exported to Mitsuba and loading in Sionna RT. **The Blosm HTTP 400 is
resolved** — see "Resolved blocker" below.

## Files

```
/Users/ming/Documents/aga_challenges/
├── COTS_Challenge_3.pdf            # the challenge brief
├── Rural_COTS_RAN_Description.pdf  # dataset brief
├── COTS_Dataset.zip
└── extracted/COTS_Dataset/
    ├── COTS.csv                        # 7,144 rows of UE measurements
    ├── Base_Station_Information.yaml   # 4 sites, 3 cell IDs each
    ├── trace.py, plot.py               # folium map scripts (provided)
    └── *_map.html                      # pre-rendered maps
```

## THE ANSWER: scene extent to import

Paste into the Blosm `Extent` panel:

```
max lat   42.0500
min lon  -93.8950     max lon  -93.6250
min lat   41.9200
```

14.4 km N-S × 22.3 km E-W = 321 km². Contains all 7,144 measurement rows and all four
base stations, with ~1.7 km terrain padding beyond the outermost measurements on the
S/W/N edges.

Why this wide: measurements only reach −93.678 East, but Curtiss Farm, Wilson Hall and
Research Park all sit further east. Curtiss and Wilson Hall must be in-scene to simulate
the 283 rows they serve. Research Park adds only 1.5 km more and is a free negative
control — it never serves a single row in the data, so a correct simulation must
reproduce that.

### Optional smaller calibration box (±4 km around Agronomy Farm)

```
max lat   42.0570
min lon  -93.8220     max lon  -93.7250
min lat   41.9850
```
8.0 × 8.0 km. 2,828 rows inside; 2,202 served (all by Agronomy — no other site wins in
this box); 626 no-service. 725 points within 500 m of the tower. Good for fast parameter
fitting; **note it clips 43% of Agronomy's served range** (Agronomy reaches 10.9 km) and
under-samples sector `015` (309 of its 1,054 rows).

## Resolved blocker (was: Blosm HTTP 400)

Not a Blosm bug. **Overpass was congested**: `/api/map` returns
`Dispatcher_Client::request_read_and_idx::timeout` (HTTP 504), and `overpass.kumi.systems`
504s as well. There is also a **Squid proxy** in this network path that returns spurious
502s on unrelated downloads — retry with `--retry 5 --retry-all-errors`.

Overpass is bypassed entirely now. Both data sources are local, so the import makes no
network calls at all:

- `clip_osm.py` — Geofabrik `iowa-latest.osm.pbf` -> two-pass pyosmium clip -> `ames.osm`
  (51 MB, 336k nodes, 10,079 buildings, 28,455 ways). Uses `BackReferenceWriter` so the
  output is reference-complete without a whole-state node-location index.
- Skadi terrain tiles `N41W094` / `N42W094` pre-seeded into `scene/blosm_data/terrain/`,
  which is where Blosm looks before fetching.

### Scene pipeline (all headless, all reproducible)

```bash
cd /Users/ming/Documents/aga_challenges/scene
/Users/ming/radioconda/bin/python3 clip_osm.py            # -> ames.osm
BL=/Applications/Blender.app/Contents/MacOS/Blender
$BL -b -P import_scene.py                                  # -> ames.blend
$BL -b -P verify_geo.py                                    # -> georef.json
$BL -b -P export_mitsuba.py                                # -> mitsuba/ames.xml
export DRJIT_LIBLLVM_PATH=/Users/ming/radioconda/lib/libLLVM-19.dylib
/Users/ming/radioconda/bin/python3 calibrate.py 800 15,25,35,45,60
```

## Environment gotchas

- **Blender 4.2.23 LTS**, with `blosm` 2.7.28 (free, so `mode='3Dsimple'`) and
  `mitsuba-blender` already installed.
- Python is `/Users/ming/radioconda/bin/python3` — the system `python3` has no pandas.
- **Sionna RT 2.0.1 will not import without**
  `DRJIT_LIBLLVM_PATH=/Users/ming/radioconda/lib/libLLVM-19.dylib`. Installing `sionna-rt`
  downgrades mitsuba 3.9.1 -> 3.8.0 and drjit 1.5.0 -> 1.3.1.
- **Delete `Terrain_envelope` before export.** It is a Blosm helper box; left in the scene
  it wraps everything in an occluder and every ray terminates on it.
- Export with `axis_forward='Y', axis_up='Z'` (identity). The addon defaults to `-Z`/`Y`,
  which rotates the scene and breaks the lat/lon -> XY mapping.

## Verified scene facts

- **Origin `scene["lat"]=41.98499870300293`, `scene["lon"]=-93.7599983215332`.**
  Projection is spherical transverse Mercator, `radius=6378137`, `k=1`, centred there
  (`blosm/util/transverse_mercator.py`). Round-trip error 1e-10 m. Cached in `georef.json`.
- **`Terrain["height_offset"] = 262`** — terrain z is relative. Absolute elevation = z + 262.
  Irrelevant to RF (only relative heights matter) but it will bite any comparison to a DEM.
- Terrain 457,310 verts / 455,868 faces; buildings 170,748 verts / 95,427 faces.
- Base stations on the terrain surface: Agronomy `(-1123.3, 4009.6, z=77.0)`,
  Curtiss `(8196.3, 2059.5, 43.0)`, Wilson Hall `(9022.0, 3189.3, 35.1)`,
  Research Park `(10227.9, 681.2, 34.2)`.
- **All 7,144 measurement rows fall inside the terrain footprint.**
- Scene 22.4 x 14.5 km vs measured footprint 16.2 x 11.0 km. On a 200 m grid the drive
  visited **938 of 8,176 cells (11.5%)** — the remaining 88.5% is what Challenge 3 predicts.
- Terrain edge snaps to arc-second posts, so the SW corner sits 39.7 m south of the
  requested extent. Harmless.

## Calibration status — the real open problem

`calibrate.py` places receivers on the actual terrain at each measured location and scores
predicted path gain against measured RSRP.

```
calibrate.py <n_rx> <heights,csv> <scene.xml> [diff|nodiff]
```

### Terrain resolution vs diffraction, 2x2 (800 sampled Agronomy rows, max_depth=3)

Best row from each configuration:

| terrain | diffraction | h_ant | linked | corr | RMSE dB |
|---|---|---|---|---|---|
| 30 m skadi | off | 15 | 580 | 0.795 | **8.99** |
| 30 m skadi | on  | 60 | 754 | 0.671 | 11.71 |
| 10 m 3DEP  | off | 15 | 605 | 0.784 | 9.14 |
| 10 m 3DEP  | on  | 60 | 761 | 0.740 | 10.55 |

**Finding 1 — terrain resolution is NOT the limiting factor.** The USGS 3DEP 1/3 arc-second
DEM (7.7 x 10.3 m posts, 8.2M triangles) scores 9.14 dB against skadi's 8.99 dB at 30 m
posts. It finds slightly more links (605 vs 580) because the horizon geometry is better,
but the error is unchanged. The obvious upgrade does not pay, so **use the 30 m scene** —
it is 18x lighter and no worse. Do not spend more time on DEM resolution.

**Finding 2 — diffraction hurts, but less on finer terrain.** Enabling
`diffraction=True, edge_diffraction=True` degrades the fit on both meshes, and degrades it
*less* on the 10 m mesh (10.55 vs 11.71 dB). That is the signature of a tessellation
artifact: a faceted DEM presents every triangle boundary as a candidate diffracting edge
with an unphysically large dihedral angle, and refining the mesh shallows those angles.
Still net-negative on both, so **leave diffraction off** until it can be restricted to
building edges only.

**Finding 3 — antenna height is still not identifiable.** Flat from 15 to 60 m in every
configuration. Note the RMSE column is **not** apples-to-apples across heights: a taller
antenna links more receivers, and the extra ones are marginal far-out points that predict
badly, so lower heights score better partly by being scored on an easier subset. Compare on
a common linked subset before drawing any conclusion about height.

**Where the residual is not:** terrain resolution (ruled out), and not diffraction. Still
open: vegetation (shelterbelts are excluded from the scene entirely), the ITU material
choice, the tr38901 pattern vs the real sector antenna, and EIRP/tilt which are absorbed
into the fitted `offset` constant rather than modelled.

### Best-known configuration

30 m skadi terrain, `diffraction=False`, `max_depth=3`, LOS + specular, three sectors at
compass 0/115/240 deg, 3.4608 GHz. `offset` (EIRP + antenna gain) fits at ~25 dB.

## Superseded blocker notes

Blosm returns `HTTP 400 Bad Request` on the OpenStreetMap import. Persisted after
shrinking the box. (One earlier failure was my error — I gave test values with min lat
> max lat, an inverted bbox.)

### Plan: bypass Blosm's Overpass call, feed it a local file

```bash
curl -g -o ames.osm \
  "https://overpass-api.de/api/map?bbox=-93.8950,41.9200,-93.6250,42.0500"
```
`/api/map` takes `bbox=W,S,E,N`, returns OSM XML, and has no 50k-node cap. If it also
400s, the response body carries the real reason (Blosm's dialog swallows it).

### Then drive Blender headless

```python
# import_scene.py  →  blender -b -P import_scene.py
import bpy

S, W, N, E = 41.9200, -93.8950, 42.0500, -93.6250
b = bpy.context.scene.blosm

# Property names drift between Blosm versions. If anything below errors, dump them:
# print([p.identifier for p in b.bl_rna.properties])

b.minLat, b.maxLat, b.minLon, b.maxLon = S, N, W, E

# Terrain FIRST — it stamps the georeference origin and gives buildings a surface.
b.dataType = 'terrain'
bpy.ops.blosm.import_data()

b.dataType = 'osm'
b.osmSource = 'file'
b.osmFilepath = '/absolute/path/to/ames.osm'
bpy.ops.blosm.import_data()

print("ORIGIN lat/lon:", bpy.context.scene.get("lat"), bpy.context.scene.get("lon"))
bpy.ops.wm.save_as_mainfile(filepath='/absolute/path/to/ames.blend')
```

Fallbacks if the file route also fails: switch the Overpass endpoint in
`Edit → Preferences → Add-ons → Blosm` to `overpass.kumi.systems`; or tile the import
into quadrants (Blosm stamps `scene["lat"]/["lon"]` on the first successful import and
reuses it, so tiles align automatically).

## Scene-building rules that decide whether this works

1. **Import terrain AND OSM**, as two passes at the identical extent. Terrain first.
   Rural Iowa at 3.46 GHz over 10 km links is terrain-shadowing-dominated; buildings are
   sparse farmsteads except at the eastern edge (ISU campus / west Ames).
2. **Never change the extent between the two imports** — the layers land in different
   local frames and everything downstream misaligns.
3. **Read the origin off `scene["lat"]` / `scene["lon"]` after import and use that exact
   number** for every lat/lon → scene-XY conversion. A known origin beats a preferred
   one. Do NOT use a fixed-`cos(lat)` conversion across the full box: the latitude spread
   costs ~8 m at the corners, which is your DEM resolution.
4. **Terrain resolution matters.** At 3460.8 MHz the first Fresnel radius at the midpoint
   of a 10 km link is 14.7 m and the 4/3-earth bulge is 5.9 m. SRTM's 30 m posts are
   marginal — prefer USGS 3DEP 1/3 arc-second (10 m) for Iowa if it can be substituted.

## Radio parameters recovered from the data

- **Carrier: 3460.8 MHz** (NR-ARFCN 630720), single band, λ = 8.67 cm. `band` and `arfcn`
  are single-valued in the whole dataset, so they are useless as ML features.
- **Sector azimuths.** Cell ID suffix encodes sector index: `0x00B`=11→S1, `0x015`=21→S2,
  `0x01F`=31→S3. Binning Agronomy's served points by bearing, each sector wins a clean
  contiguous arc — **00B ≈ 0°, 015 ≈ 115°, 01F ≈ 240°**: a standard 0/120/240 three-sector
  site. Handover boundaries fall at ~55°/165°/305°, exactly the predicted bisectors.
  Curtiss `01F` is consistent with the same convention. Wilson Hall has only 106 samples
  on one sector at 3–9 km — treat its orientation as unknown.
- **Antenna heights are NOT in the dataset.** Largest free parameter. Fit against the 725
  points within 500 m of Agronomy before trying to match the wider route.
- **Season:** March 19–20, pre-planting. Bare fields, no foliage — one less unknown in
  the material model.

### Base stations (`Base_Station_Information.yaml`)

| Site | lat | lon | rows served |
|---|---|---|---|
| Agronomy Farm | 42.021016348205585 | −93.77358107943655 | 3,838 |
| Curtiss Farm | 42.00345729383988 | −93.66091628902467 | 177 |
| Wilson Hall | 42.0135968572502 | −93.65091684111805 | 106 |
| Research Park | 41.991051378648365 | −93.63638030677834 | **0** |

## Dataset facts worth not rediscovering

- 7,144 rows, 4 drive runs over Mar 19–20 2026 (84 / 12 / 171 / 249 min), ~2.6 s sampling,
  ~276 km driven, 14% stationary. Real footprint ~11 × 16 km, up to 12.2 km from Agronomy
  — the README's "five miles" understates it.
- **42% of rows have no serving cell** (3,023 = 2,885 null + 138 with `cellid=FFFFFFFFF`,
  `arfcn=-1`), across **232 distinct outage segments**. Median 6.4 km from nearest site vs
  3.2 km when served. On a 100 m grid, **1,066 of 1,935 visited cells never had service.**
  Longest hole is 29 min of driving near (41.940, −93.773), ~9.2 km out. This is the
  strongest signal in the data and it lives in the rows most people `dropna()` away.
- **Uplink is the binding constraint, not downlink.** DL saturates ~230 Mbps for any
  SINR > 0 (Spearman 0.23). UL tracks RSRP hard (0.78), spanning 8→63 Mbps. 7.9% of test
  rows have UL < 10 Mbps while DL > 100 Mbps. Median UL/DL ratio 0.195. Define
  "underserved" on uplink + coverage; a DL-based objective calls everything fine.
- **Latency degrades only at the edge.** Overall Spearman ping~RSRP is −0.22, but binned:
  ≥−70 dBm → 22 ms median / 50 ms p95; ≤−110 dBm → 62 ms median / **286 ms p95**. Max 982 ms.
- **RSRQ is near-useless** — std 1.2 dB, median −11, half the mass in [−11,−10].
- Only 4 of 12 cells ever serve. 55 handovers total. Practically a single-site study.

### Data traps

- `sinr` and `rsrq` load as **object dtype** — 11 rows contain a literal `'-'`.
- `cellid=FFFFFFFFF` / `arfcn=-1` rows carry RSRP, SINR, even throughput, but have **no
  valid serving cell**. They are a no-service state, not measurements.
- Consecutive samples are ~22 m apart (2.6 s at 8.6 m/s). A random train/test split leaks
  badly — the challenge brief explicitly requires geographically separated test segments.
  **Split by spatial block or by run.**
- Max derived GPS speed is 89.9 m/s (200 mph) → needs outlier filtering before any speed
  feature.
- Missing UL/DL is **not MCAR** — it's missing exactly where service failed. Treating it
  as random biases the service surface optimistic in precisely the places Challenge 3
  cares about.
- The provided `plot.py` filters to Agronomy cells only and drops nulls. It is a starting
  visualization, not a template to inherit.

## Licence note

Dataset is Arathon-only while non-public: not to be copied, redistributed, or published
outside the event. Avoid sending measurement coordinates to third-party services.

## Suggested next steps in the new session

Steps 1-4 of the previous handoff are **done** (see "Resolved blocker" and the pipeline
above). What remains is making the propagation model good enough to be worth optimizing
over. In priority order:

1. **Close the 9 dB RMSE gap.** Until the model can tell 15 m from 60 m of antenna height,
   no fitted parameter means anything and no placement recommendation is defensible.
   Cheapest experiments first:
   - restrict diffraction to the buildings mesh, leaving terrain LOS+specular only;
   - decimate the terrain (`terrainReductionRatio`) and see whether the diffraction
     artifact shrinks with triangle count — that would confirm the tessellation diagnosis;
   - substitute USGS 3DEP 1/3 arc-second (10 m) for the 30 m skadi tiles. Blosm hardcodes
     `https://s3.amazonaws.com/elevation-tiles-prod/skadi/...` and the `.hgt` format is a
     fixed 1"/3" grid, so 3DEP cannot be dropped into the cache — build the terrain mesh
     directly from the DEM instead of via Blosm.
2. **Add the vegetation that was deliberately left out.** `import_scene.py` sets
   `forests = vegetation = False`. Iowa shelterbelts and farmstead tree lines are real
   attenuators at 3.46 GHz even in a bare-field March. This is a candidate explanation for
   the residual, and for the links the tracer currently misses.
3. **Use Research Park as the negative control it is.** It serves 0 of 7,144 rows. A model
   that predicts usable coverage from it is wrong regardless of how well it fits Agronomy.
4. Only then: fit EIRP/tilt, build the predicted service surface over the 88.5% of the
   scene the drive never visited, and solve the facility-location problem — remembering
   that "underserved" must be defined on **uplink**, not downlink.

### Reusable pieces already in `scene/`

`georef.json` holds the projection constants; every lat/lon -> XY conversion downstream
should read them from there rather than re-deriving. `calibrate.py` already contains the
`fromGeo` projection, the terrain ray-cast receiver placement, and the sector-aware
scoring loop — extend it rather than starting over.
