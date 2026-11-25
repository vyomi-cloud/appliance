"""Knowledge processing + search primitives shared by Bedrock Knowledge Bases and the OpenSearch data plane (C6 + C12).

Substrate-independent (Nano Pyodide + Mesh container), pure Python + stdlib. Nothing here is a search engine of our own:

  * lexical (BM25) ranking  -> SQLite FTS5 ``bm25()`` (stdlib ``sqlite3``; public domain). If the sqlite build has no FTS5 (some
    Pyodide builds) it falls back to a 15-line BM25 so results stay equivalent; ``fts5_available()`` reports which one is live.
  * vector ranking          -> cosine over the vectors from the local-LLM seam (core/llm_core.embed). Exact scan: fine to ~10k chunks.
  * parsing                 -> text/CSV/HTML natively, .docx/.xlsx/.pptx via zipfile + ElementTree (stdlib), .pdf via pure-Python
                               ``pypdf`` (BSD; on Nano it must be loadable into Pyodide, else PDFs fail with an explicit reason).
  * PII scan                -> the existing Bedrock Guardrails engine (core/bedrock_guardrails_core.evaluate), same policies as the runtime.
  * rerank                  -> embedding similarity blended with lexical coverage over the same seam (no extra model download).

Honest limits: no cross-encoder model is shipped (a bge-reranker GGUF behind llama.cpp's /v1/rerank is the Mesh upgrade path);
scanned PDFs have no OCR; legacy .doc/.xls/.ppt are rejected; SEMANTIC chunking uses the local embedder (hash embedder = lexical breakpoints).
"""
from __future__ import annotations

import io
import math
import os
import re
import sqlite3
import threading
import zipfile

try:
    from core import llm_core as llm
except ImportError:  # Pyodide flat layout
    import llm_core as llm  # type: ignore

_TOK = re.compile(r"[A-Za-z0-9_]+")
TEXT_EXT = (".txt", ".md", ".markdown", ".csv", ".json", ".html", ".htm", ".xml", ".log", ".tsv", ".yaml", ".yml", ".rst")
PARSE_EXT = TEXT_EXT + (".docx", ".xlsx", ".pptx", ".pdf")


def tokens(s) -> list:
    return [t.lower() for t in _TOK.findall(str(s or ""))]


# ═════════════════════════ lexical: BM25 via FTS5 ═════════════════════════
def fts5_available() -> bool:
    try:
        c = sqlite3.connect(":memory:")
        c.execute("create virtual table t using fts5(a)")
        c.close()
        return True
    except sqlite3.Error:
        return False


_LOCK = threading.RLock()


class TextIndex:
    """BM25 index over a list of texts; ``search(query)`` -> {doc_position: score} for docs containing at least one query term."""

    def __init__(self, texts):
        self.texts = [str(t or "") for t in texts]
        self.db = None
        try:
            self.db = sqlite3.connect(":memory:", check_same_thread=False)
            self.db.execute("create virtual table d using fts5(t, tokenize='unicode61')")
            self.db.executemany("insert into d(rowid, t) values (?, ?)", [(i + 1, t) for i, t in enumerate(self.texts)])
        except sqlite3.Error:
            self.db = None
            self._toks = [tokens(t) for t in self.texts]
            self._avg = (sum(len(t) for t in self._toks) / len(self._toks)) if self._toks else 1.0

    def search(self, query: str) -> dict:
        terms = list(dict.fromkeys(tokens(query)))
        if not terms or not self.texts:
            return {}
        if self.db is not None:
            q = " OR ".join('"' + t + '"' for t in terms)
            try:
                with _LOCK:      # one shared in-memory connection (check_same_thread=False): concurrent queries segfault sqlite
                    rows = self.db.execute("select rowid, bm25(d) from d where d match ? ", (q,)).fetchall()
            except sqlite3.Error:
                return {}
            return {rid - 1: max(-sc, 1e-3) for rid, sc in rows}      # FTS5 bm25() is lower-is-better (negative)
        n, out = len(self._toks), {}
        df = {t: sum(1 for d in self._toks if t in d) for t in terms}
        for i, d in enumerate(self._toks):
            sc = 0.0
            for t in terms:
                f = d.count(t)
                if f:
                    idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                    sc += idf * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * len(d) / self._avg))
            if sc > 0:
                out[i] = sc
        return out


_CACHE: dict = {}


def text_index(texts) -> TextIndex:
    key = hash(tuple(texts))
    with _LOCK:      # a concurrent request must not clear the cache (closing its connection) while another thread queries it
        ti = _CACHE.get(key)
        if ti is None:
            if len(_CACHE) > 24:
                _CACHE.clear()
            ti = _CACHE[key] = TextIndex(texts)
        return ti


def bm25(texts, query) -> dict:
    return text_index(texts).search(query)


# ═════════════════════════ fusion + rerank ═════════════════════════
def rrf(rankings, k: int = 60) -> dict:
    """Reciprocal Rank Fusion over rankings (each = list of ids best-first) -> {id: score in 0..1}."""
    out: dict = {}
    for r in rankings:
        for pos, i in enumerate(r):
            out[i] = out.get(i, 0.0) + 1.0 / (k + pos + 1)
    top = len(rankings) / (k + 1) or 1.0
    return {i: v / top for i, v in out.items()}


def hybrid(texts, vecs, query, qvec, allowed=None, k=10, weight_lex=0.5):
    """Hybrid search over parallel lists. Returns [(position, score)] best-first; ``allowed`` = set of positions (metadata filter)."""
    pos = [i for i in range(len(texts)) if allowed is None or i in allowed]
    lex = {i: s for i, s in bm25([texts[i] for i in pos], query).items()}
    lex_r = [pos[i] for i, _ in sorted(lex.items(), key=lambda x: -x[1])]
    vec_s = sorted(((llm.cosine(qvec, vecs[i]), i) for i in pos), reverse=True)
    vec_r = [i for _, i in vec_s]
    fused = rrf([vec_r, lex_r]) if weight_lex else rrf([vec_r])
    return sorted(fused.items(), key=lambda x: -x[1])[:k]


_RR = {"backend": "embedding+lexical"}


def rerank_backend() -> str:
    """Which reranker answered the last call: 'cross-encoder (<endpoint>)' or 'embedding+lexical'."""
    return _RR["backend"]


def _cross_encoder(query: str, texts, endpoint: str):
    """OPTIONAL true cross-encoder: any Jina/Cohere/llama.cpp-style ``POST <endpoint>`` with {model, query, documents} ->
    {results:[{index, relevance_score}]} (e.g. ``llama-server --reranking`` with a bge-reranker GGUF on the Mesh). Not shipped; the operator sets
    ``VYOMI_RERANK_ENDPOINT``. -> [(index, score 0..1)] or None when unreachable."""
    import json as _json
    import urllib.request as _u
    try:
        req = _u.Request(endpoint, data=_json.dumps({"model": os.environ.get("VYOMI_RERANK_MODEL", "reranker"), "query": query, "documents": list(texts),
                                                     "top_n": len(texts)}).encode(), headers={"content-type": "application/json"})
        with _u.urlopen(req, timeout=30) as r:
            res = _json.loads(r.read())["results"]
        out = []
        for x in res:
            sc = float(x.get("relevance_score", x.get("score", 0.0)))
            out.append((int(x["index"]), round(sc if 0.0 <= sc <= 1.0 else 1.0 / (1.0 + math.exp(-sc)), 6)))
        return out
    except Exception:  # noqa: BLE001
        return None


def rerank(query: str, texts, top_n: int | None = None):
    """-> [(index, relevance 0..1)] best-first. A real cross-encoder when ``VYOMI_RERANK_ENDPOINT`` answers; otherwise embedding
    similarity (0.7) + query-term coverage (0.3) over the shared embedding seam (labelled by ``rerank_backend()``)."""
    if not texts:
        return []
    ep = os.environ.get("VYOMI_RERANK_ENDPOINT")
    if ep:
        ce = _cross_encoder(query, texts, ep)
        if ce is not None:
            _RR["backend"] = f"cross-encoder ({ep})"
            ce.sort(key=lambda x: -x[1])
            return ce[:top_n] if top_n else ce
    _RR["backend"] = "embedding+lexical" + (" (cross-encoder endpoint unreachable)" if ep else "")
    vs = llm.embed([query] + list(texts))["vectors"]
    qt = set(tokens(query))
    out = []
    for i, t in enumerate(texts):
        cos = max(llm.cosine(vs[0], vs[i + 1]), 0.0)
        cov = (len(qt & set(tokens(t))) / len(qt)) if qt else 0.0
        out.append((i, round(0.7 * cos + 0.3 * cov, 6)))
    out.sort(key=lambda x: -x[1])
    return out[:top_n] if top_n else out


# ═════════════════════════ parse / chunk ═════════════════════════
class ParseError(Exception):
    pass


MAX_DOC_BYTES = 50 * 1024 * 1024           # Bedrock KB per-file limit (50 MB)
MAX_UNZIPPED = 200 * 1024 * 1024           # zip-bomb guard for the Office containers
_LEGACY = {".doc": "Word 97-2003 (.doc)", ".xls": "Excel 97-2003 (.xls)", ".ppt": "PowerPoint 97-2003 (.ppt)"}


def _zip(data: bytes, what: str):
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ParseError(f"not a valid {what} file (corrupt or not an Office Open XML package)")
    if sum(i.file_size for i in z.infolist()) > MAX_UNZIPPED:
        raise ParseError(f"{what} expands beyond the {MAX_UNZIPPED // 1048576} MB safety limit")
    return z


def _xml(z, name: str):
    import xml.etree.ElementTree as ET
    try:
        return ET.fromstring(z.read(name))
    except KeyError:
        return None
    except ET.ParseError as e:
        raise ParseError(f"corrupt XML part {name}: {e}")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _table(rows, markdown: bool) -> str:
    """Rows of cell strings -> markdown table (structure kept, FM-style parsing) or 'header: value' lines (plain text parsing)."""
    rows = [[str(c).replace("\n", " ").strip() for c in r] for r in rows if any(str(c).strip() for c in r)]
    if not rows:
        return ""
    if markdown:
        w = max(len(r) for r in rows)
        rows = [r + [""] * (w - len(r)) for r in rows]
        return "\n".join(["| " + " | ".join(rows[0]) + " |", "|" + "---|" * w] + ["| " + " | ".join(r) + " |" for r in rows[1:]])
    head, body = rows[0], rows[1:]
    if not body:
        return " | ".join(head)
    return "\n".join("; ".join(f"{h}: {v}" if h else v for h, v in zip(head + [""] * (len(r) - len(head)), r) if v) for r in body)


def _docx(data, md):
    z = _zip(data, ".docx")
    root = _xml(z, "word/document.xml")
    if root is None:
        raise ParseError("not a valid .docx file (word/document.xml missing)")
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

    def para(p):
        out, style = [], ""
        for e in p.iter():
            t = _local(e.tag)
            if t == "t":
                out.append(e.text or "")
            elif t in ("tab",):
                out.append("\t")
            elif t in ("br", "cr"):
                out.append("\n")
            elif t == "pStyle":
                style = e.get(W + "val", "")
        s = "".join(out).strip()
        m = re.match(r"(?i)heading\s*([1-6])", style)
        return ("#" * int(m.group(1)) + " " + s) if (m and s) else s

    blocks = []
    body = root.find(W + "body")
    for el in (list(body) if body is not None else []):
        t = _local(el.tag)
        if t == "p":
            s = para(el)
            if s:
                blocks.append(s)
        elif t == "tbl":
            rows = [[" ".join(filter(None, (para(p) for p in tc.iter(W + "p")))) for tc in tr.findall(W + "tc")] for tr in el.iter(W + "tr")]
            s = _table(rows, md)
            if s:
                blocks.append(s)
    return "\n\n".join(blocks)


def _xlsx(data, md):
    z = _zip(data, ".xlsx")
    S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    wb = _xml(z, "xl/workbook.xml")
    if wb is None:
        raise ParseError("not a valid .xlsx file (xl/workbook.xml missing)")
    sst = []
    sroot = _xml(z, "xl/sharedStrings.xml")
    if sroot is not None:
        sst = ["".join(t.text or "" for t in si.iter(S + "t")) for si in sroot.findall(S + "si")]
    rels = {}
    rr = _xml(z, "xl/_rels/workbook.xml.rels")
    if rr is not None:
        rels = {r.get("Id"): r.get("Target") for r in rr}
    out = []
    for sh in wb.iter(S + "sheet"):
        tgt = rels.get(sh.get(R + "id")) or ""
        part = tgt.lstrip("/") if tgt.startswith("/") else "xl/" + tgt
        ws = _xml(z, part)
        if ws is None:
            continue
        rows = []
        for row in ws.iter(S + "row"):
            cells = {}
            for c in row.findall(S + "c"):
                col = re.match(r"[A-Z]+", c.get("r") or "A")
                ci = 0
                for ch in (col.group(0) if col else "A"):
                    ci = ci * 26 + ord(ch) - 64
                v = c.find(S + "v")
                ty = c.get("t")
                if ty == "s" and v is not None and (v.text or "").isdigit() and int(v.text) < len(sst):
                    val = sst[int(v.text)]
                elif ty == "inlineStr":
                    val = "".join(t.text or "" for t in c.iter(S + "t"))
                elif ty == "b":
                    val = "TRUE" if v is not None and v.text == "1" else "FALSE"
                else:
                    val = (v.text or "") if v is not None else ""
                cells[ci] = val
            if cells:
                rows.append([cells.get(i, "") for i in range(1, max(cells) + 1)])
        t = _table(rows, md)
        if t:
            out.append(f"## {sh.get('name') or 'Sheet'}\n\n{t}")
    return "\n\n".join(out)


def _pptx(data, md):
    z = _zip(data, ".pptx")
    A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"

    def num(n):
        m = re.search(r"(\d+)\.xml$", n)
        return int(m.group(1)) if m else 0

    def text_of(root):
        return "\n".join(s for s in ("".join(t.text or "" for t in p.iter(A + "t")).strip() for p in root.iter(A + "p")) if s)

    slides = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)), key=num)
    if not slides:
        raise ParseError("not a valid .pptx file (no slides found)")
    out = []
    for n in slides:
        body = text_of(_xml(z, n))
        notes = z.namelist().count(f"ppt/notesSlides/notesSlide{num(n)}.xml") and text_of(_xml(z, f"ppt/notesSlides/notesSlide{num(n)}.xml"))
        blk = f"## Slide {num(n)}\n\n{body}" + (f"\n\nSpeaker notes: {notes}" if notes else "")
        out.append(blk)
    return "\n\n".join(out)


def _csv(txt, delim, md):
    import csv
    rows = list(csv.reader(io.StringIO(txt), delimiter=delim))
    return _table(rows, md)


def _html(txt):
    import html as _h
    txt = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", txt)
    txt = re.sub(r"(?is)<!--.*?-->", " ", txt)
    txt = re.sub(r"(?is)<h([1-6])[^>]*>(.*?)</h\1>", lambda m: "\n\n" + "#" * int(m.group(1)) + " " + re.sub(r"<[^>]+>", "", m.group(2)) + "\n\n", txt)
    txt = re.sub(r"(?i)</?(p|div|br|li|tr|table|ul|ol|section|article|pre|blockquote)[^>]*>", "\n\n", txt)
    txt = re.sub(r"(?i)</t[dh]>", " | ", txt)
    txt = _h.unescape(re.sub(r"<[^>]+>", " ", txt))
    return re.sub(r"[ \t]+", " ", re.sub(r"\n[ \t]*", "\n", txt))


def parse_document(key: str, data: bytes, markdown_tables: bool = False) -> str:
    """Document bytes -> text. ``markdown_tables`` = parsingStrategy BEDROCK_FOUNDATION_MODEL (tables keep their structure as
    markdown); default parsing flattens table rows into 'header: value' text. Raises ParseError with the failure reason."""
    k = key.lower()
    ext = k[k.rfind("."):] if "." in k else ""
    if len(data) > MAX_DOC_BYTES:
        raise ParseError(f"file is {len(data) // 1048576} MB, over the 50 MB per-file limit")
    if ext in _LEGACY:
        raise ParseError(f"legacy binary {_LEGACY[ext]} is not supported (save as .docx/.xlsx/.pptx)")
    if ext == ".docx":
        txt = _docx(data, markdown_tables)
    elif ext == ".xlsx":
        txt = _xlsx(data, markdown_tables)
    elif ext == ".pptx":
        txt = _pptx(data, markdown_tables)
    elif ext == ".pdf":
        try:
            import pypdf  # type: ignore
        except ImportError:
            raise ParseError("PDF parsing needs the pure-Python 'pypdf' package (not installed on this substrate)")
        try:
            rd = pypdf.PdfReader(io.BytesIO(data))
            if rd.is_encrypted and not rd.decrypt(""):
                raise ParseError("PDF is password-protected")
            pages = [(p.extract_text() or "").strip() for p in rd.pages]
        except ParseError:
            raise
        except Exception as e:  # noqa: BLE001
            raise ParseError(f"unreadable PDF: {e}")
        if not any(pages):
            raise ParseError("PDF has no extractable text (scanned/image-only PDF; OCR is not available)")
        txt = "\n\n".join(pages)
    elif ext in TEXT_EXT:
        try:
            txt = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ParseError("not valid UTF-8 text")
        if ext in (".html", ".htm"):
            txt = _html(txt)
        elif ext in (".csv", ".tsv"):
            txt = _csv(txt, "\t" if ext == ".tsv" else ",", markdown_tables)
    else:
        raise ParseError(f"unsupported document type {ext or '(no extension)'}")
    txt = txt.strip()
    if not txt:
        raise ParseError("document has no extractable text")
    return txt


_HEAD = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])|\n+")


def _semantic(text: str, max_tokens: int, buffer_size: int = 1, pct: int = 95):
    """Embedding-based semantic chunking (what Bedrock does): split into sentences, embed each sentence merged with its
    ``buffer_size`` neighbours, cut where the cosine distance between consecutive groups exceeds the ``pct`` percentile of all
    distances, then window any chunk over ``max_tokens``. Same embedding seam as retrieval."""
    sents = [s.strip() for s in _SENT.split(text) if s and s.strip()]
    if len(sents) < 3:
        return [(text, "")]
    if len(sents) > 3000:                      # embedding every sentence of a huge doc is O(n) model calls: use the paragraph packer
        return None
    groups = [" ".join(sents[max(0, i - buffer_size):i + buffer_size + 1]) for i in range(len(sents))]
    vecs = llm.embed(groups)["vectors"]
    dist = [1.0 - llm.cosine(vecs[i], vecs[i + 1]) for i in range(len(vecs) - 1)]
    srt = sorted(dist)
    thr = srt[min(len(srt) - 1, int(len(srt) * max(0, min(pct, 100)) / 100))]
    out, cur, head = [], [sents[0]], ""
    for i, d in enumerate(dist):
        if d > thr:
            out.append(" ".join(cur))
            cur = []
        cur.append(sents[i + 1])
    out.append(" ".join(cur))
    res = []
    for c in out:
        res.extend(split_text(c, max_tokens, 0, "FIXED_SIZE") if len(c.split()) > max_tokens else [(c, "")])
    return res


def chunk_document(text: str, cfg: dict):
    """Chunk one parsed document per the data source chunkingConfiguration (``cfg`` from ``chunk_config``).
    -> [{"text", "section", "parent"?}]. HIERARCHICAL returns child chunks that carry their parent chunk's text (retrieval returns
    the parent, as Bedrock does); SEMANTIC is embedding-breakpoint based; FIXED_SIZE a sliding window; NONE one chunk per file."""
    strat = cfg["strategy"]
    if strat == "NONE":
        t = text.strip()
        return [{"text": t, "section": ""}] if t else []
    if strat == "HIERARCHICAL":
        out = []
        for ptxt, head in split_text(text, cfg["parent_tokens"], 0, "SEMANTIC_PACK"):
            kids = split_text(ptxt, cfg["max_tokens"], int(100 * cfg["overlap_tokens"] / max(cfg["max_tokens"], 1)), "FIXED_SIZE")
            for ktxt, _ in kids:
                out.append({"text": ktxt, "section": head, "parent": ptxt})
        return out
    if strat == "SEMANTIC":
        res = _semantic(text, cfg["max_tokens"], cfg.get("buffer_size", 1), cfg.get("breakpoint_pct", 95))
        if res is None:
            res = split_text(text, cfg["max_tokens"], 0, "SEMANTIC_PACK")
        return [{"text": c, "section": h} for c, h in res]
    return [{"text": c, "section": h} for c, h in split_text(text, cfg["max_tokens"], cfg["overlap_pct"], "FIXED_SIZE")]


def chunk_config(vic: dict) -> dict:
    """vectorIngestionConfiguration -> normalised chunk config. Raises ValueError (-> ValidationException) on a bad config."""
    c = (vic or {}).get("chunkingConfiguration") or {}
    strat = c.get("chunkingStrategy", "FIXED_SIZE")
    if strat not in ("FIXED_SIZE", "NONE", "HIERARCHICAL", "SEMANTIC"):
        raise ValueError(f"chunkingStrategy must be one of FIXED_SIZE, NONE, HIERARCHICAL, SEMANTIC (got {strat})")
    cfg = {"strategy": strat, "max_tokens": 300, "overlap_pct": 20}
    if strat == "FIXED_SIZE":
        f = c.get("fixedSizeChunkingConfiguration") or {}
        cfg["max_tokens"], cfg["overlap_pct"] = int(f.get("maxTokens", 300)), int(f.get("overlapPercentage", 20))
        if cfg["max_tokens"] < 1 or not 0 <= cfg["overlap_pct"] <= 99:
            raise ValueError("fixedSizeChunkingConfiguration: maxTokens must be >= 1 and overlapPercentage 0-99")
    elif strat == "HIERARCHICAL":
        h = c.get("hierarchicalChunkingConfiguration") or {}
        lv = h.get("levelConfigurations")
        if not isinstance(lv, list) or len(lv) != 2:
            raise ValueError("hierarchicalChunkingConfiguration.levelConfigurations must contain exactly two levels (parent, child)")
        cfg["parent_tokens"], cfg["max_tokens"] = int(lv[0].get("maxTokens", 1500)), int(lv[1].get("maxTokens", 300))
        cfg["overlap_tokens"] = int(h.get("overlapTokens", 60))
        if cfg["parent_tokens"] <= cfg["max_tokens"]:
            raise ValueError("hierarchical parent maxTokens must be larger than the child maxTokens")
        if cfg["overlap_tokens"] >= cfg["max_tokens"]:
            raise ValueError("hierarchical overlapTokens must be smaller than the child maxTokens")
    elif strat == "SEMANTIC":
        s = c.get("semanticChunkingConfiguration") or {}
        cfg["max_tokens"] = int(s.get("maxTokens", 300))
        cfg["buffer_size"] = int(s.get("bufferSize", 0))
        cfg["breakpoint_pct"] = int(s.get("breakpointPercentileThreshold", 95))
        if not 0 <= cfg["buffer_size"] <= 1 or not 50 <= cfg["breakpoint_pct"] <= 99:
            raise ValueError("semanticChunkingConfiguration: bufferSize must be 0-1 and breakpointPercentileThreshold 50-99")
    return cfg


def parsing_config(vic: dict) -> dict:
    """vectorIngestionConfiguration.parsingConfiguration -> {"markdown_tables": bool, "strategy": str}. BEDROCK_DATA_AUTOMATION needs a
    managed service this simulator does not have: ValueError (-> ValidationException) rather than silently ignoring it."""
    pc = (vic or {}).get("parsingConfiguration") or {}
    st = pc.get("parsingStrategy")
    if not pc:
        return {"markdown_tables": False, "strategy": "DEFAULT"}
    if st == "BEDROCK_FOUNDATION_MODEL":
        if not ((pc.get("bedrockFoundationModelConfiguration") or {}).get("modelArn")):
            raise ValueError("parsingConfiguration.bedrockFoundationModelConfiguration.modelArn is required for BEDROCK_FOUNDATION_MODEL parsing")
        return {"markdown_tables": True, "strategy": st}
    if st == "BEDROCK_DATA_AUTOMATION":
        raise ValueError("parsingStrategy BEDROCK_DATA_AUTOMATION is not available (needs Amazon Bedrock Data Automation); use BEDROCK_FOUNDATION_MODEL or omit parsingConfiguration")
    raise ValueError("parsingConfiguration.parsingStrategy must be BEDROCK_FOUNDATION_MODEL or BEDROCK_DATA_AUTOMATION")


def split_text(text: str, max_tokens: int | None = 300, overlap_pct: int = 20, strategy: str = "FIXED_SIZE"):
    """-> [(chunk_text, section_heading)]. FIXED_SIZE = sliding word window; SEMANTIC_PACK (also any other value) = paragraph+heading-aware packing."""
    text = (text or "").strip()
    if not text:
        return []
    if max_tokens is None or strategy == "NONE":
        return [(text, "")]
    if strategy == "FIXED_SIZE":
        words = text.split()
        step = max(1, max_tokens - int(max_tokens * overlap_pct / 100))
        out, i = [], 0
        while i < len(words):
            out.append((" ".join(words[i:i + max_tokens]), ""))
            if i + max_tokens >= len(words):
                break
            i += step
        return out
    out, head, buf, n = [], "", [], 0
    def flush():
        nonlocal buf, n
        if buf:
            out.append(("\n\n".join(buf), head))
        buf, n = [], 0
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        m = _HEAD.match(para.splitlines()[0])
        if m:
            flush()
            head = m.group(1).strip()
        w = len(para.split())
        if w > max_tokens:                                # oversize paragraph: window it
            flush()
            out.extend((c, head) for c, _ in split_text(para, max_tokens, overlap_pct, "FIXED_SIZE"))
            continue
        if n + w > max_tokens:
            flush()
        buf.append(para)
        n += w
    flush()
    return out


# ═════════════════════════ PII guard (Bedrock Guardrails engine) ═════════════════════════
def guard(text: str, guardrail_id: str | None, version: str = "DRAFT"):
    """-> (text_out, verdict) with verdict in ok | redacted | blocked. No guardrail id -> ok."""
    if not guardrail_id:
        return text, "ok"
    try:
        from core import bedrock_guardrails_core as g
    except ImportError:
        import bedrock_guardrails_core as g  # type: ignore
    try:
        r = g.evaluate(g.resolve_policy(guardrail_id, version), text, "INPUT")
    except Exception:  # noqa: BLE001 - unknown guardrail: do not silently ingest unscanned content
        return text, "blocked"
    if r["blocked"]:
        return text, "blocked"
    return (r["text"], "redacted") if r["action"] != "NONE" else (text, "ok")
