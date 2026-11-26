"""rag_design.py: the one place the RAG design is read from.

The design file `rag-design.json` (schema vyomi.rag-design/v1) is what you build and test in the console's RAG Studio. This module finds it
(RAG_DESIGN_PATH, else ./rag-design.json, else the parent folder, else next to this file), merges it over the defaults below and hands the
chapters plain values. The defaults are exactly what the course used before there was a design, so with no file nothing changes.
A bad value never stops a chapter: it prints a warning and the default is used for that field."""
import copy
import json
import os
import sys

CLOUD = "azure"
DEFAULTS = {
    "schema": "vyomi.rag-design/v1", "name": "facilities-rag", "cloud": CLOUD,
    "chunking": {"strategy": "FIXED_SIZE", "maxTokens": 200, "overlapPct": 10},
    "embedding": {"model": "", "dimensions": None},
    "retrieve": {"topK": 3, "searchType": "hybrid", "hybridWeight": 0.5, "filter": None},
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
