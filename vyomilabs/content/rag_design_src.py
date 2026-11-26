"""Source of the three code blocks of the "Design the RAG" chapter (layer 14), shared by the three clouds: the rag_design.py loader, the
default rag-design.json (the schema example) and show_design.py. The loader's DEFAULTS equal the constants the later chapters used before
this chapter existed, so a course without a saved design behaves exactly as it always did. Cloud-specific mapping of the values (what a
chunking size means in a Bedrock data source, a Vertex import or an AI Search index) stays in each cloud's lab file."""
import json

# per cloud: default search type (today's behaviour) and the document store the design points at
CLOUD = {
    "aws": dict(search="vector", bucket="facilities-docs"),
    "gcp": dict(search="vector", bucket="facilities-docs"),
    "azure": dict(search="hybrid", bucket="facilitiesdocs"),
}

LOADER = '''
"""rag_design.py: the one place the RAG design is read from.

The design file `rag-design.json` (schema vyomi.rag-design/v1) is what you build and test in the console's RAG Studio. This module finds it
(RAG_DESIGN_PATH, else ./rag-design.json, else the parent folder, else next to this file), merges it over the defaults below and hands the
chapters plain values. The defaults are exactly what the course used before there was a design, so with no file nothing changes.
A bad value never stops a chapter: it prints a warning and the default is used for that field."""
import copy
import json
import os
import sys

CLOUD = "@CLOUD@"
DEFAULTS = {
    "schema": "vyomi.rag-design/v1", "name": "facilities-rag", "cloud": CLOUD,
    "chunking": {"strategy": "FIXED_SIZE", "maxTokens": 200, "overlapPct": 10},
    "embedding": {"model": "", "dimensions": None},
    "retrieve": {"topK": 3, "searchType": "@SEARCH@", "hybridWeight": 0.5, "filter": None},
    "rerank": {"enabled": False, "topN": 2},
    "generate": {"groundingThreshold": 0},
    "sources": [], "golden": [], "createdAt": "",
}
# (section, key): (kind, low, high or choices). Anything outside these rules falls back to the default.
RULES = {
    ("chunking", "strategy"): ("choice", ("FIXED_SIZE",)),
    ("chunking", "maxTokens"): ("int", 20, 8192),
    ("chunking", "overlapPct"): ("int", 0, 50),
    ("embedding", "dimensions"): ("int?", 1, 8192),
    ("retrieve", "topK"): ("int", 1, 100),
    ("retrieve", "searchType"): ("choice", ("vector", "keyword", "hybrid")),
    ("retrieve", "hybridWeight"): ("num", 0, 1),
    ("rerank", "enabled"): ("bool",),
    ("rerank", "topN"): ("int", 1, 100),
    ("generate", "groundingThreshold"): ("num", 0, 1),
}
_cache = {}


def _find():
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.environ.get("RAG_DESIGN_PATH"), "rag-design.json", os.path.join("..", "rag-design.json"), os.path.join(here, "rag-design.json")):
        if p and os.path.isfile(p):
            return os.path.abspath(p)
    return None


def _ok(rule, v):
    kind = rule[0]
    if kind == "bool":
        return isinstance(v, bool)
    if kind == "choice":
        return v in rule[1]
    if kind == "int?" and v is None:
        return True
    if kind in ("int", "int?"):
        return isinstance(v, int) and not isinstance(v, bool) and rule[1] <= v <= rule[2]
    return isinstance(v, (int, float)) and not isinstance(v, bool) and rule[1] <= v <= rule[2]


def _read(path):
    problems, merged = [], copy.deepcopy(DEFAULTS)
    if not path:
        return merged, problems
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            raise ValueError("the top level must be an object")
    except (OSError, ValueError) as e:
        return merged, ["%s: cannot read (%s); using the defaults" % (path, e)]
    for key, val in raw.items():
        if isinstance(DEFAULTS.get(key), dict):
            if not isinstance(val, dict):
                problems.append("%s must be an object; using the default" % key)
                continue
            for k, v in val.items():
                if (key, k) == ("retrieve", "searchType") and isinstance(v, str):      # RAG Studio writes HYBRID / SEMANTIC; this course says hybrid / vector
                    v = {"hybrid": "hybrid", "semantic": "vector", "vector": "vector", "keyword": "keyword"}.get(v.lower(), v)
                rule = RULES.get((key, k))
                if rule and not _ok(rule, v):
                    problems.append("%s.%s = %r is not allowed (%s); using %r" % (key, k, v, _describe(rule), DEFAULTS[key][k]))
                else:
                    merged[key][k] = v
        else:
            merged[key] = val
    if merged.get("cloud") != CLOUD:
        problems.append("this design was made for %r, this course builds %r" % (merged.get("cloud"), CLOUD))
    return merged, problems


def _describe(rule):
    return {"choice": lambda: "one of " + ", ".join(map(str, rule[1])), "bool": lambda: "true or false"}.get(rule[0], lambda: "a number from %s to %s" % rule[1:3])()


def _state():
    path = _find()
    stamp = (path, os.path.getmtime(path) if path else None)
    if _cache.get("stamp") != stamp:
        design, problems = _read(path)
        for p in problems:
            print("rag_design: warning: " + p, file=sys.stderr)
        _cache.update(stamp=stamp, path=path, design=design, problems=problems)
    return _cache


def load():
    """The design: the file merged over the defaults (a fresh copy you may change)."""
    return copy.deepcopy(_state()["design"])


def source():
    """The path of the design file in use, or None when the built-in defaults are used."""
    return _state()["path"]


def problems():
    return list(_state()["problems"])


def customised(section):
    """True when the design changes this section from the course defaults (so a chapter only sends extra settings when you asked for them)."""
    return load()[section] != DEFAULTS[section]


def chunk_cfg():
    c = load()["chunking"]
    return dict(strategy=c["strategy"], maxTokens=c["maxTokens"], overlapPct=c["overlapPct"])


def top_k():
    return load()["retrieve"]["topK"]


def search_type():
    return load()["retrieve"]["searchType"]


def rerank():
    r = load()["rerank"]
    return dict(enabled=r["enabled"], topN=r["topN"])


def grounding_threshold():
    return load()["generate"]["groundingThreshold"]


def dimensions():
    """The embedding vector size the design asks for, or None for the model's own size."""
    return load()["embedding"]["dimensions"]
'''

SHOW = '''
import rag_design

d = rag_design.load()
print("design file:", rag_design.source() or "none found, using the built-in defaults")
print("name:", d["name"], "| cloud:", d["cloud"])
c = d["chunking"]
print("chunking:", c["strategy"], "| maxTokens", c["maxTokens"], "| overlap", c["overlapPct"], "%")
e = d["embedding"]
print("embedding:", e["model"] or "the model this simulator hosts", "| dimensions", e["dimensions"] or "model default")
r = d["retrieve"]
print("retrieve: topK", r["topK"], "|", r["searchType"], "search", "| hybridWeight", r["hybridWeight"], "| filter", r["filter"])
rr = d["rerank"]
print("rerank:", "on, keep the best %d" % rr["topN"] if rr["enabled"] else "off")
print("generate: refuse below a grounding score of", d["generate"]["groundingThreshold"])
print("sources:", len(d["sources"]), "| golden questions:", len(d["golden"]))
bad = rag_design.problems()
print("design OK" if not bad else "design has %d problem(s); the defaults are used for those fields" % len(bad))
for p in bad:
    print("  -", p)
'''


def loader_code(cloud):
    return LOADER.replace("@CLOUD@", cloud).replace("@SEARCH@", CLOUD[cloud]["search"])


def design_json(cloud):
    c = CLOUD[cloud]
    d = {"schema": "vyomi.rag-design/v1", "name": "facilities-rag", "cloud": cloud,
         "chunking": {"strategy": "FIXED_SIZE", "maxTokens": 200, "overlapPct": 10},
         "embedding": {"model": "", "dimensions": None},
         "retrieve": {"topK": 3, "searchType": c["search"].replace("vector", "SEMANTIC").upper(), "hybridWeight": 0.5, "filter": None},
         "rerank": {"enabled": False, "topN": 2},
         "generate": {"groundingThreshold": 0},
         "sources": [{"bucket": c["bucket"], "prefix": "docs/"}],
         "golden": [{"question": "What should I do when boiler pressure exceeds 30 psi?", "expectedSources": ["boiler-sop"], "expectedAnswer": "close the main steam valve"},
                    {"question": "AHU-7 supply air temperature drift chilled water valve", "expectedSources": ["hvac-maintenance-manual"], "expectedAnswer": ""}],
         "createdAt": "2026-11-26T09:00:00Z"}
    return json.dumps(d, indent=2) + "\n"


STUDIO = {"aws": "Bedrock, RAG Studio", "gcp": "Vertex AI, RAG Studio", "azure": "AI Search, RAG Studio"}


def design_blocks(b, cloud):
    """The three lab blocks of chapter 14, built with the cloud lab file's own block constructor `b`."""
    return [
        b("Write the design loader", "Every later chapter that chunks, searches or answers imports this one file instead of hard-coding its settings. It finds your design file, merges it over the defaults (which are exactly the values the course used before this chapter existed), and returns plain numbers. A value that is out of range prints a warning and falls back to its default, so a typo never stops a chapter.",
          "rag_design.py", loader_code(cloud)),
        b("Save the starting design", "The design file, in the schema %s writes when you export a design. This one is the course's starting point, so saving it changes nothing yet. Replace it with the file you export from %s once you have tuned and tested your own design: chapters 12, 6 and 11 will build and answer with your numbers. Keep the name `rag-design.json` next to your other files." % ("`vyomi.rag-design/v1`", STUDIO[cloud]),
          "rag-design.json", design_json(cloud), lang="json"),
        b("Check the design", "Loads the design the way the later chapters will, checks every value against its allowed range and prints what they will use. Run it after every change to `rag-design.json`.",
          "show_design.py", SHOW, run="python show_design.py", expect="design OK"),
    ]
