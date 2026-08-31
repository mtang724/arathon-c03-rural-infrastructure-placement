"""One figure per method showing what it works FROM, not what it produces.

Four predicted-coverage maps look nearly identical -- all four models put 34-41%
of cells above the threshold -- so showing four of them tells an audience almost
nothing about how the methods differ. These show the input instead: the curve the
baseline fits, the scene the tracer walks, the profiles the operator reads, and
the field the network learns.

    python -m common.method_figs
"""
import json
import pathlib

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "sionna-approach" / "deck_panels"
CSV = ROOT / "terrain-approach" / "data" / "labeled.csv"

INK, MUTE, RULE = "#1C1917", "#79716B", "#D9D3CB"
OCHRE, SLATE, SAGE, RUST = "#9A6E1E", "#3E5C6B", "#6B7F5C", "#B4532A"
FIG = dict(figsize=(3.5, 2.65), dpi=200)


def frame(ax):
    for sp in ax.spines.values():
        sp.set_color(RULE)
    ax.tick_params(colors=MUTE, labelsize=7.5, length=2.5)
    for lb in ax.get_xticklabels() + ax.get_yticklabels():
        lb.set_color(MUTE)


def main():
    OUT.mkdir(exist_ok=True)
    df = pd.read_csv(CSV, dtype={"cellid": str})
    df = df[df.rsrp.notna() & df.dist_m.notna() & (df.dist_m > 50)]

    # 1. baseline: the curve it fits, drawn through the cloud it fits to
    fig, ax = plt.subplots(**FIG)
    ax.scatter(df.dist_m / 1000, df.rsrp, s=1.4, c="#C9C2B8", linewidths=0)
    edges = np.geomspace(0.05, df.dist_m.max() / 1000, 22)
    mid = np.sqrt(edges[:-1] * edges[1:])
    med = [df.rsrp[(df.dist_m / 1000 >= a) & (df.dist_m / 1000 < b)].median()
           for a, b in zip(edges[:-1], edges[1:])]
    ax.plot(mid, med, color=OCHRE, lw=2.4)
    ax.axvline(3.0, color=INK, lw=0.9, ls=":")
    ax.text(3.15, -128, "slope changes\nat 3 km", fontsize=7.5, color=INK)
    ax.set_xscale("log"); ax.set_xlabel("distance from tower (km)", fontsize=8)
    ax.set_ylabel("signal (dBm)", fontsize=8); ax.set_ylim(-135, -40)
    frame(ax); fig.tight_layout(pad=0.25)
    fig.savefig(OUT / "how_baseline.png", facecolor="white"); plt.close(fig)

    # 2. ray tracing: the reconstructed scene itself
    src = ROOT / "sionna-approach" / "scene" / "preview_30m.png"
    if src.exists():
        im = Image.open(src).convert("RGB")
        w, h = im.size
        im.crop((int(w * 0.18), int(h * 0.06), int(w * 0.82), int(h * 0.78))) \
          .resize((700, 530), Image.LANCZOS) \
          .save(OUT / "how_raytracing.png")

    # 3. deep learning: the terrain profiles it consumes as functions
    prof = ROOT / "terrain-approach" / "data" / "profiles.npz"
    if prof.exists():
        d = np.load(prof)
        g = d["grel"]
        rng = np.random.default_rng(3)
        pick = rng.choice(len(g), 60, replace=False)
        fig, ax = plt.subplots(**FIG)
        for i in pick:
            ax.plot(np.linspace(0, 1, g.shape[1]), g[i], color=SAGE, lw=0.55,
                    alpha=0.5)
        ax.plot(np.linspace(0, 1, g.shape[1]), g[pick].mean(axis=0),
                color=INK, lw=2.0)
        ax.set_xlabel("tower  →  receiver", fontsize=8)
        ax.set_ylabel("ground height (m)", fontsize=8)
        ax.text(0.03, 0.9, "60 of 3,838 links", transform=ax.transAxes,
                fontsize=7.5, color=INK)
        frame(ax); fig.tight_layout(pad=0.25)
        fig.savefig(OUT / "how_deeplearning.png", facecolor="white")
        plt.close(fig)

    # 4. PINN: the leftover field, once distance is taken out
    fit = np.polyfit(np.log10(df.dist_m), df.rsrp, 1)
    resid = df.rsrp - np.polyval(fit, np.log10(df.dist_m))
    fig, ax = plt.subplots(**FIG)
    lim = float(np.nanpercentile(np.abs(resid), 96))
    sc = ax.scatter(df.lon, df.lat, c=np.clip(resid, -lim, lim), cmap="RdBu_r",
                    s=2.2, linewidths=0, vmin=-lim, vmax=lim)
    ax.set_aspect(1 / np.cos(np.radians(float(df.lat.mean()))))
    ax.set_xticks([]); ax.set_yticks([])
    ax.text(0.03, 0.04, "what distance alone\ncannot explain",
            transform=ax.transAxes, fontsize=7.5, color=INK,
            bbox=dict(fc="white", ec="none", alpha=0.85, pad=1.6))
    frame(ax); fig.tight_layout(pad=0.25)
    fig.savefig(OUT / "how_pinn.png", facecolor="white"); plt.close(fig)

    for f in sorted(OUT.glob("how_*.png")):
        print(f"  {f.name}  {Image.open(f).size}")


if __name__ == "__main__":
    main()
