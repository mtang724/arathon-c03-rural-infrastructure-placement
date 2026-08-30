"""Render experiments.jsonl into a markdown table for the report.

usage: summarize_experiments.py [out.md]
"""
import json, sys
from pathlib import Path
BASE = Path(__file__).resolve().parent
rows = [json.loads(l) for l in open(BASE / "experiments.jsonl") if l.strip()]
VARY = ["terrain_mesh", "ground_material", "antenna_height_m", "downtilt_deg",
        "max_depth", "diffraction", "tx_pattern"]
out = ["| tag | terrain | ground | h (m) | tilt° | diffr | link | RMSE dB | r | bias dB | offset dB | n test |",
       "|---|---|---|---|---|---|---|---|---|---|---|---|"]
for r in rows:
    p, s = r["params"], r["results"]
    out.append("| `{}` | {} | {} | {:g} | {:g} | {} | {:.2f} | **{:.2f}** | {:.3f} | {:+.2f} | {:.1f} | {} |".format(
        r["tag"], p["terrain_mesh"].replace(".ply", ""), p["ground_material"].replace("itu_", ""),
        p["antenna_height_m"], p["downtilt_deg"], "on" if p["diffraction"] else "off",
        s["link_rate"], s["test_rmse_db"], s["test_corr"], s["test_bias_db"],
        s["offset_db"], s["n_test"]))
txt = "\n".join(out)
print(txt)
if len(sys.argv) > 1:
    Path(sys.argv[1]).write_text(txt + "\n")
    print(f"\nwrote {sys.argv[1]}", file=sys.stderr)
