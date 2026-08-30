"""
Stage 10 -- robustness with a defensible shadow-fading model.

The first version added the SAME shadow draw to the existing macro and to the
candidate, i.e. it treated shadow fading as a property of the LOCATION. That is
wrong, and it was wrong in the direction that flatters the result: it made the
two transmitters' errors cancel in the comparison, so the reported confidence
(winner within 2 km in 100% of draws) was far too high for a site that beats its
nearest rival by only 6.6%.

Shadow fading is a property of the PATH. Two transmitters at different bearings
look through different terrain and vegetation, so their fades are only partly
shared. What is genuinely common is clutter close to the receiver -- a tree line
beside the road obstructs every direction at once -- while everything mid-path
is specific to the link.

So the shadow at cell c from transmitter t is decomposed as

    S_t(c) = sqrt(rho) * Common(c) + sqrt(1 - rho) * Own_t(c)

with rho set by the angle the two paths subtend at the receiver:

    rho(theta) = RHO0 * exp(-theta / THETA_C)

Two paths arriving from nearly the same bearing share nearly all their clutter;
paths from opposite sides share only the receiver's immediate surroundings.
Because rho is an assumption and not a measurement, it is swept: rho = 1 is the
old (over-confident) model, rho = 0 treats the paths as fully independent, and
the angular model sits between them.
"""
import json

import numpy as np
import pandas as pd

from config import DATA, REPORTS, SERVING_SITE
from coverage import Scorer, avail_to_rsrp, build_candidates, build_grid
from coverage_terrain import macro_rsrp, ASSETS, fit_with_terrain, rsrp_from_node
from features import haversine_m, load_sites
from model import fit_outage_curve, fit_pathloss
from propagation import DEM, TX_AGL, link_features

RHO0 = 0.60          # correlation for two paths arriving on the same bearing
THETA_C = 45.0       # degrees; decay constant of the angular correlation
N_DRAWS = 200
SEED = 42


def bearing_deg(from_lat, from_lon, to_lat, to_lon):
    p1, p2 = np.radians(from_lat), np.radians(to_lat)
    dl = np.radians(np.asarray(to_lon) - from_lon)
    y = np.sin(dl) * np.cos(p2)
    x = np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dl)
    return (np.degrees(np.arctan2(y, x)) + 360.0) % 360.0


def run(verbose=True):
    rng = np.random.default_rng(SEED)
    dem = DEM()
    df = pd.read_csv(DATA / "labeled_terrain.csv", dtype={"cellid": str})
    plf = fit_pathloss(df); oc = fit_outage_curve(df, plf)
    pl = fit_with_terrain(df); sigma = pl["sigma"]
    thr = avail_to_rsrp(oc, 0.50)
    cells = build_grid(df); sc = Scorer(cells)
    clat, clon = cells.lat.to_numpy(), cells.lon.to_numpy()
    sites, _ = load_sites(); tl, to = sites[SERVING_SITE]

    base_r = macro_rsrp(pl, dem, clat, clon).astype(np.float32)

    cand = build_candidates(df, cells, plf)
    A = ASSETS["macro"]
    nC, nX = len(cand), len(cells)
    if verbose:
        print(f"[robust] {nC} candidates x {nX} cells, sigma {sigma:.2f} dB, "
              f"{N_DRAWS} draws")

    # delivered RSRP and per-path correlation weights
    R = np.empty((nC, nX), np.float32)
    W = np.empty((nC, nX), np.float32)          # sqrt(rho) per (candidate, cell)
    b_macro = bearing_deg(clat, clon, tl, to)   # cell -> existing macro
    for i, c in enumerate(cand.itertuples()):
        F = link_features(dem, c.lat, c.lon, clat, clon, tx_agl=A["agl"])
        d = haversine_m(c.lat, c.lon, clat, clon)
        R[i] = rsrp_from_node(pl, d, F["diff_db"], A["deficit"], F["fresnel_frac"])
        b_c = bearing_deg(clat, clon, c.lat, c.lon)
        th = np.abs((b_c - b_macro + 180.0) % 360.0 - 180.0)   # 0..180
        W[i] = np.sqrt(RHO0 * np.exp(-th / THETA_C))
    if verbose:
        rho = (W ** 2)
        print(f"[robust] angular rho: median {np.median(rho):.2f}, "
              f"p10 {np.percentile(rho,10):.2f}, p90 {np.percentile(rho,90):.2f}")

    base_score = sc(base_r >= thr)
    ranked = np.array([sc(np.maximum(base_r, R[i]) >= thr) - base_score
                       for i in range(nC)])
    top = int(np.argmax(ranked))
    dref = haversine_m(cand.loc[top, "lat"], cand.loc[top, "lon"],
                       cand.lat.to_numpy(), cand.lon.to_numpy())
    if verbose:
        print(f"[robust] deterministic winner: {cand.loc[top,'lat']:.5f},"
              f"{cand.loc[top,'lon']:.5f}  gain {ranked[top]:.3f}")
        r2 = np.sort(ranked)[::-1]
        print(f"[robust] runner-up gain {r2[1]:.3f} "
              f"({100*(r2[0]-r2[1])/r2[1]:.1f}% behind)\n")

    out = {"sigma_db": sigma, "n_draws": N_DRAWS, "rho0": RHO0, "theta_c": THETA_C,
           "winner": {"lat": float(cand.loc[top, "lat"]),
                      "lon": float(cand.loc[top, "lon"]),
                      "gain": float(ranked[top])}, "models": {}}

    for name, wfun in [("rho = 1  (location-shared, the old model)", None),
                       ("rho = 0.5 (constant, 3GPP-style)", 0.5),
                       ("rho(theta) angular  <- default", "ang"),
                       ("rho = 0  (fully independent paths)", 0.0)]:
        wins = np.zeros(nC, int)
        for _ in range(N_DRAWS):
            common = rng.normal(0, sigma, nX).astype(np.float32)
            if wfun is None:
                s_mac = common
                s_can = np.broadcast_to(common, (nC, nX))
            else:
                w = W if wfun == "ang" else np.float32(np.sqrt(wfun))
                own_m = rng.normal(0, sigma, nX).astype(np.float32)
                own_c = rng.normal(0, sigma, (nC, nX)).astype(np.float32)
                wm = np.sqrt(RHO0) if wfun == "ang" else w
                s_mac = wm * common + np.sqrt(max(0.0, 1 - (wm ** 2 if np.isscalar(wm)
                                                            else RHO0))) * own_m
                s_can = w * common[None, :] + np.sqrt(np.clip(1 - w ** 2, 0, 1)) * own_c
            bb = base_r + s_mac
            bs = sc(bb >= thr)
            gains = np.array([sc(np.maximum(bb, R[i] + s_can[i]) >= thr) - bs
                              for i in range(nC)])
            wins[int(np.argmax(gains))] += 1
        f = wins / N_DRAWS
        rec = {"exact": float(f[top]),
               "within_1km": float(f[dref <= 1000].sum()),
               "within_2km": float(f[dref <= 2000].sum()),
               "within_3km": float(f[dref <= 3000].sum()),
               "distinct_winners": int((wins > 0).sum()),
               "top5": [{"lat": float(cand.loc[i, "lat"]),
                         "lon": float(cand.loc[i, "lon"]),
                         "freq": float(f[i]),
                         "m_from_winner": round(float(dref[i]))}
                        for i in np.argsort(-f)[:5] if f[i] > 0]}
        out["models"][name] = rec
        if verbose:
            print(f"  {name:<42} exact {100*rec['exact']:>3.0f}%  "
                  f"<=1km {100*rec['within_1km']:>3.0f}%  "
                  f"<=2km {100*rec['within_2km']:>3.0f}%  "
                  f"<=3km {100*rec['within_3km']:>3.0f}%  "
                  f"({rec['distinct_winners']} distinct winners)")

    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "robustness.json").write_text(json.dumps(out, indent=2))
    if verbose:
        print("\n[robust] wrote reports/robustness.json")
    return out


if __name__ == "__main__":
    run()
