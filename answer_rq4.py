"""RQ4 — does model-driven siting beat the naive baselines the brief names?

Runs common/baselines.py for both simulators, both decisive asset classes, and two
criteria, so the answer cannot rest on one lucky configuration.

usage: python answer_rq4.py [--out reports/rq4.json]
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "terrain-approach" / "src"))

from common import criteria as crit                                  # noqa: E402
from common.baselines import compare                                 # noqa: E402
from common.demand import ASSETS, Scorer, build_candidates, build_grid  # noqa: E402
from common.recommend import load_adapter, node_surfaces, threshold_rsrp  # noqa: E402

CASES = [("availability", 0.50), ("uplink_p50_mbps", 10.0)]
ASSETS_TESTED = ["macro", "relay"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "terrain-approach" / "data" / "labeled.csv"))
    ap.add_argument("--out", default=str(ROOT / "reports" / "rq4.json"))
    a = ap.parse_args()

    df = pd.read_csv(a.data, dtype={"cellid": str})
    if "outage" not in df:
        df["outage"] = df.cellid.isna() | df.cellid.eq("FFFFFFFFF")
    rows = df[df.rsrp.notna() & df.site.eq("Agronomy Farm")].copy().reset_index(drop=True)

    from features import load_sites
    from propagation import DEM, TX_AGL, link_features
    mlat, mlon = load_sites()[0]["Agronomy Farm"]
    F = link_features(DEM(), mlat, mlon, rows.lat.values, rows.lon.values, tx_agl=TX_AGL)
    rows["fresnel_frac"], rows["diff_db"] = F["fresnel_frac"], F["diff_db"]

    sims = [load_adapter(s)(rows) for s in
            ("terrain-approach/src:adapter:ParametricSimulator",
             "sionna-approach:adapter:SionnaHybridSimulator")]

    cells = build_grid(df)
    cand = build_candidates(df, cells, mlat, mlon, donor_rsrp_fn=sims[0].macro_rsrp)
    scorer = Scorer(cells)
    print(f"[rq4] {len(cells):,} demand cells | {len(cand)} candidates | "
          f"{scorer.tot_rk:.1f} route-km")

    out = []
    for sim in sims:
        print(f"\n[rq4] {sim.info.name}")
        cs = crit.build(df, sim, verbose=False)
        R_by_agl = node_surfaces(sim, cand, cells)
        for asset in ASSETS_TESTED:
            R = R_by_agl[ASSETS[asset]["agl"]] - ASSETS[asset]["deficit"]
            for cname, target in CASES:
                if cname not in cs:
                    continue
                thr = threshold_rsrp(cs[cname], target)
                if not np.isfinite(thr):
                    continue
                t = compare(sim, df, cells, cand, R, asset, thr, scorer, mlat, mlon)
                t.insert(0, "criterion", f"{cname}>={target}")
                t.insert(0, "asset", asset)
                t.insert(0, "model", sim.info.name)
                out.append(t)

    res = pd.concat(out, ignore_index=True)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(str(a.out).replace(".json", ".csv"), index=False)

    # ---- the verdict, across every configuration -------------------------
    opt = res[res.method.str.startswith("optimiser")]
    base = res[res.method.str.startswith("worst measured")]
    m = opt.merge(base, on=["model", "asset", "criterion"], suffixes=("_opt", "_base"))
    m["ratio"] = m.gain_opt / m.gain_base.replace(0, np.nan)
    print("\n" + "=" * 78)
    print("RQ4 VERDICT — optimiser vs the brief's named baseline")
    print("=" * 78)
    print(f"  {'model':<20}{'asset':<8}{'criterion':<24}{'opt':>8}{'worst':>8}{'x':>7}")
    for _, r in m.iterrows():
        print(f"  {r.model:<20}{r.asset:<8}{r.criterion:<24}"
              f"{100*r.gain_opt:>8.2f}{100*r.gain_base:>8.2f}"
              f"{r.ratio:>7.1f}" if np.isfinite(r.ratio) else
              f"  {r.model:<20}{r.asset:<8}{r.criterion:<24}"
              f"{100*r.gain_opt:>8.2f}{100*r.gain_base:>8.2f}{'inf':>7}")
    print(f"\n  optimiser beats the worst-measured-point baseline in "
          f"{int((m.gain_opt > m.gain_base).sum())} of {len(m)} configurations")
    print(f"  median advantage: {m.ratio.median():.1f}x")
    pr = base.random_percentile.dropna()
    print(f"\n  the named baseline sits at the {pr.median():.0f}th percentile of "
          f"random feasible placements (median across configurations)")
    Path(a.out).write_text(json.dumps({
        "verdict": {"n_configs": int(len(m)),
                    "optimiser_wins": int((m.gain_opt > m.gain_base).sum()),
                    "median_ratio": float(m.ratio.median()),
                    "baseline_random_percentile_median": float(pr.median())},
        "rows": res.to_dict("records")}, indent=2))
    print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
