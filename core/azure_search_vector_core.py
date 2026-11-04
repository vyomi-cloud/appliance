"""Azure AI Search: vector fields, vector / hybrid queries, skillsets and integrated vectorization (index projections).

An additive companion to core/azure_search_core.py (kept separate so the shared engine file stays small). Pure Python, no
framework imports; the embedding model is the shared local seam (core/llm_core.embed).

* Vector fields: ``Collection(Edm.Single)`` with ``dimensions`` + ``vectorSearchProfile`` (profile -> algorithm -> optional
  vectorizer, defined in the index's ``vectorSearch``). Documents are length-checked against ``dimensions``.
* Queries: ``vectorQueries`` = ``[{"kind":"vector","vector":[...],"fields":"f","k":n}, {"kind":"text","text":"...","fields":"f"}]``.
  ``text`` queries are embedded through the field profile's vectorizer (integrated vectorization at query time). Exact cosine
  scan (an HNSW graph is not built). With ``search`` text too the result is hybrid: reciprocal-rank-fusion (k=60) of the
  keyword ranking and the vector ranking, ``@search.score`` is the fused score (pure vector: cosine similarity).
* Skillsets: ``#Microsoft.Skills.Text.SplitSkill`` (pages, maximumPageLength / pageOverlapLength, characters) and
  ``#Microsoft.Skills.Text.AzureOpenAIEmbeddingSkill`` (and ``Vision`` / other embedding skill names are rejected) really
  execute inside an indexer run over an enrichment tree with ``/document/...`` paths and ``*`` contexts, and
  ``indexProjections`` (selectors: targetIndexName, parentKeyFieldName, sourceContext, mappings; parameters.projectionMode)
  writes one child document per chunk into the target index. Any other skill type is stored (validated by name) but makes
  the indexer fail with the skill named, never a silent skip.

Honest limits: no OCR / entity / language / image skills, no knowledge store, no custom WebApi skill, no semantic ranker, no
HNSW (exact scan), scoring is TF-IDF for the keyword half; the Azure OpenAI resource named in a skill / vectorizer is not
contacted - the local embedding model answers and its dimension is truncated/padded to the declared ``dimensions``.
"""
from __future__ import annotations

import hashlib
import math
import re

try:
    from core import llm_core as llm
except ImportError:  # Pyodide flat layout
    import llm_core as llm  # type: ignore

SPLIT = "#Microsoft.Skills.Text.SplitSkill"
EMBED = "#Microsoft.Skills.Text.AzureOpenAIEmbeddingSkill"
KNOWN_PREFIX = "#Microsoft.Skills."


def validate_vector_field(f, index_body):
    """-> error string or None for a Collection(Edm.Single) field definition."""
    dims = f.get("dimensions")
    if not isinstance(dims, int) or isinstance(dims, bool) or not 2 <= dims <= 4096:
        return f"Vector field '{f['name']}' must declare dimensions between 2 and 4096."
    if f.get("key") or f.get("sortable") or f.get("facetable") or f.get("filterable"):
        return f"Vector field '{f['name']}' cannot be a key, sortable, facetable or filterable."
    prof = f.get("vectorSearchProfile")
    profiles = {p.get("name"): p for p in ((index_body.get("vectorSearch") or {}).get("profiles") or [])}
    if prof not in profiles:
        return f"Vector field '{f['name']}' references vectorSearchProfile '{prof}' which is not defined in vectorSearch.profiles."
    algos = {a.get("name") for a in ((index_body.get("vectorSearch") or {}).get("algorithms") or [])}
    if profiles[prof].get("algorithm") not in algos:
        return f"Vector profile '{prof}' references an algorithm that is not defined in vectorSearch.algorithms."
    vz = profiles[prof].get("vectorizer")
    if vz and vz not in {v.get("name") for v in ((index_body.get("vectorSearch") or {}).get("vectorizers") or [])}:
        return f"Vector profile '{prof}' references vectorizer '{vz}' which is not defined."
    return None


def coerce_vector(f, value):
    if not isinstance(value, list) or any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in value):
        raise ValueError("expected an array of numbers")
    if len(value) != f.get("dimensions"):
        raise ValueError(f"expected {f.get('dimensions')} dimensions but got {len(value)}")
    return [float(x) for x in value]


def _embed(text, dims):
    v = llm.embed(text)["vectors"][0]
    v = (list(v) + [0.0] * dims)[:dims]
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _cos(a, b):
    return sum(x * y for x, y in zip(a, b)) / ((math.sqrt(sum(x * x for x in a)) or 1.0) * (math.sqrt(sum(y * y for y in b)) or 1.0))


def vector_rank(idx, docs, queries):
    """-> (ranked [(score, doc)], error) over candidate ``docs`` (already filtered). One list: the union ranking by best score."""
    fm = {f["name"]: f for f in idx["fields"]}
    best = {}
    keyf = next(f["name"] for f in idx["fields"] if f["key"])
    for q in queries:
        kind = q.get("kind", "vector")
        flds = [x.strip() for x in str(q.get("fields") or "").split(",") if x.strip()]
        if not flds:
            return None, "vectorQueries[].fields is required."
        for fn in flds:
            f = fm.get(fn)
            if not f or f["type"] != "Collection(Edm.Single)":
                return None, f"Field '{fn}' is not a vector field."
            if kind == "vector":
                qv = q.get("vector")
                if not isinstance(qv, list) or len(qv) != f["dimensions"]:
                    return None, f"The query vector must have {f['dimensions']} dimensions (field '{fn}')."
            elif kind == "text":
                prof = next((p for p in (idx.get("vectorSearch") or {}).get("profiles", []) if p.get("name") == f.get("vectorSearchProfile")), {})
                if not prof.get("vectorizer"):
                    return None, f"Field '{fn}' has no vectorizer in its profile; use kind 'vector' with an explicit vector."
                if not q.get("text"):
                    return None, "vectorQueries[].text is required for kind 'text'."
                try:
                    qv = _embed(str(q["text"]), f["dimensions"])
                except llm.LlmUnavailable as e:
                    return None, f"The vectorizer's embedding model is not available: {e}"
            else:
                return None, f"Unsupported vector query kind '{kind}'."
            k = int(q.get("k") or 50)
            scored = sorted(((_cos(qv, d[fn]), d) for d in docs if d.get(fn)), key=lambda x: -x[0])[:k]
            for s, d in scored:
                if d[keyf] not in best or s > best[d[keyf]][0]:
                    best[d[keyf]] = (s, d)
    return sorted(best.values(), key=lambda x: -x[0]), None


def fuse(keyword_scored, vector_scored, keyf):
    """Reciprocal rank fusion of two ranked lists of (score, doc)."""
    score, docs = {}, {}
    for ranked in (keyword_scored, vector_scored):
        for r, (_s, d) in enumerate(ranked, 1):
            score[d[keyf]] = score.get(d[keyf], 0.0) + 1.0 / (60 + r)
            docs[d[keyf]] = d
    return sorted(((s, docs[k]) for k, s in score.items()), key=lambda x: -x[0])


# ───────────────────────────── skillsets ─────────────────────────────
def validate_skillset(body):
    skills = body.get("skills")
    if not isinstance(skills, list) or not skills:
        return "A skillset must define at least one skill."
    for i, s in enumerate(skills):
        t = s.get("@odata.type") or ""
        if not t.startswith(KNOWN_PREFIX):
            return f"skills[{i}]: '@odata.type' must be a #Microsoft.Skills.* type."
        if not isinstance(s.get("inputs"), list) or not isinstance(s.get("outputs"), list) or not s["outputs"]:
            return f"skills[{i}]: inputs and outputs are required."
        if t == SPLIT:
            ml = s.get("maximumPageLength", 5000)
            if not isinstance(ml, int) or ml < 300:
                return f"skills[{i}]: maximumPageLength must be an integer >= 300."
            ov = s.get("pageOverlapLength", 0)
            if not isinstance(ov, int) or ov < 0 or ov >= ml:
                return f"skills[{i}]: pageOverlapLength must be >= 0 and less than maximumPageLength."
        if t == EMBED:
            d = s.get("dimensions")
            if d is not None and (not isinstance(d, int) or not 2 <= d <= 4096):
                return f"skills[{i}]: dimensions must be between 2 and 4096."
            if not s.get("resourceUri") or not s.get("deploymentId"):
                return f"skills[{i}]: resourceUri and deploymentId are required."
    proj = body.get("indexProjections")
    if proj:
        sel = proj.get("selectors")
        if not isinstance(sel, list) or not sel:
            return "indexProjections.selectors must list at least one selector."
        for j, x in enumerate(sel):
            for req in ("targetIndexName", "parentKeyFieldName", "sourceContext", "mappings"):
                if not x.get(req):
                    return f"indexProjections.selectors[{j}].{req} is required."
        mode = (proj.get("parameters") or {}).get("projectionMode", "includeIndexingParentDocuments")
        if mode not in ("includeIndexingParentDocuments", "skipIndexingParentDocuments"):
            return "indexProjections.parameters.projectionMode is invalid."
    return None


def _split_text(text, ml, ov):
    if len(text) <= ml:
        return [text] if text else []
    out, i = [], 0
    while i < len(text):
        j = min(len(text), i + ml)
        if j < len(text):   # prefer to cut on a sentence end, else whitespace
            cut = max(text.rfind(". ", i, j), text.rfind("\n", i, j))
            if cut <= i + ml // 2:
                cut = text.rfind(" ", i, j)
            if cut > i:
                j = cut + 1
        out.append(text[i:j].strip())
        if j >= len(text):
            break
        i = max(j - ov, i + 1)
    return [c for c in out if c]


def _get(tree, path):
    cur = tree
    for seg in [s for s in path.split("/") if s]:
        if isinstance(cur, list):
            cur = cur[int(seg)] if seg.isdigit() and int(seg) < len(cur) else None
        elif isinstance(cur, dict):
            cur = cur.get(seg)
        else:
            return None
        if cur is None:
            return None
    return cur


def _set(tree, path, value):
    segs = [s for s in path.split("/") if s]
    cur = tree
    for seg in segs[:-1]:
        cur = cur[int(seg)] if isinstance(cur, list) else cur.setdefault(seg, {})
    if isinstance(cur, list):
        cur[int(segs[-1])] = value
    else:
        cur[segs[-1]] = value


def _expand(tree, ctx):
    """'/document/pages/*' -> concrete paths ['/document/pages/0', ...]; contexts without '*' are returned as-is."""
    if "*" not in ctx:
        return [ctx]
    head, _, tail = ctx.partition("/*")
    arr = _get(tree, head)
    if not isinstance(arr, list):
        return []
    out = []
    for i in range(len(arr)):
        out += _expand(tree, f"{head}/{i}{tail}")
    return out


def _bind(source, ctx_pattern, ctx_concrete):
    """Rewrite wildcards in ``source`` with the indices of the concrete context, as Azure does for nested contexts."""
    pat, con = ctx_pattern.split("/"), ctx_concrete.split("/")
    idx = [c for p, c in zip(pat, con) if p == "*"]
    out = []
    for seg in source.split("/"):
        out.append(idx.pop(0) if seg == "*" and idx else seg)
    return "/".join(out)


def run_skillset(skillset, document):
    """Execute the skills over ``document`` -> (tree, error). Mutates a copy; the tree root is {"document": ...}."""
    tree = {"document": dict(document)}
    for n, s in enumerate(skillset["skills"]):
        t = s["@odata.type"]
        ctx = s.get("context") or "/document"
        if t not in (SPLIT, EMBED):
            return tree, f"Skill #{n + 1} ({s.get('name') or t}) of type {t} cannot be executed by Vyomi (only SplitSkill and AzureOpenAIEmbeddingSkill run)."
        ins = {i["name"]: i.get("source") for i in s["inputs"]}
        outs = {o["name"]: o.get("targetName") or o["name"] for o in s["outputs"]}
        for concrete in _expand(tree, ctx):
            src = _bind(ins.get("text") or "", ctx, concrete)
            text = _get(tree, src)
            if t == SPLIT:
                if not isinstance(text, str):
                    text = "" if text is None else str(text)
                pages = _split_text(text, s.get("maximumPageLength", 5000), s.get("pageOverlapLength", 0))
                _set(tree, f"{concrete}/{outs.get('textItems', 'pages')}", pages)
            else:
                if text is None or (isinstance(text, str) and not text.strip()):
                    continue
                dims = s.get("dimensions") or 1536
                try:
                    vec = _embed(str(text), dims)
                except llm.LlmUnavailable as e:
                    return tree, f"Skill #{n + 1} ({s.get('name') or 'embedding'}): the embedding model is not available: {e}"
                target = outs.get("embedding", "embedding")
                # a page string cannot hold children, so per-page outputs live in a sibling list parallel to the strings
                parent, _, leaf = concrete.rpartition("/")
                if leaf.isdigit():
                    holder = _get(tree, parent)
                    key = f"{parent.rsplit('/', 1)[-1]}__{target}"
                    side = _get(tree, parent.rsplit("/", 1)[0] + "/" + key)
                    if side is None:
                        side = [None] * len(holder)
                        _set(tree, parent.rsplit("/", 1)[0] + "/" + key, side)
                    side[int(leaf)] = vec
                else:
                    _set(tree, f"{concrete}/{target}", vec)
    return tree, None


def _resolve(tree, source, concrete_ctx, ctx_pattern):
    """Value of a projection mapping source for one chunk, honouring the page-sibling layout above."""
    src = _bind(source, ctx_pattern, concrete_ctx)
    v = _get(tree, src)
    if v is not None:
        return v
    # '/document/pages/*/text_vector' -> sibling list 'pages__text_vector'
    parent, _, leaf = src.rpartition("/")
    gp, _, idx = parent.rpartition("/")
    arr_parent = gp.rsplit("/", 1)
    if idx.isdigit() and len(arr_parent) == 2:
        side = _get(tree, f"{arr_parent[0]}/{arr_parent[1]}__{leaf}")
        if isinstance(side, list) and int(idx) < len(side):
            return side[int(idx)]
    return None


def project(skillset, tree, parent_key):
    """-> {targetIndexName: [child docs]} for the skillset's index projections of one enriched document."""
    out = {}
    for sel in (skillset.get("indexProjections") or {}).get("selectors") or []:
        ctx = sel["sourceContext"]
        for n, concrete in enumerate(_expand(tree, ctx)):
            child = {sel["parentKeyFieldName"]: parent_key}
            for m in sel["mappings"]:
                child[m["name"]] = _resolve(tree, m.get("source") or "", concrete, ctx) if m.get("source") else None
            child["__ordinal"] = n
            out.setdefault(sel["targetIndexName"], []).append(child)
    return out


def child_key(parent_key, n):
    return hashlib.sha1(f"{parent_key}_{n}".encode()).hexdigest()[:24]
