"""
Exploratory data analysis -- the dataset as it is, nothing inferred.

Writes reports/eda.json: every column profiled, every value exported for
plotting, percentiles at p1/p5/p10/p25/p50/p75/p90/p95/p99 for every numeric
field, plus the structural oddities a first read turns up.

No model, no prediction, no recommendation.  This file only describes.
"""
import json

import numpy as np
import pandas as pd

from config import DATASET, REPORTS

PCTS = [1, 5, 10, 25, 50, 75, 90, 95, 99]
NUMERIC = ["ping_ms", "rsrp", "sinr", "rsrq", "uplink", "downlink"]
EARTH_R = 6_371_000.0


def _r(x, n=3):
    if x is None:
        return None
    try:
        f = float(x)
        return None if np.isnan(f) else round(f, n)
    except (TypeError, ValueError):
        return None


def run(verbose=True):
    # ---- read twice: once as raw strings, once coerced ------------------
    # The string pass is how the odd tokens get found at all; coercing first
    # would silently convert them to NaN and hide them.
    raw = pd.read_csv(DATASET / "COTS.csv", dtype=str, keep_default_na=False)
    df = pd.read_csv(DATASET / "COTS.csv", dtype={"cellid": str})
    for c in ["ping_ms", "arfcn", "rsrp", "sinr", "rsrq", "uplink", "downlink"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["ts"] = pd.to_datetime(df["timestamp_local"], format="mixed", utc=True)
    df = df.sort_values("ts").reset_index(drop=True)
    n = len(df)

    A = {"n_rows": n, "n_cols": len(raw.columns), "columns": list(raw.columns)}

    # ---- 1. column inventory -------------------------------------------
    inv = []
    for c in raw.columns:
        v = raw[c]
        empty = int((v == "").sum())
        odd = []
        if c in NUMERIC + ["arfcn", "lat", "lon"]:
            bad = v[(v != "") & (~v.str.match(r"^-?\d+\.?\d*(e-?\d+)?$", na=False))]
            odd = sorted(bad.unique())[:5]
        inv.append({"name": c, "present": n - empty, "missing": empty,
                    "missing_pct": round(100 * empty / n, 1),
                    "unique": int(v.nunique()), "odd_tokens": odd,
                    "odd_count": int(len(bad)) if odd else 0})
    A["inventory"] = inv

    # ---- 2. missingness co-occurrence ----------------------------------
    # Which columns go blank together.  This is the structure that says the
    # blanks are not random: they arrive in a handful of exact patterns.
    cols = ["ping_ms", "band", "cellid", "arfcn", "rsrp", "sinr", "rsrq", "uplink", "downlink"]
    m = df[cols].isna()
    pat = m.apply(lambda r: "".join("1" if x else "0" for x in r), axis=1)
    vc = pat.value_counts()
    A["missing_patterns"] = {
        "columns": cols,
        "rows": [{"pattern": p, "n": int(k), "pct": round(100 * k / n, 1),
                  "missing": [cols[i] for i, ch in enumerate(p) if ch == "1"],
                  "present": [cols[i] for i, ch in enumerate(p) if ch == "0"]}
                 for p, k in vc.items() if k >= 1][:14]}

    # ---- 3. timing ------------------------------------------------------
    dt = df["ts"].diff().dt.total_seconds()
    t0 = df["ts"].iloc[0]
    df["t"] = (df["ts"] - t0).dt.total_seconds()
    df["run"] = (dt > 120).cumsum().astype(int)
    A["time"] = {
        "start": str(df["ts"].iloc[0]), "end": str(df["ts"].iloc[-1]),
        "span_hours": round(float(df["t"].iloc[-1] / 3600), 2),
        "interval": {"min": _r(dt.min()), "p25": _r(dt.quantile(.25)),
                     "median": _r(dt.median()), "p75": _r(dt.quantile(.75)),
                     "p99": _r(dt.quantile(.99)), "max": _r(dt.max()),
                     "mode": _r(dt.round(1).mode().iloc[0])},
        "gaps_over_120s": int((dt > 120).sum()),
        "hist": np.histogram(np.log10(dt.dropna().clip(lower=0.5)), bins=40)[0].tolist(),
        "hist_edges": [_r(x, 3) for x in np.histogram(
            np.log10(dt.dropna().clip(lower=0.5)), bins=40)[1]],
    }
    runs = []
    for r_, g in df.groupby("run"):
        runs.append({"run": int(r_), "n": int(len(g)),
                     "start": str(g["ts"].min()), "end": str(g["ts"].max()),
                     "t_start": _r(g["t"].min()), "t_end": _r(g["t"].max()),
                     "minutes": round(float((g["ts"].max() - g["ts"].min()).total_seconds() / 60), 1),
                     "day": str(g["ts"].dt.date.iloc[0]),
                     "with_radio": int(g["cellid"].notna().sum()),
                     "with_ping": int(g["ping_ms"].notna().sum()),
                     "with_throughput": int(g["uplink"].notna().sum()),
                     "no_cell_pct": round(100 * float(g["cellid"].isna().mean()), 1)})
    A["runs"] = runs

    # ---- 4. GPS / mobility ---------------------------------------------
    la, lo = np.radians(df["lat"].to_numpy()), np.radians(df["lon"].to_numpy())
    a = (np.sin(np.diff(la) / 2) ** 2
         + np.cos(la[:-1]) * np.cos(la[1:]) * np.sin(np.diff(lo) / 2) ** 2)
    step = np.r_[np.nan, 2 * EARTH_R * np.arcsin(np.sqrt(np.clip(a, 0, 1)))]
    speed = np.where((dt > 0.5) & (dt < 120), step / dt * 2.23694, np.nan)
    df["step_m"], df["speed_mph"] = step, speed
    A["gps"] = {
        "lat_min": _r(df.lat.min(), 6), "lat_max": _r(df.lat.max(), 6),
        "lon_min": _r(df.lon.min(), 6), "lon_max": _r(df.lon.max(), 6),
        "ns_km": _r((df.lat.max() - df.lat.min()) * 111.32, 2),
        "ew_km": _r((df.lon.max() - df.lon.min()) * 111.32 * np.cos(np.radians(42)), 2),
        "unique_positions": int(df.duplicated(["lat", "lon"]).eq(False).sum()),
        "repeated_positions": int(df.duplicated(["lat", "lon"]).sum()),
        "zero_steps": int((step == 0).sum()),
        "step_pct": {f"p{p}": _r(np.nanpercentile(step[1:], p), 2) for p in PCTS},
        "speed_pct": {f"p{p}": _r(np.nanpercentile(speed[~np.isnan(speed)], p), 2) for p in PCTS},
        "stationary_pct": round(100 * float(np.nanmean(speed < 1)), 1),
        "max_speed": _r(np.nanmax(speed), 1), "max_step": _r(np.nanmax(step), 1),
    }

    # ---- 5. per-variable profile ---------------------------------------
    prof = {}
    for c in NUMERIC + ["lat", "lon", "speed_mph", "step_m"]:
        v = df[c].dropna()
        if len(v) == 0:
            continue
        lo_, hi_ = float(v.min()), float(v.max())
        nd = 6 if c in ("lat", "lon") else 3   # coordinates need the extra places
        hist, edges = np.histogram(v, bins=44)
        p99v = float(np.percentile(v, 99))
        clipped = v[v <= p99v]
        h99, e99 = np.histogram(clipped, bins=44) if len(clipped) > 1 else (hist, edges)
        # ECDF thinned to 300 points for plotting
        sv = np.sort(v.to_numpy())
        k = np.linspace(0, len(sv) - 1, min(300, len(sv))).astype(int)
        prof[c] = {
            "n": int(len(v)), "missing": int(n - len(v)),
            "min": _r(lo_, nd), "max": _r(hi_, nd), "mean": _r(v.mean(), nd),
            "std": _r(v.std(), nd),
            "n_unique": int(v.nunique()),
            "integer_share": round(100 * float((v == v.round()).mean()), 1),
            "min_step": _r(float(np.diff(np.unique(sv)).min()) if v.nunique() > 1 else 0, 6),
            "at_min": int((v == lo_).sum()), "at_max": int((v == hi_).sum()),
            "pct": {f"p{p}": _r(np.percentile(v, p), nd) for p in PCTS},
            "hist": hist.tolist(), "edges": [_r(x, 4) for x in edges],
            "hist99": h99.tolist(), "edges99": [_r(x, 4) for x in e99],
            "n_above_p99": int((v > p99v).sum()),
            "ecdf_x": [_r(x, 3) for x in sv[k]],
            "ecdf_y": [_r((i + 1) / len(sv), 4) for i in k],
        }
        # discrete columns get an exact value count
        if v.nunique() <= 100:
            prof[c]["values"] = [{"v": _r(k2), "n": int(v2)}
                                 for k2, v2 in sorted(v.value_counts().items())]
    A["profiles"] = prof


    # ---- 5b. column-by-column detail ------------------------------------
    # Grouped the way the dataset documentation groups them, but every fact
    # below is measured from the file rather than taken from the schema.
    GROUPS = [
        ("Time and position", "present on every row", [
            ("timestamp_local", "Local timestamp",
             "string, ISO 8601 with UTC offset", "—",
             "Microsecond precision. The trailing -05:00 is the offset from Coordinated "
             "Universal Time, i.e. US Central Daylight Time."),
            ("lat", "Latitude", "float", "decimal degrees",
             "Position north of the equator, in WGS 84 (World Geodetic System 1984, the "
             "reference frame GPS reports in). Seven decimal places."),
            ("lon", "Longitude", "float", "decimal degrees",
             "Position east of the prime meridian; negative means west. Seven decimal places."),
        ]),
        ("Service experience", "what an application would feel", [
            ("ping_ms", "Ping round-trip time, in milliseconds", "float", "ms",
             "How long a small packet took to reach the server and return. "
             "ms = millisecond, one thousandth of a second."),
            ("uplink", "Uplink throughput", "float", "Mbps",
             "Rate from device to network, measured with iperf. Mbps = megabits per "
             "second. Never appears without downlink."),
            ("downlink", "Downlink throughput", "float", "Mbps",
             "Rate from network to device. Never appears without uplink."),
        ]),
        ("Serving radio context", "which cell was in use", [
            ("band", "Spectrum band label", "string", "—",
             "Human-readable name for the slice of spectrum in use. One value only, so it "
             "carries no information beyond present or absent."),
            ("cellid", "Cell identifier", "string", "—",
             "Which individual cell (one sector of one base station) the device was camped "
             "on. Read as text: leading zeros are significant."),
            ("arfcn", "Absolute Radio-Frequency Channel Number", "float", "channel number",
             "The integer index that names a carrier frequency. In 5G New Radio this is the "
             "NR-ARFCN; 630720 corresponds to 3460.8 MHz. Two values only."),
        ]),
        ("Radio quality", "all three arrive as whole numbers", [
            ("rsrp", "Reference Signal Received Power", "integer", "dBm",
             "Power the device received on the cell's always-on reference signal. "
             "dBm = decibels relative to one milliwatt, so values are negative and more "
             "negative is weaker."),
            ("sinr", "Signal-to-Interference-plus-Noise Ratio", "integer", "dB",
             "How far the wanted signal sits above interference plus background noise. "
             "dB = decibel, a ratio on a logarithmic scale; higher is a cleaner channel."),
            ("rsrq", "Reference Signal Received Quality", "integer", "dB",
             "Quality rather than raw strength: it folds in how loaded the carrier is. "
             "Closer to zero is better."),
        ]),
    ]
    detail = []
    for gname, gnote, cols in GROUPS:
        for cname, cfull, ctype, cunit, cnote in cols:
            col = raw[cname]
            present = int((col != "").sum())
            distinct = int(col[col != ""].nunique())
            row = {"group": gname, "group_note": gnote, "name": cname,
                   "full": cfull, "type": ctype, "unit": cunit, "note": cnote,
                   "present": present, "missing": n - present, "distinct": distinct,
                   "fill_pct": round(100 * present / n, 1)}
            if cname in prof:
                p = prof[cname]
                row.update({"min": p["min"], "max": p["max"], "p25": p["pct"]["p25"],
                            "p50": p["pct"]["p50"], "p75": p["pct"]["p75"],
                            "p1": p["pct"]["p1"], "p99": p["pct"]["p99"],
                            "integer_share": p["integer_share"],
                            "min_step": p["min_step"], "kind": "numeric"})
            elif cname == "timestamp_local":
                row.update({"kind": "time", "first": str(df["ts"].iloc[0]),
                            "last": str(df["ts"].iloc[-1]),
                            "span_hours": A["time"]["span_hours"]})
            else:
                vc3 = col[col != ""].value_counts()
                row.update({"kind": "categorical",
                            "values": [{"v": str(k3), "n": int(v3),
                                        "pct": round(100 * v3 / present, 1)}
                                       for k3, v3 in vc3.items()]})
            # odd tokens, if the column has any
            bad3 = col[(col != "") & (~col.str.match(r"^-?\d+\.?\d*(e-?\d+)?$", na=False))]
            if cname not in ("timestamp_local", "band", "cellid") and len(bad3):
                row["odd"] = {"tokens": sorted(bad3.unique())[:4], "n": int(len(bad3))}
            detail.append(row)
    A["column_detail"] = detail

    # Missingness tiers: how many distinct fill levels exist across the 12 columns
    tiers = {}
    for c in raw.columns:
        k4 = int((raw[c] == "").sum())
        tiers.setdefault(k4, []).append(c)
    A["fill_tiers"] = [{"missing": k4, "present": n - k4, "columns": v4,
                        "pct": round(100 * (n - k4) / n, 1)}
                       for k4, v4 in sorted(tiers.items())]


    # ---- 5c. glossary ----------------------------------------------------
    # Every abbreviation used by the file, its column names, its units, or the
    # material shipped alongside it.
    A["glossary"] = [
        {'term': 'ARFCN', 'full': 'Absolute Radio-Frequency Channel Number', 'where': 'column', 'note': 'An integer index that names a carrier frequency, so a channel can be written as one number instead of a frequency in megahertz. The 5G variant is the NR-ARFCN; 630720 here maps to 3460.8 MHz.'},
        {'term': 'RSRP', 'full': 'Reference Signal Received Power', 'where': 'column', 'note': "Power the handset measures on the cell's always-on reference signal. Reported in dBm, so values are negative and more negative means weaker."},
        {'term': 'SINR', 'full': 'Signal-to-Interference-plus-Noise Ratio', 'where': 'column', 'note': 'How far the wanted signal sits above interference plus background noise. Higher is a cleaner channel.'},
        {'term': 'RSRQ', 'full': 'Reference Signal Received Quality', 'where': 'column', 'note': 'Quality rather than raw strength: it folds in how loaded the carrier is. Closer to zero is better.'},
        {'term': 'Cell ID', 'full': 'Cell identifier', 'where': 'column', 'note': 'Names one sector of one base station. A three-sector site has three of them.'},
        {'term': 'ms', 'full': 'Millisecond', 'where': 'unit', 'note': 'One thousandth of a second.'},
        {'term': 'Mbps', 'full': 'Megabits per second', 'where': 'unit', 'note': 'One million bits per second. Eight bits to a byte, so 8 Mbps is one megabyte per second.'},
        {'term': 'dBm', 'full': 'Decibels relative to one milliwatt', 'where': 'unit', 'note': 'An absolute power level on a logarithmic scale. Every 10 dB down is ten times less power, so -80 dBm is ten times weaker than -70 dBm.'},
        {'term': 'dB', 'full': 'Decibel', 'where': 'unit', 'note': 'A ratio between two quantities on a logarithmic scale. Unlike dBm it is relative, not an absolute amount.'},
        {'term': 'UE', 'full': 'User Equipment', 'where': 'context', 'note': 'The 3GPP term for the device on the customer side of the link. Here, the modem in the vehicle.'},
        {'term': 'RAN', 'full': 'Radio Access Network', 'where': 'context', 'note': 'The radio half of a mobile network: the base stations and antennas that connect devices to the core network.'},
        {'term': 'COTS', 'full': 'Commercial Off-The-Shelf', 'where': 'context', 'note': 'Standard vendor equipment bought as sold, rather than research hardware built for the experiment.'},
        {'term': 'NR', 'full': 'New Radio', 'where': 'context', 'note': 'The 5G air interface. Band n78 is its 3.3-3.8 GHz mid-band allocation.'},
        {'term': 'TDD', 'full': 'Time Division Duplex', 'where': 'context', 'note': 'Uplink and downlink share one frequency and take turns in time, rather than using two separate frequencies.'},
        {'term': 'GPS', 'full': 'Global Positioning System', 'where': 'context', 'note': 'The satellite system the lat and lon columns come from.'},
        {'term': 'WGS 84', 'full': 'World Geodetic System 1984', 'where': 'context', 'note': 'The coordinate reference frame GPS reports positions in.'},
        {'term': 'iperf', 'full': 'IP performance measurement tool', 'where': 'context', 'note': 'The utility that produced the uplink and downlink numbers by pushing traffic and timing it.'},
        {'term': 'CSV', 'full': 'Comma-Separated Values', 'where': 'context', 'note': 'The plain-text table format the dataset ships in.'},
        {'term': 'ECDF', 'full': 'Empirical Cumulative Distribution Function', 'where': 'method', 'note': "The 'cumulative' panel on each column card: for any value on the horizontal axis it reads off what share of rows fall at or below it."},
        {'term': 'p50, p90, ...', 'full': 'Percentiles', 'where': 'method', 'note': 'p50 is the median, so half the values fall below it. p90 means nine tenths fall below it. p1 and p99 bound the extremes without being a single outlier.'},
    ]

    # ---- 6. categoricals ------------------------------------------------
    A["categorical"] = {}
    for c in ["band", "cellid", "arfcn"]:
        vc2 = df[c].value_counts(dropna=False)
        A["categorical"][c] = [{"value": ("(blank)" if pd.isna(k) else str(k)),
                                "n": int(v2), "pct": round(100 * v2 / n, 1)}
                               for k, v2 in vc2.items()]

    # ---- 7. correlation --------------------------------------------------
    cm = df[NUMERIC + ["speed_mph"]].corr(method="spearman")
    A["correlation"] = {"labels": list(cm.columns),
                        "matrix": [[_r(x, 3) for x in row] for row in cm.to_numpy()]}

    # ---- 8. raw series, columnar, every row -----------------------------
    # Exported in full because the brief is to plot the data as it is, not a
    # summary of it.  Columnar so the JSON does not repeat 7,144 key names.
    A["series"] = {
        "t": [_r(x, 1) for x in df["t"]],
        "lat": [_r(x, 5) for x in df["lat"]],
        "lon": [_r(x, 5) for x in df["lon"]],
        "run": [int(x) for x in df["run"]],
        "ping_ms": [_r(x, 2) for x in df["ping_ms"]],
        "rsrp": [None if pd.isna(x) else int(x) for x in df["rsrp"]],
        "sinr": [None if pd.isna(x) else int(x) for x in df["sinr"]],
        "rsrq": [None if pd.isna(x) else int(x) for x in df["rsrq"]],
        "uplink": [_r(x, 2) for x in df["uplink"]],
        "downlink": [_r(x, 2) for x in df["downlink"]],
        "speed_mph": [_r(x, 1) for x in df["speed_mph"]],
        "step_m": [_r(x, 1) for x in df["step_m"]],
        "cell": [("" if pd.isna(x) else str(x)) for x in df["cellid"]],
    }

    # ---- 9. structural oddities -----------------------------------------
    A["oddities"] = {
        "duplicate_rows": int(df.duplicated().sum()),
        "duplicate_timestamps": int(df["ts"].duplicated().sum()),
        "duplicate_positions": int(df.duplicated(["lat", "lon"]).sum()),
        "dash_tokens_sinr_rsrq": int(len(raw[(raw.sinr == "-")])),
        "cellid_sentinel": int((df["cellid"] == "FFFFFFFFF").sum()),
        "arfcn_negative": int((df["arfcn"] == -1).sum()),
        "throughput_without_cellid": int((df["downlink"].notna() & df["cellid"].isna()).sum()),
        "ping_without_cellid": int((df["ping_ms"].notna() & df["cellid"].isna()).sum()),
        "uplink_downlink_always_paired": bool(
            (df["uplink"].notna() == df["downlink"].notna()).all()),
        "rsrp_at_floor_140": int((df["rsrp"] == -140).sum()),
        "position_only_rows": int(m.all(axis=1).sum()),
        "speed_over_80mph": int(np.nansum(speed > 80)),
    }

    # ---- 10. throughput pairing -----------------------------------------
    b = df.dropna(subset=["uplink", "downlink"])
    A["throughput"] = {
        "n_pairs": int(len(b)),
        "pearson": _r(b["uplink"].corr(b["downlink"])),
        "spearman": _r(b["uplink"].corr(b["downlink"], method="spearman")),
        "ratio_pct": {f"p{p}": _r(np.percentile(b["downlink"] / b["uplink"], p))
                      for p in PCTS},
        "scatter": [[_r(u, 2), _r(d, 2)] for u, d in
                    zip(b["uplink"], b["downlink"])],
    }

    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "eda.json").write_text(json.dumps(A, separators=(",", ":")))
    if verbose:
        sz = (REPORTS / "eda.json").stat().st_size / 1e6
        print(f"[eda] {n} rows x {A['n_cols']} cols profiled")
        print(f"[eda] {len(A['missing_patterns']['rows'])} distinct missingness patterns")
        print(f"[eda] {len(prof)} numeric variables, percentiles at {PCTS}")
        print(f"[eda] wrote reports/eda.json ({sz:.2f} MB)")
    return A


if __name__ == "__main__":
    run()
