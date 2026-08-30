"""A1 -- measure the irreducible error floor of the measurements themselves.

ACCURACY.md gates all Stage B mechanism work on this number. If two passes over the
same road disagree by ~8 dB, then the twin's 8.6 dB held-out RMSE is already at the
noise floor and further propagation modelling cannot pay.

Two independent estimators, both from COTS.csv alone -- no ray tracing, no GPU:

  1. Repeat-pass reproducibility. Where two *different drive runs* sample the same
     ground cell on the same serving cell, the RSRP difference is pure reproducibility
     error. If those differences have std sigma_d, each measurement carries noise
     sigma_d/sqrt(2) -- and that is the best RMSE any position-only model can achieve.

     DE-CLUSTERING IS ESSENTIAL. The van parks: 601 of 4,121 served samples sit in
     6 cells, one of them 369 samples deep. A naive radius query over sample pairs
     returns ~100x100 pairs from each stop, so the estimate collapses onto a handful
     of parking spots and reports their stationary repeatability, not the road's.
     We therefore draw ONE sample per (cell, run) and average over repeated draws.

  2. Short-lag variogram nugget. Semivariance extrapolated to zero lag absorbs
     receiver noise, small-scale fading and GPS error together. Computed on RSRP
     detrended by log-distance so the deterministic path-loss slope does not leak
     into the nugget.

usage: error_floor.py [out_prefix]
"""
import json, math, os, sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

BASE = Path(__file__).resolve().parent
SCENE = BASE.parent / "scene"


def _find_data():
    """Locate COTS.csv. Override with COTS_DATA=/path/to/dir."""
    env = os.environ.get("COTS_DATA")
    if env:
        return Path(env)
    for cand in [BASE / "data", SCENE / "data",
                 *(p / "extracted" / "COTS_Dataset" for p in BASE.parents)]:
        if (cand / "COTS.csv").exists():
            return cand
    raise SystemExit("COTS.csv not found. Set COTS_DATA=/path/to/COTS_Dataset")


# cell id -> site. Suffix encodes the sector; the prefix encodes the site.
CELL_SITE = {"00019C00B": "Agronomy Farm", "00019C015": "Agronomy Farm",
             "00019C01F": "Agronomy Farm", "00019401F": "Curtiss Farm",
             "0001A0015": "Wilson Hall"}
RUN_GAP_S = 300.0        # a break longer than this starts a new drive run
NUGGET_FIT_M = 250.0     # short-lag window the nugget is extrapolated from


def robust_sd(v):
    """MAD-based sigma -- immune to the heavy tails RSRP differences actually have."""
    return 1.4826 * np.median(np.abs(v - np.median(v)))


def load():
    data = _find_data()
    df = pd.read_csv(data / "COTS.csv", dtype={"cellid": str})
    df["rsrp"] = pd.to_numeric(df["rsrp"], errors="coerce")
    df["ts"] = pd.to_datetime(df["timestamp_local"], format="ISO8601")
    df = df.sort_values("ts").reset_index(drop=True)

    dt = df["ts"].diff().dt.total_seconds()
    df["run"] = (dt > RUN_GAP_S).fillna(False).cumsum().astype(int)

    g = json.loads((SCENE / "georef.json").read_text())
    lat0r, lon0, R, K = (math.radians(g["origin_lat"]), g["origin_lon"],
                         g["radius"], g["k"])
    lat, lon = np.radians(df.lat.values), np.radians(df.lon.values - lon0)
    B = np.sin(lon) * np.cos(lat)
    df["x"] = 0.5 * K * R * np.log((1 + B) / (1 - B))
    df["y"] = K * R * (np.arctan(np.tan(lat) / np.cos(lon)) - lat0r)

    # distance to the serving site, for the log-distance detrend
    df["site"] = df.cellid.map(CELL_SITE)
    sx = df.site.map(lambda s: g["sites"][s]["x"] if isinstance(s, str) else np.nan)
    sy = df.site.map(lambda s: g["sites"][s]["y"] if isinstance(s, str) else np.nan)
    df["d_site"] = np.hypot(df.x - sx, df.y - sy)
    return df, g


def detrend(df):
    """Remove a per-sector log-distance trend so the variogram sees residual only."""
    res = np.full(len(df), np.nan)
    fits = {}
    for cid, sub in df.groupby("cellid"):
        m = sub.rsrp.notna() & (sub.d_site > 0)
        if m.sum() < 30:
            continue
        s = sub[m]
        A = np.column_stack([np.ones(len(s)), np.log10(s.d_site.values)])
        coef, *_ = np.linalg.lstsq(A, s.rsrp.values, rcond=None)
        res[s.index] = s.rsrp.values - A @ coef
        fits[cid] = (coef, len(s), float(np.std(s.rsrp.values - A @ coef)))
    df["rsrp_res"] = res
    return fits


def repeat_pairs(df, radius, cross_run_only=True, min_dt_s=0.0):
    """RSRP differences between samples within `radius` m on the same serving cell.

    Kept for the stationary-resample estimate (1b) only. For cross-run reproducibility
    use cell_repeat_diffs, which de-clusters -- see the module docstring.
    """
    out = []
    for cid, sub in df.groupby("cellid"):
        sub = sub[sub.rsrp.notna()]
        if len(sub) < 2:
            continue
        xy = np.column_stack([sub.x.values, sub.y.values])
        tree = cKDTree(xy)
        for i, j in tree.query_pairs(radius, output_type="ndarray"):
            ri, rj = sub.run.values[i], sub.run.values[j]
            if cross_run_only and ri == rj:
                continue
            dt = abs((sub.ts.values[i] - sub.ts.values[j]) / np.timedelta64(1, "s"))
            if dt < min_dt_s:
                continue
            out.append((np.hypot(*(xy[i] - xy[j])), dt,
                        sub.rsrp.values[i] - sub.rsrp.values[j],
                        sub.d_site.values[i], cid))
    return pd.DataFrame(out, columns=["sep_m", "dt_s", "d_rsrp", "d_site", "cellid"])


def decluster(df, cell_m, seed, col="rsrp"):
    """One randomly chosen sample per (grid cell, run, serving cell)."""
    d = df[df[col].notna() & df.cellid.isin(CELL_SITE)].copy()
    d["cx"] = np.floor(d.x / cell_m).astype(int)
    d["cy"] = np.floor(d.y / cell_m).astype(int)
    return (d.sample(frac=1.0, random_state=seed)
             .groupby(["cx", "cy", "cellid", "run"], as_index=False)
             .first())


def cell_repeat_diffs(df, cell_m, seed):
    """Cross-run RSRP differences, one sample per (cell, run) -- de-clustered."""
    one = decluster(df, cell_m, seed)
    out = []
    for (cx, cy, cid), s in one.groupby(["cx", "cy", "cellid"]):
        if len(s) < 2:
            continue
        v, r, ts = s.rsrp.values, s.run.values, s.ts.values
        for i in range(len(s)):
            for j in range(i + 1, len(s)):
                out.append((v[i] - v[j], float(s.d_site.values[i]),
                            abs((ts[i] - ts[j]) / np.timedelta64(1, "s")),
                            f"{r[i]}-{r[j]}", cid))
    return pd.DataFrame(out, columns=["d_rsrp", "d_site", "dt_s", "runs", "cellid"])


def repeat_sd(df, cell_m, n_draws=25):
    """sigma_d over independent de-clustered draws: mean, spread, and cell count."""
    sds, ns, means = [], [], []
    for k in range(n_draws):
        p = cell_repeat_diffs(df, cell_m, seed=1000 + k)
        if len(p) < 15:
            continue
        sds.append(np.std(p.d_rsrp.values, ddof=1))
        means.append(p.d_rsrp.values.mean())
        ns.append(len(p))
    if not sds:
        return None
    return dict(cell_m=cell_m, sd=float(np.mean(sds)), sd_se=float(np.std(sds)),
                mean=float(np.mean(means)), n_pairs=int(np.mean(ns)))


def variogram(df, col, max_lag=1000.0, n_bins=20, cross_run_only=False,
              cell_m=None, seed=0):
    """Classical and Cressie-robust semivariance in distance bins.

    Pass cell_m to de-cluster first -- otherwise parked-vehicle repeats dominate the
    shortest lag bin and the nugget is really a stationary-repeatability estimate.
    """
    sub = decluster(df, cell_m, seed, col=col) if cell_m else df[df[col].notna()]
    sub = sub[sub[col].notna()]
    rows = []
    for cid, s in sub.groupby("cellid"):
        if len(s) < 50:
            continue
        xy = np.column_stack([s.x.values, s.y.values])
        tree = cKDTree(xy)
        pairs = tree.query_pairs(max_lag, output_type="ndarray")
        if not len(pairs):
            continue
        i, j = pairs[:, 0], pairs[:, 1]
        if cross_run_only:
            k = s.run.values[i] != s.run.values[j]
            i, j = i[k], j[k]
        if not len(i):
            continue
        rows.append(np.column_stack([
            np.hypot(xy[i, 0] - xy[j, 0], xy[i, 1] - xy[j, 1]),
            s[col].values[i] - s[col].values[j]]))
    if not rows:
        return pd.DataFrame(columns=["lag_m", "n", "gamma", "gamma_robust"])
    P = np.vstack(rows)
    edges = np.linspace(0, max_lag, n_bins + 1)
    b = np.digitize(P[:, 0], edges) - 1
    out = []
    for k in range(n_bins):
        m = b == k
        if m.sum() < 30:
            continue
        d = P[m, 1]
        # Cressie-Hawkins robust estimator: resistant to the outliers a raw
        # mean-square picks up from a handful of deep fades.
        rob = (np.mean(np.abs(d) ** 0.5) ** 4) / (2 * (0.457 + 0.494 / m.sum()))
        out.append((0.5 * (edges[k] + edges[k + 1]), int(m.sum()),
                    0.5 * np.mean(d ** 2), rob))
    return pd.DataFrame(out, columns=["lag_m", "n", "gamma", "gamma_robust"])


def nugget(vg, col="gamma", fit_to=NUGGET_FIT_M):
    """Linear extrapolation of the short-lag variogram to zero lag."""
    s = vg[vg.lag_m <= fit_to]
    if len(s) < 2:
        return np.nan, np.nan
    A = np.column_stack([np.ones(len(s)), s.lag_m.values])
    coef, *_ = np.linalg.lstsq(A, s[col].values, rcond=None)
    return float(coef[0]), float(coef[1])


def main():
    prefix = sys.argv[1] if len(sys.argv) > 1 else "error_floor"
    df, g = load()

    print("=" * 74)
    print("A1  IRREDUCIBLE ERROR FLOOR")
    print("=" * 74)
    served = df[df.cellid.isin(CELL_SITE)]
    print(f"{len(df):,} rows, {df.run.nunique()} runs, "
          f"{len(served):,} served with RSRP, "
          f"{df.rsrp.isna().sum():,} rows report no RSRP at all")
    print(df.groupby("run").agg(n=("ts", "size"),
                                served=("cellid", lambda c: c.isin(CELL_SITE).sum()),
                                start=("ts", "min")).to_string())

    # how clustered is the sampling? this is why de-clustering is not optional
    c = served.assign(cx=(served.x // 20).astype(int), cy=(served.y // 20).astype(int))
    n20 = c.groupby(["cx", "cy"]).size()
    print(f"\nsampling is clustered: {int(n20[n20 >= 20].sum()):,} of {len(served):,} "
          f"served samples sit in {int((n20 >= 20).sum())} cells of 20 m "
          f"(deepest {int(n20.max())}). Naive pair counting would weight those "
          f"~n^2 and\nmeasure a parking spot, not a road. All cross-run estimates "
          f"below draw one sample per (cell, run).")

    fits = detrend(df)
    print("\nlog-distance detrend, RSRP = a + b*log10(d_m):")
    print(f"  {'cell':<12}{'n':>6}{'a':>9}{'b':>8}{'sd_resid':>10}")
    for cid, (coef, n, sd) in sorted(fits.items()):
        print(f"  {cid:<12}{n:>6}{coef[0]:>9.1f}{coef[1]:>8.1f}{sd:>10.2f}")

    # ---- Estimator 1: de-clustered cross-run reproducibility ------------------
    print("\n" + "-" * 74)
    print("1. REPEAT-PASS REPRODUCIBILITY  (de-clustered: one sample per cell per run)")
    print("-" * 74)
    print(f"  {'cell_m':>7}{'pairs':>7}{'mean':>8}{'sd':>8}{'+-':>6}"
          f"   sigma_meas = sd/sqrt(2)")
    rows = []
    for cm in (10.0, 20.0, 30.0, 50.0, 100.0, 200.0):
        r = repeat_sd(df, cm)
        if r is None:
            print(f"  {cm:>7.0f}   (too few repeat cells)")
            continue
        rows.append(r)
        print(f"  {cm:>7.0f}{r['n_pairs']:>7}{r['mean']:>8.2f}{r['sd']:>8.2f}"
              f"{r['sd_se']:>6.2f}        {r['sd']/math.sqrt(2):>5.2f} dB")
    rep = pd.DataFrame(rows)

    # sd grows with cell size because real spatial variation enters; extrapolate to 0
    sigma_d0 = np.nan
    if len(rep) >= 3:
        s = rep[rep.cell_m <= 100]
        A = np.column_stack([np.ones(len(s)), s.cell_m.values])
        c2, *_ = np.linalg.lstsq(A, s.sd.values ** 2, rcond=None)
        sigma_d0 = math.sqrt(max(c2[0], 0.0))
        print(f"\n  sd^2 is linear in cell size (real spatial variation enters as the")
        print(f"  cell grows). Extrapolating to a zero-size cell over cell_m <= 100 m:")
        print(f"    sd(0)      = {sigma_d0:.2f} dB")
        print(f"    sigma_meas = sd(0)/sqrt(2) = {sigma_d0/math.sqrt(2):.2f} dB")

    p20 = cell_repeat_diffs(df, 20.0, seed=1000)
    if len(p20) > 40:
        print("\n  20 m cells, one draw, stratified:")
        for by, bins, labels in (
                ("d_site", [0, 1000, 3000, 6000, 1e9], ["<1km", "1-3km", "3-6km", ">6km"]),
                ("dt_s", [0, 3600, 86400, 1e9], ["<1h", "1h-1d", ">1d"])):
            k = p20.assign(band=pd.cut(p20[by], bins, labels=labels))
            a = k.groupby("band", observed=True).d_rsrp.agg(
                n="size", mean="mean", sd=lambda v: np.std(v, ddof=1))
            print(f"    by {by}:")
            print("      " + a.to_string().replace("\n", "\n      "))

    # ---- Estimator 1b: stationary re-samples ----------------------------------
    print("\n" + "-" * 74)
    print("1b. STATIONARY RE-SAMPLES  (same run, <3 m apart, >30 s apart)")
    print("-" * 74)
    st = repeat_pairs(df, 3.0, cross_run_only=False, min_dt_s=30.0)
    sigma_stat = np.nan
    if len(st) >= 20:
        d = st.d_rsrp.values
        sigma_stat = float(np.std(d, ddof=1)) / math.sqrt(2)
        print(f"  {len(st):,} pairs from the parked stops   mean {d.mean():+.2f}  "
              f"sd {np.std(d, ddof=1):.2f}  ->  sigma_meas {sigma_stat:.2f} dB")
        print("  Receiver noise + temporal fading, with position error removed. A LOWER")
        print("  bound: a position-only model must also absorb GPS and micro-siting error.")
    else:
        print(f"  only {len(st)} pairs -- not enough to estimate")

    # ---- Estimator 2: variogram nugget ----------------------------------------
    print("\n" + "-" * 74)
    print("2. VARIOGRAM NUGGET  (de-clustered, detrended RSRP, per serving cell)")
    print("-" * 74)
    vg_x = variogram(df, "rsrp_res", max_lag=600.0, n_bins=24,
                     cross_run_only=True, cell_m=20.0)
    vg_all = variogram(df, "rsrp_res", max_lag=600.0, n_bins=24, cell_m=20.0)
    sigma_nug = np.nan
    for label, vg in (("all pairs", vg_all), ("cross-run only", vg_x)):
        if vg.empty:
            print(f"\n  {label}: no bins with enough pairs")
            continue
        c0, slope = nugget(vg)
        c0r, _ = nugget(vg, "gamma_robust")
        print(f"\n  {label}:")
        print(f"    {'lag_m':>7}{'n':>9}{'gamma':>9}{'gamma_rob':>11}{'sqrt(2g)':>10}")
        for _, r in vg[vg.lag_m <= NUGGET_FIT_M * 1.5].iterrows():
            print(f"    {r.lag_m:>7.0f}{int(r.n):>9,}{r.gamma:>9.1f}"
                  f"{r.gamma_robust:>11.1f}{math.sqrt(2*r.gamma):>10.2f}")
        print(f"    nugget over lags <= {NUGGET_FIT_M:.0f} m: c0 = {c0:.2f} dB^2"
              f"  -> sigma = {math.sqrt(max(c0,0)):.2f} dB"
              f"   [robust {math.sqrt(max(c0r,0)):.2f}]")
        if label == "cross-run only":
            sigma_nug = math.sqrt(max(c0, 0.0))

    # ---- Synthesis -------------------------------------------------------------
    sigma_rep = sigma_d0 / math.sqrt(2) if sigma_d0 == sigma_d0 else np.nan
    print("\n" + "=" * 74)
    print("SYNTHESIS")
    print("=" * 74)
    print(f"  stationary re-sample (lower bound)        = {sigma_stat:5.2f} dB")
    print(f"  repeat-pass, de-clustered, cell -> 0      = {sigma_rep:5.2f} dB")
    print(f"  variogram nugget, cross-run               = {sigma_nug:5.2f} dB")
    vals = [v for v in (sigma_rep, sigma_nug) if v == v]
    sig = float(np.mean(vals)) if vals else float("nan")
    rmse = 8.58
    print(f"\n  sigma_floor (repeat-pass / nugget mean)   = {sig:.2f} dB")
    print(f"  twin held-out RMSE                       = {rmse:.2f} dB")
    if sig < rmse:
        print(f"  model-attributable  sqrt({rmse:.2f}^2 - {sig:.2f}^2) = "
              f"{math.sqrt(rmse**2 - sig**2):.2f} dB")
        print(f"\n  A perfect position-only model would still score ~{sig:.2f} dB.")
        print(f"  Headroom between the twin and that floor: "
              f"{rmse - sig:.2f} dB of RMSE.")
    else:
        print("\n  The floor meets or exceeds the model's RMSE: the twin is already at")
        print("  the noise floor. STOP Stage B; spend the time on siting.")

    out = Path(f"{prefix}_summary.json")
    out.write_text(json.dumps({
        "sigma_stationary_dB": None if sigma_stat != sigma_stat else sigma_stat,
        "sigma_repeat_pass_dB": None if sigma_rep != sigma_rep else sigma_rep,
        "sigma_variogram_nugget_dB": None if sigma_nug != sigma_nug else sigma_nug,
        "sigma_floor_dB": sig,
        "twin_heldout_rmse_dB": rmse,
        "model_attributable_dB": (math.sqrt(rmse**2 - sig**2) if sig < rmse else None),
        "repeat_pass_table": rep.to_dict("records"),
        "variogram_cross_run": vg_x.to_dict("records"),
    }, indent=2))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
