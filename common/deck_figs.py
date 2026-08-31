"""Every map in the deck, drawn from the same data on the same axes.

The gap slide previously paired a crop from one project figure with a crop from
another. They looked comparable and were not: different extents, different
projections, different colour ramps. Two maps side by side is an implicit claim
that only the content differs, so both panels are now drawn here, from the same
bundle grid, with one extent and one colour scale.

    python -m common.deck_figs

Writes sionna-approach/deck_panels/{decision,gap_measured,gap_predicted}.png.
"""
import csv
import json
import pathlib

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "sionna-approach" / "deck_panels"
BUNDLE = ROOT / "reports" / "bundle_sionna-hybrid.json"
CSV = ROOT / "extracted" / "COTS_Dataset" / "COTS.csv"

INK, MUTE, RULE = "#1C1917", "#79716B", "#D9D3CB"
RUST, SLATE = "#B4532A", "#3E5C6B"
VMIN, VMAX = -120.0, -55.0


def frame(ax, lat):
    ax.set_aspect(1 / np.cos(np.radians(lat)))
    ax.set_xticks([]); ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_color(RULE)


def main():
    OUT.mkdir(exist_ok=True)
    b = json.loads(BUNDLE.read_text())
    g = b["grid"]
    glon = np.array(g["lon"], float); glat = np.array(g["lat"], float)
    gv = np.array(b["baseline_rsrp_dbm"], float)
    # one extent for every map, so the panels really are comparable
    pad = 0.004
    ext = (glon.min() - pad, glon.max() + pad, glat.min() - pad, glat.max() + pad)
    mid = float(glat.mean())

    mlon, mlat, mv = [], [], []
    with open(CSV) as fh:
        for r in csv.DictReader(fh):
            try:
                v = float(r["rsrp"])
            except (TypeError, ValueError):
                continue
            mlon.append(float(r["lon"])); mlat.append(float(r["lat"])); mv.append(v)
    mlon, mlat, mv = map(np.array, (mlon, mlat, mv))

    for name, fn in (("gap_measured", "measured"), ("gap_predicted", "predicted")):
        fig, ax = plt.subplots(figsize=(4.3, 3.5), dpi=200)
        if fn == "measured":
            ax.scatter(glon, glat, c="#EDEAE5", s=3.0, marker="s", linewidths=0)
            ax.scatter(mlon, mlat, c=np.clip(mv, VMIN, VMAX), cmap="viridis",
                       vmin=VMIN, vmax=VMAX, s=1.6, linewidths=0)
            note = f"{len(mlon):,} samples, all on roads"
        else:
            ax.scatter(glon, glat, c=np.clip(gv, VMIN, VMAX), cmap="viridis",
                       vmin=VMIN, vmax=VMAX, s=3.0, marker="s", linewidths=0)
            note = f"{len(glon):,} cells, every one predicted"
        ax.set_xlim(ext[0], ext[1]); ax.set_ylim(ext[2], ext[3]); frame(ax, mid)
        ax.text(0.02, 0.03, note, transform=ax.transAxes, fontsize=8.5,
                color=INK, bbox=dict(fc="white", ec="none", alpha=0.85, pad=2))
        fig.tight_layout(pad=0.2)
        fig.savefig(OUT / f"{name}.png", facecolor="white"); plt.close(fig)
        print(f"  {name}.png")

    # --- why another tower at all: show the service that is missing ---------
    # A continuous signal ramp is pretty and does not answer "why build". Split
    # the surface at the service threshold instead, so the unserved ground is
    # the thing the eye lands on.
    cand = b["prediction"]["candidates"]
    clon = np.array([c["lon"] for c in cand]); clat = np.array([c["lat"] for c in cand])
    hyp = json.loads((ROOT / "reports" / "hypothesis_test.json").read_text())
    rec = hyp["optimiser"]
    sites = json.loads((ROOT / "sionna-approach" / "scene" / "georef.json").read_text())["sites"]

    THR = -90.0
    served = gv >= THR
    fig, ax = plt.subplots(figsize=(6.2, 3.4), dpi=200)
    ax.scatter(glon[served], glat[served], c="#BFD3C1", s=2.6, marker="s",
               linewidths=0, label="usable service")
    ax.scatter(glon[~served], glat[~served], c=RUST, s=2.6, marker="s",
               linewidths=0, alpha=0.85, label="little or none")
    for nm, sv in sites.items():
        ax.plot(sv["lon"], sv["lat"], "^", ms=9, mfc=INK, mec="white", mew=1.1,
                zorder=5)
    ax.plot(rec["lon"], rec["lat"], "*", ms=24, mfc="#FFD400", mec=INK, mew=1.2,
            zorder=6)
    ax.annotate("one more here?", (rec["lon"], rec["lat"]),
                xytext=(13, -20), textcoords="offset points", fontsize=10.5,
                color=INK, weight="bold",
                bbox=dict(fc="white", ec=RULE, alpha=0.93, pad=2.5),
                arrowprops=dict(arrowstyle="-", color=INK, lw=1.0))
    ax.set_xlim(ext[0], ext[1]); ax.set_ylim(ext[2], ext[3]); frame(ax, mid)
    leg = ax.legend(loc="upper left", fontsize=8.5, frameon=True, markerscale=3,
                    borderpad=0.4, handletextpad=0.5)
    leg.get_frame().set_edgecolor(RULE); leg.get_frame().set_alpha(0.93)
    pct = 100.0 * float((~served).mean())
    ax.text(0.02, 0.035, f"{pct:.0f}% of the area has little or no service",
            transform=ax.transAxes, fontsize=9.5, color=INK, weight="bold",
            bbox=dict(fc="white", ec="none", alpha=0.88, pad=2.4))
    fig.tight_layout(pad=0.2)
    fig.savefig(OUT / "decision.png", facecolor="white"); plt.close(fig)
    print(f"  decision.png   {pct:.0f}% unserved")


if __name__ == "__main__":
    main()
