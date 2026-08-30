"""Run the ReVeal-MT adapter through common/'s shared testbench."""
import sys, json
sys.path[:0] = [".", "pinn-approach/src"]
import numpy as np, pandas as pd

# Build the measurement frame from the already-processed COTS features.
SRC = "/home/david_alcantara/COTS3_Relay_Sionna/data/processed/scored_measurements.parquet"
m = pd.read_parquet(SRC)
df = pd.DataFrame({
    "lat": m.lat.values, "lon": m.lon.values, "rsrp": m.rsrp.values,
    "dist_m": m.dist_serving.values, "az_deg": m.bear_serving.values,
    # Blank cellid is the no-service state, and it is a blank STRING here, not
    # NaN -- 2,885 of 7,144 rows. `Testbench.from_frame` derives outage as
    # `cellid.isna() | cellid.eq("FFFFFFFFF")`, which silently misses every one
    # of them and reports a 99.8% base rate instead of 63.9%. Normalise first.
    "cellid": m.cellid.replace("", np.nan).values,
    "site": m.serving_site.values,
    "uplink": m.uplink.values, "downlink": m.downlink.values,
    "sinr": m.sinr.values, "rsrq": pd.to_numeric(m.rsrq, errors="coerce").values,
})
print(f"frame: {len(df):,} rows, {df.rsrp.notna().sum():,} with RSRP")

from common.backtest import Testbench, table
from common.simulator import check, describe
from adapter import ReVealMTSimulator

tb = Testbench.from_frame(df, serving_site="Agronomy Farm")
print(f"modelling rows: {len(tb.rows):,}")
for k, v in tb.blocks.items():
    print(f"  {k:<20} {len(np.unique(v))} folds, test sizes "
          f"{[int((v==b).sum()) for b in np.unique(v)]}")

sim = ReVealMTSimulator(epochs=3000)
sim.fit(tb.rows.lat.to_numpy(), tb.rows.lon.to_numpy(), tb.rows.rsrp.to_numpy())
print("\ncontract check:")
check(sim, tb.rows.lat.to_numpy()[:200], tb.rows.lon.to_numpy()[:200])
print("  PASS")
print(describe(sim))

rep = tb.run({"reveal-mt-pinn": sim}, out_path="reports/backtest_pinn.json")
print()
print(table(rep) if callable(table) else rep)
json.dump(rep, open("reports/backtest_pinn.json", "w"), indent=2, default=str)
