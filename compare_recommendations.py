"""Sweep every model against every parameter, and report how much the answer moves.

`common/recommend.py` holds the model-agnostic sweep. This runner supplies the
approach-specific preparation `common/` deliberately does not know about --
terrain-approach's fit needs two terrain columns that live in a gitignored artifact
nothing writes, so they are rebuilt from its own `link_features`.

usage: python compare_recommendations.py [--out reports/recommendations.json]
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "terrain-approach" / "src"))

from common.recommend import analyse, load_adapter, sweep     # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "terrain-approach" / "data" / "labeled.csv"))
    ap.add_argument("--out", default=str(ROOT / "reports" / "recommendations.json"))
    ap.add_argument("--site", default="Agronomy Farm")
    a = ap.parse_args()

    df = pd.read_csv(a.data, dtype={"cellid": str})
    if "outage" not in df:
        df["outage"] = df.cellid.isna() | df.cellid.eq("FFFFFFFFF")
    rows = df[df.rsrp.notna() & df.site.eq(a.site)].copy().reset_index(drop=True)

    from features import load_sites
    from propagation import DEM, TX_AGL, link_features
    mlat, mlon = load_sites()[0][a.site]
    F = link_features(DEM(), mlat, mlon, rows.lat.values, rows.lon.values,
                      tx_agl=TX_AGL)
    rows["fresnel_frac"], rows["diff_db"] = F["fresnel_frac"], F["diff_db"]

    sims = []
    for spec in ("terrain-approach/src:adapter:ParametricSimulator",
                 "sionna-approach:adapter:SionnaHybridSimulator"):
        sims.append(load_adapter(spec)(rows))
        print(f"[load] {sims[-1].info.name:<24} sigma {sims[-1].sigma_db:.2f} dB")

    rec, cells, cand = sweep(sims, df, mlat, mlon)
    res = analyse(rec)

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": res,
                               "recommendations": rec.to_dict("records")}, indent=2))
    rec.to_csv(str(out).replace(".json", ".csv"), index=False)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
