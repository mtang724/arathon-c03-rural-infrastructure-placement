"""Refine the twin by fitting what the dataset can actually identify.

The twin currently fits ONE scalar (`offset`, EIRP + antenna gain) and asserts everything
else. [`DEPLOYMENT.md`](../DEPLOYMENT.md) establishes why that is the weak point: the real
radio is a 192-element AIR 6419 that sweeps a *set* of SSB beams over elevation, so there
is no single boresight and no single downtilt. Fitting a tilt angle to one `tr38901`
element is the wrong model shape -- which is why the 0-10 deg tilt sweep in RESULTS.md came
out monotonically harmful.

So instead of fitting a tilt, fit the pattern itself: an empirical gain correction read off
the training-block residuals as a function of elevation angle and azimuth offset. This
subsumes tilt, pattern shape and per-sector EIRP in one object.

Model ladder, each fitted on TRAIN blocks and scored on HELD-OUT blocks:

  M0  global offset                      the current model
  M1  per-sector offsets                 3 params; a >3 dB spread means azimuth/pattern
  M2  M1 + g(elevation angle)            the empirical vertical pattern
  M2c M1 + f(log distance)   CONTROL     elevation and distance are near-collinear, so
                                         this says whether M2 is a pattern or a path-loss fix
  M3  M2 + h(azimuth offset)             the empirical horizontal pattern

Corrections are lookup tables over quantile bins -- fitted on train, applied to test by
linear interpolation. That is deliberately the most interpretable form: the table IS the
pattern, and it can be read against a real antenna datasheet.

usage: fit_pattern.py <pred.npz> [scene.xml]
"""
import json
import math
import sys
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parent
SCENE = BASE.parent / "scene"
BLOCK = 2000.0
RSRP_FLOOR = -140.0     # A3 sensitivity floor: minimum RSRP the UE ever reported
N_BINS = 12


def load_geometry(npz_path, xml):
    """Path gains from the npz, plus the geometry the pattern is a function of."""
    d = np.load(npz_path, allow_pickle=True)
    tx_order = [str(t) for t in d["tx_order"]]
    mx, my, rsrp = d["meas_x"], d["meas_y"], d["meas_rsrp"]
    serv = np.array([tx_order.index(str(c)) for c in d["meas_cell"]])
    pg = d["meas_pg"][np.arange(len(serv)), serv]
    h_ant = float(d["h_ant"])
    sx, sy, sg = float(d["site_x"]), float(d["site_y"]), float(d["site_ground"])

    # receiver ground height is not stored in the npz -- ray-cast it back out of the scene
    import mitsuba as mi
    from sionna.rt import load_scene
    scene = load_scene(str(SCENE / xml), merge_shapes=True)
    o = mi.Point3f(mx.astype(np.float32), my.astype(np.float32),
                   np.full(len(mx), 600.0, np.float32))
    si = scene.mi_scene.ray_intersect(mi.Ray3f(o=o, d=mi.Vector3f(0, 0, -1)))
    rz = np.array(si.p.z) + 1.5

    dx, dy = mx - sx, my - sy
    d_h = np.hypot(dx, dy)
    h_tx = sg + h_ant
    # depression angle: positive means the receiver is below the transmitter
    elev = np.degrees(np.arctan2(h_tx - rz, d_h))
    # azimuth offset from the serving sector's boresight, signed, in [-180, 180]
    AZ = {"00019C00B": 0.0, "00019C015": 115.0, "00019C01F": 240.0}
    bore = np.array([AZ[tx_order[s]] for s in serv])
    brg = (np.degrees(np.arctan2(dx, dy))) % 360.0          # compass bearing tx->rx
    az_off = (brg - bore + 180.0) % 360.0 - 180.0
    return dict(pg=pg, rsrp=rsrp, serv=serv, tx_order=tx_order, mx=mx, my=my,
                d_h=d_h, elev=elev, az_off=az_off, n_sec=len(tx_order))


def blocked_split(mx, my):
    bx = np.floor(mx / BLOCK).astype(int)
    by = np.floor(my / BLOCK).astype(int)
    return ((bx + by) % 2 == 1)


def fit_table(x, resid, n_bins=N_BINS):
    """Mean residual per quantile bin -> (bin centre, correction) lookup table."""
    edges = np.quantile(x, np.linspace(0, 1, n_bins + 1))
    edges[0] -= 1e-6
    edges[-1] += 1e-6
    ctr, val = [], []
    for k in range(n_bins):
        m = (x > edges[k]) & (x <= edges[k + 1])
        if m.sum() < 20:
            continue
        ctr.append(float(np.median(x[m])))
        val.append(float(np.mean(resid[m])))
    return np.array(ctr), np.array(val)


def apply_table(x, ctr, val):
    if len(ctr) < 2:
        return np.zeros_like(x)
    return np.interp(x, ctr, val)          # flat extrapolation outside the fitted range


def score(pred, meas):
    r = pred - meas
    return dict(n=int(len(r)), rmse=float(np.sqrt(np.mean(r**2))),
                mae=float(np.mean(np.abs(r))), bias=float(r.mean()),
                corr=float(np.corrcoef(pred, meas)[0, 1]))


def main():
    npz = sys.argv[1]
    xml = sys.argv[2] if len(sys.argv) > 2 else "mitsuba/ames.xml"
    g = load_geometry(npz, xml)

    ok = g["pg"] > 0
    test = blocked_split(g["mx"], g["my"])
    tr, te = ok & ~test, ok & test
    pgdb = np.full(len(g["pg"]), np.nan)
    pgdb[ok] = 10 * np.log10(g["pg"][ok])
    rsrp, serv, elev, az, d_h = g["rsrp"], g["serv"], g["elev"], g["az_off"], g["d_h"]

    print("=" * 78)
    print("REFINING THE TWIN -- empirical pattern fitted on training blocks")
    print("=" * 78)
    print(f"{ok.sum():,} linked of {len(ok):,} measured  |  train {tr.sum():,}  "
          f"test {te.sum():,}  (2 km checkerboard)")
    rho = np.corrcoef(elev[ok], np.log10(d_h[ok]))[0, 1]
    print(f"\nCONFOUND CHECK: corr(elevation angle, log10 distance) = {rho:+.3f}")
    print("  Elevation angle is a near-deterministic function of distance at fixed")
    print("  terrain height, so M2 needs the M2c control to be interpretable.")

    # ---- A2: residual decomposition on the current model ---------------------
    off0 = float(np.mean(rsrp[tr] - pgdb[tr]))
    res0 = pgdb + off0 - rsrp
    print(f"\n--- A2  residual decomposition (global offset {off0:.1f} dB) ---")
    for name, x, unit in (("elevation angle", elev, "deg"),
                          ("azimuth off boresight", np.abs(az), "deg"),
                          ("distance", d_h / 1000.0, "km")):
        edges = np.quantile(x[ok], np.linspace(0, 1, 7))
        print(f"  by {name} ({unit}):")
        for k in range(6):
            m = ok & (x > edges[k]) & (x <= edges[k + 1])
            if m.sum() < 10:
                continue
            print(f"    {edges[k]:7.2f}..{edges[k+1]:<7.2f} n={m.sum():>5}  "
                  f"mean resid {np.mean(res0[m]):+7.2f}  sd {np.std(res0[m]):6.2f}")
    print("  by sector:")
    for s, cid in enumerate(g["tx_order"]):
        m = ok & (serv == s)
        if m.sum():
            print(f"    {cid}  n={m.sum():>5}  mean resid {np.mean(res0[m]):+7.2f}  "
                  f"sd {np.std(res0[m]):6.2f}")

    # ---- model ladder --------------------------------------------------------
    results = {}

    def report(tag, pred_all, extra=""):
        s = score(pred_all[te], rsrp[te])
        st = score(pred_all[tr], rsrp[tr])
        s["rmse_train"] = st["rmse"]
        results[tag] = s
        base = results.get("M0", s)["rmse"]
        print(f"  {tag:<5}{st['rmse']:>8.2f}{s['rmse']:>8.2f}{s['bias']:>8.2f}"
              f"{s['corr']:>8.3f}{s['rmse']-base:>+9.2f}   {extra}")

    print(f"\n--- model ladder, all scored on the SAME held-out blocks (n={te.sum():,}) ---")
    print(f"  {'model':<5}{'TRAIN':>8}{'TEST':>8}{'bias':>8}{'r':>8}{'dTEST':>9}   notes")

    # M0: global offset
    pred = pgdb + off0
    report("M0", pred, "global offset (current model)")

    # M1: per-sector offsets
    offs = np.array([float(np.mean(rsrp[tr & (serv == s)] - pgdb[tr & (serv == s)]))
                     if (tr & (serv == s)).sum() else off0 for s in range(g["n_sec"])])
    pred1 = pgdb + offs[serv]
    report("M1", pred1, f"per-sector offsets {np.round(offs,1)} spread "
                        f"{offs.max()-offs.min():.1f} dB")

    # M2: + empirical elevation pattern
    r1 = pred1 - rsrp
    ce, ve = fit_table(elev[tr], r1[tr])
    pred2 = pred1 - apply_table(elev, ce, ve)
    report("M2", pred2, f"+ g(elevation), {len(ce)} bins, span "
                        f"{ve.max()-ve.min():.1f} dB")

    # M2c: control -- same machinery on log distance instead
    cd, vd = fit_table(np.log10(d_h[tr]), r1[tr])
    pred2c = pred1 - apply_table(np.log10(d_h), cd, vd)
    report("M2c", pred2c, f"CONTROL: f(log d), span {vd.max()-vd.min():.1f} dB")

    # M3: + empirical azimuth pattern, on what M2 leaves
    r2 = pred2 - rsrp
    ca, va = fit_table(az[tr], r2[tr])
    pred3 = pred2 - apply_table(az, ca, va)
    report("M3", pred3, f"+ h(azimuth), span {va.max()-va.min():.1f} dB")

    # ---- A3 sensitivity floor -------------------------------------------------
    print(f"\n--- A3  with a {RSRP_FLOOR:.0f} dBm receiver sensitivity floor ---")
    for tag, p in (("M0", pred), ("M3", pred3)):
        keep = te & (p > RSRP_FLOOR)
        s = score(p[keep], rsrp[keep])
        print(f"  {tag:<5} n={s['n']:>5} (dropped {int(te.sum()-keep.sum())})  "
              f"RMSE {s['rmse']:.2f}  bias {s['bias']:+.2f}  r {s['corr']:.3f}")

    # ---- does the elevation correction transfer at all? ----------------------
    print("\n--- bin-count sweep on g(elevation): does ANY resolution transfer? ---")
    print(f"  {'bins':>5}{'train RMSE':>12}{'test RMSE':>11}{'span dB':>9}"
          f"{'corr(corr_pred, test resid)':>29}")
    for nb in (2, 3, 4, 6, 8, 12, 20):
        c, v = fit_table(elev[tr], r1[tr], n_bins=nb)
        if len(c) < 2:
            continue
        adj = apply_table(elev, c, v)
        pk = pred1 - adj
        rho2 = np.corrcoef(adj[te], r1[te])[0, 1]
        print(f"  {nb:>5}{score(pk[tr], rsrp[tr])['rmse']:>12.2f}"
              f"{score(pk[te], rsrp[te])['rmse']:>11.2f}{v.max()-v.min():>9.1f}"
              f"{rho2:>29.3f}")
    print("  A real antenna pattern transfers: the correction fitted on train blocks")
    print("  should correlate with the residual it is meant to remove on test blocks.")

    # ---- the fitted pattern, as a table you can read against a datasheet ------
    print("\n--- fitted empirical vertical pattern (relative gain vs elevation) ---")
    print(f"  {'elev deg':>9}{'correction dB':>15}")
    for c, v in zip(ce, ve):
        print(f"  {c:>9.2f}{-v:>15.2f}")

    out = BASE / "fit_pattern_summary.json"
    out.write_text(json.dumps({
        "npz": str(npz), "offset_global": off0,
        "sector_offsets": dict(zip(g["tx_order"], offs.tolist())),
        "elev_table": {"deg": ce.tolist(), "gain_db": (-ve).tolist()},
        "az_table": {"deg": ca.tolist(), "gain_db": (-va).tolist()},
        "corr_elev_logd": float(rho),
        "heldout": results}, indent=2))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
