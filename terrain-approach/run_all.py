"""
Run the whole pipeline end to end.

    python run_all.py

Four stages, each of which can also be run on its own from src/:
    features.py       COTS.csv        -> data/labeled.csv
    model.py          labeled.csv     -> data/grid.csv, reports/model.json
    optimize.py       grid.csv        -> reports/results.json, data/planner_data.json
    percentiles.py    labeled+grid    -> reports/percentiles.json
    analysis.py       all reports     -> reports/analysis.json

The planner is no longer built here. It is a repository-wide tool now, driven by
a coverage bundle rather than by this approach's internals:

    python -c "import sys; sys.path[:0]=['..','src']; import pandas as pd; ..."
    python -m common.build_planner bundles/*.json --dem data/dem10.npz

See ../common/PLANNER.md.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import analysis
import features
import model
import optimize
import percentiles

if __name__ == "__main__":
    t0 = time.time()
    print("=" * 66)
    features.build()
    print("=" * 66)
    model.run()
    print("=" * 66)
    optimize.run()
    print("=" * 66)
    percentiles.run()
    print("=" * 66)
    analysis.run()
    print("=" * 66)
    print(f"done in {time.time()-t0:.0f}s")
