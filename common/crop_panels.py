"""Cut the measured and predicted panels out of the coverage validation figure.

The deck is otherwise all native objects, but these two maps are the exception:
a drawn schematic of a survey is a claim about the survey, and these are the
survey. Re-run after regenerating coverage_validation_ms.png.

    python -m common.crop_panels
"""
import pathlib
import numpy as np
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "sionna-approach" / "coverage_validation_ms.png"
OUT = ROOT / "sionna-approach" / "deck_panels"


def bands(mask, axis, floor=0.01, minlen=1):
    ink = mask.sum(axis=axis)
    on = ink > ink.max() * floor
    res, st = [], None
    for i, v in enumerate(on):
        if v and st is None:
            st = i
        elif not v and st is not None:
            if i - st >= minlen:
                res.append((st, i))
            st = None
    if st is not None:
        res.append((st, len(on)))
    return res


def main():
    src = Image.open(SRC).convert("RGB")
    ink = np.asarray(src).min(axis=2) < 235
    cols = bands(ink, 0, 0.02, 80)          # the three panels
    rows = bands(ink, 1)                    # [0] is the figure's own suptitle
    top = rows[1][0] - 8 if len(rows) > 1 else 0
    OUT.mkdir(exist_ok=True)
    for name, (x0, x1) in zip(("measured", "predicted"), cols):
        src.crop((x0, top, x1, src.size[1])).save(OUT / f"{name}.png")
        print(f"  {name}.png  x {x0}-{x1}")


if __name__ == "__main__":
    main()
