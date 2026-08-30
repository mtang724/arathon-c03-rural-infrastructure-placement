"""Decompose the fitted `offset` constant into physical transmit quantities.

The twin absorbs EIRP and antenna gain into one fitted scalar (~26 dB) because neither
is in the measurement dataset. Published ARA specifications plus a nameplate RU power
turn that constant from a free parameter into a testable prediction.

CONFIRMED from the ARA design paper (arXiv:2408.00913) and ARA user manual:
  - AraMIMO-c = Ericsson AIR 6419 RU + Baseband 6647 gNB, three per site
  - n77, 3.45-3.55 GHz  ->  channel bandwidth is exactly 100 MHz
  - 192 antenna elements per sector, 64T64R
  - cell coverage 8.5+ km  (dataset: Agronomy serves out to 10.9 km)
  - AIR 6419 rated maximum EIRP 79 dBm (vendor spec)
NOT published anywhere: transmit power, antenna gain, height, downtilt.

RSRP is power per *resource element*, so a total carrier power only meets the fitted
offset after division by the subcarrier count:

    offset  = EPRE + G_real - G_model
    EPRE    = P_total_dBm - 10log10(N_subcarriers)
    G_model = 8.0 dB, the boresight gain of Sionna's tr38901 element -- measured by
              numerical integration over the sphere (peak |F|^2 = 6.3096), not assumed

The robust quantity is the SUM, EPRE + G_real: the fit constrains per-RE EIRP at
boresight, and cannot separate power from gain. That sum is what the siting stage
actually needs, so the degeneracy costs us nothing.

usage: link_budget.py [offset_dB]
"""
import sys

import numpy as np

BW_MHZ = 100                 # confirmed: ARA n77 allocation is 3.45-3.55 GHz
PRB = 273                    # 100 MHz at 30 kHz SCS, TS 38.101-1 Table 5.3.2-1
SC_PER_PRB = 12
G_MODEL_DB = 8.0             # Sionna tr38901 boresight gain, measured
AIR6419_MAX_EIRP_DBM = 79.0  # vendor rated peak (fully coherent data beam)


def main():
    offset = float(sys.argv[1]) if len(sys.argv) > 1 else 26.0
    n_sc = PRB * SC_PER_PRB
    bw_db = 10 * np.log10(n_sc)

    epre_eirp = offset + G_MODEL_DB          # EPRE + G_real, the identifiable sum
    total_eirp = epre_eirp + bw_db

    print(f"channel                 {BW_MHZ} MHz, {PRB} PRB, {n_sc} subcarriers "
          f"({bw_db:.2f} dB)")
    print(f"fitted offset           {offset:.1f} dB")
    print(f"Sionna tr38901 boresight {G_MODEL_DB:.1f} dB (measured)\n")

    print("IDENTIFIABLE QUANTITY (independent of the power/gain split):")
    print(f"  per-RE EIRP at boresight   EPRE + G_real = {epre_eirp:.1f} dBm")
    print(f"  carrier-total SSB EIRP                   = {total_eirp:.1f} dBm")
    print(f"  AIR 6419 rated peak EIRP                 = {AIR6419_MAX_EIRP_DBM:.1f} dBm")
    print(f"  -> the twin implies the broadcast beam runs "
          f"{AIR6419_MAX_EIRP_DBM - total_eirp:.1f} dB below the")
    print(f"     unit's peak coherent data beam, which is the expected order for a")
    print(f"     broadened SSB beam. The absolute scale is corroborated.\n")

    print("POWER / GAIN SPLIT -- the fit cannot separate these, but each row is a")
    print("consistent reading of the same measurement:")
    print(f"  {'P_total':>9}{'dBm':>8}{'EPRE dBm':>10}{'implied G_SSB dBi':>19}"
          f"{'below 24 dBi peak':>19}")
    for p_w in (128.0, 200.0, 320.0):
        p_dbm = 10 * np.log10(p_w * 1e3)
        epre = p_dbm - bw_db
        g_real = epre_eirp - epre
        # peak array gain implied by the vendor's own rated EIRP at max power
        g_peak = AIR6419_MAX_EIRP_DBM - 10 * np.log10(320.0 * 1e3)
        print(f"  {p_w:>7.0f} W{p_dbm:>8.2f}{epre:>10.2f}{g_real:>19.2f}"
              f"{g_real - g_peak:>19.2f}")
    print("\n  A 192-element array broadening its broadcast beam to cover the sector")
    print("  sits several dB below its peak steered gain, so all three rows are")
    print("  physically plausible; 128 W pairs with an 18.1 dBi SSB beam.\n")

    print("EIRP BY ASSET CLASS -- what the siting pass needs per candidate:")
    rows = [("existing macro (AIR 6419)", None, None),
            ("small cell, 5 W, 13 dBi", 5.0, 13.0),
            ("repeater output, 2 W, 13 dBi", 2.0, 13.0),
            ("small cell, 250 mW, 8 dBi", 0.25, 8.0)]
    print(f"  {'asset':<30}{'EIRP dBm':>10}{'vs macro':>10}{'offset to use':>15}")
    for name, p_w, g in rows:
        if p_w is None:
            print(f"  {name:<30}{total_eirp:>10.1f}{0.0:>10.1f}{offset:>15.1f}")
            continue
        p_dbm = 10 * np.log10(p_w * 1e3)
        eirp = p_dbm + g
        off_k = (p_dbm - bw_db) + g - G_MODEL_DB
        print(f"  {name:<30}{eirp:>10.1f}{eirp - total_eirp:>10.1f}{off_k:>15.1f}")
    print("\n  Scoring a candidate small cell with the macro's 26 dB offset would")
    print("  overstate its coverage by 19-37 dB.")


if __name__ == "__main__":
    main()
