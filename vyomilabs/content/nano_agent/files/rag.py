"""Knowledge: split the handbook into passages, embed them once, and find the passages that answer a question.

Search blends two signals. Keywords catch exact terms (an id, "PRV", "90 days"); embeddings catch the same meaning in different words ("trapped"
vs "stuck"). The blended score is also the evidence test: below SUPPORT_MIN nothing in the handbook answers the question, and the agent must refuse."""
import json
import math
import re

from botocore.exceptions import ClientError

from aws import rt, s3
from data import BUCKET
from llmx import EMBED_MODEL

INDEX_KEY = "index/passages.json"
SUPPORT_MIN = 0.38         # blended score below this = "the documents do not support an answer" (measured in chapter 5)
W_DENSE, W_KEY = 0.5, 0.5
STOP = set("the a an of to in is are was be for and or on at by with what how do does did when must should can i we you it that this as from my our your if there any".split())


def tokens(text):
    out = []
    for w in re.findall(r"[a-z0-9][a-z0-9\-]*", text.lower()):
        if w in STOP:
            continue
        for suf in ("ing", "es", "s"):
            if len(w) > 4 and w.endswith(suf):
                w = w[: -len(suf)]
                break
        out.append(w)
    return out


def chunk(name, text, max_chars=320):
    """One passage per sentence group, each carrying its document title so a passage still makes sense alone."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    title = lines[0].lstrip("# ").strip()
    out = []
    for line in lines[1:]:
        parts, cur = [], ""
        for sent in re.split(r"(?<=[.!?])\s+", line):
            if cur and len(cur) + len(sent) > max_chars:
                parts.append(cur)
                cur = ""
            cur = (cur + " " + sent).strip()
        if cur:
            parts.append(cur)
        for p in parts:
            out.append({"id": "%s#%d" % (name, len(out) + 1), "doc": name, "title": title, "text": p})
    return out


def embed(text):
    r = rt.invoke_model(modelId=EMBED_MODEL, body=json.dumps({"inputText": text}))
    return json.loads(r["body"].read())["embedding"]


def build_index(docs):
    """docs = {name: text}. Embeds every passage and stores the index in S3 next to the documents."""
    chunks = []
    for name, text in sorted(docs.items()):
        chunks += chunk(name, text)
    for c in chunks:
        c["vec"] = [round(x, 5) for x in embed(c["title"] + ". " + c["text"])]
    s3.put_object(Bucket=BUCKET, Key=INDEX_KEY, Body=json.dumps(chunks).encode())
    _cache["chunks"] = chunks
    return chunks


_cache = {}


def load_index():
    if "chunks" not in _cache:
        _cache["chunks"] = json.loads(s3.get_object(Bucket=BUCKET, Key=INDEX_KEY)["Body"].read())
    return _cache["chunks"]


def ensure_index(docs):
    """The index if it exists, otherwise build it (so a chapter can be run on its own)."""
    try:
        return load_index()
    except ClientError:
        return build_index(docs)


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def key_score(q_tokens, c):
    """Share of the question's terms found in the passage (title included)."""
    have = set(tokens(c["title"] + " " + c["text"]))
    return sum(1 for t in q_tokens if t in have) / len(q_tokens) if q_tokens else 0.0


def search(query, chunks=None, k=3, mode="hybrid"):
    chunks = chunks or load_index()
    qt = tokens(query)
    qv = embed(query) if mode != "keyword" else None
    scored = []
    for c in chunks:
        ks = key_score(qt, c)
        ds = max(0.0, cosine(qv, c["vec"])) if qv else 0.0
        s = ks if mode == "keyword" else ds if mode == "dense" else W_KEY * ks + W_DENSE * ds
        scored.append((round(s, 3), c))
    scored.sort(key=lambda p: -p[0])
    return [{"score": s, "doc": c["doc"], "id": c["id"], "text": c["text"]} for s, c in scored[:k]]
