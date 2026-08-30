"""Challenge 3: where does one added asset help most, and what does it change?

The brief asks "where would one additional relay, repeater, small cell, or measurement
campaign deliver the greatest improvement?", and wants before/after coverage under
explicit service thresholds, gains per intervention, and sensitivity to placement
constraints.

The design decision, from PLAN.md: Sionna's PathSolver takes MANY transmitters in one
solve, so K candidate sites cost one chunked pass and produce a dense path-gain matrix
G[m, k]. Everything after that -- the objective, the ranking, the before/after maps -- is
arithmetic over G. No ray tracing in the loop.

Each candidate is traced at TWO mast heights in the same solve, because the brief's asset
menu spans a 10 m relay pole and a macro-class mast, and height changes the geometry, not
just the link budget.

Power comes from DEPLOYMENT.md rather than being assumed. With an isotropic TX pattern the
traced path gain carries no antenna gain, so the per-asset constant is exactly the per-RE
EIRP: P_dBm - 10log10(3276 subcarriers) + antenna gain.

  macro-class   128 W, 18.1 dBi, 36.6 m   ->  34.0 dB   (reproduces the fitted macro)
  small cell      5 W, 13 dBi,   10 m     ->  14.8 dB
  relay/repeater  2 W, 13 dBi,   10 m     ->  10.9 dB

Candidates also get the same ITU-R P.526 profile diffraction the served surface uses, so
a candidate behind a ridge is penalised for it rather than credited with free space.

usage: siting.py <before_surface.npz> <scene.xml> <out_prefix> [candidate_spacing_m]
"""
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parent
SCENE = BASE.parent / "scene"
sys.path.insert(0, str(BASE))
from terrain_features import load_dem, profile_features   # noqa: E402
from make_surface import to_geo                           # noqa: E402

FC = 3.4608e9
LAMBDA = 299792458.0 / FC
N_SC_DB = 10 * np.log10(273 * 12)          # 100 MHz at 30 kHz SCS -> 35.15 dB

ASSETS = {                                  # name: (watts, dBi, mast_m)
    "relay/repeater": (2.0, 13.0, 10.0),
    "small cell":     (5.0, 13.0, 10.0),
    "macro-class":    (128.0, 18.1, 36.576),
}
MASTS = sorted({a[2] for a in ASSETS.values()})
THRESHOLDS = [-100.0, -105.0, -110.0]


def eirp_per_re(watts, gain_dbi):
    return 10 * np.log10(watts * 1e3) - N_SC_DB + gain_dbi


def trace(xml, cand_xy, dem_z, H, W, gx, gy, gz, out):
    """One chunked solve: every candidate at every mast height, all demand cells."""
    import mitsuba as mi
    from sionna.rt import load_scene, Transmitter, Receiver, PlanarArray, PathSolver
    scene = load_scene(str(SCENE / xml), merge_shapes=True)
    scene.frequency = FC
    assert "cuda" in mi.variant(), f"expected a GPU variant, got {mi.variant()}"
    scene.rx_array = PlanarArray(num_rows=1, num_cols=1, pattern="iso", polarization="V")
    scene.tx_array = PlanarArray(num_rows=1, num_cols=1, pattern="iso", polarization="V")

    def ground_z(x, y):
        o = mi.Point3f(np.asarray(x, np.float32), np.asarray(y, np.float32),
                       np.full(len(x), 600.0, np.float32))
        si = scene.mi_scene.ray_intersect(mi.Ray3f(o=o, d=mi.Vector3f(0, 0, -1)))
        return np.array(si.p.z), np.array(si.is_valid())

    cz, cok = ground_z(cand_xy[:, 0], cand_xy[:, 1])
    cand_xy, cz = cand_xy[cok], cz[cok]
    names = []
    for h in MASTS:
        for i in range(len(cand_xy)):
            nm = f"c{i}_h{h:g}"
            scene.add(Transmitter(name=nm, position=[float(cand_xy[i, 0]),
                                                     float(cand_xy[i, 1]),
                                                     float(cz[i] + h)]))
            names.append(nm)
    print(f"{len(cand_xy)} candidates x {len(MASTS)} masts = {len(names)} transmitters")

    solver = PathSolver()
    CH = int(os.environ.get("RT_CHUNK", 1500))
    parts, t0 = [], time.time()
    for lo in range(0, len(gx), CH):
        hi = min(lo + CH, len(gx))
        for nm in list(scene.receivers):
            scene.remove(nm)
        for i in range(lo, hi):
            scene.add(Receiver(name=f"r{i}", position=[float(gx[i]), float(gy[i]),
                                                       float(gz[i]) + 1.5]))
        p = solver(scene, max_depth=3, los=True, specular_reflection=True,
                   diffuse_reflection=False, refraction=False, synthetic_array=True)
        a, _ = p.cir(normalize_delays=False, out_type="numpy")
        parts.append(np.sum(np.abs(a) ** 2, axis=(1, 3, 4, 5)).astype(np.float32))
        print(f"  {hi:6d}/{len(gx)}  {time.time()-t0:6.1f}s", flush=True)
        del a, p
    G = np.concatenate(parts, axis=0)
    order = list(scene.transmitters)
    np.savez_compressed(out, G=G, tx_names=np.array(order),
                        cand_x=cand_xy[:, 0], cand_y=cand_xy[:, 1], cand_z=cz,
                        masts=np.array(MASTS))
    print(f"wrote {out}  G {G.shape}")
    return G, order, cand_xy, cz


def main():
    before_p, xml, prefix = sys.argv[1], sys.argv[2], sys.argv[3]
    spacing = float(sys.argv[4]) if len(sys.argv) > 4 else 2000.0
    S = np.load(before_p, allow_pickle=True)
    gx, gy, gz = S["grid_x"], S["grid_y"], S["grid_z"]
    before = S["rsrp_mean"]
    alpha = float(S["alpha_unlinked"])
    fs_off = float(S["fs_offset_db"])
    g = json.loads((SCENE / "georef.json").read_text())

    # ---- candidates on a regular grid over the demand area -------------------
    cx = np.arange(gx.min() + spacing / 2, gx.max(), spacing)
    cy = np.arange(gy.min() + spacing / 2, gy.max(), spacing)
    CX, CY = np.meshgrid(cx, cy)
    cand = np.column_stack([CX.ravel(), CY.ravel()])
    print(f"candidate grid {len(cx)} x {len(cy)} = {len(cand)} at {spacing:.0f} m spacing")

    cache = Path(f"{prefix}_G.npz")
    if cache.exists():
        d = np.load(cache, allow_pickle=True)
        G, order = d["G"], [str(t) for t in d["tx_names"]]
        cand = np.column_stack([d["cand_x"], d["cand_y"]]); cz = d["cand_z"]
        print(f"reusing {cache}  G {G.shape}")
    else:
        z, H, W = load_dem()
        G, order, cand, cz = trace(xml, cand, z, H, W, gx, gy, gz, cache)

    # ---- terrain profiles candidate -> every demand cell ---------------------
    z, H, W = load_dem()
    glat, glon = to_geo(gx, gy, g)
    clat, clon = to_geo(cand[:, 0], cand[:, 1], g)
    jcache = Path(f"{prefix}_J.npy")
    if jcache.exists():
        J = np.load(jcache)
        print(f"reusing {jcache}  J {J.shape}")
    else:
        J = np.zeros((len(gx), len(cand)), np.float32)
        t0 = time.time()
        for k in range(len(cand)):
            d_h = np.maximum(np.hypot(gx - cand[k, 0], gy - cand[k, 1]), 50.0)
            f = profile_features(clat[k], clon[k], MASTS[0], glat, glon, 1.5, d_h, z, H, W)
            J[:, k] = f["J_deygout"]
            if k % 10 == 0:
                print(f"  profiles {k+1}/{len(cand)}  {time.time()-t0:5.1f}s", flush=True)
        np.save(jcache, J)
        print(f"wrote {jcache}")

    # ---- evaluate every asset class at every candidate -----------------------
    idx = {nm: i for i, nm in enumerate(order)}
    D = np.hypot(gx[:, None] - cand[None, :, 0], gy[:, None] - cand[None, :, 1])
    fs = 20 * np.log10(LAMBDA / (4 * np.pi * np.maximum(D, 1.0)))
    results = {}
    for aname, (wpow, gdbi, mast) in ASSETS.items():
        off = eirp_per_re(wpow, gdbi)
        cols = [idx[f"c{k}_h{mast:g}"] for k in range(len(cand))]
        pg = G[:, cols]
        linked = pg > 0
        with np.errstate(divide="ignore"):
            pgdb = np.where(linked, 10 * np.log10(np.where(linked, pg, 1.0)), np.nan)
        # same hybrid as the served surface: tracer where it has a path, free space
        # minus fitted diffraction loss where it does not
        cand_rsrp = np.where(linked, np.where(np.isfinite(pgdb), pgdb, 0.0) + off,
                             fs + off + fs_off - 26.0 - alpha * J) - 0.0
        cand_rsrp = np.where(linked, cand_rsrp, fs + off - alpha * J)
        after = np.maximum(before[:, None], cand_rsrp)
        rows = []
        for thr in THRESHOLDS:
            b = float(np.mean(before > thr))
            a = np.mean(after > thr, axis=0)
            k = int(np.argmax(a))
            rows.append(dict(threshold=thr, before_pct=100 * b,
                             best_after_pct=float(100 * a[k]),
                             gain_pts=float(100 * (a[k] - b)), best_k=k,
                             best_xy=[float(cand[k, 0]), float(cand[k, 1])]))
        results[aname] = dict(eirp_per_re_db=off, mast_m=mast, rows=rows)
        print(f"\n{aname}  ({wpow:g} W, {gdbi:g} dBi, {mast:g} m mast, "
              f"per-RE EIRP {off:.1f} dBm)")
        for r in rows:
            print(f"  threshold {r['threshold']:.0f} dBm:  before {r['before_pct']:.1f}%"
                  f"  ->  {r['best_after_pct']:.1f}%   (+{r['gain_pts']:.1f} pts)"
                  f"  best candidate #{r['best_k']}")

    np.savez_compressed(f"{prefix}_eval.npz", cand_x=cand[:, 0], cand_y=cand[:, 1],
                        before=before, gx=gx, gy=gy)
    Path(f"{prefix}_results.json").write_text(json.dumps(results, indent=2))
    print(f"\nwrote {prefix}_results.json")


if __name__ == "__main__":
    main()
