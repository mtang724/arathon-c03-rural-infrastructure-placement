"""
Stage 14b -- the architecture zoo.

`fno_compare.py` established the only framing on this dataset that poses a real
operator-learning problem: terrain profile along the link -> received power. That
framing is the reusable part. Swapping the architecture inside it is a one-line
change, so the other names on the list get the same splits, the same backbone,
the same controls.

WHICH ARCHITECTURES, AND WHY EACH ONE IS HERE

  FNO   the baseline. Global Fourier modes on the path.

  TFNO  FNO with Tucker-factorised spectral weights. The interesting variant,
        because the binding constraint here is not expressiveness -- 3,838 rows
        sit on ~436 distinct 200 m cells -- and factorisation is a parameter
        reduction, which is the direction that should help.

  UNO   U-shaped neural operator: resolution is scaled down and back up between
        integral layers. More machinery and more parameters, which is the wrong
        direction under this sample size, but it is on the list and it is cheap
        to include, so it runs and the number speaks.

  WNO   Wavelet neural operator, implemented here because neuraloperator does
        not ship one and no wavelet package is installed. This is the
        architecture with an actual physical argument behind it. Fourier modes
        are global over the whole path; a knife edge is LOCAL, and ITU-R P.526
        takes the single worst point on the profile. Wavelets are localised in
        position and in scale, which is the right prior for "one sharp
        obstruction somewhere along this path". If any architecture on the list
        deserves to beat the Fourier one at this specific task, it is this one.

RULED OUT WITHOUT RUNNING, for reasons that do not depend on a result:

  SFNO    spherical harmonics on the sphere. The survey box is 11 x 16 km, and
          this neuraloperator build does not ship SFNO in any case.
  CoDANO  codomain attention ACROSS several coupled physical variables. There is
          one output variable here, and far less data than its capacity needs.

THE WAVELET TRANSFORM

Periodised orthonormal db4, built once as an explicit N x N matrix by pushing
the identity through the filter bank. At N = 128 that matrix is smaller than the
FFT it replaces, it is exact, and orthogonality is asserted rather than assumed
-- for an orthonormal basis the inverse transform is the transpose, so there is
no separate reconstruction code to get subtly wrong.
"""
import numpy as np
import torch
import torch.nn as nn
from neuralop.models import FNO, TFNO, UNO

# Daubechies-4 decomposition low-pass filter (8 taps), the pywt `dec_lo`.
DB4_LO = np.array([
    -0.010597401784997278, 0.032883011666982945, 0.030841381835986965,
    -0.187034811718881140, -0.027983769416983850, 0.630880767929590400,
    0.714846570552541500, 0.230377813308855230])


def _qmf(lo):
    """Quadrature mirror: dec_hi[k] = (-1)^k * dec_lo[L-1-k]."""
    lo = np.asarray(lo, float)
    return ((-1.0) ** np.arange(len(lo))) * lo[::-1]


def dwt_matrix(n, level=3, lo=DB4_LO):
    """Orthonormal periodised DWT as one dense matrix, coarse coefficients first.

    Row block layout is [a_L, d_L, d_{L-1}, ..., d_1], so the leading rows are
    the coarse scales and truncating to the first K rows is the direct analogue
    of an FNO keeping its lowest K Fourier modes.
    """
    hi = _qmf(lo)
    A = np.eye(n)
    m = n
    while m >= 2 * len(lo) and level > 0:
        P = np.zeros((m, m))
        for i in range(m // 2):
            for k in range(len(lo)):
                j = (2 * i + k) % m
                P[i, j] += lo[k]
                P[m // 2 + i, j] += hi[k]
        A[:m] = P @ A[:m]
        m //= 2
        level -= 1
    err = np.abs(A @ A.T - np.eye(n)).max()
    assert err < 1e-10, f"db4 basis is not orthonormal (max error {err:.2e})"
    return A


class WaveletConv1d(nn.Module):
    """The WNO analogue of a spectral convolution.

    Transform to the wavelet domain, apply a learned channel mixing to the
    first `n_coef` coefficients, drop the rest, transform back. Identical in
    structure to FNO's mode truncation -- only the basis differs, and the basis
    is the whole point: Fourier atoms span the path, wavelet atoms do not.
    """

    def __init__(self, in_ch, out_ch, n_coef, n, level=3):
        super().__init__()
        W = torch.from_numpy(dwt_matrix(n, level)).float()
        self.register_buffer("W", W[:n_coef])              # (n_coef, n)
        self.weight = nn.Parameter(
            torch.randn(in_ch, out_ch, n_coef) * (1.0 / in_ch))

    def forward(self, x):
        c = torch.einsum("bin,kn->bik", x, self.W)         # analysis
        c = torch.einsum("bik,iok->bok", c, self.weight)   # learned mixing
        return torch.einsum("bok,kn->bon", c, self.W)      # synthesis


class WNO1d(nn.Module):
    """Wavelet neural operator, 1-D, in the shape neuraloperator's FNO uses.

    Lift to `hidden` channels, alternate wavelet-domain mixing with a pointwise
    channel skip and GELU, project out. The pointwise skip is what carries the
    local, resolution-independent part, exactly as in FNO.
    """

    def __init__(self, in_channels, out_channels, hidden_channels, n_layers,
                 n_coef, n_points, level=3):
        super().__init__()
        self.lift = nn.Conv1d(in_channels + 1, hidden_channels, 1)
        self.blocks = nn.ModuleList(
            WaveletConv1d(hidden_channels, hidden_channels, n_coef, n_points, level)
            for _ in range(n_layers))
        self.skips = nn.ModuleList(
            nn.Conv1d(hidden_channels, hidden_channels, 1) for _ in range(n_layers))
        self.proj = nn.Sequential(
            nn.Conv1d(hidden_channels, 2 * hidden_channels, 1), nn.GELU(),
            nn.Conv1d(2 * hidden_channels, out_channels, 1))
        self.register_buffer(
            "grid", torch.linspace(0, 1, n_points).view(1, 1, n_points))

    def forward(self, x):
        # Same grid channel neuraloperator's positional_embedding='grid' adds,
        # so the two architectures see the same information.
        x = torch.cat([x, self.grid.expand(x.shape[0], 1, x.shape[-1])], 1)
        x = self.lift(x)
        for blk, sk in zip(self.blocks, self.skips):
            x = torch.nn.functional.gelu(blk(x) + sk(x))
        return self.proj(x)


def build(arch, in_ch, out_ch, hidden, layers, modes, n_points):
    """One operator, by name, at matched width and depth.

    Width, depth and the retained-coefficient count are held equal across
    architectures so the comparison is about the basis and the block structure
    rather than about who was given more parameters.
    """
    if arch == "fno":
        return FNO(n_modes=(modes,), in_channels=in_ch, out_channels=out_ch,
                   hidden_channels=hidden, n_layers=layers)
    if arch == "tfno":
        return FNO(n_modes=(modes,), in_channels=in_ch, out_channels=out_ch,
                   hidden_channels=hidden, n_layers=layers,
                   factorization="tucker", rank=0.42, implementation="factorized")
    if arch == "uno":
        # A symmetric contraction and expansion: full resolution, half, full.
        # Modes are scaled with resolution so no level is asked for more modes
        # than it has points.
        return UNO(in_channels=in_ch, out_channels=out_ch,
                   hidden_channels=hidden, n_layers=layers,
                   uno_out_channels=[hidden] * layers,
                   uno_n_modes=[[modes], [modes // 2], [modes]][:layers],
                   uno_scalings=[[1.0], [0.5], [2.0]][:layers],
                   lifting_channels=4 * hidden, projection_channels=4 * hidden,
                   # UNO's horizontal skips CONCATENATE, so a block's input can
                   # be twice its output width -- soft-gating, neuraloperator's
                   # default, requires them equal and raises. A linear skip is
                   # the shape-agnostic choice.
                   channel_mlp_skip="linear")
    if arch == "wno":
        return WNO1d(in_ch, out_ch, hidden, layers, 2 * modes, n_points)
    raise ValueError(f"unknown architecture {arch!r}")


ARCHITECTURES = ["fno", "tfno", "uno", "wno"]


def n_free(model):
    """Real degrees of freedom.

    torch counts a complex parameter as one element, and FNO's spectral weights
    are complex while WNO's wavelet weights are real. Counting them the same way
    would understate the Fourier models by exactly a factor of two, so complex
    tensors are doubled here.
    """
    return sum(q.numel() * (2 if q.is_complex() else 1) for q in model.parameters())


if __name__ == "__main__":
    n = 128
    W = dwt_matrix(n)
    x = np.random.default_rng(0).normal(size=n)
    print(f"[wav] db4 level 3 basis {W.shape}, orthonormal to "
          f"{np.abs(W @ W.T - np.eye(n)).max():.2e}")
    print(f"[wav] round trip error {np.abs(W.T @ (W @ x) - x).max():.2e}")
    xb = torch.randn(4, 1, n)
    for a in ARCHITECTURES:
        m = build(a, 1, 16, 16, 3, 16, n)
        print(f"[zoo] {a:<5} {n_free(m):>8,} real parameters   "
              f"out {tuple(m(xb).shape)}")
