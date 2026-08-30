import io, json, pathlib, re

BLOCK_RE = re.compile(r'(?m)^(/\* -+ .*? -+ \*/)$')


def wrap_blocks(js):
    """Isolate each top-level block in try/catch.

    A single uncaught throw in one chart used to blank every section after it --
    which is exactly how `step_m` (profiled but never exported as a series) took
    out sections 07 through 11. Each block now fails alone and says so in the
    console instead of taking the page down with it.
    """
    parts = BLOCK_RE.split(js)
    out = [parts[0]]
    for i in range(1, len(parts) - 1, 2):
        name = re.sub(r"[/*\-]", "", parts[i]).strip().replace("'", "")
        out.append(parts[i])
        out.append("\ntry{\n" + parts[i + 1] + "\n}catch(err){console.error('[block] "
                   + name + "', err);}\n")
    return "".join(out)


tpl = io.open("eda.html", encoding="utf-8").read()
head, s1, rest = tpl.partition("<script>")
js, s2, tail = rest.partition("</script>")
tpl = head + s1 + wrap_blocks(js) + s2 + tail

data = json.load(io.open(pathlib.Path(__file__).resolve().parent.parent
                         / "reports" / "eda.json", encoding="utf-8"))
out = tpl.replace("__DATA__", json.dumps(data, separators=(",", ":")))
io.open("eda_report.html", "w", encoding="utf-8").write(out)

js2 = out.split("<script>")[1].split("</script>")[0]
print("blocks wrapped:", js2.count("catch(err)"))
print("brace", js2.count("{") - js2.count("}"),
      "paren", js2.count("(") - js2.count(")"),
      "bracket", js2.count("[") - js2.count("]"),
      "backtick even", js2.count("`") % 2 == 0)
bad = False
for t in ['div', 'section', 'table', 'tr', 'td', 'th', 'thead', 'tbody', 'p', 'h1', 'h2',
          'h3', 'h4', 'span', 'style', 'script', 'header', 'footer', 'canvas', 'button']:
    o = len(re.findall(r'<%s[\s>]' % t, out)); c = len(re.findall(r'</%s>' % t, out))
    if o != c:
        print("MISMATCH", t, o, c); bad = True
print("tags ok" if not bad else "TAG PROBLEM")

ids = re.findall(r'id="([a-zA-Z0-9\-]+)"', out)
need = ["tiles", "tbl-inv", "colcards", "c-tiers", "glossary", "c-miss", "c-time", "c-int",
        "c-runs", "tbl-runs", "mapSeg", "mapcv", "c-step", "c-speed", "cards", "c-pctall",
        "c-pctnorm", "tbl-pct", "discrete", "cats", "c-cell", "c-corr", "c-ud", "tbl-odd"]
missing = [i for i in need if i not in ids]
print("required ids present" if not missing else "MISSING IDS: %s" % missing)

# every column charted in section 06 must have BOTH a profile and a series
order = re.search(r'const ORDER=\[(.*?)\];', js2).group(1)
cols = [c.strip().strip('"') for c in order.split(",")]
prof, ser = set(data["profiles"]), set(data["series"])
gap = [c for c in cols if c not in prof or c not in ser]
print("every charted column has profile+series" if not gap else "GAP: %s" % gap)
print("size %.2f MB" % (len(out) / 1e6))
