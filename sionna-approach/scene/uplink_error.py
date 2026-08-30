"""End-to-end service-level error: how well does the twin predict UPLINK, not RSRP?

RMSE elsewhere in this repo is on RSRP in dBm -- the radio quantity the ray tracer natively
produces. Challenge 3 asks about service, and uplink is the binding constraint, so this
chains the two stages and scores the thing a placement decision would actually use:

    ray-traced path gain  ->(+offset)->  predicted RSRP  ->(fitted curve)->  predicted uplink

Both the offset and the RSRP->uplink curve are fitted on the training blocks only.
"""
import json, math, sys
import numpy as np, pandas as pd
from pathlib import Path

BASE = Path(__file__).resolve().parent
NPZ = sys.argv[1] if len(sys.argv) > 1 else "pred_ms_h30.npz"
BLOCK = 2000.0
DATA = None
for c in [BASE / "data", *(p / "extracted" / "COTS_Dataset" for p in BASE.parents)]:
    if (c / "COTS.csv").exists(): DATA = c; break

g = json.load(open(BASE / "georef.json"))
LAT0, LON0, R, K = g["origin_lat"], g["origin_lon"], g["radius"], g["k"]
lat0r = math.radians(LAT0)
def fromGeo(lat, lon):
    lat = np.radians(lat); lon = np.radians(lon - LON0)
    B = np.sin(lon) * np.cos(lat)
    return (0.5*K*R*np.log((1+B)/(1-B)), K*R*(np.arctan(np.tan(lat)/np.cos(lon)) - lat0r))

d = np.load(BASE / NPZ, allow_pickle=True)
order = [str(t) for t in d["tx_order"]]
serv = np.array([order.index(str(c)) for c in d["meas_cell"]])
pg = d["meas_pg"][np.arange(len(serv)), serv]
mx, my, rsrp = d["meas_x"], d["meas_y"], d["meas_rsrp"]

# rejoin uplink by matching on the projected coordinates
df = pd.read_csv(DATA / "COTS.csv", dtype={"cellid": str})
df["rsrp_n"] = pd.to_numeric(df["rsrp"], errors="coerce")
df = df[df.cellid.isin(order) & df.rsrp_n.notna()].copy()
df["x"], df["y"] = fromGeo(df.lat.values, df.lon.values)
key = {(round(a, 2), round(b, 2)): u for a, b, u in zip(df.x, df.y, df.uplink)}
ul = np.array([key.get((round(a, 2), round(b, 2)), np.nan) for a, b in zip(mx, my)])

bx = np.floor(mx / BLOCK).astype(int); by = np.floor(my / BLOCK).astype(int)
is_test = ((bx + by) % 2 == 1)
linked = pg > 0
tr, te = linked & ~is_test, linked & is_test
pred_rsrp = np.full(len(pg), np.nan)
pred_rsrp[linked] = 10 * np.log10(pg[linked])
pred_rsrp += float(np.mean(rsrp[tr] - pred_rsrp[tr]))

print(f"scene: {NPZ}")
print(f"\nSTAGE 1  RSRP (dBm) -- what every RMSE in this repo reports")
r1 = pred_rsrp[te] - rsrp[te]
print(f"  n {int(te.sum()):5d}   RMSE {np.sqrt(np.mean(r1**2)):5.2f} dB   "
      f"MAE {np.abs(r1).mean():5.2f}   r {np.corrcoef(pred_rsrp[te], rsrp[te])[0,1]:.3f}")

has = linked & np.isfinite(ul)
trU, teU = has & ~is_test, has & is_test
print(f"\nSTAGE 2  RSRP -> uplink (Mbps), curve fitted on train blocks only")
# uplink saturates, so fit in log space against RSRP with a monotone cubic
co = np.polyfit(rsrp[trU], np.log10(np.clip(ul[trU], 0.1, None)), 3)
pred_ul = 10 ** np.polyval(co, pred_rsrp)
meas_ul = ul
r2 = pred_ul[teU] - meas_ul[teU]
rel = np.abs(r2) / np.clip(meas_ul[teU], 1e-6, None)
print(f"  n {int(teU.sum()):5d}   RMSE {np.sqrt(np.mean(r2**2)):5.1f} Mbps   "
      f"MAE {np.abs(r2).mean():5.1f} Mbps   median |rel err| {100*np.median(rel):4.0f}%")
print(f"  measured uplink on those points: median {np.median(meas_ul[teU]):.1f} Mbps, "
      f"IQR {np.percentile(meas_ul[teU],25):.1f}-{np.percentile(meas_ul[teU],75):.1f}")
print(f"  r(pred, meas) = {np.corrcoef(pred_ul[teU], meas_ul[teU])[0,1]:.3f}")

print(f"\nSTAGE 3  the decision: is this location underserved?  (uplink < 10 Mbps)")
for thr in (5, 10, 20):
    yt = meas_ul[teU] < thr; yp = pred_ul[teU] < thr
    tp = int((yt & yp).sum()); fp = int((~yt & yp).sum()); fn = int((yt & ~yp).sum())
    prec = tp/(tp+fp) if tp+fp else float("nan"); rec = tp/(tp+fn) if tp+fn else float("nan")
    print(f"  < {thr:2d} Mbps: prevalence {100*yt.mean():4.1f}%   "
          f"precision {prec:.2f}   recall {rec:.2f}   "
          f"F1 {2*prec*rec/(prec+rec) if prec+rec else float('nan'):.2f}")
