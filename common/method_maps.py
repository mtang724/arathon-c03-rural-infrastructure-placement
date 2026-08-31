"""One predicted-coverage map per method, on a single shared scale.

Every bundle carries the same 4,731-cell demand grid, so rendering them with one
colour scale and one set of axes makes the differences between the models
genuinely comparable -- which four separately-styled figures would not.

    python -m common.method_maps

Writes sionna-approach/deck_panels/map_<name>.png.
"""
import json
import pathlib

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "sionna-approach" / "deck_panels"

# label, file, and the deck's accent for that method
METHODS = [
    ("Baseline", "reports/bundle_terrain-parametric.json", "#9A6E1E"),
    ("Ray tracing", "reports/bundle_sionna-hybrid.json", "#3E5C6B"),
    ("Deep learning", "bundles/terrain-fno.json", "#6B7F5C"),
    ("PINN", "reports/bundle_reveal-mt-pinn.json", "#B4532A"),
]
VMIN, VMAX = -120.0, -55.0


def main():
    OUT.mkdir(exist_ok=True)
    loaded = []
    for label, rel, col in METHODS:
        f = ROOT / rel
        if not f.exists():
            print(f"  {label}: missing {rel}")
            continue
        d = json.loads(f.read_text())
        g = d["grid"]
        loaded.append((label, col, np.array(g["lon"], float),
                       np.array(g["lat"], float),
                       np.array(d["baseline_rsrp_dbm"], float)))

    for label, col, lon, lat, v in loaded:
        fig, ax = plt.subplots(figsize=(3.5, 3.2), dpi=200)
        ax.scatter(lon, lat, c=np.clip(v, VMIN, VMAX), cmap="viridis",
                   vmin=VMIN, vmax=VMAX, s=3.1, marker="s", linewidths=0)
        ax.set_aspect(1 / np.cos(np.radians(float(lat.mean()))))
        ax.set_xticks([]); ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_color("#D9D3CB")
        # the served fraction is the number the eye is actually estimating
        served = 100.0 * float((v >= -90.0).mean())
        ax.set_title(f"{label}", fontsize=12, color=col, weight="bold",
                     loc="left", pad=6)
        ax.text(0.02, 0.03, f"{served:.0f}% of cells above threshold",
                transform=ax.transAxes, fontsize=8, color="#44403C",
                bbox=dict(fc="white", ec="none", alpha=0.8, pad=1.8))
        fig.tight_layout(pad=0.25)
        name = label.lower().replace(" ", "_")
        fig.savefig(OUT / f"map_{name}.png", facecolor="white")
        plt.close(fig)
        print(f"  map_{name}.png   {served:.0f}% above -90 dBm")


if __name__ == "__main__":
    main()
