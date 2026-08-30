"""ReVeal-MT physics-informed neural network, behind the shared contract.

A replication and extension of Shahid et al., ReVeal (IEEE DySPAN 2025) and
ReVeal-MT (arXiv 2512.04100) -- from the group that runs ARA -- applied to the
COTS drive test.

The model is a sum of parametric per-transmitter terms plus a **learned
shadowing field**:

    a_i(x, y) = (1/10) * ( EIRP_i + G_i(bearing) - 10*eta*log10(r_i/d0) + Z(x, y) )
    RSRP      = 10 * log10( sum_i 10^a_i )

`Z` is a 3x304 MLP over position. EIRP per sector and the path-loss exponent are
free parameters, fitted jointly with the network.

**Why this can answer the counterfactual.** Neither published ReVeal variant
takes the transmitter as a network input, so as published neither can score a
transmitter that was never measured. ReVeal-MT's Algorithm 1 does treat
transmitter powers and locations as trainable parameters, and that is the hook:
once `Z` is shared across transmitters, a new node is added by writing down its
own `r` and reusing `Z`. That extension is what makes `node_rsrp` meaningful
here, and it is ours, not the paper's.

**The assumption it rests on.** `Z` depends on position only, not on the
transmitter-to-receiver path. Real shadowing is directional -- a ridge blocks
from the west and not from the east -- so a shared `Z` is a first-order
approximation, an excess-loss map of the ground. It is the same approximation
the log-distance-plus-shadowing family always makes, and it is what buys
transferability to an unmeasured transmitter. It will be weakest for a candidate
on the far side of terrain from the macro, which is where relays are
interesting, so treat siting output as a ranking rather than an absolute.

Deviations from the papers, all deliberate and all measured:

* **SiLU, not the published ReLU.** A ReLU network is piecewise linear in its
  input, so its second derivative is exactly zero almost everywhere: the
  predicted Laplacian is identically 0 and the physics loss -- the entire point
  of the method -- has no gradient. Measured: mean|laplacian| 0.000e+00 for
  ReLU against 1.66e-02 for SiLU.
* **lambda = 0.** The physics term is close to unobservable from a drive test.
  Its 5-point stencil needs a grid cell with all four neighbours populated, and
  on a road network that yields at most 17 usable collocation points out of
  4,121 measurements -- with curvature still ~10x larger than physically
  possible. No lambda > 0 improved held-out error. ReVeal sampled a 2-D area
  with the Local Pivotal Method; a route samples a curve, and second derivatives
  across a curve are unobservable.
* **A censored term the papers do not need.** 3,023 of 7,144 rows report no
  serving cell and carry no RSRP, and they are exactly the coverage holes.
  Training only on rows that have RSRP would interpolate over the holes
  optimistically. At a no-service point the truth is "below the attach floor",
  so the loss penalises the prediction only if it rises above that floor.

**A caution this model deserves more than most.** `common/BACKTEST.md` warns
that a model consuming a per-location descriptor can answer by looking up its
own training set. This one's *entire input is position*, which is the extreme
case. Its random-split number is therefore meaningless and the geographic
columns are the only ones worth reading.
"""
from __future__ import annotations

import math

import numpy as np

from common.schema import SimulatorInfo

HIDDEN, N_LAYERS, DROPOUT, LR = 304, 3, 0.2, 0.00369
# The bound applies to the SPATIAL VARIATION of the field only, never to its
# mean. Unbounded, Z spans -120 to -43 dB here: it is absorbing a large DC
# offset (the macro's unobserved EIRP) on top of real shadowing. Clamping the
# sum therefore saturates 100% of points and destroys the fit -- in-sample RMSE
# went 6.9 -> 44 dB at Z_MAX = 25. Splitting a free scalar offset from a bounded
# variation fixes that: the offset absorbs EIRP, the bound constrains shadowing,
# which really is a +/-20 dB quantity.
Z_MAX = 20.0
D0 = 100.0
BEAMWIDTH, MAX_ATT = 65.0, 30.0
EPOCHS = 3000

# Agronomy Farm serves 93% of the rows; its three sectors, with azimuths
# inferred from the bearing distribution of the points each one serves.
SITE_LAT, SITE_LON = 42.021016348205585, -93.77358107943655
SECTOR_AZ = (342.70, 102.70, 222.70)


def _enu(lat, lon):
    """Local metric frame anchored at the serving site."""
    k = 111320.0
    return (np.asarray(lon, float) - SITE_LON) * k * math.cos(math.radians(SITE_LAT)), \
           (np.asarray(lat, float) - SITE_LAT) * k


class ReVealMTSimulator:
    """ReVeal-MT behind `common`'s two-method simulator contract."""

    def __init__(self, attach_dbm: float = -87.5, seed: int = 20260830,
                 epochs: int = EPOCHS, device: str | None = None):
        self.attach_dbm = float(attach_dbm)
        self.seed = int(seed)
        self.epochs = int(epochs)
        self._device = device
        self.sigma_db = 8.8            # replaced by the measured residual after fit
        self._fitted = False
        self.info = SimulatorInfo(
            name="reveal-mt-pinn", label="ReVeal-MT PINN",
            approach="pinn-approach", sigma_db=self.sigma_db, fitted_on_rows=0,
            notes="Learned shadowing field over parametric per-sector path loss; "
                  "lambda=0 (the PDE term is unobservable from a route).")

    # ---------------------------------------------------------------- fit --
    def fit(self, lat, lon, rsrp, out_lat=None, out_lon=None):
        """Fit on served rows, with unserved rows entering as censored data."""
        import torch
        import torch.nn as nn

        dev = torch.device(self._device or
                           ("cuda" if torch.cuda.is_available() else "cpu"))
        torch.manual_seed(self.seed)

        x, y = _enu(lat, lon)
        xy = np.column_stack([x, y])
        self._mu, self._sd = xy.mean(0), xy.std(0) + 1e-9
        Xn = (xy - self._mu) / self._sd

        layers, d = [], 2
        for _ in range(N_LAYERS):
            layers += [nn.Linear(d, HIDDEN), nn.SiLU(), nn.Dropout(DROPOUT)]
            d = HIDDEN
        net = nn.Sequential(*layers, nn.Linear(d, 1)).to(dev)

        # An unbounded MLP over (x, y) has no constraint outside the convex
        # hull of its training data: on a held-out bearing wedge this model
        # predicted +395 dBm, more power than was transmitted, while scoring
        # 7.5 dB on its own training rows in the same fold. Bounding the
        # spatial variation makes extrapolation decay to the parametric
        # log-distance law plus a fixed offset -- wrong, but physical and
        # finite.
        # The offset has to travel ~80 dB from any neutral start, which a
        # single scalar cannot do at the network's learning rate -- it reached
        # only -10.8 dB in 3,000 steps and the fit stayed broken at 35 dB. So
        # it is initialised from the data and given its own much larger step.
        z0 = nn.Parameter(torch.zeros((), device=dev))

        def Zf(Xn_t):
            return z0 + Z_MAX * torch.tanh(net(Xn_t).squeeze(-1) / Z_MAX)
        eirp = nn.Parameter(torch.full((3,), 49.0, device=dev))
        # Constrained to [1.5, 5]: unconstrained the exponent runs away to ~9,
        # because Z is flexible enough to absorb any exponent and the two are
        # degenerate.
        eta_raw = nn.Parameter(torch.zeros((), device=dev))
        opt = torch.optim.Adam(
            [{"params": list(net.parameters()), "lr": LR},
             {"params": [eta_raw], "lr": LR},
             {"params": [eirp, z0], "lr": 1.0}])   # dB-scale params, dB-scale steps

        def T(v):
            return torch.tensor(np.asarray(v), dtype=torch.float32, device=dev)

        tx = T(np.column_stack(_enu(np.full(3, SITE_LAT), np.full(3, SITE_LON))))
        az = T(np.array(SECTOR_AZ))
        Xd, XYd, Yd = T(Xn), T(xy), T(np.asarray(rsrp, float))
        has_cens = out_lat is not None and len(np.atleast_1d(out_lat)) > 0
        if has_cens:
            ox, oy = _enu(out_lat, out_lon)
            oxy = np.column_stack([ox, oy])
            Xc, XYc = T((oxy - self._mu) / self._sd), T(oxy)

        with torch.no_grad():
            # start the offset where the parametric part already matches the data
            r0 = torch.sqrt(((T(xy)[:, None, :] - tx[None, :, :]) ** 2).sum(-1) + 1.0)
            pl0 = (49.0 - 10.0 * 3.0 * torch.log10(r0 / D0)).max(dim=1).values
            z0.copy_((T(np.asarray(rsrp, float)) - pl0).median())

        def total(Xn_t, xy_t, extra=None):
            eta = 1.5 + 3.5 * torch.sigmoid(eta_raw)
            e, t, a_ = eirp, tx, az
            if extra is not None:
                e = torch.cat([e, extra["eirp"]])
                t = torch.cat([t, extra["xy"]])
                a_ = torch.cat([a_, extra["az"]])
            dx = xy_t[:, None, 0] - t[None, :, 0]
            dy = xy_t[:, None, 1] - t[None, :, 1]
            r = torch.sqrt(dx ** 2 + dy ** 2 + 1.0)
            bear = torch.rad2deg(torch.atan2(dx, dy))
            dd = torch.remainder(bear - a_[None, :] + 180.0, 360.0) - 180.0
            g = -torch.minimum(12.0 * (dd / BEAMWIDTH) ** 2,
                               torch.full_like(dd, MAX_ATT))
            if extra is not None:                      # the added node is omni
                g = torch.cat([g[:, :-1], torch.zeros_like(g[:, -1:])], dim=1)
            a = (e[None, :] + g - 10.0 * eta * torch.log10(r / D0)
                 + Zf(Xn_t)[:, None]) / 10.0
            return 10.0 * torch.logsumexp(a * math.log(10.0), 1) / math.log(10.0)

        for _ in range(self.epochs):
            net.train()
            opt.zero_grad()
            loss = (total(Xd, XYd) - Yd).abs().mean()
            if has_cens:
                loss = loss + torch.clamp(total(Xc, XYc) - self.attach_dbm,
                                          min=0.0).mean()
            # z0 and eirp are degenerate against each other, so pin the
            # spatial variation to zero mean and let z0 carry the offset.
            loss = loss + 0.1 * (Zf(Xd) - z0).mean().abs()
            loss.backward()
            opt.step()

        net.eval()
        self._Zf, self._z0 = Zf, z0
        self._net, self._eirp, self._tx, self._az, self._dev = net, eirp, tx, az, dev
        self._eta = float(1.5 + 3.5 * torch.sigmoid(eta_raw))
        self._total = total
        self._torch = torch
        self._fitted = True
        with torch.no_grad():
            resid = total(Xd, XYd).cpu().numpy() - np.asarray(rsrp, float)
        self.sigma_db = float(np.std(resid))
        self.info = SimulatorInfo(
            name=self.info.name, label=self.info.label, approach=self.info.approach,
            sigma_db=self.sigma_db, fitted_on_rows=int(len(np.atleast_1d(rsrp))),
            notes=self.info.notes)
        return self

    # ----------------------------------------------------------- contract --
    def macro_rsrp(self, lat, lon):
        import torch
        x, y = _enu(lat, lon)
        xy = np.column_stack([x, y])
        with torch.no_grad():
            v = self._total(
                torch.tensor((xy - self._mu) / self._sd, dtype=torch.float32,
                             device=self._dev),
                torch.tensor(xy, dtype=torch.float32, device=self._dev))
        return v.cpu().numpy().astype(float)

    def node_rsrp(self, tx_lat, tx_lon, agl_m, eirp_deficit_db, lat, lon):
        """Power from a NEW omni node, reusing the learned shadowing field.

        `eirp_deficit_db` is dB below the existing macro, so the node's EIRP is
        referenced to the fitted per-sector mean rather than to any absolute
        power -- the macro's true EIRP is not observed anywhere in this dataset.
        """
        import torch
        x, y = _enu(lat, lon)
        xy = np.column_stack([x, y])
        tx_x, tx_y = _enu(np.atleast_1d(tx_lat), np.atleast_1d(tx_lon))
        ref = float(self._eirp.detach().mean())
        with torch.no_grad():
            Xn = torch.tensor((xy - self._mu) / self._sd, dtype=torch.float32,
                              device=self._dev)
            XY = torch.tensor(xy, dtype=torch.float32, device=self._dev)
            dx = XY[:, 0] - float(tx_x[0])
            dy = XY[:, 1] - float(tx_y[0])
            r = torch.sqrt(dx ** 2 + dy ** 2 + 1.0)
            v = (ref - float(eirp_deficit_db)
                 - 10.0 * self._eta * torch.log10(r / D0)
                 + self._Zf(Xn))
        return v.cpu().numpy().astype(float)

    def refit(self, train):
        """A copy fitted only on `train`, as the testbench requires."""
        t = train[train.rsrp.notna()]
        out = train[train.rsrp.isna()] if "rsrp" in train else train.iloc[:0]
        new = ReVealMTSimulator(self.attach_dbm, self.seed, self.epochs,
                                self._device)
        return new.fit(t.lat.to_numpy(), t.lon.to_numpy(), t.rsrp.to_numpy(),
                       out.lat.to_numpy(), out.lon.to_numpy())
