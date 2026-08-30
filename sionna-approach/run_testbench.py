"""Run this approach's model, and the other approach's, through the shared testbench.

`common/backtest.py` supplies identical splits, identical buffering and identical metrics
for every simulator in the repository, so this is the comparison that means something --
earlier ones put each approach's own number, from its own protocol, side by side.

usage: run_testbench.py [labeled.csv]
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "terrain-approach" / "src"))
sys.path.insert(0, str(ROOT / "sionna-approach"))

from common.backtest import Testbench, table          # noqa: E402


def main():
    csv = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        ROOT / "terrain-approach" / "data" / "labeled.csv"
    df = pd.read_csv(csv, dtype={"cellid": str})
    bench = Testbench.from_frame(df, serving_site="Agronomy Farm")
    print(f"testbench: {len(bench.rows):,} modelling rows of {len(bench.df):,}")

    # terrain-approach's fit needs two terrain columns that live in a gitignored
    # artifact nothing writes; rebuild them from its own link_features
    from propagation import DEM, TX_AGL, link_features
    from features import load_sites
    dem = DEM()
    sites, _ = load_sites()
    tl, to = sites["Agronomy Farm"]
    F = link_features(dem, tl, to, bench.rows.lat.values, bench.rows.lon.values,
                      tx_agl=TX_AGL)
    bench.rows["fresnel_frac"], bench.rows["diff_db"] = F["fresnel_frac"], F["diff_db"]

    reports = {}

    from adapter import simulators
    for sim in simulators(bench.rows):
        print(f"\n{sim.info.label}  (sigma {sim.sigma_db:.2f} dB, "
              f"fitted on {sim.info.fitted_on_rows:,} rows)")
        reports[sim.info.name] = bench.rsrp_report(sim)

    # both approaches name their module `adapter`, so load the other one by path
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "ta_adapter", ROOT / "terrain-approach" / "src" / "adapter.py")
    ta_adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ta_adapter)
    other = ta_adapter.ParametricSimulator(bench.rows)
    print(f"\n{other.info.label}  (sigma {other.sigma_db:.2f} dB, "
          f"fitted on {other.info.fitted_on_rows:,} rows)")
    reports[other.info.name] = bench.rsrp_report(other)

    print("\n" + "=" * 78)
    for nm, rep in reports.items():
        print(f"\n{nm}")
        try:
            print(table(rep))
        except Exception:
            for k, v in rep.items():
                if isinstance(v, dict):
                    print(f"  {k:<22} RMSE {v.get('rmse', float('nan')):.2f}  "
                          f"MAE {v.get('mae', float('nan')):.2f}  "
                          f"R2 {v.get('r2', float('nan')):+.3f}")


if __name__ == "__main__":
    main()
