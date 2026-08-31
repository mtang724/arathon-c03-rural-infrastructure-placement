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


def hybrid_surface():
    """The completed surface, cropped clear of its own title.

    coverage_validation_ms.png's predicted panel is the ray tracer alone, so 43%
    of it is grey unmodelled cells -- which undercuts the very point the slide is
    making. surface_hybrid.png panel (b) is the same surface after profile
    diffraction fills those holes. Its title names the ITU recommendation, so the
    crop starts below it and the slide supplies its own caption.
    """
    f = ROOT / "sionna-approach" / "surface_hybrid.png"
    if not f.exists():
        return False
    src = Image.open(f).convert("RGB")
    ink = np.asarray(src).min(axis=2) < 235
    cols = bands(ink, 0, 0.02, 60)
    if len(cols) < 2:
        return False
    x0, x1 = cols[1]                              # panel (b)
    band = ink[:, x0:x1]
    rows = bands(band, 1, 0.02, 1)
    body = max(rows, key=lambda r: r[1] - r[0])   # the map, not the titles
    OUT.mkdir(exist_ok=True)
    src.crop((x0, body[0] - 4, x1, body[1] + 4)).save(OUT / "predicted.png")
    print(f"  predicted.png  panel b, x {x0}-{x1}, y {body[0]}-{body[1]}")
    return True


def main():
    src = Image.open(SRC).convert("RGB")
    ink = np.asarray(src).min(axis=2) < 235
    cols = bands(ink, 0, 0.02, 80)          # the three panels
    rows = bands(ink, 1)                    # [0] is the figure's own suptitle
    top = rows[1][0] - 8 if len(rows) > 1 else 0
    OUT.mkdir(exist_ok=True)
    names = ["measured", "predicted"]
    if hybrid_surface():          # a better predicted panel exists; keep measured only
        names = ["measured"]
    for name, (x0, x1) in zip(names, cols):
        src.crop((x0, top, x1, src.size[1])).save(OUT / f"{name}.png")
        print(f"  {name}.png  x {x0}-{x1}")


if __name__ == "__main__":
    main()
