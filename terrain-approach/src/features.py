"""
Stage 1 -- turn COTS.csv into a labelled, feature-complete frame.

The single most important thing that happens here is that we DO NOT drop rows
with missing radio data.  2,885 of 7,144 rows (40.4%) report no serving cell.
Those are not missing measurements; they are measured absences of service, and
they are exactly the demand Challenge 3 asks us to serve.  A reflexive
df.dropna() deletes every coverage hole in the dataset and then reports that
coverage is excellent.
"""
import numpy as np
import pandas as pd
import yaml

from config import DATASET, DATA, SERVING_SITE

EARTH_R = 6_371_000.0


def haversine_m(lat1, lon1, lat2, lon2):
    """Great-circle distance in metres.  Vectorised over the first pair."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dlam = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlam / 2) ** 2
    return 2 * EARTH_R * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def bearing_deg(lat1, lon1, lat2, lon2):
    """Initial bearing FROM point 1 TO point 2, degrees clockwise from north.

    Used to give the path-loss fit an antenna-pattern term.  Without it the
    fitted path-loss exponent comes out at 1.72 -- below free space, which is
    physically impossible -- because the sector's beam shape gets absorbed into
    the distance term.
    """
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dl = np.radians(np.asarray(lon2) - np.asarray(lon1))
    y = np.sin(dl) * np.cos(p2)
    x = np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dl)
    return (np.degrees(np.arctan2(y, x)) + 360.0) % 360.0


def load_sites():
    """Base stations from the YAML, with a cellid -> (site, sector) lookup."""
    raw = yaml.safe_load((DATASET / "Base_Station_Information.yaml").read_text())
    sites, cell_map = {}, {}
    for s in raw["base_stations"]:
        sites[s["name"]] = (
            float(s["location"]["latitude"]),
            float(s["location"]["longitude"]),
        )
        for cid in s["cell_ids"]:
            # Last three hex digits identify the sector within the site.
            cell_map[cid] = (s["name"], cid[-3:])
    return sites, cell_map


def build(verbose=True):
    sites, cell_map = load_sites()

    # dtype=str on cellid preserves leading zeros AND keeps the FFFFFFFFF
    # sentinel readable instead of silently coercing to a float.
    df = pd.read_csv(DATASET / "COTS.csv", dtype={"cellid": str})

    # sinr and rsrq contain a literal '-' in 11 rows.  Left alone, pandas types
    # the whole column as object and every downstream numeric op either throws
    # or silently misbehaves.
    for col in ["sinr", "rsrq", "rsrp", "ping_ms", "uplink", "downlink", "arfcn"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["ts"] = pd.to_datetime(df["timestamp_local"], format="mixed", utc=True)
    df = df.sort_values("ts").reset_index(drop=True)

    # ---- three-state service label -------------------------------------
    # FFFFFFFFF with arfcn -1 is the modem's "camped but no valid cell" state:
    # 138 rows, none of which carry a ping result.  It is an outage, not a cell.
    invalid = df["cellid"].isna() | df["cellid"].eq("FFFFFFFFF") | df["arfcn"].eq(-1)
    df["outage"] = invalid.astype(int)
    df["state"] = np.where(
        invalid, "OUTAGE",
        np.where(df["uplink"].notna() & df["downlink"].notna(),
                 "MEASURED", "CONNECTED_NO_TEST"),
    )

    # ---- collection runs ------------------------------------------------
    # A gap over 2 minutes means the van stopped and restarted; 4 runs result.
    gap = df["ts"].diff().dt.total_seconds()
    df["run"] = (gap > 120).cumsum().astype(int)

    # ---- serving site / sector -----------------------------------------
    df["site"] = df["cellid"].map(lambda c: cell_map.get(c, (None, None))[0])
    df["sector"] = df["cellid"].map(lambda c: cell_map.get(c, (None, None))[1])

    # ---- geometry relative to the serving site --------------------------
    for name, (slat, slon) in sites.items():
        key = name.split()[0].lower()
        df[f"d_{key}"] = haversine_m(df["lat"], df["lon"], slat, slon)
        df[f"az_{key}"] = bearing_deg(slat, slon, df["lat"], df["lon"])

    key = SERVING_SITE.split()[0].lower()
    df["dist_m"] = df[f"d_{key}"]
    df["az_deg"] = df[f"az_{key}"]
    df["log_d"] = np.log10(df["dist_m"].clip(lower=30.0))
    # Two Fourier harmonics of azimuth give the fit enough freedom to represent
    # a three-sector antenna pattern without us having to know the boresights.
    for h in (1, 2):
        df[f"az_cos{h}"] = np.cos(h * np.radians(df["az_deg"]))
        df[f"az_sin{h}"] = np.sin(h * np.radians(df["az_deg"]))

    # ---- mobility -------------------------------------------------------
    step = haversine_m(df["lat"].shift(), df["lon"].shift(), df["lat"], df["lon"])
    dt = df["ts"].diff().dt.total_seconds()
    df["speed_mph"] = np.where(dt.between(0.5, 120), step / dt * 2.23694, np.nan)

    DATA.mkdir(parents=True, exist_ok=True)
    df.to_csv(DATA / "labeled.csv", index=False)

    if verbose:
        n = len(df)
        print(f"[features] {n} rows -> {DATA/'labeled.csv'}")
        print("[features] service state:")
        for k, v in df["state"].value_counts().items():
            print(f"             {k:<20} {v:>5}  ({v/n:5.1%})")
        print(f"[features] runs: {df['run'].nunique()}  "
              f"({', '.join(str(x) for x in df.groupby('run').size().tolist())} rows)")
        print(f"[features] serving site counts: "
              f"{df['site'].value_counts().to_dict()}")
        keep = df['state'].eq('MEASURED').sum()
        print(f"[features] rows usable for throughput modelling: {keep}")
    return df


if __name__ == "__main__":
    build()
