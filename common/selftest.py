"""
Is the testbench working, and is my simulator wired into it correctly?

Two different questions, and this answers both.

    # 1. Is the bench itself sound? Reproduce a known-good result.
    python -m common.selftest --adapter terrain-approach/src:adapter:ParametricSimulator \
        --data terrain-approach/data/labeled_terrain.csv --site "Agronomy Farm" \
        --expect 7.35,7.33,9.66,9.78

    # 2. Is MY model wired in correctly? Same command, your adapter, no --expect.
    python -m common.selftest --adapter my-approach/src:adapter:MySimulator \
        --data my-approach/data/labeled.csv --site "Agronomy Farm"

WHY A REFERENCE CHECK AND NOT A UNIT TEST. The failure this guards against is
not a crash. It is the bench quietly changing what it measures -- a different
row filter, a different blocking seed, a buffer that stopped being applied --
after which every number it produces is still plausible and no longer comparable
with anything published before. So the test is: run the model whose numbers are
already written down in MODEL.md, and check they come back.

`--expect` takes in-sample, random, KMeans and angular-wedge RMSE in dB. For the
terrain-approach parametric model those are 7.35, 7.33, 9.66, 9.78. If your
build disagrees, the bench changed, not the weather.

`common/` still imports no approach: the adapter is loaded from the path you
give it.
"""
from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from .backtest import SPLITS, Testbench, table
from .simulator import check, describe

TOL_DB = 0.02


def load_adapter(spec: str):
    """`dir:module:Class` -> the class, with `dir` prepended to sys.path."""
    try:
        d, mod, cls = spec.split(":")
    except ValueError:
        raise SystemExit(f"--adapter must be dir:module:Class, got {spec!r}")
    sys.path.insert(0, str(Path(d).resolve()))
    sys.path.insert(0, str(Path.cwd()))
    return getattr(importlib.import_module(mod), cls)


def verify(sim, df, site=None, expect=None, verbose=True):
    """Contract check, then the full bench, then the reference comparison."""
    lat = df.lat.to_numpy()[:200]
    lon = df.lon.to_numpy()[:200]
    check(sim, lat, lon)
    if verbose:
        print("contract .......... PASS")
        print(f"model ............. {describe(sim)}\n")

    tb = Testbench.from_frame(df, serving_site=site)
    if verbose:
        print(f"modelling rows .... {len(tb.rows):,}")
        for nm in SPLITS:
            f = list(tb.folds(nm))
            print(f"  {nm:<20} {len(f)} folds, test sizes "
                  f"{[len(t) for _, _, t in f]}")
        print()

    rep = tb.run({sim.info.name: sim}, verbose=False)
    r = rep["simulators"][sim.info.name]
    print(table(rep))

    if not expect:
        print("\nNo --expect given, so this only shows the bench RAN. To prove "
              "the bench is\nunchanged, run it against a model whose numbers are "
              "already published.")
        return True

    got = [r["in_sample"]["rmse"]] + [r[s]["rmse"] for s in SPLITS]
    names = ["in sample", "random split", "kmeans blocks", "angular wedges"]
    print("\nreference check (tolerance {:.2f} dB)".format(TOL_DB))
    ok = True
    for nm, g, e in zip(names, got, expect):
        good = abs(g - e) <= TOL_DB
        ok &= good
        print(f"  {nm:<16} got {g:6.2f}   expected {e:6.2f}   "
              f"{'PASS' if good else 'FAIL  <-- the bench changed'}")
    print("\n" + ("ALL PASS -- the testbench measures what it measured before."
                  if ok else
                  "FAILED -- do not compare these numbers with previously "
                  "published ones\nuntil you know which of the row filter, the "
                  "blocking, the buffer or the\nseed moved."))
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--adapter", required=True, help="dir:module:Class")
    ap.add_argument("--data", required=True, help="measurement CSV")
    ap.add_argument("--site", default=None, help="serving site name")
    ap.add_argument("--expect", default=None,
                    help="in_sample,random,kmeans,wedges RMSE in dB")
    a = ap.parse_args()

    cls = load_adapter(a.adapter)
    df = pd.read_csv(a.data, dtype={"cellid": str})
    expect = [float(x) for x in a.expect.split(",")] if a.expect else None
    sys.exit(0 if verify(cls(df), df, a.site, expect) else 1)


if __name__ == "__main__":
    main()
