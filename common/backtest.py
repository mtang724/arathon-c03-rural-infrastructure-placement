"""
The shared backtest testbench.

One harness, one set of splits, one set of metrics, for every simulator in this
repository. If two models are compared on different splits they are not being
compared, so the splits live here rather than inside any one approach.

WHAT IT ASKS. Run the simulator with NO added transmitter and compare it to what
the van actually recorded. Everything downstream -- coverage percentages, siting,
the recommendation -- rests on the claim that the model describes the network as
it is today, so that claim gets tested first and separately.

THREE SPLITS, AND WHY MORE THAN ONE.

  RANDOM SPLIT is reported and should be DISCOUNTED. Consecutive samples are
  2.63 s apart, which is metres apart at driving speed, so a random split tests
  the model on places it trained on. For a model that consumes any per-location
  descriptor it is worse than uninformative: a terrain profile identifies its own
  location to a median of 12 m, so a flexible model can answer by looking up its
  training set and score better than the physics while having learned no physics.
  It is here as a contamination gauge -- the gap between it and the geographic
  splits measures how much a model is memorising.

  KMEANS ON POSITION carves compact regions. One is the near-tower cluster, so
  holding it out deletes every sample under ~2 km and forces the distance law to
  extrapolate inward. Harshest, and least like deployment, where near-tower data
  always exists.

  ANGULAR WEDGES cut bearing sectors. Every wedge spans the full distance range,
  so distance support survives and what is held out is a bearing sector -- which
  tests the antenna-pattern term instead.

The gap between the last two is a finding about this survey's radial geometry,
not about any model. Report both. Neither is cherry-picked.

THE 200 m BUFFER. Training rows within 200 m of any test row are dropped, so no
road segment is shared across the split. That radius is not arbitrary: 99.6% of
profile-space nearest neighbours in this dataset lie within 200 m, so this is
the distance at which lookup stops being possible.

MODELS WITH NOTHING TO FIT. A ray tracer has no fitted constants, so `refit`
returns itself and every fold uses the same predictions. The harness records
`fitted: false` and says so in the report. That is a stronger position than a
fitted model can claim, not a weaker one -- there is no leakage to worry about,
and the in-sample and held-out columns should agree. If they do not, something
else is wrong.

USAGE

    from common.backtest import Testbench
    tb = Testbench.from_frame(df, serving_site="Agronomy Farm")
    report = tb.run({"my-model": my_sim, "parametric": their_sim})

See BACKTEST.md for the full walkthrough.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.isotonic import IsotonicRegression

EARTH_R = 6_371_000.0
N_BLOCKS = 5
BUFFER_M = 200.0
RANDOM_SEED = 42
GRID_M = 200.0
SPLITS = ("random_split", "kmeans_on_position", "angular_wedges")

REQUIRED = ("lat", "lon", "rsrp", "outage", "dist_m", "az_deg")


def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = (np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2)
         * np.sin(np.radians(np.asarray(lon2) - np.asarray(lon1)) / 2) ** 2)
    return 2 * EARTH_R * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def score(pred, obs):
    e = np.asarray(pred, float) - np.asarray(obs, float)
    obs = np.asarray(obs, float)
    return {"mae": float(np.abs(e).mean()),
            "rmse": float(np.sqrt((e ** 2).mean())),
            "bias": float(e.mean()),
            "r2": float(1 - (e ** 2).sum() / ((obs - obs.mean()) ** 2).sum())}


# ==========================================================================
# The bench
# ==========================================================================

@dataclass
class Testbench:
    """The measurements, the modelling subset, and the blocks. Built once."""

    df: pd.DataFrame            # every row, including measured absences
    rows: pd.DataFrame          # the modelling subset: served by the site, RSRP present
    blocks: dict

    # ------------------------------------------------------------ build --
    @staticmethod
    def from_frame(df: pd.DataFrame, serving_site: str | None = None,
                   site_col: str = "site", min_dist_m: float = 30.0,
                   seed: int = RANDOM_SEED) -> "Testbench":
        """Prepare the bench from a measurement frame.

        Required columns: lat, lon, rsrp, dist_m, az_deg, and either `outage`
        or a `cellid` from which it is derived. Optional and used if present:
        uplink, downlink, sinr, rsrq.

        `min_dist_m` drops samples in the tower's near field, where a
        log-distance law has no business being evaluated and a handful of rows
        would otherwise dominate the fit.
        """
        df = df.copy()
        if "outage" not in df:
            if "cellid" not in df:
                raise KeyError("frame needs either 'outage' or 'cellid'")
            df["outage"] = df.cellid.isna() | df.cellid.eq("FFFFFFFFF")
        missing = [c for c in REQUIRED if c not in df]
        if missing:
            raise KeyError(f"measurement frame is missing {missing}")

        r = df
        if serving_site is not None and site_col in df:
            r = r[r[site_col].eq(serving_site)]
        r = r[r.rsrp.notna() & (r.dist_m > min_dist_m)].copy().reset_index(drop=True)
        if len(r) < 500:
            raise ValueError(f"only {len(r)} modelling rows -- too few to block")

        rng = np.random.default_rng(seed)
        xy = np.column_stack([r.lat * 111.32,
                              r.lon * 111.32 * np.cos(np.radians(42))])
        blocks = {
            "random_split": rng.integers(0, N_BLOCKS, len(r)),
            "kmeans_on_position": KMeans(N_BLOCKS, n_init=10,
                                         random_state=seed).fit_predict(xy),
            "angular_wedges": np.floor((r.az_deg.to_numpy() % 360)
                                       / (360 / N_BLOCKS)).astype(int)}
        return Testbench(df=df, rows=r, blocks=blocks)

    # ------------------------------------------------------------ folds --
    def buffered_train(self, test_mask, m=BUFFER_M):
        """Training indices at least `m` from every test row."""
        la, lo = self.rows.lat.to_numpy(), self.rows.lon.to_numpy()
        keep = np.ones((~test_mask).sum(), bool)
        tl, to = la[test_mask][:, None], lo[test_mask][:, None]
        trl, tro = la[~test_mask], lo[~test_mask]
        for i in range(0, test_mask.sum(), 400):
            D = haversine_m(tl[i:i + 400], to[i:i + 400], trl[None, :], tro[None, :])
            keep &= D.min(axis=0) > m
        return np.where(~test_mask)[0][keep]

    def folds(self, split):
        """(block id, train idx, test idx) for one blocking scheme."""
        b = self.blocks[split]
        for k in np.unique(b):
            te = b == k
            if te.sum() < 40 or (~te).sum() < 200:
                continue
            tr = (np.where(~te)[0] if split == "random_split"
                  else self.buffered_train(te))
            if len(tr) < 200:
                continue
            yield int(k), tr, np.where(te)[0]

    # ------------------------------------------------------------- eval --
    def rsrp_report(self, sim, splits=SPLITS, verbose=True):
        """In-sample and held-out RSRP accuracy for one simulator."""
        r, y = self.rows, self.rows.rsrp.to_numpy(float)
        lat, lon = r.lat.to_numpy(), r.lon.to_numpy()
        out = {"in_sample": dict(score(sim.macro_rsrp(lat, lon), y), n=len(r))}

        probe = sim.refit(r.iloc[self.folds(splits[0]).__next__()[1]]) \
            if splits else sim
        out["fitted"] = probe is not sim
        for nm in splits:
            folds = []
            for _, tr, te in self.folds(nm):
                s = sim.refit(r.iloc[tr])
                folds.append(score(s.macro_rsrp(lat[te], lon[te]), y[te]))
            if not folds:
                continue
            out[nm] = dict({k: float(np.mean([f[k] for f in folds]))
                            for k in folds[0]}, n_folds=len(folds))
            if verbose:
                v = out[nm]
                print(f"    {nm:<22} MAE {v['mae']:5.2f}  RMSE {v['rmse']:5.2f}  "
                      f"R2 {v['r2']:+.3f}  ({v['n_folds']} folds)", flush=True)
        return out

    def coverage_report(self, sim, avail_target=0.50, min_n=5):
        """Does the model get SERVICE right, not just received power?

        Fitted on the full data, because this is calibration rather than
        extrapolation: the question is whether the availability curve and the
        threshold reproduce the measured service pattern at all. The base rate
        is reported alongside because a classifier that cannot beat "always say
        served" has not earned its accuracy figure.
        """
        from .criteria import _cells
        agg = _cells(self.df, GRID_M)
        pred = np.asarray(sim.macro_rsrp(agg.lat.to_numpy(), agg.lon.to_numpy()),
                          float)
        iso = IsotonicRegression(increasing=True, out_of_bounds="clip",
                                 y_min=0, y_max=1)
        iso.fit(pred, agg.avail.to_numpy(), sample_weight=agg.n.to_numpy())

        grid = np.arange(-140.0, -30.0, 0.05)
        curve = np.clip(iso.predict(grid), 0, 1)
        ok = np.where(curve >= avail_target)[0]
        thr = float(grid[ok[0]]) if len(ok) else float("inf")

        j = agg[agg.n >= min_n]
        p = np.asarray(sim.macro_rsrp(j.lat.to_numpy(), j.lon.to_numpy()), float)
        truth = (j.avail >= avail_target).to_numpy()
        covered = p >= thr
        pa = np.clip(iso.predict(p), 0, 1)
        return {"cells_compared": int(len(j)),
                "rsrp_threshold_dbm": thr,
                "cellwise_agreement_pct": 100 * float((covered == truth).mean()),
                "base_rate_pct": 100 * float(truth.mean()),
                "brier": float(((pa - j.avail.to_numpy()) ** 2).mean()),
                "observed_avail_pct": 100 * float(
                    np.average(j.avail, weights=j.n)),
                "predicted_avail_pct": 100 * float(np.average(pa, weights=j.n))}

    # -------------------------------------------------------------- run --
    def run(self, sims: dict, splits=SPLITS, out_path=None, verbose=True):
        """Every simulator through every split, plus the coverage check."""
        rep = {"n_rows": int(len(self.rows)), "splits": list(splits),
               "buffer_m": BUFFER_M, "n_blocks": N_BLOCKS, "seed": RANDOM_SEED,
               "simulators": {}}
        for name, sim in sims.items():
            if verbose:
                print(f"\n[bench] {name}", flush=True)
            r = self.rsrp_report(sim, splits, verbose)
            r["coverage"] = self.coverage_report(sim)
            r["info"] = {"label": getattr(sim.info, "label", name),
                         "approach": getattr(sim.info, "approach", "?"),
                         "sigma_db": float(sim.sigma_db)}
            rep["simulators"][name] = r

        if out_path:
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_text(json.dumps(rep, indent=2))
        if verbose:
            print(table(rep))
        return rep


def table(rep) -> str:
    """The comparison, as the one block anybody actually reads."""
    cols = ["in_sample"] + [s for s in rep["splits"]]
    head = (f"\n{'simulator':<26}{'fit?':>6}" + "".join(f"{c[:9]:>10}" for c in cols)
            + f"{'agree%':>9}{'base%':>8}")
    lines = [head, "-" * len(head)]
    for name, r in rep["simulators"].items():
        row = f"{name:<26}{'yes' if r.get('fitted') else 'no':>6}"
        for c in cols:
            row += f"{r[c]['rmse']:>10.2f}" if c in r else f"{'--':>10}"
        cv = r["coverage"]
        lines.append(row + f"{cv['cellwise_agreement_pct']:>9.1f}"
                           f"{cv['base_rate_pct']:>8.1f}")
    lines.append("\nRMSE in dB. Discount the random split -- see the module "
                 "docstring. The\ngeographic splits are the ones that decide "
                 "anything.")
    return "\n".join(lines)


__all__ = ["Testbench", "score", "table", "SPLITS", "BUFFER_M", "N_BLOCKS",
           "RANDOM_SEED"]
