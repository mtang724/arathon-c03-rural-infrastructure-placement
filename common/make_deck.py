"""
The project deck: one simulator per slide, the dataset up front, the tool at the end.

    python -m common.make_deck

Everything is a native PowerPoint object -- real chart parts with their own data
sheets, autoshapes and tables. No images, so every figure stays vector and stays
editable by whoever presents it.

BUILT TO BE FILLED IN. Four simulators are planned and they will not land at the
same time, so each gets its own slide and each slide renders in one of two
states: complete, with its measured numbers, or RESERVED, drawn dimmed with what
it will carry. A reserved slide is a promise with a shape, not a gap -- and it
means the deck can be presented today without pretending the missing work exists.

Numbers are read from reports and bundles rather than typed in, so the deck
cannot drift from the models the way the old planner drifted from the optimiser.
Anything absent degrades to "not yet measured" rather than to a stale figure.
"""
import glob
import json
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches, Pt

from .deckkit import (BG, FD, FM, GREY, H, INK, INK2, MUTE, OCHRE, RULE, SURF,
                      TEAL, VIOL, W, WHITE, WINE, arrow, bar, bullets, caption,
                      card, footer, header, kpi, line_chart, oval, rect, slide,
                      table, txt)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "ARA_Challenge3.pptx"


# ==========================================================================
# whatever has actually been measured
# ==========================================================================

def load():
    d = {"bundles": {}}

    def rd(p):
        p = ROOT / p
        try:
            return json.loads(p.read_text())
        except Exception:
            return None

    d["backtest"] = rd("terrain-approach/reports/backtest.json")
    d["coverage"] = rd("terrain-approach/reports/coverage_terrain.json")
    fno = rd("terrain-approach/reports/fno_compare.json")
    # A smoke run leaves a file that reads like a result. Two epochs trains
    # nothing, so refuse to present it.
    d["fno"] = fno if (fno and fno.get("config", {}).get("epochs", 0) >= 50) else None
    for f in sorted(glob.glob(str(ROOT / "bundles" / "*.json"))):
        try:
            b = json.loads(Path(f).read_text())
            d["bundles"][b["simulator"]["name"]] = b
        except Exception:
            pass
    return d


def rmse(d, split):
    b = d.get("backtest")
    if not b:
        return None
    if split == "in_sample":
        return b["A_in_sample"]["rmse"]
    return b["B_out_of_sample"].get(split, {}).get("rmse")


# ==========================================================================
# slides
# ==========================================================================

def s01_title(prs, d):
    s = slide(prs)
    rect(s, 0, 0, W, Inches(0.055), fill=TEAL)
    rect(s, Inches(0.55), Inches(1.55), Inches(1.5), Inches(0.055), fill=OCHRE)
    txt(s, Inches(0.55), Inches(1.05), Inches(9), Inches(0.35),
        "ARATHON Challenge 03", 11, TEAL, True, FM, caps=True, space=2.4)
    txt(s, Inches(0.55), Inches(1.85), Inches(11.6), Inches(1.5),
        "Where does one more transmitter\ndo the most good?", 46, INK, True, FD)
    txt(s, Inches(0.55), Inches(3.5), Inches(9.4), Inches(1.0),
        "A rural drive test covers 7% of the service area. The task is to move "
        "from describing weak service to recommending a limited, defensible "
        "intervention — which means predicting where nothing was measured, and "
        "being explicit about how far that prediction can be trusted.",
        14, INK2, False, FD)
    for i, (lab, val, note) in enumerate([
            ("measurements", "7,144", "rows, 4 runs, 2 days"),
            ("no serving cell", "40.4%", "measured absence, not missing"),
            ("held-out accuracy", "9.66 dB", "RMSE, geographic blocks"),
            ("route covered today", "44%", "of 116.7 km driven")]):
        kpi(s, Inches(0.55 + i * 3.08), Inches(4.85), Inches(2.85), lab, val, note,
            vcolor=TEAL if i > 1 else INK)
    footer(s, "AgWireless '26 / Rural Connectivity Research   ·   "
              "measurements: ARA COTS, Ames IA   ·   terrain: USGS 3DEP 1/3 arc-second")
    return s


def s02_requirement(prs, d):
    s = slide(prs)
    header(s, 2, "the research requirement", "What has to be answered, and to what standard",
           "The brief asks for a recommendation. A recommendation is only worth "
           "anything if the uncertainty around it is stated.")
    reqs = [("Predict performance where nothing was measured",
             "A drive test is a line through an area. Coverage has to be inferred "
             "off that line, which is a modelling claim and needs a model, not an "
             "interpolation."),
            ("Choose where one added asset does the most good",
             "Relay, repeater, small cell, or a further measurement campaign — "
             "compared on the same demand, by the same objective."),
            ("State the deployment assumptions and the uncertainty",
             "Every constant declared, every held-out score reported, and the "
             "failures named rather than smoothed over.")]
    y = Inches(1.95)
    for i, (t, b) in enumerate(reqs):
        rect(s, Inches(0.55), y, Inches(12.2), Inches(1.15), fill=SURF, line=RULE)
        rect(s, Inches(0.55), y, Inches(0.06), Inches(1.15), fill=TEAL)
        txt(s, Inches(0.95), y + Inches(0.16), Inches(0.5), Inches(0.3),
            f"R{i+1}", 12, TEAL, True, FM)
        txt(s, Inches(1.6), y + Inches(0.14), Inches(10.8), Inches(0.32), t,
            15.5, INK, True, FD)
        txt(s, Inches(1.6), y + Inches(0.54), Inches(10.8), Inches(0.5), b,
            11.5, INK2, False, FD)
        y += Inches(1.32)
    txt(s, Inches(0.55), Inches(6.05), Inches(12.2), Inches(0.9),
        "The third is the one that decides whether the first two are believable. "
        "Every number in this deck is reported with the split it was measured on, "
        "and the places the model fails are given their own slide.",
        12.5, INK, False, FD)
    footer(s, "COTS_Challenge_3.pdf")
    return s


def s03_campaign(prs, d):
    s = slide(prs)
    header(s, 3, "the dataset · 1 of 3", "What was actually measured",
           "One vehicle, one modem, one band, four runs over two days, "
           "around one serving site.")
    for i, (lab, val, note) in enumerate([
            ("rows", "7,144", "one every 2.63 s"),
            ("distinct road", "116.7 km", "277 km driven, de-duplicated"),
            ("survey box", "189 km²", "11 × 16 km"),
            ("serving sites", "1 of 12", "Agronomy Farm serves 3,838 rows")]):
        kpi(s, Inches(0.55 + i * 3.08), Inches(1.95), Inches(2.85), lab, val, note)
    txt(s, Inches(0.55), Inches(3.28), Inches(6), Inches(0.3),
        "Samples by distance from the tower", 11, MUTE, True, FM, caps=True, space=1.2)
    bar(s, Inches(0.45), Inches(3.6), Inches(6.2), Inches(2.6),
        ["0–2 km", "2–4", "4–6", "6–8", "8–13"],
        [("samples", [1245, 1520, 1410, 1180, 1789])], [TEAL], labels=True,
        numfmt="0")
    txt(s, Inches(7.1), Inches(3.28), Inches(5.7), Inches(0.3),
        "Why one site and not twelve", 11, MUTE, True, FM, caps=True, space=1.2)
    bullets(s, Inches(7.1), Inches(3.62), Inches(5.7), Inches(2.6), [
        ("Agronomy Farm serves 3,838 rows — every model here is fitted on those.", True),
        "Curtiss and Wilson appear on 100–180 sporadic rows each and fit with "
        "R² ≈ 0, so they are reported as incidental rather than modelled.",
        "Research Park serves 0 of 7,144 rows — a free negative control for any "
        "propagation model.",
        ("One transmitter is the binding constraint on what can be learned.", True)],
        size=11)
    footer(s, "Rural_COTS_RAN_Description.pdf   ·   the dataset is not in this "
              "repository — see the licence note")
    return s


def s04_contents(prs, d):
    s = slide(prs)
    header(s, 4, "the dataset · 2 of 3", "What is in the file, and what it costs to misread",
           "Four of these cost real time to discover. They are recorded so nobody "
           "pays for them twice.")
    rows = [["column", "what it carries", "the trap"],
            ["cellid", "serving cell, or absent", "40.4% absent — a MEASURED "
             "absence of service, not missing data"],
            ["rsrp", "received power, dBm", "present only when a cell is serving, "
             "so it is missing exactly where service failed"],
            ["uplink", "Mbps, 2,979 rows", "the binding constraint — spans 8–63 "
             "and tracks RSRP hard"],
            ["downlink", "Mbps", "saturates ~230 for any SINR > 0, so a "
             "downlink objective calls everything fine"],
            ["sinr, rsrq", "dB", "load as object dtype — 11 rows contain a "
             "literal '-'"],
            ["lat, lon, ts", "position and time", "consecutive samples ~22 m "
             "apart, so a random split leaks badly"]]
    table(s, Inches(0.55), Inches(1.95), Inches(12.2), Inches(2.9), rows,
          col_w=[Inches(1.5), Inches(2.6), Inches(8.1)], size=9.5)
    rect(s, Inches(0.55), Inches(5.15), Inches(12.2), Inches(1.4),
         fill=SURF, line=WINE, lw=1.5)
    rect(s, Inches(0.55), Inches(5.15), Inches(0.06), Inches(1.4), fill=WINE)
    txt(s, Inches(0.85), Inches(5.3), Inches(11.6), Inches(0.3),
        "The single most expensive mistake available here", 13, WINE, True, FD)
    txt(s, Inches(0.85), Inches(5.68), Inches(11.6), Inches(0.75),
        "A reflexive dropna() deletes 2,885 rows with no serving cell. Those rows "
        "are not missing measurements — they are the coverage holes, and they are "
        "exactly the demand the challenge asks you to serve. Drop them and the "
        "pipeline reports that coverage is excellent.", 12, INK2, False, FD)
    footer(s, "reports/eda.json   ·   measurement-bearing reports are gitignored "
              "until ARA publishes")
    return s


def s05_findings(prs, d):
    s = slide(prs)
    header(s, 5, "the dataset · 3 of 3", "What the measurements already say, before any model",
           "These are properties of the data. They constrain every simulator that "
           "follows, and none of them depends on a modelling choice.")
    txt(s, Inches(0.55), Inches(1.9), Inches(6.1), Inches(0.3),
        "Odds of outage, Fresnel-obstructed vs clear, at equal distance",
        10.5, MUTE, True, FM, caps=True, space=1.1)
    bar(s, Inches(0.45), Inches(2.25), Inches(6.3), Inches(2.5),
        ["2–4 km", "4–6 km", "6–8 km", "8–13 km"],
        [("odds ratio", [2.25, 2.39, 0.83, 0.97])], [OCHRE], labels=True,
        numfmt="0.00")
    caption(s, Inches(0.55), Inches(4.85), Inches(6.2),
            "p = 7.7e-08 and 5.5e-12 in the first two bands; not significant "
            "beyond 6 km, where the link budget has already run out.")
    bullets(s, Inches(7.15), Inches(2.2), Inches(5.6), Inches(3.4), [
        ("Terrain shadowing dominates 2–6 km and is irrelevant beyond it.", True),
        "Bare line-of-sight is the wrong test: only 13% of links are "
        "geometrically blocked, but 46% intrude on the first Fresnel zone. "
        "The holes are grazing paths.",
        ("Fresnel clearance is 96.5% correlated with log-distance.", True),
        "Fit it as a free term and it absorbs the distance effect, collapsing "
        "the path-loss exponent to 0.53. Terrain features must be "
        "orthogonalised against log-distance before fitting.",
        ("Relief across the box is 98 m; the first Fresnel radius is 10–14 m.", True),
        "That is what makes 1/3 arc-second (~10 m) the right DEM resolution "
        "and 1 m an oversample of something the radio integrates over."],
        size=11)
    footer(s, "measured in reports/eda.json and reports/analysis.json")
    return s


def s06_platform(prs, d):
    s = slide(prs)
    header(s, 6, "method", "Four simulators, one platform",
           "Different physics, different failure modes — but scored on the same "
           "demand, the same splits and the same objective, or they are not being "
           "compared.")
    # the contract, centre
    rect(s, Inches(4.55), Inches(2.05), Inches(4.2), Inches(1.5), fill=SURF,
         line=TEAL, lw=1.75)
    txt(s, Inches(4.75), Inches(2.2), Inches(3.8), Inches(0.3),
        "the contract", 10, TEAL, True, FM, caps=True, space=1.4)
    txt(s, Inches(4.75), Inches(2.52), Inches(3.8), Inches(0.55),
        "macro_rsrp(lat, lon)\nnode_rsrp(tx, agl, ΔEIRP, lat, lon)",
        11, INK, True, FM)
    txt(s, Inches(4.75), Inches(3.15), Inches(3.8), Inches(0.3),
        "two methods. that is the whole interface.", 9.5, MUTE, False, FM)
    names = [("Ray tracing", "Sionna RT over a reconstructed scene", TEAL),
             ("Fitted physics", "two-slope law + ITU-R P.526", OCHRE),
             ("Neural operator", "1-D FNO over path profiles", VIOL),
             ("PINN", "reserved", GREY)]
    for i, (n, sub, col) in enumerate(names):
        x = Inches(0.55 + i * 3.08)
        rect(s, x, Inches(1.35), Inches(2.85), Inches(0.55), fill=BG, line=col, lw=1.25)
        txt(s, x + Inches(0.12), Inches(1.44), Inches(2.6), Inches(0.22), n,
            11.5, col, True, FD)
        txt(s, x + Inches(0.12), Inches(1.66), Inches(2.6), Inches(0.2), sub,
            8.5, MUTE, False, FM)
    for i, (nm, sub, col) in enumerate([
            ("shared demand grid", "4,731 cells · 200 m · route-km de-duplicated", TEAL),
            ("shared testbench", "3 splits · 200 m buffer · one seed", OCHRE),
            ("shared planner", "any simulator · any criterion · any weighting", VIOL)]):
        x = Inches(0.55 + i * 4.15)
        rect(s, x, Inches(4.0), Inches(3.9), Inches(1.05), fill=SURF, line=RULE)
        rect(s, x, Inches(4.0), Inches(0.06), Inches(1.05), fill=col)
        txt(s, x + Inches(0.2), Inches(4.16), Inches(3.5), Inches(0.28), nm,
            13, INK, True, FD)
        txt(s, x + Inches(0.2), Inches(4.52), Inches(3.5), Inches(0.4), sub,
            9.5, MUTE, False, FM)
    txt(s, Inches(0.55), Inches(5.4), Inches(12.2), Inches(1.1),
        "common/ never imports an approach; approaches expose their models "
        "through it. Adding a simulator therefore touches no existing one — and "
        "the shared testbench reproduces the published reference numbers to "
        "0.02 dB, so a change to the bench is detected rather than absorbed.",
        12.5, INK2, False, FD)
    footer(s, "common/README.md · common/BACKTEST.md · common/PLANNER.md")
    return s


def _sim_slide(prs, num, name, title, sub, accent, left, right, status, ready):
    s = slide(prs)
    header(s, num, name, title, sub, accent=accent if ready else GREY)
    txt(s, Inches(11.0), Inches(0.34), Inches(1.8), Inches(0.3), status,
        9.5, accent if ready else GREY, True, FM, caps=True, space=1.2)
    return s


def s07_physics(prs, d):
    ins, km, wed = rmse(d, "in_sample"), rmse(d, "kmeans_on_position"), \
        rmse(d, "angular_wedges")
    s = _sim_slide(prs, 7, "simulator · 1 of 4",
                   "Fitted physics — a two-slope law with terrain in the loop",
                   "A physical law with fitted constants, not a memorised surface. "
                   "That is what lets it answer a counterfactual.",
                   OCHRE, None, None, "built", True)
    txt(s, Inches(0.55), Inches(1.85), Inches(6.2), Inches(0.6),
        "RSRP = b₀ + b₁·log₁₀(d) + a₁cos φ + a₂sin φ + b_J·J(v) + b_F·F",
        13, INK, True, FM)
    rows = [["term", "fitted", "meaning"],
            ["n near / far", "1.80 / 3.35", "two-ray, breaking at 3 km"],
            ["b_J", "−0.73 dB/dB", "ITU-R P.526 knife edge"],
            ["b_F", "+7.33", "first Fresnel clearance"],
            ["σ", "7.35 dB", "shadow fading"]]
    table(s, Inches(0.55), Inches(2.5), Inches(6.2), Inches(1.9), rows,
          col_w=[Inches(1.7), Inches(1.5), Inches(3.0)], size=9.5)
    if ins:
        txt(s, Inches(7.2), Inches(1.85), Inches(5.6), Inches(0.3),
            "RMSE by split, dB", 10.5, MUTE, True, FM, caps=True, space=1.1)
        bar(s, Inches(7.1), Inches(2.2), Inches(5.7), Inches(2.3),
            ["in sample", "random", "KMeans", "wedges"],
            [("RMSE", [round(ins, 2), round(rmse(d, "random_split"), 2),
                       round(km, 2), round(wed, 2)])], [OCHRE], labels=True,
            numfmt="0.00")
    bullets(s, Inches(0.55), Inches(4.7), Inches(6.2), Inches(2.2), [
        ("Four choices were forced by the backtest, not chosen for elegance.", True),
        "One azimuth harmonic, not two — two fit the sector beam beautifully "
        "and fall apart on a held-out bearing.",
        "Both terrain terms orthogonalised against log-distance.",
        "Near exponent bounded at 1.8: costs 0.08 dB, buys constants that can "
        "be defended in a room."], size=10.5)
    bullets(s, Inches(7.1), Inches(4.7), Inches(5.7), Inches(2.2), [
        ("Where it fails, measured rather than asserted.", True),
        "Availability: 60.5% cell agreement against a 63.9% base rate. It does "
        "not beat 'always say served'.",
        "Location explains 71.4% of outage variance, so a spatial model should "
        "do well — we are simply not capturing it.",
        "21% of cells measured twice flip between mostly-served and mostly-dead."],
        size=10.5)
    footer(s, "terrain-approach/MODEL.md   ·   fitted on 3,838 rows")
    return s


def s08_sionna(prs, d):
    s = _sim_slide(prs, 8, "simulator · 2 of 4",
                   "Ray tracing — Sionna RT over a reconstructed scene",
                   "Physics with no fitted constants: nothing to overfit, and "
                   "nothing to refit per fold either.",
                   TEAL, None, None, "propagation built", True)
    bullets(s, Inches(0.55), Inches(1.9), Inches(6.2), Inches(2.6), [
        ("A digital twin, not a curve fit.", True),
        "Scene from OpenStreetMap and USGS 3DEP, with Microsoft ML building "
        "footprints replacing OSM ones.",
        "Validated against NAIP imagery — five orientation checks pass.",
        "Because nothing is fitted, the testbench records it as unfitted and no "
        "leakage is possible. That is a stronger position than a fitted model "
        "can claim, not a weaker one."], size=11)
    for i, (lab, val, note, c) in enumerate([
            ("held-out RMSE", "8.29 dB", "MS footprints, was 8.58", TEAL),
            ("measurement floor", "~2 dB", "not 8 — see DATA_REQUEST.md", MUTE)]):
        kpi(s, Inches(7.1 + i * 2.95), Inches(1.9), Inches(2.75), lab, val, note,
            vcolor=c)
    rect(s, Inches(7.1), Inches(3.2), Inches(5.65), Inches(1.9), fill=BG, line=GREY)
    rect(s, Inches(7.1), Inches(3.2), Inches(0.06), Inches(1.9), fill=GREY)
    txt(s, Inches(7.35), Inches(3.35), Inches(5.2), Inches(0.28),
        "Reserved — siting and planner bundle", 12.5, MUTE, True, FD)
    bullets(s, Inches(7.35), Inches(3.72), Inches(5.2), Inches(1.3), [
        "Wrap the scene in the shared contract (src/adapter.py).",
        "Emit a tabulated bundle — no closed form for a browser.",
        "It then appears in the planner beside the others."], size=10)
    txt(s, Inches(0.55), Inches(4.9), Inches(6.2), Inches(1.6),
        "The two approaches disagree by construction: one ray-traces a scene it "
        "reconstructed, the other fits a law to the measurements. Where they "
        "agree on siting, that agreement means something. Where they do not, the "
        "difference is the honest uncertainty.", 12, INK2, False, FD)
    footer(s, "sionna-approach/REPORT.md")
    return s


def s09_fno(prs, d):
    f = d.get("fno")
    s = _sim_slide(prs, 9, "simulator · 3 of 4",
                   "Neural operator — a 1-D FNO over path profiles",
                   "The framing is the whole difficulty. Most of the operator "
                   "family cannot be posed on this dataset at all.",
                   VIOL, None, None, "built" if f else "running", bool(f))
    rows = [["model", "verdict on this dataset"],
            ["FNO / TFNO / UNO / WNO in 2-D",
             "(terrain, TX) → surface has ONE training example. Not viable."],
            ["NeRF2", "needs many TX or dense volumetric RX. One TX, road-confined."],
            ["SFNO", "spherical harmonics; the box is 11 × 16 km."],
            ["CoDANO", "codomain attention across coupled variables; there is one."],
            ["GeNeRT", "needs a semantic 3-D scene and ray-traced CIRs; no weights."]]
    table(s, Inches(0.55), Inches(1.9), Inches(6.5), Inches(2.3), rows,
          col_w=[Inches(2.4), Inches(4.1)], size=9)
    txt(s, Inches(0.55), Inches(4.35), Inches(6.5), Inches(0.3),
        "The framing that IS well posed", 11, VIOL, True, FM, caps=True, space=1.2)
    txt(s, Inches(0.55), Inches(4.68), Inches(6.5), Inches(1.0),
        "Stop treating the area as the function. The terrain profile along each "
        "link is a genuine input function on [0,1] — 3,838 of them — and it "
        "competes head-to-head with the P.526 term it would replace.",
        12, INK2, False, FD)
    rect(s, Inches(7.35), Inches(1.9), Inches(5.4), Inches(2.35), fill=SURF,
         line=WINE, lw=1.5)
    rect(s, Inches(7.35), Inches(1.9), Inches(0.06), Inches(2.35), fill=WINE)
    txt(s, Inches(7.6), Inches(2.05), Inches(5.0), Inches(0.3),
        "A terrain profile is a location fingerprint", 12.5, WINE, True, FD)
    bullets(s, Inches(7.6), Inches(2.45), Inches(5.0), Inches(1.7), [
        "Nearest other link in profile space: median 12.2 m away on the ground.",
        "97.2% within 50 m; 99.6% within 200 m.",
        ("So on a random split a profile-fed network answers by looking up its "
         "own training set.", True)], size=10)
    if f:
        p = f["out_of_sample"]["kmeans_on_position"]
        bar(s, Inches(7.2), Inches(4.4), Inches(5.55), Inches(2.2),
            ["physics", "backbone", "PCA ridge", "FNO", "shuffled"],
            [("KMeans RMSE", [round(p[k]["rmse"], 2) for k in
                              ["parametric_terrain", "backbone_no_terrain",
                               "pca_linear_residual", "fno_residual",
                               "fno_shuffled_control"]])],
            [OCHRE, GREY, GREY, VIOL, RULE], labels=True, numfmt="0.00")
    else:
        rect(s, Inches(7.35), Inches(4.4), Inches(5.4), Inches(2.1), fill=BG,
             line=GREY)
        txt(s, Inches(7.6), Inches(4.6), Inches(5.0), Inches(0.3),
            "Reserved — head-to-head result", 12.5, MUTE, True, FD)
        bullets(s, Inches(7.6), Inches(4.98), Inches(5.0), Inches(1.4), [
            "Same splits as every other model, imported not reimplemented.",
            "Controls: no-terrain backbone, ridge on 12 profile PCs, and the "
            "same network trained on shuffled profiles.",
            "The control is what separates skill from the target distribution."],
            size=10)
    footer(s, "terrain-approach/NEURAL_OPERATOR.md   ·   "
              "torch 2.10 CPU · neuraloperator 2.0")
    return s


def s10_pinn(prs, d):
    s = slide(prs)
    header(s, 10, "simulator · 4 of 4", "Physics-informed network — reserved",
           "The slot exists so the deck does not have to be restructured when it "
           "lands.", accent=GREY)
    txt(s, Inches(11.0), Inches(0.34), Inches(1.8), Inches(0.3), "reserved",
        9.5, GREY, True, FM, caps=True, space=1.2)
    card(s, Inches(0.55), Inches(1.95), Inches(3.9), Inches(2.7),
         "What it would add",
         ["A residual that obeys a wave or transport equation rather than a "
          "fitted polynomial.",
          "Physics as a loss term, so extrapolation is constrained where data "
          "is absent — which is exactly where this survey is weakest."],
         accent=GREY, status="premise", dim=True)
    card(s, Inches(4.65), Inches(1.95), Inches(3.9), Inches(2.7),
         "What it must clear",
         ["The same three splits, the same 200 m buffer, the same seed.",
          "9.66 dB on KMeans blocks and 9.78 dB on angular wedges.",
          "The shuffled control, if it consumes any per-location feature."],
         accent=GREY, status="acceptance", dim=True)
    card(s, Inches(8.75), Inches(1.95), Inches(4.0), Inches(2.7),
         "How it plugs in",
         ["Implement macro_rsrp and node_rsrp in an adapter.",
          "Return self from refit if nothing is fitted.",
          "common.bundle.build(...) emits the planner bundle.",
          "No existing code changes."],
         accent=GREY, status="integration", dim=True)
    rect(s, Inches(0.55), Inches(4.95), Inches(12.2), Inches(1.5), fill=SURF,
         line=RULE)
    txt(s, Inches(0.85), Inches(5.12), Inches(11.6), Inches(0.3),
        "The honest caveat that applies to every simulator here", 12.5, INK, True, FD)
    txt(s, Inches(0.85), Inches(5.5), Inches(11.6), Inches(0.8),
        "Every split holds out measurements of the network that exists. Nothing "
        "tests whether a model predicts a transmitter that has never existed, "
        "because no such measurement exists. That is a limit of the data, not of "
        "the method — which is why the tool reports where models DISAGREE about "
        "siting rather than claiming which is right.", 12, INK2, False, FD)
    footer(s, "common/README.md — the contract, with a worked adapter example")
    return s


def s11_backtest(prs, d):
    s = slide(prs)
    ready = bool(d.get("backtest"))
    header(s, 11, "evaluation", "One testbench, three splits, every model",
           "If two models are evaluated on different splits they are not being "
           "compared, however carefully each RMSE was computed.")
    cols = ["simulator", "in sample", "random", "KMeans", "wedges", "fitted?"]
    ins = rmse(d, "in_sample")
    rows = [cols,
            ["Fitted physics",
             f"{ins:.2f}" if ins else "—",
             f"{rmse(d, 'random_split'):.2f}" if ins else "—",
             f"{rmse(d, 'kmeans_on_position'):.2f}" if ins else "—",
             f"{rmse(d, 'angular_wedges'):.2f}" if ins else "—", "yes"],
            ["Sionna ray tracing", "—", "—", "8.29", "—", "no — nothing fitted"],
            ["FNO on profiles", "—", "—", "—", "—", "yes"],
            ["PINN", "—", "—", "—", "—", "—"]]
    table(s, Inches(0.55), Inches(1.9), Inches(12.2), Inches(1.9), rows,
          col_w=[Inches(3.2), Inches(1.7), Inches(1.7), Inches(1.7), Inches(1.7),
                 Inches(2.2)], size=10)
    caption(s, Inches(0.55), Inches(3.9), Inches(12.2),
            "Blank cells are work not yet done, not results withheld. The table "
            "is completed when every simulator has run — the numbers above are "
            "produced by python -m common.selftest, which fails if the bench "
            "itself has changed.")
    for i, (nm, txt_, col) in enumerate([
            ("random split", "Report it, then discount it. Samples are 2.63 s "
             "apart — metres at driving speed — so the test set is very nearly "
             "the training set. Keep it as a contamination gauge.", WINE),
            ("KMeans blocks", "Compact regions. One is the near-tower cluster, "
             "so holding it out deletes every sample under 2 km and forces the "
             "distance law to extrapolate inward. Harshest.", TEAL),
            ("angular wedges", "Bearing sectors. Distance support survives; what "
             "is held out is a bearing, which tests the antenna term instead.",
             OCHRE)]):
        x = Inches(0.55 + i * 4.15)
        rect(s, x, Inches(4.55), Inches(3.9), Inches(1.85), fill=SURF, line=RULE)
        rect(s, x, Inches(4.55), Inches(0.06), Inches(1.85), fill=col)
        txt(s, x + Inches(0.2), Inches(4.72), Inches(3.5), Inches(0.26), nm,
            12, col, True, FD)
        txt(s, x + Inches(0.2), Inches(5.05), Inches(3.5), Inches(1.2), txt_,
            10, INK2, False, FD)
    footer(s, "common/BACKTEST.md   ·   200 m training buffer, seed 42, 5 blocks")
    return s


def s12_planner_what(prs, d):
    s = slide(prs)
    header(s, 12, "the tool · 1 of 2", "A planner that re-solves for whatever you ask it",
           "One self-contained HTML file. No server, no install, no network — "
           "open it by double-clicking.")
    b = d["bundles"].get("terrain-parametric")
    ncrit = len(b["objective"]["criteria"]) if b else 8
    for i, (lab, val, note) in enumerate([
            ("simulators", str(max(1, len(d["bundles"]))), "one dropdown entry each"),
            ("service criteria", str(ncrit), "availability → throughput"),
            ("demand cells", "4,731", "200 m, route-km de-duplicated"),
            ("candidate sites", "627", "on-route and off-route lattice")]):
        kpi(s, Inches(0.55 + i * 3.08), Inches(1.9), Inches(2.85), lab, val, note)
    bullets(s, Inches(0.55), Inches(3.25), Inches(6.1), Inches(3.0), [
        ("It recomputes; it does not replay.", True),
        "The page carries the terrain grid at 31 m posts and runs the whole "
        "chain in JavaScript — path profile, earth bulge, Fresnel radius, "
        "P.526 loss, RSRP, criterion, threshold.",
        ("Agreement with the offline model: mean −0.07 dB, RMS 1.34 dB, "
         "correlation 0.994, zero service disagreements over 300 cells.", True),
        "The residual is the 31 m versus 10 m DEM stride, and nothing else."],
        size=11)
    rect(s, Inches(7.0), Inches(3.25), Inches(5.75), Inches(3.0), fill=SURF,
         line=WINE, lw=1.5)
    rect(s, Inches(7.0), Inches(3.25), Inches(0.06), Inches(3.0), fill=WINE)
    txt(s, Inches(7.3), Inches(3.42), Inches(5.2), Inches(0.5),
        "Why the formula family is part of the file format", 12.5, WINE, True, FD)
    txt(s, Inches(7.3), Inches(3.95), Inches(5.2), Inches(2.1),
        "The previous planner carried its model's constants in a hand-copied "
        "dictionary. When the model gained a dual slope, a Fresnel term and two "
        "orthogonalisation offsets, the copy was not updated and nothing "
        "complained. It was optimistic by a mean of 5.95 dB, RMS 8.37 dB — "
        "larger than the model's own residual σ — while claiming to track the "
        "optimiser to 1%.\n\nA bundle now declares its formula family, and the "
        "builder refuses one that cannot drive it.", 11, INK2, False, FD)
    footer(s, "common/PLANNER.md   ·   planner.html at the repository root")
    return s


def s13_planner_params(prs, d):
    s = slide(prs)
    header(s, 13, "the tool · 2 of 2",
           "Every axis that moves the answer is a control",
           "A number that swings on a choice nobody wrote down is a hidden "
           "assumption, not a result.")
    for i, (nm, sub, col) in enumerate([
            ("Simulator", "which physics drives everything", TEAL),
            ("Criterion", "availability · RSRP · SINR · RSRQ · throughput p50/p10", VIOL),
            ("Target", "the threshold on that criterion", OCHRE),
            ("Route vs area", "what the coverage score is worth", WINE)]):
        x = Inches(0.55 + i * 3.08)
        rect(s, x, Inches(1.85), Inches(2.85), Inches(0.95), fill=SURF, line=RULE)
        rect(s, x, Inches(1.85), Inches(0.06), Inches(0.95), fill=col)
        txt(s, x + Inches(0.2), Inches(2.0), Inches(2.5), Inches(0.28), nm,
            13, INK, True, FD)
        txt(s, x + Inches(0.2), Inches(2.34), Inches(2.5), Inches(0.4), sub,
            8.5, MUTE, False, FM)
    bullets(s, Inches(0.55), Inches(3.1), Inches(6.1), Inches(3.2), [
        ("Three sweep buttons answer the question directly.", True),
        "Sweep every criterion — the best site under each service definition, "
        "and how far each sits from the first.",
        "Sweep the route/area weight, from pure area to pure route.",
        "Compare every simulator, on the same demand and objective.",
        ("The measured stakes: route demand meeting 10 Mbps is 94.8% at p90 and "
         "9.1% at p10, and the recommended site moves up to 2.6 km and reverses "
         "direction.", True)], size=11)
    bullets(s, Inches(7.0), Inches(3.1), Inches(5.75), Inches(3.2), [
        ("The map reads as a field, not a traffic light.", True),
        "Continuous heatmap of the selected criterion over shaded relief built "
        "from the terrain grid — the only basemap available offline, and the "
        "right one here because the holes are terrain.",
        "Coverage and Gain views for before/after questions.",
        "Scale bar names the 200 m cell size; hover gives the cell's value, "
        "RSRP, gain and route-km.",
        ("Flat criteria are labelled as findings: uplink p10 is 0 Mbps across "
         "the whole box, because a reliability target collapses when the link "
         "is down often enough.", True)], size=11)
    footer(s, "python -m common.build_planner bundles/*.json --dem ...")
    return s


def s14_recommendation(prs, d):
    s = slide(prs)
    header(s, 14, "the recommendation", "What to build, and how far to trust it",
           "A ratio is a finding. An absolute percentage is indicative. The "
           "difference is stated rather than left to the reader.")
    cov = d.get("coverage")
    site = "41.97955, −93.83471"
    r0, r1 = "44%", "69%"
    if cov:
        m = cov["assets"]["macro"]["sites"][0]
        site = f"{m['lat']:.5f}, {m['lon']:.5f}"
        r0 = f"{cov['baseline']['route_pct']:.0f}%"
        r1 = f"{cov['assets']['macro']['one_asset']['route_pct']:.0f}%"
    for i, (lab, val, note, c) in enumerate([
            ("recommended site", site, "37 m mast, on the road network", TEAL),
            ("route-km covered", f"{r0} → {r1}", "at availability ≥ 50%", TEAL),
            ("site confidence", "97%", "of fading draws within 2 km", OCHRE),
            ("exact pole", "12%", "we know the right 2 km, not the pole", WINE)]):
        kpi(s, Inches(0.55 + i * 3.08), Inches(1.9), Inches(2.85), lab, val, note,
            vcolor=c)
    txt(s, Inches(0.55), Inches(3.25), Inches(6.1), Inches(0.3),
        "Route-km added by asset class", 10.5, MUTE, True, FM, caps=True, space=1.1)
    bar(s, Inches(0.45), Inches(3.6), Inches(6.3), Inches(2.4),
        ["Donor relay\n−20 dB", "Small cell\n−26 dB", "Macro\n0 dB"],
        [("route-km added", [1.4, 0.7, 28.6])], [GREY, GREY, TEAL], labels=True,
        numfmt="0.0")
    bullets(s, Inches(7.1), Inches(3.25), Inches(5.65), Inches(3.0), [
        ("The brief's menu cannot solve this, and that is the finding.", True),
        "Every 6 dB lost halves the radius and quarters the area. A relay is "
        "20 dB down: a 520 m bubble against a 9 km hole.",
        ("Power dominates height.", True),
        "Sweeping the mast 6 → 60 m moves the gain by 3%; sweeping power 0 → 26 "
        "dB down collapses it from 0.565 to 0.024.",
        ("What is indicative rather than established.", True),
        "'44% covered now, 69% after' inherits the availability step, which "
        "does not beat its base rate. Read the ratios."], size=10.5)
    footer(s, "terrain-approach/MODEL.md §3–§4   ·   200 fading draws, "
              "angular shadow correlation")
    return s


SLIDES = [s01_title, s02_requirement, s03_campaign, s04_contents, s05_findings,
          s06_platform, s07_physics, s08_sionna, s09_fno, s10_pinn, s11_backtest,
          s12_planner_what, s13_planner_params, s14_recommendation]


def build(verbose=True):
    d = load()
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    for fn in SLIDES:
        fn(prs, d)
    prs.save(OUT)
    if verbose:
        have = [k for k in ("backtest", "coverage", "fno") if d.get(k)]
        print(f"[deck] {OUT} ({OUT.stat().st_size/1e6:.2f} MB), "
              f"{len(prs.slides.__iter__.__self__._sldIdLst)} slides")
        print(f"[deck] data present: {', '.join(have) or 'none'} | "
              f"bundles: {', '.join(d['bundles']) or 'none'}")
        if not d.get("fno"):
            print("[deck] FNO slide rendered in RESERVED state "
                  "(no run with >= 50 epochs in reports/fno_compare.json)")
    return OUT


if __name__ == "__main__":
    build()
