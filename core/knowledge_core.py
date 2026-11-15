"""Knowledge processing + search primitives shared by Bedrock Knowledge Bases and the OpenSearch data plane (C6 + C12).

Substrate-independent (Nano Pyodide + Mesh container), pure Python + stdlib. Nothing here is a search engine of our own:

  * lexical (BM25) ranking  -> SQLite FTS5 ``bm25()`` (stdlib ``sqlite3``; public domain). If the sqlite build has no FTS5 (some
    Pyodide builds) it falls back to a 15-line BM25 so results stay equivalent; ``fts5_available()`` reports which one is live.
  * vector ranking          -> cosine over the vectors from the local-LLM seam (core/llm_core.embed). Exact scan: fine to ~10k chunks.
  * parsing                 -> text formats natively, .docx via zipfile XML, .pdf via the optional pure-Python ``pypdf`` (BSD) when present.
  * PII scan                -> the existing Bedrock Guardrails engine (core/bedrock_guardrails_core.evaluate), same policies as the runtime.
  * rerank                  -> embedding similarity blended with lexical coverage over the same seam (no extra model download).

Honest limits: no cross-encoder model is shipped (a bge-reranker GGUF behind llama.cpp's /v1/rerank is the Mesh upgrade path);
PDF needs pypdf; chunk strategies SEMANTIC/HIERARCHICAL are heading/paragraph-aware packers, not model-driven.
"""
from __future__ import annotations

import io
import math
import re
import sqlite3
import zipfile

try:
    from core import llm_core as llm
except ImportError:  # Pyodide flat layout
    import llm_core as llm  # type: ignore

_TOK = re.compile(r"[A-Za-z0-9_]+")
TEXT_EXT = (".txt", ".md", ".markdown", ".csv", ".json", ".html", ".htm", ".xml", ".log", ".tsv", ".yaml", ".yml", ".rst")
PARSE_EXT = TEXT_EXT + (".docx", ".pdf")


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


def rerank(query: str, texts, top_n: int | None = None):
    """-> [(index, relevance 0..1)] best-first. Embedding similarity (0.7) + query-term coverage (0.3)."""
    if not texts:
        return []
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


def parse_document(key: str, data: bytes) -> str:
    k = key.lower()
    if k.endswith(".docx"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                xml = z.read("word/document.xml").decode("utf-8", "replace")
        except (zipfile.BadZipFile, KeyError):
            raise ParseError("not a valid .docx file")
        xml = re.sub(r"</w:p>", "\n\n", xml)
        return re.sub(r"<[^>]+>", "", xml).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    if k.endswith(".pdf"):
        try:
            import pypdf  # type: ignore
        except ImportError:
            raise ParseError("PDF parsing needs the optional pure-Python 'pypdf' package (not installed)")
        try:
            return "\n\n".join((p.extract_text() or "") for p in pypdf.PdfReader(io.BytesIO(data)).pages)
        except Exception as e:  # noqa: BLE001
            raise ParseError(f"unreadable PDF: {e}")
    if not k.endswith(TEXT_EXT):
        raise ParseError("unsupported document type")
    try:
        txt = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ParseError("not valid UTF-8 text")
    if k.endswith((".html", ".htm")):
        txt = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", txt, flags=re.S | re.I)
        txt = re.sub(r"<[^>]+>", " ", txt)
    return txt


_HEAD = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")


def split_text(text: str, max_tokens: int | None = 300, overlap_pct: int = 20, strategy: str = "FIXED_SIZE"):
    """-> [(chunk_text, section_heading)]. FIXED_SIZE = sliding word window; SEMANTIC/HIERARCHICAL = paragraph+heading-aware packing."""
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
