"""End to end: measurements -> both simulators -> shared testbench -> one planner.

The repository now has two independent models of the same network -- a ray-traced digital
twin and a fitted parametric law -- and `common/` gives them one contract, one testbench
and one planner. This runs the whole thing:

  1. features      COTS.csv -> labeled.csv                (terrain-approach/src)
  2. testbench     both models, identical splits          (common/backtest.py)
  3. bundles       one coverage bundle per simulator      (common/bundle.py)
  4. planner       one page carrying both                 (common/build_planner.py)

Nothing here knows how either model works. That is the point of the contract: a third
approach is added by writing an adapter, not by touching this file.

usage: run_pipeline.py [--skip-features] [--draws N]
"""
import argparse
import importlib.util
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "terrain-approach" / "src"))
sys.path.insert(0, str(ROOT / "sionna-approach"))

OUT = ROOT / "reports"


def load_by_path(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-features", action="store_true")
    ap.add_argument("--draws", type=int, default=120)
    ap.add_argument("--skip-testbench", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    t0 = time.time()

    # -- 1. measurements -----------------------------------------------------
    csv = ROOT / "terrain-approach" / "data" / "labeled.csv"
    if not a.skip_features or not csv.exists():
        print("=" * 70); print("[1/4] features")
        import features
        features.build()
    df = pd.read_csv(csv, dtype={"cellid": str})
    print(f"      {len(df):,} rows")

    # -- 2. the two simulators, behind one contract --------------------------
    print("=" * 70); print("[2/4] simulators")
    from common.backtest import Testbench
    bench = Testbench.from_frame(df, serving_site="Agronomy Farm")

    from propagation import DEM, TX_AGL, link_features
    from features import load_sites
    dem = DEM()
    sites, _ = load_sites()
    mlat, mlon = sites["Agronomy Farm"]
    F = link_features(dem, mlat, mlon, bench.rows.lat.values, bench.rows.lon.values,
                      tx_agl=TX_AGL)
    bench.rows["fresnel_frac"], bench.rows["diff_db"] = F["fresnel_frac"], F["diff_db"]

    ta = load_by_path("ta_adapter", ROOT / "terrain-approach" / "src" / "adapter.py")
    sa = load_by_path("sa_adapter", ROOT / "sionna-approach" / "adapter.py")
    sims = [ta.ParametricSimulator(bench.rows),
            sa.SionnaHybridSimulator(bench.rows, only_site="Agronomy Farm"),
            sa.SionnaHybridSimulator(bench.rows)]
    for s in sims:
        print(f"      {s.info.name:<26} sigma {s.sigma_db:5.2f} dB  "
              f"fitted on {s.info.fitted_on_rows:,} rows")

    # -- 3. the shared testbench --------------------------------------------
    if not a.skip_testbench:
        print("=" * 70); print("[3/4] testbench -- identical splits for every model")
        import json
        rep = {}
        for s in sims:
            print(f"  {s.info.name}")
            rep[s.info.name] = bench.rsrp_report(s)
        (OUT / "testbench.json").write_text(json.dumps(rep, indent=2))
        print(f"      wrote {OUT/'testbench.json'}")

    # -- 4. bundles and one planner -----------------------------------------
    print("=" * 70); print("[4/4] coverage bundles and the planner")
    from common import bundle as bundle_mod
    from common import build_planner
    paths = []
    for s in sims:
        if s.info.name.endswith("-agronomy"):
            continue          # the comparison variant, not a planning surface
        p = OUT / f"bundle_{s.info.name}.json"
        bundle_mod.build(s, df, mlat, mlon, out=p, draws=a.draws)
        paths.append(p)
    build_planner.build(paths, dem_path=str(ROOT / "terrain-approach" / "data" / "dem10.npz"),
                        out=str(ROOT / "planner.html"))
    print("=" * 70)
    print(f"done in {time.time()-t0:.0f}s -> {ROOT/'planner.html'}")


if __name__ == "__main__":
    main()
