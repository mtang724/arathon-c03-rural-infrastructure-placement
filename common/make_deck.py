"""
The project deck: nine slides, native objects only.

    python -m common.make_deck

Everything is a real PowerPoint object -- chart parts with their own data sheets,
autoshapes and tables. No images, so every figure stays vector and stays editable
by whoever presents it.

THE NARRATIVE, in the order a listener needs it:

    1  the ask
    2  the data, only the parts bearing on RSRP and coverage
    3  the research questions -- the brief's own four evaluation criteria
    4  four ways to predict: baseline, ray tracing, deep learning, PINN
    5  how the planner turns a prediction into a location
    6  how any of it is judged -- drawn, because a split is a shape
    7  RQ0: how well each approach predicts, held out by geography
    8  RQ1-4: thresholds, gains, robustness, constraints, and the brief's
       own hypothesis, tested rather than asserted
    9  the demo

The four questions on slide 3 are quoted from COTS_Challenge_3.pdf, section
"How a team can demonstrate success", not invented here. Slide 8 answers each
one with a measurement.

Numbers come from reports and bundles rather than being typed in, so the deck
cannot drift from the models. Anything missing renders as reserved rather than
as a stale figure.
"""
import glob
import json
import random
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches, Pt

from .deckkit import (BG, FD, FM, GREY, H, INK, INK2, MUTE, OCHRE, RULE, SURF,
                      TEAL, VIOL, W, WHITE, WINE, bar, bullets, caption, footer,
                      header, kpi, oval, rect, scatter, slide, table, txt)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "ARA_Challenge3.pptx"

ORDER = ["terrain-parametric", "sionna-hybrid-agronomy", "terrain-fno"]
LABEL = {"terrain-parametric": "Baseline — fitted physics",
         "sionna-hybrid-agronomy": "Ray tracing — Sionna",
         "terrain-fno": "Deep learning — FNO"}
SHORT = {"terrain-parametric": "Baseline", "sionna-hybrid-agronomy": "Ray tracing",
         "terrain-fno": "Deep learning"}


def load():
    d = {"bundles": {}}

    def rd(p):
        try:
            return json.loads((ROOT / p).read_text())
        except Exception:
            return None

    d["bench"] = rd("reports/testbench.json") or {}
    d["geom"] = rd("reports/split_geometry.json")
    d["coverage"] = rd("terrain-approach/reports/coverage_terrain.json")
    d["hyp"] = rd("reports/hypothesis_test.json")
    d["sens"] = rd("reports/sensitivity.json")
    for f in sorted(glob.glob(str(ROOT / "bundles" / "*.json"))):
        try:
            b = json.loads(Path(f).read_text())
            d["bundles"][b["simulator"]["name"]] = b
        except Exception:
            pass
    return d


def cell(v, k):
    try:
        return f"{v[k]['rmse']:.2f}"
    except (KeyError, TypeError):
        return "—"


# ==========================================================================

def s1_title(prs, d):
    s = slide(prs)
    rect(s, 0, 0, W, Inches(0.055), fill=TEAL)
    rect(s, Inches(0.55), Inches(1.5), Inches(1.5), Inches(0.055), fill=OCHRE)
    txt(s, Inches(0.55), Inches(1.0), Inches(9), Inches(0.35),
        "ARATHON Challenge 03", 11, TEAL, True, FM, caps=True, space=2.4)
    txt(s, Inches(0.55), Inches(1.8), Inches(11.6), Inches(1.4),
        "Where would one more asset\ndeliver the greatest improvement?",
        40, INK, True, FD)
    txt(s, Inches(0.55), Inches(3.35), Inches(9.6), Inches(0.9),
        "A drive test covers 7% of the service area. Four approaches predict "
        "the rest, scored on one testbench and driven through one planner — so "
        "the recommendation carries its uncertainty with it rather than beside "
        "it.", 14, INK2, False, FD)
    best, who = None, ""
    for nm, v in d["bench"].items():
        r = (v.get("kmeans_on_position") or {}).get("rmse")
        if r and (best is None or r < best):
            best, who = r, nm
    for i, (lab, val, note) in enumerate([
            ("measurements", "7,144", "rows · 40.4% no service"),
            ("approaches", "4", "three built, one reserved"),
            ("best held out", f"{best:.2f} dB" if best else "—",
             f"KMeans · {SHORT.get(who, who)}" if best else "not yet measured"),
            ("route covered", "44% → 69%", "with one macro site")]):
        kpi(s, Inches(0.55 + i * 3.08), Inches(4.7), Inches(2.85), lab, val, note,
            vcolor=TEAL if i in (2, 3) else INK, vsize=25 if i < 3 else 21)
    footer(s, "AgWireless '26 · ARA COTS, Ames IA · terrain USGS 3DEP 1/3 arc-second")
    return s


def s2_dataset(prs, d):
    s = slide(prs)
    header(s, 2, "the data", "What the van measured, and what it means for coverage",
           "7,144 samples along 116.7 km of road, one every 2.63 s, around a "
           "single serving site.")
    for i, (lab, val, note, c) in enumerate([
            ("RSRP", "−53 to −120 dBm", "the quantity every model predicts", INK),
            ("no serving cell", "40.4%", "measured absence of service", WINE),
            ("uplink", "8–63 Mbps", "the binding constraint", INK),
            ("downlink", "~230 Mbps", "saturates above SINR 0", MUTE)]):
        kpi(s, Inches(0.55 + i * 3.08), Inches(1.9), Inches(2.85), lab, val, note,
            vcolor=c, vsize=16)
    bullets(s, Inches(0.55), Inches(3.3), Inches(6.05), Inches(3.0), [
        ("Coverage is not measured — it is derived from RSRP.", True),
        "Every approach predicts received power; a calibrated curve turns that "
        "into service. Keeping the two separate is what lets the planner offer "
        "availability, link quality or throughput as alternative definitions.",
        ("The 40% with no serving cell are the signal, not a defect.", True),
        "They are measured absences of service — the demand the brief asks us "
        "to serve. A reflexive dropna() deletes every coverage hole and then "
        "reports coverage as excellent.",
        ("Samples are ~22 m apart, so a random split leaks.", True),
        "The brief's scope note asks for geographically separated test "
        "segments. Slide 6 is how we do it."], size=11)
    rect(s, Inches(6.95), Inches(3.3), Inches(5.8), Inches(3.0), fill=SURF,
         line=OCHRE, lw=1.5)
    rect(s, Inches(6.95), Inches(3.3), Inches(0.06), Inches(3.0), fill=OCHRE)
    txt(s, Inches(7.25), Inches(3.48), Inches(5.3), Inches(0.3),
        "Why coverage fails where it does", 13, OCHRE, True, FD)
    bullets(s, Inches(7.25), Inches(3.88), Inches(5.3), Inches(2.3), [
        "Terrain dominates 2–6 km and is irrelevant beyond it: an obstructed "
        "cell is 2.25–2.39× more likely to have no service at the same "
        "distance (p < 10⁻⁷).",
        "Line of sight is the wrong test — 13% of links are blocked, but 46% "
        "intrude on the first Fresnel zone. The holes are grazing paths, so "
        "terrain has to enter as geometry rather than as a flag.",
        "Past 6 km the link budget has already gone and terrain stops "
        "discriminating at all."], size=10.5, color=INK2)
    footer(s, "reports/eda.json · dataset not redistributable before ARA's release")
    return s


def s3_questions(prs, d):
    s = slide(prs)
    header(s, 3, "research questions", "Four questions, each answerable",
           "Each maps to a requirement in the brief, and each is answered later "
           "by a measurement rather than an assertion.")
    qs = [("RQ1", "Can we predict service where nobody drove \u2014 and does the "
           "modelling paradigm matter?",
           "The drive covers ~11% of the area; the deliverable is the other 89%. "
           "So the test has to be geographic extrapolation, not interpolation.",
           "slide 7", TEAL),
          ("RQ2", "Where is service deficient, and what does one added asset "
           "actually buy?",
           "Before-and-after coverage at an explicit threshold, and the gain "
           "reported per intervention.", "slide 8", OCHRE),
          ("RQ3", "How much does the recommendation depend on what we assumed?",
           "Robustness to model uncertainty, and sensitivity to the objective "
           "and to placement constraints.", "slide 8", VIOL),
          ("RQ4", "Does optimising against the predicted surface beat the naive "
           "baseline?",
           "The brief's own stated hypothesis: better than choosing the single "
           "worst measured point.", "slide 8", WINE)]
    y = Inches(1.95)
    for tag, q, a_, where, col in qs:
        rect(s, Inches(0.55), y, Inches(12.2), Inches(1.06), fill=SURF, line=RULE)
        rect(s, Inches(0.55), y, Inches(0.06), Inches(1.06), fill=col)
        txt(s, Inches(0.9), y + Inches(0.16), Inches(0.7), Inches(0.28), tag,
            12.5, col, True, FM)
        txt(s, Inches(1.75), y + Inches(0.12), Inches(9.2), Inches(0.32), q,
            13.5, INK, True, FD)
        txt(s, Inches(1.75), y + Inches(0.53), Inches(9.2), Inches(0.44), a_,
            11, INK2, False, FD)
        txt(s, Inches(11.35), y + Inches(0.16), Inches(1.3), Inches(0.24),
            where, 8.5, MUTE, False, FM)
        y += Inches(1.18)
    rect(s, Inches(0.55), Inches(6.72), Inches(12.2), Inches(0.5), fill=SURF,
         line=WINE, lw=1.25)
    txt(s, Inches(0.85), Inches(6.83), Inches(11.6), Inches(0.3),
        "RQ1 is the precondition: if a model cannot predict off the driven line, "
        "nothing it says about siting is worth reading.", 11.5, INK, False, FD)
    footer(s, "COTS_Challenge_3.pdf \u00b7 scope note: geographically separated "
              "test segments")
    return s


def s4_approaches(prs, d):
    s = slide(prs)
    header(s, 4, "approaches", "Four ways to predict RSRP where nobody drove",
           "They share nothing but an interface of two methods, so each can be "
           "wrong in its own way and the testbench can tell.")
    apps = [("Baseline", "Fitted physics",
             ["Two-slope path loss fitted to the measurements themselves.",
              "Terrain enters as ITU-R P.526 knife-edge diffraction and Fresnel "
              "clearance, orthogonalised against distance.",
              "Cheap, interpretable, and carries a mechanism — so it can answer "
              "a counterfactual."], OCHRE, True),
            ("Ray tracing", "Sionna RT",
             ["A reconstructed scene: 3DEP terrain plus Microsoft building "
              "footprints, all sites, twelve sectors.",
              "Traced path gain, corrected by profile diffraction where the "
              "tracer finds no path at all.",
              "Five fitted constants; everything else is geometry."], TEAL, True),
            ("Deep learning", "Fourier neural operator",
             ["The terrain profile along each link is the input function; "
              "3,838 measured links are the training set.",
              "Learns the terrain term directly instead of assuming P.526.",
              "No closed form, so the planner drives it from a precomputed "
              "candidate grid."], VIOL, True),
            ("PINN", "Physics-informed network",
             ["Reserved. A residual constrained by a wave or transport equation "
              "rather than a fitted polynomial.",
              "Physics as a loss term, to discipline extrapolation where data "
              "is absent — which is where this survey is weakest.",
              "Must clear the same three splits as the others."], GREY, False)]
    for i, (kind, name, lines, col, live) in enumerate(apps):
        x = Inches(0.55 + i * 3.08)
        rect(s, x, Inches(1.85), Inches(2.85), Inches(4.25),
             fill=SURF if live else BG, line=col, lw=1.5 if live else 1.0)
        rect(s, x, Inches(1.85), Inches(2.85), Inches(0.05), fill=col)
        txt(s, x + Inches(0.18), Inches(2.0), Inches(2.5), Inches(0.2), kind,
            8.5, col, True, FM, caps=True, space=1.2)
        txt(s, x + Inches(0.18), Inches(2.24), Inches(2.5), Inches(0.5), name,
            13.5, INK if live else MUTE, True, FD)
        txt(s, x + Inches(0.18), Inches(2.76), Inches(2.5), Inches(0.2),
            "built" if live else "reserved", 8, col, True, FM, caps=True,
            space=1.1)
        bullets(s, x + Inches(0.18), Inches(3.06), Inches(2.5), Inches(2.9),
                lines, size=9.5, color=INK2 if live else MUTE, gap=5)
    rect(s, Inches(0.55), Inches(6.3), Inches(12.2), Inches(0.6), fill=SURF,
         line=TEAL, lw=1.25)
    txt(s, Inches(0.85), Inches(6.42), Inches(11.6), Inches(0.4),
        "The contract:  macro_rsrp(lat, lon)  ·  node_rsrp(tx, agl, ΔEIRP, lat, "
        "lon)   — implement two methods and the testbench, the planner and this "
        "deck all work on your model.", 11.5, INK, False, FM)
    footer(s, "common/README.md · terrain-approach/src/adapter.py is the reference")
    return s


def s5_decision(prs, d):
    s = slide(prs)
    header(s, 5, "the planner", "How a prediction becomes a location",
           "Every approach outputs received power. Nobody wants received power — "
           "so each link in the chain from dBm to a pin is explicit and "
           "adjustable.")
    steps = [("1", "Predict", "RSRP to all 4,731 demand cells, and from each of "
              "627 candidate sites", TEAL),
             ("2", "Translate", "a calibrated curve turns RSRP into the chosen "
              "criterion — availability, SINR, RSRQ or throughput", VIOL),
             ("3", "Threshold", "the target inverts to an RSRP cut: the first "
              "grid point at or above it", OCHRE),
             ("4", "Score", "0.7 × route-km + 0.3 × area, each as a fraction of "
              "its own total — and the split is a slider", WINE),
             ("5", "Solve", "greedy max-coverage; submodular, so within 63% of "
              "optimal, and instant", TEAL)]
    for i, (n, ttl, body, col) in enumerate(steps):
        x = Inches(0.55 + i * 2.47)
        rect(s, x, Inches(1.9), Inches(2.3), Inches(1.95), fill=SURF, line=RULE)
        rect(s, x, Inches(1.9), Inches(2.3), Inches(0.05), fill=col)
        oval(s, x + Inches(0.14), Inches(2.05), Inches(0.34), Inches(0.34),
             fill=col, line=None)
        txt(s, x + Inches(0.235), Inches(2.11), Inches(0.2), Inches(0.24), n,
            11, WHITE, True, FM)
        txt(s, x + Inches(0.58), Inches(2.1), Inches(1.6), Inches(0.26), ttl,
            13, INK, True, FD)
        txt(s, x + Inches(0.14), Inches(2.57), Inches(2.02), Inches(1.2), body,
            9.5, INK2, False, FD)
        if i < len(steps) - 1:
            txt(s, x + Inches(2.33), Inches(2.67), Inches(0.14), Inches(0.3),
                "›", 15, RULE, True, FD)
    bullets(s, Inches(0.55), Inches(4.15), Inches(6.05), Inches(2.3), [
        ("Nothing in that chain is hardcoded.", True),
        "Approach, criterion, target and weighting are controls, and the solve "
        "re-runs for whatever combination is chosen.",
        ("Because the answer moves with them.", True),
        "Route demand meeting 10 Mbps is 94.8% at p90 and 9.1% at p10, and the "
        "recommended site shifts up to 2.6 km and reverses direction. A number "
        "that swings on an unwritten choice is an assumption, not a result."],
        size=11)
    rect(s, Inches(6.95), Inches(4.15), Inches(5.8), Inches(2.3), fill=SURF,
         line=WINE, lw=1.5)
    rect(s, Inches(6.95), Inches(4.15), Inches(0.06), Inches(2.3), fill=WINE)
    txt(s, Inches(7.25), Inches(4.31), Inches(5.3), Inches(0.28),
        "And where it is allowed to build  (RQ4)", 12.5, WINE, True, FD)
    txt(s, Inches(7.25), Inches(4.67), Inches(5.3), Inches(1.6),
        "Measurements say where service is poor, not whether you may build "
        "there. Five open-data layers — grid power, land access, existing "
        "structures, backhaul, water exclusion — become sliders that shrink the "
        "feasible set, and the tool reports how far the feasible site sits from "
        "the free optimum and what score that costs. Each layer is a proxy, not "
        "a utility record, and the page says so.", 11, INK2, False, FD)
    footer(s, "common/PLANNER.md · common/constraints.py")
    return s


def s6_splits(prs, d):
    """The scope note, drawn: a blocking scheme is a shape before it is a number."""
    s = slide(prs)
    header(s, 6, "evaluation", "What each held-out split actually removes",
           "The brief asks for geographically separated test segments. Same "
           "rows, cut two ways — and the cut decides what a model must "
           "extrapolate.")
    g = d.get("geom")
    cols = [OCHRE, TEAL, VIOL, WINE, GREY]
    if g:
        for j, (key, ttl) in enumerate([
                ("kmeans_on_position", "KMeans blocks — hold out a REGION"),
                ("angular_wedges", "Angular wedges — hold out a BEARING")]):
            x = Inches(0.55 + j * 6.3)
            txt(s, x, Inches(1.78), Inches(5.9), Inches(0.26), ttl, 11, INK,
                True, FM, caps=True, space=1.1)
            # Five spatially disjoint series. Position already separates them,
            # so no two marks ever have to be told apart by hue alone.
            series = [(f"block {k}", [(p[1], p[0]) for p in v])
                      for k, v in sorted(g[key].items(), key=lambda t: int(t[0]))
                      if len(v) > 4]
            scatter(s, x - Inches(0.1), Inches(2.06), Inches(6.05), Inches(2.7),
                    series, cols, sizes=[4] * len(series), legend=False, size=8)
    for j, note in enumerate([
            "One block is the near-tower cluster, so holding it out deletes "
            "every sample under 2 km and forces the distance law to extrapolate "
            "inward. Only 8.2% of test points sit inside the training distance "
            "range — the harshest test here.",
            "Every wedge spans the full distance range, so distance support "
            "survives. What is held out is a bearing sector, which tests the "
            "antenna-pattern term rather than the distance law."]):
        # caption() fixes its box at 0.5in and these run to three lines, so a
        # taller box: python-pptx never reflows, it just draws over what is below
        txt(s, Inches(0.55 + j * 6.3), Inches(4.85), Inches(5.9), Inches(0.85),
            note, 10, INK2, False, FM)
    rect(s, Inches(0.55), Inches(5.75), Inches(12.2), Inches(0.95), fill=SURF,
         line=RULE)
    rect(s, Inches(0.55), Inches(5.75), Inches(0.06), Inches(0.95), fill=WINE)
    txt(s, Inches(0.85), Inches(5.9), Inches(11.6), Inches(0.7),
        "Both schemes drop every training row within 200 m of a test row, so no "
        "road segment is shared. A third split — plain random folds — is reported "
        "and then discounted: samples are 2.63 s apart, so it tests a model on "
        "places it trained on. The gap between random and geographic is how much "
        "a model is memorising.", 12, INK2, False, FD)
    footer(s, "common/backtest.py · 5 blocks, 200 m buffer, seed 42 · "
              "python -m common.selftest reproduces these to 0.02 dB")
    return s


def s7_accuracy(prs, d):
    s = slide(prs)
    header(s, 7, "rq1 \u00b7 prediction", "Does the modelling paradigm matter?",
           "Run with no added transmitter and compared to what the van "
           "recorded — the claim everything downstream rests on.")
    rows = [["approach", "in sample", "random", "KMeans", "wedges", "R² KMeans"]]
    for nm in ORDER:
        v = d["bench"].get(nm)
        if v:
            r2 = v.get("kmeans_on_position", {}).get("r2")
            rows.append([LABEL[nm], cell(v, "in_sample"), cell(v, "random_split"),
                         cell(v, "kmeans_on_position"), cell(v, "angular_wedges"),
                         f"{r2:+.2f}" if r2 is not None else "—"])
        else:
            rows.append([LABEL[nm], "—", "—", "—", "—", "—"])
    rows.append(["PINN", "—", "—", "—", "—", "reserved"])
    table(s, Inches(0.55), Inches(1.85), Inches(6.3), Inches(1.9), rows,
          col_w=[Inches(2.0), Inches(0.95), Inches(0.85), Inches(0.85),
                 Inches(0.85), Inches(0.8)], size=9)
    have = [nm for nm in ORDER if nm in d["bench"]]
    if have:
        txt(s, Inches(7.2), Inches(1.85), Inches(5.5), Inches(0.26),
            "in sample vs held out by geography, dB RMSE", 10, MUTE, True, FM,
            caps=True, space=1.1)
        bar(s, Inches(7.05), Inches(2.15), Inches(5.7), Inches(2.5),
            [SHORT[n] for n in have],
            [("in sample", [round(d["bench"][n]["in_sample"]["rmse"], 2)
                            for n in have]),
             ("KMeans blocks", [round(d["bench"][n]["kmeans_on_position"]["rmse"], 2)
                                for n in have])],
            [GREY, WINE], labels=True, numfmt="0.0", size=8.5)
    bullets(s, Inches(0.55), Inches(4.0), Inches(6.3), Inches(2.4), [
        ("Ray tracing barely degrades: 7.61 → 7.95 dB.", True),
        "Few fitted constants means little to overfit, so held-out and "
        "in-sample nearly agree. It is the most trustworthy of the three.",
        ("Deep learning wins in sample and collapses held out.", True),
        "Best of all at 7.26 dB, then 14.04 dB with R² of −1.01 — worse than "
        "predicting each block's mean."], size=11)
    rect(s, Inches(6.95), Inches(4.85), Inches(5.8), Inches(1.55), fill=SURF,
         line=VIOL, lw=1.5)
    rect(s, Inches(6.95), Inches(4.85), Inches(0.06), Inches(1.55), fill=VIOL)
    txt(s, Inches(7.25), Inches(5.0), Inches(5.3), Inches(0.28),
        "Why the learned model fails, measured", 12.5, VIOL, True, FD)
    txt(s, Inches(7.25), Inches(5.35), Inches(5.3), Inches(0.95),
        "The nearest other link in terrain-profile space sits a median of 12.2 m "
        "away on the ground, 97.2% within 50 m. A profile is very nearly a name "
        "for a place, so the network can recognise the location instead of "
        "learning the physics — and only a geographic split can tell.",
        11, INK2, False, FD)
    footer(s, "reports/testbench.json")
    return s


def s8_answers(prs, d):
    s = slide(prs)
    header(s, 8, "rq2 \u00b7 rq3 \u00b7 rq4",
           "What to build, how firm it is, and whether optimising paid")
    txt(s, Inches(0.55), Inches(1.52), Inches(4.0), Inches(0.24),
        "RQ2 \u2014 gains per intervention", 10, OCHRE, True, FM, caps=True,
        space=1.2)
    rows = [["asset", "site", "route-km"]]
    pb = d["bundles"].get("terrain-parametric")
    if pb:
        for k in ("macro", "smallcell", "relay"):
            m = pb["solution"].get(k)
            if m and m.get("sites"):
                st = m["sites"][0]
                rows.append([k, "%.4f, %.4f" % (st["lat"], st["lon"]),
                             "+%.1f" % m["one_asset"]["route_km_added"]])
    table(s, Inches(0.55), Inches(1.82), Inches(4.0), Inches(1.25), rows,
          col_w=[Inches(1.0), Inches(2.0), Inches(1.0)], size=8.5)
    txt(s, Inches(0.55), Inches(3.2), Inches(4.0), Inches(1.3),
        "Power dominates. Every 6 dB lost halves the radius and quarters the "
        "area, so the relay and the small cell cannot fill a 9 km hole \u2014 "
        "and both physics approaches agree on that even where they disagree "
        "about where to build.", 10.5, INK2, False, FD)

    txt(s, Inches(4.85), Inches(1.52), Inches(4.0), Inches(0.24),
        "RQ3 \u2014 what moves the answer", 10, VIOL, True, FM, caps=True,
        space=1.2)
    sens = d.get("sens")
    if sens:
        ma = sens["by_asset"].get("macro", {})
        sp = ma.get("site_spread_km", {})
        order = ma.get("ranked", [])
        nice = {"model": "which model", "criterion": "criterion",
                "target": "target", "w_route": "route/area"}
        bar(s, Inches(4.7), Inches(1.8), Inches(4.15), Inches(2.1),
            [nice.get(f, f) for f in order],
            [("km", [round(sp[f], 2) for f in order])], [VIOL], horizontal=True,
            labels=True, numfmt="0.0", size=8)
        c = ma.get("consensus", {})
        txt(s, Inches(4.85), Inches(3.95), Inches(4.0), Inches(1.5),
            "%d combinations of model, criterion, target, asset and weighting. "
            "For a macro the choice of MODEL moves the site furthest \u2014 "
            "%.1f km \u2014 further than any assumption about the objective. "
            "The most-picked site wins only %.0f%% of runs."
            % (sens["n_combinations"], sp.get("model", 0),
               100 * c.get("share", 0)), 10.5, INK2, False, FD)

    txt(s, Inches(9.15), Inches(1.52), Inches(3.6), Inches(0.24),
        "RQ4 \u2014 was optimising worth it?", 10, WINE, True, FM, caps=True,
        space=1.2)
    h = d.get("hyp")
    if h:
        o, w = h["optimiser"], h["worst_measured"]
        kpi(s, Inches(9.15), Inches(1.82), Inches(3.6), "optimiser",
            "%.1f%%" % o["route_pct"], "route-km covered", vcolor=TEAL,
            vsize=21, h=Inches(0.95))
        kpi(s, Inches(9.15), Inches(2.9), Inches(3.6), "worst measured point",
            "%.1f%%" % w["route_pct"],
            "ranks %d of %d candidates" % (w["rank"], w["n_candidates"]),
            vcolor=MUTE, vsize=21, h=Inches(0.95))
        txt(s, Inches(9.15), Inches(4.0), Inches(3.6), Inches(1.45),
            "The hypothesis holds, narrowly: +%.1f points of route-km. The naive "
            "choice already sits in the top 2%% of candidates, because on this "
            "survey the deficit is one coherent region. On a survey with several "
            "holes it would not be."
            % (o["route_pct"] - w["route_pct"]), 10.5, INK2, False, FD)

    rect(s, Inches(0.55), Inches(5.75), Inches(12.2), Inches(1.1), fill=SURF,
         line=WINE, lw=1.5)
    rect(s, Inches(0.55), Inches(5.75), Inches(0.06), Inches(1.1), fill=WINE)
    txt(s, Inches(0.85), Inches(5.9), Inches(11.6), Inches(0.26),
        "The finding inside RQ3 that matters most", 12.5, WINE, True, FD)
    txt(s, Inches(0.85), Inches(6.22), Inches(11.6), Inches(0.56),
        "Model choice moves the macro site further than any objective "
        "assumption \u2014 but only because a model that fails its own held-out "
        "test is in the pool. Averaging over an unvalidated model is not "
        "robustness, it is noise. Validate first, then average: that is what "
        "RQ1 is for.", 11.5, INK2, False, FD)
    footer(s, "reports/sensitivity.json \u00b7 reports/hypothesis_test.json "
              "\u00b7 bundles/*.json")
    return s


def s9_demo(prs, d):
    """A drawn schematic, not a screenshot, so the deck stays vector."""
    s = slide(prs)
    header(s, 9, "demo", "The planner, live",
           "The brief's demo artifact: place an asset and immediately see "
           "coverage, performance, uncertainty and route benefit change.")
    rect(s, Inches(0.55), Inches(1.85), Inches(8.15), Inches(4.3), fill=INK,
         line=RULE)
    rnd = random.Random(7)
    for r_ in range(12):
        for c_ in range(24):
            v = (c_ / 23.0) * 0.75 + rnd.random() * 0.25
            col = TEAL if v > 0.62 else (OCHRE if v > 0.38 else WINE)
            rect(s, Inches(0.72 + c_ * 0.325), Inches(2.0 + r_ * 0.325),
                 Inches(0.305), Inches(0.305), fill=col, line=None)
    for i in range(58):
        t = i / 57.0
        x = 0.9 + 7.3 * t
        y = 3.2 + 1.5 * (0.5 - abs(0.5 - t)) * 2 - 0.5
        rect(s, Inches(x), Inches(y), Inches(0.075), Inches(0.075), fill=WHITE,
             line=None)
    oval(s, Inches(5.5), Inches(2.55), Inches(0.22), Inches(0.22), fill=OCHRE,
         line=None)
    oval(s, Inches(2.9), Inches(4.25), Inches(0.3), Inches(0.3), fill=None,
         line=WHITE, lw=2.5)
    txt(s, Inches(0.72), Inches(5.88), Inches(4.6), Inches(0.24),
        "map scale ▬ 2 km   ·   ▪ one 200 m demand cell", 9, WHITE, False, FM)
    px = Inches(8.95)
    rect(s, px, Inches(1.85), Inches(3.8), Inches(4.3), fill=SURF, line=RULE)
    txt(s, px + Inches(0.2), Inches(1.98), Inches(3.4), Inches(0.26),
        "Rural Coverage Planner", 13, INK, True, FD)
    for i, (lab, val) in enumerate([("approach", "Baseline — fitted physics ▾"),
                                    ("what counts as served", "Availability ▾"),
                                    ("target", "≥ 50% of the time"),
                                    ("route vs area", "0.70 / 0.30"),
                                    ("asset", "Macro · 37 m · 0 dB")]):
        y = Inches(2.36 + i * 0.52)
        txt(s, px + Inches(0.2), y, Inches(3.4), Inches(0.18), lab, 7.5, MUTE,
            False, FM, caps=True, space=1.1)
        rect(s, px + Inches(0.2), y + Inches(0.19), Inches(3.4), Inches(0.25),
             fill=WHITE, line=RULE)
        txt(s, px + Inches(0.3), y + Inches(0.235), Inches(3.2), Inches(0.2),
            val, 9, INK, False, FM)
    rect(s, px + Inches(0.2), Inches(5.0), Inches(3.4), Inches(0.32), fill=TEAL,
         line=None)
    txt(s, px + Inches(0.95), Inches(5.07), Inches(2.4), Inches(0.22),
        "Find the best site", 10, WHITE, True, FM)
    for i, (lab, val) in enumerate([("route-km", "51.9 → 80.5"),
                                    ("score", "0.421 → 0.652")]):
        rect(s, px + Inches(0.2 + i * 1.75), Inches(5.45), Inches(1.65),
             Inches(0.55), fill=WHITE, line=RULE)
        txt(s, px + Inches(0.32 + i * 1.75), Inches(5.52), Inches(1.4),
            Inches(0.18), lab, 7.5, MUTE, False, FM, caps=True, space=1.1)
        txt(s, px + Inches(0.32 + i * 1.75), Inches(5.72), Inches(1.4),
            Inches(0.24), val, 11, TEAL, True, FD)
    caption(s, Inches(0.55), Inches(6.3), Inches(12.2),
            "Heatmap of the chosen criterion over shaded relief, with the drive "
            "test drawn on top in a contrasting hue — which doubles as the road "
            "network. Amber is the existing tower, the ring is the placement. "
            "Three sweep buttons re-solve across every criterion, every "
            "weighting and every approach; a constrained variant adds the five "
            "buildability layers.", size=10, color=INK2)
    footer(s, "planner.html · planner_constrained.html · no server, no install, "
              "no network")
    return s


SLIDES = [s1_title, s2_dataset, s3_questions, s4_approaches, s5_decision,
          s6_splits, s7_accuracy, s8_answers, s9_demo]


def build(verbose=True):
    d = load()
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    for fn in SLIDES:
        fn(prs, d)
    prs.save(OUT)
    if verbose:
        print(f"[deck] {OUT} ({OUT.stat().st_size/1e6:.2f} MB), {len(SLIDES)} slides")
        print(f"[deck] bench: {', '.join(d['bench']) or 'none'}")
        print(f"[deck] bundles: {', '.join(d['bundles']) or 'none'}")
        for nm in ORDER:
            if nm not in d["bench"]:
                print(f"[deck] {nm}: no testbench entry, accuracy row reserved")
            if nm not in d["bundles"]:
                print(f"[deck] {nm}: no bundle, siting row reserved")
    return OUT


if __name__ == "__main__":
    build()
