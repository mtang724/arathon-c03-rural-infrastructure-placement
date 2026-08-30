"""
Stage 14 -- a neural operator against the hand-derived diffraction physics.

THE QUESTION. `coverage_terrain.py` turns a terrain profile into decibels with
two textbook terms: ITU-R P.526 knife-edge loss at the worst obstruction, and
first-Fresnel clearance, each carrying one fitted coefficient. Both compress the
whole profile to a single scalar before the fit ever sees it. A Fourier neural
operator does not have to -- it consumes the profile as a function. So:

    can a learned operator beat textbook diffraction physics at turning a
    terrain profile into decibels?

THE FRAMING, AND WHY THE OBVIOUS ONE FAILS. The literature framing for radio
maps is (terrain, transmitter position) -> received-power surface. On this
dataset that framing has ONE training example, because there is one serving
transmitter. Nothing in the FNO / TFNO / UNO / SFNO / CoDANO family survives
that; NEURAL_OPERATOR.md makes the case model by model. Treating the per-link
PROFILE as the input function instead gives 3,838 genuine examples of a real
operator, and it competes head to head with the term it would replace.

TWO VARIANTS AND A CONTROL:

  (a) RESIDUAL. Fit the distance-and-azimuth backbone with NO terrain terms,
      then ask the operator to explain what is left. The profile is normalised
      to unit horizontal length, so the operator is answering the terrain
      question and only the terrain question. This is the head-to-head: the
      parametric model answers the same question with b_diff*J(v) + b_fres*F.

  (b) END TO END. Predict RSRP from the bare ground profile plus explicit
      distance and azimuth channels. More freedom, and more ways to go wrong.

  (c) SHUFFLED CONTROL. Variant (a) trained on profiles paired with the wrong
      links. Whatever it still scores comes from the target distribution rather
      than from terrain, so any honest reading of (a) has to net it off.

  (d) LINEAR-ON-PCA. The same residual target, regressed on the leading
      principal components of the profile. Not deep, not an operator, four lines
      of numpy. It is here because "the neural operator beat the physics" and
      "any flexible learner beat the physics" are different claims, and only one
      of them justifies a neural operator.

THE TRAP THIS FILE IS BUILT AROUND. Fresnel clearance is 96.5% correlated with
log-distance in this dataset, and that collinearity already collapsed the
parametric exponent to 0.53 once, before it was orthogonalised. A profile
sampled on an absolute axis carries its own length, so a network handed one
learns distance and looks excellent for the wrong reason. profiles.py
normalises the axis; variant (b) is handed distance explicitly so the profile is
not the only route to it; and corr(prediction, log d) is reported throughout.

EVALUATION IS backtest.py's, IMPORTED RATHER THAN REIMPLEMENTED -- the same
KMeans and angular-wedge blocks, the same 200 m buffer, the same seed. A
comparison run on different splits would not be a comparison.
"""
import json
import time

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from scipy.optimize import lsq_linear

from backtest import N_BLOCKS, buffered_train, schemes, score
from config import DATA, RANDOM_SEED, REPORTS, SERVING_SITE
import operators
from coverage_terrain import (DUAL_BREAK_M, N_FAR_MAX, N_NEAR_MAX, N_NEAR_MIN,
                              fit_with_terrain, macro_rsrp)
from propagation import DEM

EPOCHS = 200
BATCH = 512
LR = 3e-3
WEIGHT_DECAY = 1e-4
N_MODES = 16
HIDDEN = 16
LAYERS = 3
OUT_CH = 16
N_PCA = 12          # 12 components carry 95% of the variance in the profiles
RIDGE = 1.0

torch.set_num_threads(10)

MODELS = ["parametric_terrain", "backbone_no_terrain", "pca_linear_residual",
          "fno_residual", "fno_shuffled_control", "fno_end_to_end"]
SPLITS = ["random_split", "kmeans_on_position", "angular_wedges"]


# ==========================================================================
# The backbone: distance and azimuth, no terrain
# ==========================================================================

def fit_backbone(ld, az_rad, y):
    """fit_with_terrain's model with the two terrain terms deleted.

    Same structure, same bounds, same solver -- one azimuth harmonic and a dual
    slope breaking at 3 km, near exponent bounded to [1.8, 3.5]. Keeping the
    backbone identical is what makes the comparison fair: the parametric terrain
    terms and the operator are both asked to improve on THIS, so any difference
    between them is about terrain and not about the distance law.
    """
    dual = np.maximum(0.0, ld - np.log10(DUAL_BREAK_M))
    X = np.column_stack([np.ones(len(ld)), ld, np.cos(az_rad), np.sin(az_rad), dual])
    lo = np.array([-np.inf, -10 * N_NEAR_MAX, -np.inf, -np.inf, -10 * N_FAR_MAX])
    hi = np.array([np.inf, -10 * N_NEAR_MIN, np.inf, np.inf, 0.0])
    return lsq_linear(X, y, bounds=(lo, hi), max_iter=400).x


def backbone_pred(c, ld, az_rad):
    dual = np.maximum(0.0, ld - np.log10(DUAL_BREAK_M))
    return (c[0] + c[1] * ld + c[2] * np.cos(az_rad) + c[3] * np.sin(az_rad)
            + c[4] * dual)


def fit_pca_linear(Ptr, ytr, k=N_PCA, lam=RIDGE):
    """Ridge on the leading principal components of the profile.

    Twelve components carry 95% of the variance in the 128-point profiles, so
    this is close to a complete linear model of the input function space -- and
    it costs microseconds. If the operator cannot beat this, its depth and its
    spectral convolutions are not what is doing the work.
    """
    mu = Ptr.mean(0)
    _, _, Vt = np.linalg.svd(Ptr - mu, full_matrices=False)
    V = Vt[:k].T
    A = np.column_stack([np.ones(len(Ptr)), (Ptr - mu) @ V])
    G = A.T @ A + lam * np.eye(A.shape[1])
    G[0, 0] -= lam
    c = np.linalg.solve(G, A.T @ ytr)

    def predict(Pte):
        return np.column_stack([np.ones(len(Pte)), (Pte - mu) @ V]) @ c
    return predict


# ==========================================================================
# FNO -> scalar
# ==========================================================================

class ProfileOperator(nn.Module):
    """A 1-D FNO over the path profile, reduced to one number.

    The FNO maps the input function to a latent function on the same [0, 1]
    domain; the reduction to decibels is a mean AND a max over that domain. Both
    are deliberate. The mean is the natural integral functional. The max is
    there because the physics being challenged is itself a max -- P.526 takes
    the single worst edge on the path -- so withholding that reduction would
    have handicapped the network on exactly the term it is competing with.
    """

    def __init__(self, in_ch, arch="fno", n_points=128):
        super().__init__()
        self.op = operators.build(arch, in_ch, OUT_CH, HIDDEN, LAYERS,
                                  N_MODES, n_points)
        self.head = nn.Sequential(nn.Linear(2 * OUT_CH, 64), nn.GELU(),
                                  nn.Linear(64, 1))

    def forward(self, x):
        z = self.op(x)                                   # (B, OUT_CH, N)
        return self.head(torch.cat([z.mean(-1), z.amax(-1)], -1)).squeeze(-1)


def train_operator(Xtr, ytr, epochs=EPOCHS, seed=RANDOM_SEED, arch="fno",
                   verbose=False):
    """Standardise, fit, return a predictor that speaks the original units.

    A fixed epoch budget on a cosine schedule, rather than early stopping on a
    validation split. Consecutive samples here are 2.6 s and a few metres apart,
    so any random inner split is contaminated by the same near-duplication that
    makes the naive random split meaningless -- an early-stopping signal read
    off one would be tuned on the training set wearing a disguise.
    """
    torch.manual_seed(seed)
    xm = Xtr.mean(axis=(0, 2), keepdims=True)
    xs = Xtr.std(axis=(0, 2), keepdims=True) + 1e-8
    ym, ys = float(ytr.mean()), float(ytr.std()) + 1e-8

    xt = torch.from_numpy(((Xtr - xm) / xs).astype(np.float32))
    yt = torch.from_numpy(((ytr - ym) / ys).astype(np.float32))
    net = ProfileOperator(Xtr.shape[1], arch, Xtr.shape[-1])
    opt = torch.optim.AdamW(net.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)
    n = len(xt)
    g = torch.Generator().manual_seed(seed)

    net.train()
    for ep in range(epochs):
        perm = torch.randperm(n, generator=g)
        tot = 0.0
        for a in range(0, n, BATCH):
            idx = perm[a:a + BATCH]
            opt.zero_grad()
            loss = nn.functional.mse_loss(net(xt[idx]), yt[idx])
            loss.backward()
            opt.step()
            tot += float(loss.detach()) * len(idx)
        sched.step()
        if verbose and (ep + 1) % 50 == 0:
            print(f"      epoch {ep + 1:4d}  train RMSE "
                  f"{np.sqrt(tot / n) * ys:6.3f} dB")

    net.eval()

    def predict(X):
        with torch.no_grad():
            xv = torch.from_numpy(((X - xm) / xs).astype(np.float32))
            out = [net(xv[a:a + 512]).numpy() for a in range(0, len(xv), 512)]
        return np.concatenate(out) * ys + ym

    return predict


# ==========================================================================
# Feature tensors
# ==========================================================================

def channels_residual(P):
    """Variant (a): the obstruction profile alone, on a unit-length axis."""
    return P["hb"][:, None, :].astype(np.float32)


def channels_end2end(P, ld, az_rad):
    """Variant (b): bare ground profile, plus distance and bearing as channels.

    Distance is passed EXPLICITLY here so the profile is not the only route to
    it. Without this the network has every incentive to recover path length from
    the shape of the terrain it crosses, which is the failure mode this whole
    file is arranged to detect.
    """
    n, m = P["grel"].shape
    const = np.stack([ld, np.cos(az_rad), np.sin(az_rad)], 1)[:, :, None]
    return np.concatenate([P["grel"][:, None, :], np.repeat(const, m, axis=2)],
                          1).astype(np.float32)


def profile_fingerprint(hb, lat, lon):
    """Does the profile identify the LINK, or the terrain along it?

    For every measurement, find the nearest other measurement in profile space
    and report how far away it is on the ground. If profiles are effectively
    unique to a location, then a flexible learner fitted on them is doing
    nearest-neighbour lookup on position -- and on a random split, where the
    same road metre appears in both halves, that looks exactly like skill.

    This is the single most important number in the file. It is why the random
    split has to be discounted and why backtest.py's 200 m training buffer is
    the right size.
    """
    from features import haversine_m
    h = hb.astype(np.float64)
    sq = (h ** 2).sum(1)
    D2 = sq[:, None] + sq[None, :] - 2.0 * (h @ h.T)
    np.fill_diagonal(D2, np.inf)
    g = haversine_m(lat, lon, lat[np.argmin(D2, axis=1)], lon[np.argmin(D2, axis=1)])
    rnd = np.random.default_rng(RANDOM_SEED).permutation(len(h))
    return {"median_m": float(np.median(g)),
            "p90_m": float(np.percentile(g, 90)),
            "share_within_50m": float((g < 50).mean()),
            "share_within_200m": float((g < 200).mean()),
            "median_m_random_partner": float(
                np.median(haversine_m(lat, lon, lat[rnd], lon[rnd])))}


# ==========================================================================
# The comparison
# ==========================================================================

def load_profiles():
    d = np.load(DATA / "profiles.npz")
    return {k: d[k] for k in d.files}


def _data():
    """The modelled rows, their covariates, and the three input tensors."""
    P = load_profiles()
    df = pd.read_csv(DATA / "labeled_terrain.csv", dtype={"cellid": str})
    r = (df[df.site.eq(SERVING_SITE) & df.rsrp.notna() & (df.dist_m > 30)]
         .copy().reset_index(drop=True))
    assert len(r) == len(P["rsrp"]), "profiles.npz is stale -- rerun profiles.py"
    assert np.allclose(r.rsrp.to_numpy(), P["rsrp"]), "row order drifted"
    ld = r.log_d.to_numpy()
    az = np.radians(r.az_deg.to_numpy())
    Xa = channels_residual(P)
    return dict(P=P, r=r, y=r.rsrp.to_numpy(), ld=ld, az=az, Xa=Xa,
                Xb=channels_end2end(P, ld, az),
                Xc=Xa[np.random.default_rng(RANDOM_SEED).permutation(len(Xa))])


def blocks_for(r, seed=RANDOM_SEED):
    """backtest.py's blocking, plus the naive random split, in one dict."""
    rng = np.random.default_rng(seed)
    return dict(random_split=rng.integers(0, N_BLOCKS, len(r)), **schemes(r))


def folds_of(r, blocks, name):
    """The (train, test) index pairs backtest.py would use for this scheme."""
    for b in np.unique(blocks):
        te = blocks == b
        if te.sum() < 40 or (~te).sum() < 200:
            continue
        tr = np.where(~te)[0] if name == "random_split" else buffered_train(r, te)
        if len(tr) < 200:
            continue
        yield b, tr, np.where(te)[0]


def run(verbose=True, epochs=EPOCHS):
    t0 = time.time()
    dem = DEM()
    D = _data()
    P, r, y, ld, az = D["P"], D["r"], D["y"], D["ld"], D["az"]
    Xa, Xb, Xc = D["Xa"], D["Xb"], D["Xc"]

    def fit_predict(tr, te):
        """Every model, fitted on `tr`, evaluated on `te`."""
        out = {}
        pl = fit_with_terrain(r.iloc[tr])
        out["parametric_terrain"] = macro_rsrp(pl, dem, r.lat.to_numpy()[te],
                                               r.lon.to_numpy()[te])
        c = fit_backbone(ld[tr], az[tr], y[tr])
        base_te = backbone_pred(c, ld[te], az[te])
        res_tr = y[tr] - backbone_pred(c, ld[tr], az[tr])
        out["backbone_no_terrain"] = base_te
        out["pca_linear_residual"] = base_te + fit_pca_linear(
            P["hb"][tr], res_tr)(P["hb"][te])
        out["fno_residual"] = base_te + train_operator(Xa[tr], res_tr, epochs)(Xa[te])
        out["fno_shuffled_control"] = (
            base_te + train_operator(Xc[tr], res_tr, epochs)(Xc[te]))
        out["fno_end_to_end"] = train_operator(Xb[tr], y[tr], epochs)(Xb[te])
        return out

    fp = profile_fingerprint(P["hb"], r.lat.to_numpy(), r.lon.to_numpy())
    res = {"config": {"epochs": epochs, "n_modes": N_MODES, "hidden": HIDDEN,
                      "layers": LAYERS, "nprof": int(Xa.shape[-1]),
                      "n_rows": int(len(r)), "seed": RANDOM_SEED},
           "profile_fingerprint": fp,
           "in_sample": {}, "out_of_sample": {}, "corr_pred_logd": {}}

    if verbose:
        print(f"[fno] {len(r):,} links, {Xa.shape[-1]} profile points, "
              f"{epochs} epochs, {torch.get_num_threads()} threads")
        print(f"[fno] profile-space nearest neighbour is a median "
              f"{fp['median_m']:.1f} m away on the ground "
              f"({100*fp['share_within_50m']:.1f}% within 50 m) -- the profile "
              f"is a location fingerprint")
        print("\nA. in sample")
    allidx = np.arange(len(r))
    pin = fit_predict(allidx, allidx)
    for m in MODELS:
        res["in_sample"][m] = dict(score(pin[m], y), n=len(r))
        res["corr_pred_logd"][m] = float(np.corrcoef(pin[m], ld)[0, 1])
        if verbose:
            v = res["in_sample"][m]
            print(f"   {m:<24} MAE {v['mae']:5.2f}  RMSE {v['rmse']:5.2f}  "
                  f"R2 {v['r2']:+.3f}  corr(pred, log d) "
                  f"{res['corr_pred_logd'][m]:+.3f}")

    blocks_by = blocks_for(r)
    for nm in SPLITS:
        folds = {m: [] for m in MODELS}
        if verbose:
            print(f"\nB. held out -- {nm}")
        for b, tr, te_i in folds_of(r, blocks_by[nm], nm):
            te = blocks_by[nm] == b
            p = fit_predict(tr, te_i)
            for m in MODELS:
                folds[m].append(score(p[m], y[te]))
            if verbose:
                print(f"   fold {b}: n_te {int(te.sum()):4d} n_tr {len(tr):4d}   "
                      + "  ".join(f"{m[:9]} {folds[m][-1]['rmse']:5.2f}"
                                  for m in MODELS))
        res["out_of_sample"][nm] = {
            m: dict({k: float(np.mean([f[k] for f in folds[m]]))
                     for k in folds[m][0]}, n_folds=len(folds[m]))
            for m in MODELS}

    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "fno_compare.json").write_text(json.dumps(res, indent=2))

    if verbose:
        print(f"\nRMSE, dB{'':<16}{'in samp':>9}{'random':>9}{'kmeans':>9}"
              f"{'wedges':>9}")
        for m in MODELS:
            row = [res["in_sample"][m]["rmse"]] + [
                res["out_of_sample"][s][m]["rmse"] for s in SPLITS]
            print(f"{m:<24}" + "".join(f"{v:>9.2f}" for v in row))
        print(f"\n[fno] {time.time() - t0:.0f} s -- wrote reports/fno_compare.json")
    return res


def capacity_check(hidden=64, epochs=600, splits=SPLITS[1:], verbose=True):
    """Is the operator losing because it is too small? Re-run it much larger.

    The hyperparameters here were NOT selected on any of these splits. Tuning on
    the random split would have selected for memorisation -- NEURAL_OPERATOR.md
    section 4 shows why -- and tuning on the geographic splits would have been
    choosing the model on the number it is about to be judged by. So the
    headline run uses a deliberately small network, this one uses a deliberately
    large one, and both are reported. If capacity were the binding constraint,
    the two would disagree.
    """
    global HIDDEN
    t0 = time.time()
    D = _data()
    r, y, ld, az, Xa = D["r"], D["y"], D["ld"], D["az"], D["Xa"]
    was, HIDDEN = HIDDEN, hidden
    blocks_by = blocks_for(r)
    out = {"config": {"hidden": hidden, "epochs": epochs, "n_modes": N_MODES,
                      "layers": LAYERS}}
    try:
        for nm in splits:
            folds = []
            for b, tr, te in folds_of(r, blocks_by[nm], nm):
                c = fit_backbone(ld[tr], az[tr], y[tr])
                res_tr = y[tr] - backbone_pred(c, ld[tr], az[tr])
                pred = (backbone_pred(c, ld[te], az[te])
                        + train_operator(Xa[tr], res_tr, epochs)(Xa[te]))
                folds.append(score(pred, y[te]))
                if verbose:
                    print(f"   {nm} fold {b}: RMSE {folds[-1]['rmse']:.2f}",
                          flush=True)
            out[nm] = dict({k: float(np.mean([f[k] for f in folds]))
                            for k in folds[0]}, n_folds=len(folds))
    finally:
        HIDDEN = was

    path = REPORTS / "fno_compare.json"
    res = json.loads(path.read_text()) if path.exists() else {}
    res["capacity_check"] = out
    path.write_text(json.dumps(res, indent=2))
    if verbose:
        for nm in splits:
            print(f"[cap] {nm}: RMSE {out[nm]['rmse']:.2f} dB "
                  f"(hidden {hidden}, {epochs} epochs)")
        print(f"[cap] {time.time() - t0:.0f} s -- merged into "
              f"reports/fno_compare.json")
    return out


def architectures(archs=None, epochs=EPOCHS, splits=SPLITS, verbose=True):
    """The rest of the list, in the framing that makes any of them well posed.

    Only variant (a) runs here -- the residual task, where the operator is asked
    the terrain question and nothing else. Width, depth, retained modes, epochs,
    optimiser, seed and splits are all held fixed, so what varies across rows is
    the architecture and only the architecture.

    See operators.py for why these four and not the other two.
    """
    t0 = time.time()
    archs = list(archs or operators.ARCHITECTURES)
    D = _data()
    r, y, ld, az, Xa = D["r"], D["y"], D["ld"], D["az"], D["Xa"]
    blocks_by = blocks_for(r)
    out = {"config": {"hidden": HIDDEN, "layers": LAYERS, "n_modes": N_MODES,
                      "epochs": epochs, "seed": RANDOM_SEED},
           "n_free_parameters": {
               a: operators.n_free(operators.build(a, 1, OUT_CH, HIDDEN, LAYERS,
                                                   N_MODES, Xa.shape[-1]))
               for a in archs}}

    allidx = np.arange(len(r))
    c = fit_backbone(ld, az, y)
    res_all = y - backbone_pred(c, ld, az)
    out["in_sample"] = {}
    for a in archs:
        p = backbone_pred(c, ld, az) + train_operator(Xa, res_all, epochs,
                                                      arch=a)(Xa)
        out["in_sample"][a] = score(p, y)
        if verbose:
            print(f"   in sample  {a:<5} RMSE {out['in_sample'][a]['rmse']:5.2f}",
                  flush=True)

    for nm in splits:
        out[nm] = {}
        for a in archs:
            folds = []
            for b, tr, te in folds_of(r, blocks_by[nm], nm):
                cb = fit_backbone(ld[tr], az[tr], y[tr])
                res_tr = y[tr] - backbone_pred(cb, ld[tr], az[tr])
                pred = (backbone_pred(cb, ld[te], az[te])
                        + train_operator(Xa[tr], res_tr, epochs, arch=a)(Xa[te]))
                folds.append(score(pred, y[te]))
            out[nm][a] = dict({k: float(np.mean([f[k] for f in folds]))
                               for k in folds[0]}, n_folds=len(folds))
            if verbose:
                print(f"   {nm:<20} {a:<5} RMSE {out[nm][a]['rmse']:5.2f} "
                      f"({len(folds)} folds)", flush=True)

    path = REPORTS / "fno_compare.json"
    res = json.loads(path.read_text()) if path.exists() else {}
    res["architectures"] = out
    path.write_text(json.dumps(res, indent=2))
    if verbose:
        print(f"\n{'arch':<6}{'params':>9}{'in samp':>9}"
              + "".join(f"{s_[:6]:>9}" for s_ in splits))
        for a in archs:
            print(f"{a:<6}{out['n_free_parameters'][a]:>9,}"
                  f"{out['in_sample'][a]['rmse']:>9.2f}"
                  + "".join(f"{out[s_][a]['rmse']:>9.2f}" for s_ in splits))
        print(f"\n[arch] {time.time() - t0:.0f} s -- merged into "
              f"reports/fno_compare.json")
    return out


if __name__ == "__main__":
    import sys
    if "--capacity" in sys.argv:
        capacity_check()
    elif "--architectures" in sys.argv:
        architectures()
    else:
        run(epochs=int(sys.argv[1]) if len(sys.argv) > 1 else EPOCHS)
