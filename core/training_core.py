"""Vyomi training engine (T1): REAL training of small heads on frozen text embeddings, behind the cloud model-customization APIs.

One job runner shared by Bedrock CreateModelCustomizationJob, Vertex tuningJobs and Azure OpenAI fine_tuning/jobs. Cloud cores stay thin
adapters: they validate their own wire shape, call ``start`` and mirror ``view(job_id)`` into their own job record (key ``vyomiTraining``).

Trainable base model = the embedder (``all-minilm-l6-v2`` on Nano, ``nomic-embed-text`` offline/Mesh) or any id with the ``vyomi.head.``
prefix. Everything else is NOT trainable here and keeps the clouds' metadata-only behaviour (they must say so).

Task heads (all trained with Adam, mini-batch, seeded; held-out 20 % split; baseline recorded):
  classifier  softmax logistic  emb -> K             rows {"text","label"}
  router      MLP               emb -> 64 -> K       rows {"text","label"} (hyperParameters taskType=router)
  reranker    pairwise logistic [q*d, |q-d|] -> 1    rows {"query","positive","negative"}

Two runners, one artifact format (head.json, float32 base64, identical to the Nano worker so either substrate can serve either head):
  * offline / Mesh ("head-py"): a background thread; embeddings via core/llm_core.embed (nomic-embed-text through llama.cpp, or the
    labelled ``vyomi-hash-embed`` fallback when no model is up); pure-Python Adam (no numpy dependency).
  * Nano ("nano-head-js"): ``set_bridge`` registers the page's JS worker (wasm/nano-train.js): it embeds through the page's MiniLM
    (``vyomiEmbed``), trains in a Web Worker with typed arrays, and posts events back through ``on_event``.
Invocation (``invoke``) is always Python: embed (llm_core seam, async-replayed on Nano) then a tiny forward pass.

Honest limits: a head separates only what the frozen embedder separates (no new knowledge/language); this is not an LLM fine-tune; the
accuracy is the held-out split of YOUR rows, not a quality promise. Caps: 2000 rows, 5 MB, 20 labels.
"""
from __future__ import annotations

import array
import contextvars
import base64
import json
import math
import os
import random
import re
import threading
import time
from operator import mul

try:
    from core import llm_core as llm
except ImportError:  # Pyodide flat layout
    import llm_core as llm  # type: ignore

MAX_ROWS, MAX_BYTES, MAX_LABELS, MIN_ROWS = 2000, 5 * 1024 * 1024, 20, 10
TRAINABLE_EMBEDDERS = ("all-minilm-l6-v2", "nomic-embed-text")
HEAD_PREFIX = "vyomi.head."
MODELS_BUCKET = "vyomi-models"
ACTIVE = ("Queued", "Embedding", "Training", "Evaluating")
_PUBLIC = ("engine", "taskType", "status", "progress", "epoch", "epochs", "metrics", "heldOut", "rows", "artifact", "startedAt", "endedAt", "note",
           "steps", "adapterId", "baseModel")


class TrainError(Exception):
    """Validation / precondition failure; ``kind`` is validation | notfound | conflict | unavailable (adapters map it to their cloud's error)."""

    def __init__(self, msg, kind="validation"):
        super().__init__(msg)
        self.kind = kind


_JOBS: dict[str, dict] = {}
_HEADS: dict[str, dict] = {}        # model id -> head doc (cache; the object store is the source of truth)
_FILES: dict[str, bytes] = {}       # uploaded training files (Azure /openai/files), mirrored to the object store
_ST = {"bridge": None, "cancel": None, "s3": None, "gcs": None}
_STORE_OF: dict[str, object] = {}   # model id -> the object store that holds its head (each cloud space has its own store)


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def is_trainable(base_id: str) -> bool:
    b = re.sub(r"^arn:.*foundation-model/", "", str(base_id or "")).strip().lower()
    b = re.sub(r"^(us|eu|apac)\.", "", b)
    return b in TRAINABLE_EMBEDDERS or b.startswith(HEAD_PREFIX) or chat_base(base_id) is not None


def bind_s3(store):
    """The shared simulated object store (the AWS wire router binds it; heads and uploaded files live there)."""
    if store is not None:
        _ST["s3"] = store


def bind_gcs(store):
    """The simulated GCS store (gs:// URIs read from it first; falls back to the S3 store, as before)."""
    if store is not None:
        _ST["gcs"] = store


def set_bridge(start_fn=None, cancel_fn=None):
    """Nano: ``start_fn(job_id, spec_json)`` hands the job to the page's JS worker; ``cancel_fn(job_id)`` stops it."""
    _ST["bridge"], _ST["cancel"] = start_fn, cancel_fn


# ───────────── object store ─────────────
def _s3():
    try:
        from core import s3_object_core as m
    except ImportError:
        import s3_object_core as m  # type: ignore
    return m


def store_put(bucket, key, data: bytes, ctype="application/json", st=None):
    st = st or _ST["s3"]
    if st is None:
        return False
    m = _s3()
    if not st.bucket_exists(bucket):
        st.create_bucket(bucket)
    r = m.put_object(st, bucket, key, data, {"content-type": ctype})
    return r.status in (200, 201)


def store_get(bucket, key, st=None):
    st = st or _ST["s3"]
    if st is None:
        return None
    try:
        r = _s3().get_object(st, bucket, key, {}, {})
    except Exception:  # noqa: BLE001
        return None
    return r.body if r.status == 200 else None


def split_uri(uri):
    m = re.match(r"^(?:s3|gs)://([^/]+)/(.+)$", uri or "")
    if not m:
        raise TrainError("The training data location must be an object URI of the form s3://bucket/key or gs://bucket/key.")
    return m.group(1), m.group(2)


def _gcs_get(st, bucket, key):
    """Object bytes from the simulated GCS store through its own JSON-API dispatcher (the GCS core keeps objects in its own layout, so the S3 reader cannot see them)."""
    try:
        try:
            from core import gcp_storage_core as g
        except ImportError:
            import gcp_storage_core as g  # type: ignore
        from urllib.parse import quote
        if not st.bucket_exists(bucket):
            return None
        r = g.dispatch(st, "GET", "/storage/v1/b/%s/o/%s" % (bucket, quote(key, safe="")), {"alt": "media"}, {}, b"")
        return r.body if r.status == 200 else None
    except Exception:  # noqa: BLE001
        return store_get(bucket, key, st)


def read_uri(uri) -> bytes:
    b, k = split_uri(uri)
    data = None
    if uri.startswith("gs://"):
        try:
            from core import gcp_gcs_store as g
            if g.available():
                data = g.download(b, k)[0]
        except Exception:  # noqa: BLE001
            data = None
    if data is None and uri.startswith("gs://") and _ST["gcs"] is not None:
        data = _gcs_get(_ST["gcs"], b, k)
    if data is None:
        data = store_get(b, k)
    if data is None:
        raise TrainError(f"Could not read the training data at {uri}: object or bucket not found.", "notfound")
    return data


def put_file(file_id, data: bytes):
    _FILES[file_id] = data
    store_put(MODELS_BUCKET, f"files/{file_id}", data, "application/jsonl")


def get_file(file_id):
    return _FILES.get(file_id) or store_get(MODELS_BUCKET, f"files/{file_id}")


# ───────────── data ─────────────
def parse_rows(data: bytes, hp: dict | None = None):
    """-> (task, rows, labels). Enforces the contract caps; raises TrainError (adapters turn it into their cloud's validation error)."""
    hp = hp or {}
    if len(data) > MAX_BYTES:
        raise TrainError(f"Training data is {len(data)} bytes; the limit is {MAX_BYTES} bytes (5 MB).")
    rows = []
    for i, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            raise TrainError(f"Training data line {i} is not valid JSON.")
        if not isinstance(r, dict):
            raise TrainError(f"Training data line {i} must be a JSON object.")
        rows.append(r)
        if len(rows) > MAX_ROWS:
            raise TrainError(f"Training data has more than {MAX_ROWS} rows; the limit is {MAX_ROWS}.")
    if len(rows) < MIN_ROWS:
        raise TrainError(f"Training data has {len(rows)} rows; at least {MIN_ROWS} are required.")
    if all("query" in r and "positive" in r and "negative" in r for r in rows):
        task = "reranker"
        for i, r in enumerate(rows, 1):
            if not all(isinstance(r[k], str) and r[k].strip() for k in ("query", "positive", "negative")):
                raise TrainError(f"Row {i}: query, positive and negative must be non-empty strings.")
        return task, rows, []
    if all("text" in r and "label" in r for r in rows):
        for i, r in enumerate(rows, 1):
            if not isinstance(r["text"], str) or not r["text"].strip() or not isinstance(r["label"], (str, int)) or str(r["label"]) == "":
                raise TrainError(f"Row {i}: text must be a non-empty string and label a string.")
            r["label"] = str(r["label"])
        labels = sorted({r["label"] for r in rows})
        if len(labels) > MAX_LABELS:
            raise TrainError(f"Training data has {len(labels)} distinct labels; the limit is {MAX_LABELS}.")
        if len(labels) < 2:
            raise TrainError("Training data needs at least 2 distinct labels.")
        t = str(hp.get("taskType") or hp.get("task_type") or "classifier").lower()
        return ("router" if t == "router" else "classifier"), rows, labels
    raise TrainError('Each row must be {"text","label"} (classifier/router) or {"query","positive","negative"} (reranker).')


def _hp(hp):
    def num(k, d, lo, hi, cast=float):
        try:
            v = cast(hp.get(k, d))
        except (TypeError, ValueError):
            raise TrainError(f"Hyperparameter {k} must be a number.")
        if not lo <= v <= hi:
            raise TrainError(f"Hyperparameter {k} must be between {lo} and {hi}.")
        return v
    hp = {str(k): v for k, v in (hp or {}).items()}
    ep = hp.get("epochCount", hp.get("n_epochs", hp.get("epochs")))
    if ep is not None:
        hp["epochs"] = ep
    lr = hp.get("learningRate", hp.get("learning_rate"))
    if lr is not None:
        hp["lr"] = lr
    mult = hp.get("learningRateMultiplier", hp.get("learning_rate_multiplier"))
    if mult is not None:
        hp["learningRateMultiplier"] = mult
    if hp.get("batchSize", hp.get("batch_size")) is not None:
        hp["bs"] = hp.get("batchSize", hp.get("batch_size"))
    return {"epochs": num("epochs", 10, 1, 50, int), "lr": num("lr", 0.0, 0.0, 1.0), "bs": num("bs", 32, 1, 256, int)} | \
        {"mult": num("learningRateMultiplier", 1.0, 0.01, 10.0) if mult is not None else 1.0}


# ───────────── plain Adam heads (pure Python; same artifact as the Nano worker) ─────────────
def _dot(a, b):
    return sum(map(mul, a, b))


class Net:
    """Dense net; W[l][j] is the weight COLUMN j of layer l (len din). Serialised row-major (din x dout) like the JS worker."""

    def __init__(self, dims, out_act, seed=1):
        r = random.Random(seed)
        self.dims, self.out_act, self.t = list(dims), out_act, 0
        self.W, self.b = [], []
        for l in range(len(dims) - 1):
            sc = math.sqrt(2 / dims[l]) * (0.5 if l == len(dims) - 2 else 1)
            self.W.append([[r.gauss(0, 1) * sc for _ in range(dims[l])] for _ in range(dims[l + 1])])
            self.b.append([0.0] * dims[l + 1])
        self.m = [[[0.0] * len(c) for c in w] for w in self.W] + [[[0.0] * len(b)] for b in self.b]
        self.v = [[[0.0] * len(c) for c in w] for w in self.W] + [[[0.0] * len(b)] for b in self.b]

    def forward(self, x):
        acts, a, L = [x], x, len(self.W)
        for l in range(L):
            z = [_dot(a, w) + bb for w, bb in zip(self.W[l], self.b[l])]
            if l < L - 1:
                z = [v if v > 0 else 0.0 for v in z]
            elif self.out_act == "softmax":
                mx = max(z)
                e = [math.exp(v - mx) for v in z]
                s = sum(e)
                z = [v / s for v in e]
            else:
                z = [1 / (1 + math.exp(-max(-30.0, min(30.0, v)))) for v in z]
            acts.append(z)
            a = z
        return acts

    def predict(self, x):
        return self.forward(x)[-1]

    def _grad(self, x, y, gW, gb):
        acts = self.forward(x)
        out = acts[-1]
        if self.out_act == "softmax":
            dz = [o - (1.0 if j == y else 0.0) for j, o in enumerate(out)]
            loss = -math.log(out[y] + 1e-9)
        else:
            dz = [out[0] - y]
            loss = -(y * math.log(out[0] + 1e-9) + (1 - y) * math.log(1 - out[0] + 1e-9))
        for l in range(len(self.W) - 1, -1, -1):
            a = acts[l]
            for j, d in enumerate(dz):
                gb[l][j] += d
                gW[l][j] = [g + d * v for g, v in zip(gW[l][j], a)]
            if l > 0:
                nd = [0.0] * len(a)
                for j, d in enumerate(dz):
                    if d:
                        nd = [n + d * w for n, w in zip(nd, self.W[l][j])]
                dz = [n if v > 0 else 0.0 for n, v in zip(nd, a)]
        return loss, (max(range(len(out)), key=out.__getitem__) == y) if self.out_act == "softmax" else ((out[0] >= 0.5) == (y == 1))

    def step(self, X, Y, lr):
        gW = [[[0.0] * len(c) for c in w] for w in self.W]
        gb = [[0.0] * len(b) for b in self.b]
        loss = ok = 0
        for x, y in zip(X, Y):
            ls, c = self._grad(x, y, gW, gb)
            loss += ls
            ok += 1 if c else 0
        n = len(X)
        self.t += 1
        b1, b2 = 0.9, 0.999
        c1, c2 = 1 - b1 ** self.t, 1 - b2 ** self.t
        nl = len(self.W)

        def upd(p, g, m, v):
            for i in range(len(p)):
                gi = g[i] / n
                m[i] = b1 * m[i] + (1 - b1) * gi
                v[i] = b2 * v[i] + (1 - b2) * gi * gi
                p[i] -= lr * (m[i] / c1) / (math.sqrt(v[i] / c2) + 1e-8)
        for l in range(nl):
            for j in range(len(self.W[l])):
                upd(self.W[l][j], gW[l][j], self.m[l][j], self.v[l][j])
            upd(self.b[l], gb[l], self.m[nl + l][0], self.v[nl + l][0])
        return loss / n, ok / n

    def to_json(self):
        def f32(vals):
            return base64.b64encode(array.array("f", vals).tobytes()).decode()
        W = []
        for l, cols in enumerate(self.W):
            din, dout = self.dims[l], self.dims[l + 1]
            W.append(f32([cols[j][i] for i in range(din) for j in range(dout)]))
        return {"dims": self.dims, "outAct": self.out_act, "W": W, "b": [f32(b) for b in self.b]}

    @classmethod
    def from_json(cls, j):
        n = cls.__new__(cls)
        n.dims, n.out_act, n.t = list(j["dims"]), j["outAct"], 0
        n.W, n.b = [], []
        for l, s in enumerate(j["W"]):
            a = array.array("f")
            a.frombytes(base64.b64decode(s))
            din, dout = n.dims[l], n.dims[l + 1]
            n.W.append([[a[i * dout + jj] for i in range(din)] for jj in range(dout)])
        for s in j["b"]:
            a = array.array("f")
            a.frombytes(base64.b64decode(s))
            n.b.append(list(a))
        return n


def _pair_feat(q, d):
    return [a * b for a, b in zip(q, d)] + [abs(a - b) for a, b in zip(q, d)]


def _lr_for(task, hp_lr):
    return hp_lr or (0.01 if task == "classifier" else 0.003)


# ───────────── job lifecycle ─────────────
def _view(j):
    return json.loads(json.dumps({k: j.get(k) for k in _PUBLIC if j.get(k) is not None}))


def view(job_id):
    j = _JOBS.get(job_id)
    if j is None:
        raise TrainError(f"Training job {job_id} not found.", "notfound")
    return _view(j)


def active(job_id):
    j = _JOBS.get(job_id)
    return bool(j and j["status"] in ACTIVE)


def start(job_id, model_id, data: bytes, hyper: dict | None, out_uri: str | None = None, base_id: str = "", name: str = "") -> dict:
    """Validate and launch a training job. Raises TrainError on bad base/data/hyperparameters (nothing is created in that case)."""
    if chat_base(base_id) is not None:
        return start_chat(job_id, model_id, data, hyper, out_uri, base_id, name)
    if not is_trainable(base_id):
        raise TrainError(f"{base_id} is not trainable by Vyomi (trainable: {', '.join(TRAINABLE_EMBEDDERS)} or {HEAD_PREFIX}*).")
    hp = _hp(hyper)
    task, rows, labels = parse_rows(data, hyper)
    hp["task"] = task
    j = {"id": job_id, "model_id": model_id, "engine": "nano-head-js" if _ST["bridge"] else "head-py", "taskType": task, "status": "Queued",
         "progress": 0.0, "epoch": 0, "epochs": hp["epochs"], "metrics": [], "heldOut": None, "rows": len(rows), "startedAt": _now(),
         "note": ("Trains a small head on frozen text embeddings; not an LLM fine-tune."), "_cancel": False, "_out": out_uri, "_labels": labels,
         "_hp": hp, "_base": base_id, "_name": name, "_s3": _ST["s3"]}
    _JOBS[job_id] = j
    if _ST["bridge"]:
        spec = {"id": job_id, "task": task, "rows": rows, "labels": labels, "epochs": hp["epochs"], "lr": _lr_for(task, hp["lr"]) * hp["mult"], "bs": hp["bs"], "seed": 7}
        try:
            _ST["bridge"](job_id, json.dumps(spec))
        except Exception as e:  # noqa: BLE001
            _finish(j, "Failed", f"Nano training bridge failed to start: {e}")
        return _view(j)
    try:
        ctx = contextvars.copy_context()      # run in the caller's cloud space so the head lands in (and is read from) that space's object store
        t = threading.Thread(target=ctx.run, args=(_run_py, j, rows, labels, hp), daemon=True, name=f"vyomi-train-{job_id}")
        t.start()
    except RuntimeError:
        _finish(j, "Failed", "This substrate cannot run training: no thread support and no Nano training worker is registered.")
    return _view(j)


def stop(job_id):
    j = _JOBS.get(job_id)
    if j is None:
        raise TrainError(f"Training job {job_id} not found.", "notfound")
    if j["status"] not in ACTIVE:
        raise TrainError(f"Job is in state {j['status']} and cannot be stopped.", "conflict")
    j["_cancel"] = True
    if _ST["bridge"] and _ST["cancel"]:
        try:
            _ST["cancel"](job_id)
        except Exception:  # noqa: BLE001
            pass
    j["status"], j["endedAt"] = "Stopped", _now()
    return _view(j)


def _finish(j, status, note=None):
    if j["status"] == "Stopped" and status != "Stopped":
        return
    j["status"], j["endedAt"] = status, _now()
    if status == "Completed":
        j["progress"] = 1.0
    if note:
        j["note"] = note


def _check(j):
    if j["_cancel"]:
        raise InterruptedError


def _embed_texts(j, texts):
    out, model, backend = {}, None, None
    uniq = list(dict.fromkeys(texts))
    for i in range(0, len(uniq), 64):
        _check(j)
        r = llm.embed(uniq[i:i + 64])
        for t, v in zip(uniq[i:i + 64], r["vectors"]):
            out[t] = v
        model, backend = r["model"], r["backend"]
        j["progress"] = round(0.2 * min(1.0, (i + 64) / len(uniq)), 3)
    return out, model, backend


def _run_py(j, rows, labels, hp):
    try:
        j["status"] = "Embedding"
        task = hp["task"]
        rnd = random.Random(7)
        idx = list(range(len(rows)))
        rnd.shuffle(idx)
        nho = max(2, int(len(rows) * 0.2))
        ho, tr = [rows[i] for i in idx[:nho]], [rows[i] for i in idx[nho:]]
        if task == "reranker":
            texts = [t for r in rows for t in (r["query"], r["positive"], r["negative"])]
        else:
            texts = [r["text"] for r in rows] + (labels if task != "reranker" else [])
        emb, model, backend = _embed_texts(j, texts)
        j["embedder"] = model
        if backend == "vyomi-hash-embed":
            j["note"] += " Trained on the labelled vyomi-hash-embed fallback (no embedding model is running); serve it with the same fallback."
        dim = len(next(iter(emb.values())))
        lr = _lr_for(task, hp["lr"]) * hp["mult"]
        if task == "reranker":
            def mk(rs):
                X, Y = [], []
                for r in rs:
                    X.append(_pair_feat(emb[r["query"]], emb[r["positive"]]))
                    Y.append(1)
                    X.append(_pair_feat(emb[r["query"]], emb[r["negative"]]))
                    Y.append(0)
                return X, Y
            Xtr, Ytr = mk(tr)
            net = Net([2 * dim, 1], "sigmoid", 3)

            def heldacc():
                c = sum(1 for r in ho if net.predict(_pair_feat(emb[r["query"]], emb[r["positive"]]))[0] > net.predict(_pair_feat(emb[r["query"]], emb[r["negative"]]))[0])
                return c / len(ho)
            base_acc = sum(1 for r in ho if _dot(emb[r["query"]], emb[r["positive"]]) > _dot(emb[r["query"]], emb[r["negative"]])) / len(ho)
            base_note = "zero-shot cosine(query, positive) > cosine(query, negative)"
        else:
            li = {l: i for i, l in enumerate(labels)}
            Xtr, Ytr = [emb[r["text"]] for r in tr], [li[r["label"]] for r in tr]
            Xho, Yho = [emb[r["text"]] for r in ho], [li[r["label"]] for r in ho]
            net = Net([dim, 64, len(labels)] if task == "router" else [dim, len(labels)], "softmax", 3)

            def heldacc():
                return sum(1 for x, y in zip(Xho, Yho) if max(range(len(labels)), key=net.predict(x).__getitem__) == y) / len(ho)
            cnt = {}
            for y in Ytr:
                cnt[y] = cnt.get(y, 0) + 1
            maj = max(cnt, key=cnt.get)
            base_acc = sum(1 for y in Yho if y == maj) / len(ho)
            base_note = "majority class"
        j["status"] = "Training"
        order = list(range(len(Xtr)))
        E, bs = hp["epochs"], hp["bs"]
        for e in range(1, E + 1):
            _check(j)
            rnd.shuffle(order)
            tot = acc = nb = 0
            for s in range(0, len(order), bs):
                _check(j)
                b = order[s:s + bs]
                l, a = net.step([Xtr[i] for i in b], [Ytr[i] for i in b], lr)
                tot, acc, nb = tot + l, acc + a, nb + 1
            j["metrics"].append({"epoch": e, "loss": round(tot / nb, 5), "accuracy": round(acc / nb, 4), "valAccuracy": round(heldacc(), 4)})
            j["epoch"], j["progress"] = e, round(0.2 + 0.75 * e / E, 3)
        j["status"] = "Evaluating"
        _check(j)
        j["heldOut"] = {"accuracy": round(heldacc(), 4), "baseline": round(base_acc, 4), "baselineKind": base_note, "n": len(ho)}
        head = {"kind": task, "labels": labels, "embedder": model, "dims": net.to_json(), "metrics": j["metrics"], "heldOut": j["heldOut"],
                "rows": len(rows), "engine": j["engine"], "createdAt": _now()}
        _publish(j, head)
        _finish(j, "Completed")
    except InterruptedError:
        _finish(j, "Stopped")
    except Exception as e:  # noqa: BLE001
        _finish(j, "Failed", f"{e.__class__.__name__}: {e}")


def _publish(j, head):
    """Checkpoint head.json + meta into the simulated object store and register the model for invocation."""
    mid, st = j["model_id"], j.get("_s3")
    blob = json.dumps(head).encode()
    if store_put(MODELS_BUCKET, f"models/{mid}/head.json", blob, st=st):
        store_put(MODELS_BUCKET, f"models/{mid}/meta.json", json.dumps({"modelId": mid, "jobId": j["id"], "task": head["kind"], "embedder": head["embedder"], "name": j.get("_name"),
                                                                         "heldOut": head["heldOut"], "base": j["_base"]}).encode(), st=st)
        j["artifact"] = f"s3://{MODELS_BUCKET}/models/{mid}/head.json"
        _STORE_OF[mid] = st
    out = j.get("_out")
    if out:
        m = re.match(r"^s3://([^/]+)/?(.*)$", out)
        if m:
            store_put(m.group(1), f"{m.group(2).rstrip('/') + '/' if m.group(2) else ''}{mid}/head.json", blob, st=st)
    _HEADS[mid] = head


def on_event(ev_json):
    """Nano: events from the JS worker. {id, status?, epoch?, epochs?, metric?, progress?, heldOut?, head?, embedder?, error?}."""
    ev = json.loads(ev_json) if isinstance(ev_json, str) else ev_json
    j = _JOBS.get(ev.get("id"))
    if j is None or j["status"] in ("Stopped", "Completed", "Failed"):
        return
    if ev.get("embedder"):
        j["embedder"] = ev["embedder"]
    if ev.get("metric"):
        j["metrics"].append(ev["metric"])
        j["epoch"] = ev["metric"]["epoch"]
    if ev.get("progress") is not None:
        j["progress"] = ev["progress"]
    if ev.get("status") in ACTIVE:
        j["status"] = ev["status"]
    if ev.get("error"):
        _finish(j, "Failed", ev["error"])
    elif ev.get("head"):
        head = ev["head"]
        head.update(engine=j["engine"], rows=j["rows"], createdAt=_now())
        j["heldOut"] = head.get("heldOut")
        j["embedder"] = head.get("embedder")
        _publish(j, head)
        _finish(j, "Completed")


# ───────────── models + invocation ─────────────
def load_head(model_id):
    h = _HEADS.get(model_id)
    if h is None:
        raw = store_get(MODELS_BUCKET, f"models/{model_id}/head.json", _STORE_OF.get(model_id))
        if raw:
            h = _HEADS[model_id] = json.loads(raw)
    return h


def delete_model(model_id):
    _HEADS.pop(model_id, None)
    _CHAT.pop(model_id, None)
    st = _STORE_OF.pop(model_id, None) or _ST["s3"]
    if st is not None and st.bucket_exists(MODELS_BUCKET):
        for k in ("head.json", "adapter.gguf", "meta.json"):
            _s3().delete_object(st, MODELS_BUCKET, f"models/{model_id}/{k}", {}, {})


def has_model(model_id):
    return load_head(model_id) is not None or load_chat(model_id) is not None


def persisted_models():
    """meta.json of every head in the object store (cloud cores use it to rebuild their custom-model records after a reload)."""
    st = _ST["s3"]
    if st is None or not st.bucket_exists(MODELS_BUCKET):
        return []
    r = _s3().list_objects_v2(st, MODELS_BUCKET, {"list-type": "2", "prefix": "models/", "max-keys": "1000"})
    out = []
    for k in re.findall(rb"<Key>([^<]+/meta\.json)</Key>", r.body or b""):
        raw = store_get(MODELS_BUCKET, k.decode())
        if raw:
            out.append(json.loads(raw))
    return out


def _forward(head, vec):
    return Net.from_json(head["dims"]).predict(vec)


def invoke(model_id, body: dict) -> dict:
    """Run a trained head: {"task":"classify","text"} -> {label, scores}; {"task":"score","query","document"} -> {score}."""
    h = load_head(model_id)
    if h is None:
        if load_chat(model_id) is not None:
            raise TrainError(f"{model_id} is a chat-model LoRA (task 'chat'), not a classifier head: send messages, not a classify/score body.")
        raise TrainError(f"Trained model {model_id} not found.", "notfound")
    task = (body or {}).get("task") or ("score" if h["kind"] == "reranker" else "classify")
    if (task == "classify") == (h["kind"] == "reranker"):
        raise TrainError(f"This model is a {h['kind']}; task '{task}' does not apply (use {'score' if h['kind'] == 'reranker' else 'classify'}).")
    if task == "classify":
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            raise TrainError("'text' is required.")
        e = llm.embed([text])
    else:
        q, d = body.get("query"), body.get("document")
        if not (isinstance(q, str) and isinstance(d, str) and q.strip() and d.strip()):
            raise TrainError("'query' and 'document' are required.")
        e = llm.embed([q, d])
    if e["model"] != h["embedder"]:
        raise TrainError(f"Embedder mismatch: this head was trained on {h['embedder']} but the running embedder is {e['model']}.", "conflict")
    if task == "classify":
        p = _forward(h, e["vectors"][0])
        sc = {l: round(v, 6) for l, v in zip(h["labels"], p)}
        return {"label": max(sc, key=sc.get), "scores": sc, "vyomiTrained": True, "embedder": h["embedder"]}
    s = _forward(h, _pair_feat(e["vectors"][0], e["vectors"][1]))[0]
    return {"score": round(s, 6), "vyomiTrained": True, "embedder": h["embedder"]}


# ═════════════ chat-model LoRA (engine "lora-peft": offline / Mesh only; trainer/lora_train.py in a container or venv subprocess) ═════════════
# base id (Mesh open-source pool, docker/mesh-runner-llm/models.json) -> HF repo the trainer fine-tunes. ``fits`` = fits a 4 vCPU / 16 GB Codespace.
CHAT_BASES = {
    "smollm2-135m-instruct": {"hf": "HuggingFaceTB/SmolLM2-135M-Instruct", "dtype": "float32", "fits": True},
    "smollm2-360m-instruct": {"hf": "HuggingFaceTB/SmolLM2-360M-Instruct", "dtype": "float32", "fits": True},
    "qwen2.5-0.5b": {"hf": "Qwen/Qwen2.5-0.5B-Instruct", "dtype": "float32", "fits": True},
    "qwen2.5-1.5b": {"hf": "Qwen/Qwen2.5-1.5B-Instruct", "dtype": "float32", "fits": True},
    "qwen2.5-3b": {"hf": "Qwen/Qwen2.5-3B-Instruct", "dtype": "bfloat16", "fits": True},
    "llama3.1-8b": {"hf": "meta-llama/Llama-3.1-8B-Instruct", "fits": False}, "qwen2.5-7b": {"hf": "Qwen/Qwen2.5-7B-Instruct", "fits": False},
    "qwen2.5-coder-7b": {"hf": "Qwen/Qwen2.5-Coder-7B-Instruct", "fits": False}, "mistral-7b": {"hf": "mistralai/Mistral-7B-Instruct-v0.3", "fits": False},
    "gemma2-9b": {"hf": "google/gemma-2-9b-it", "fits": False}, "qwen3-8b": {"hf": "Qwen/Qwen3-8B", "fits": False},
    "deepseek-r1-8b": {"hf": "deepseek-ai/DeepSeek-R1-Distill-Llama-8B", "fits": False}, "qwen3-30b": {"hf": "Qwen/Qwen3-30B-A3B", "fits": False},
}
CHAT_CAPS = {"epochs": (1, 10, 3), "batch": (1, 16, 4), "rank": (1, 64, 8), "seq": (32, 1024, 256)}
_CHAT: dict[str, dict] = {}         # model id -> meta.json of a trained chat adapter (the object store is the source of truth)
TRAINER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "trainer")


def chat_base(base_id):
    """Canonical pool id of a chat base (or None). Accepts the pool id, ``vyomi.<id>`` / ``ollama.<id>`` / ``<id>:<tag>`` forms (NOT vendor ids such as amazon.nova-*: those stay metadata-only)."""
    b = re.sub(r"^arn:.*foundation-model/", "", str(base_id or "")).strip().lower()
    b = re.sub(r"^(us|eu|apac)\.", "", b)
    b = re.sub(r"^(vyomi|ollama)\.", "", b)
    b = re.sub(r"-v\d+(:\d+)?$", "", b)
    if ":" in b:        # ollama tag form: qwen2.5:3b-instruct-q4_K_M -> qwen2.5-3b
        name, tag = b.split(":", 1)
        sz = re.match(r"(\d+(?:\.\d+)?b)", tag)
        b = f"{name}-{sz.group(1)}" if sz else name
    for k in CHAT_BASES:
        if b == k or b == k.replace("-instruct", ""):
            return k
    return None


def parse_chat_rows(data: bytes):
    """-> list of message lists (last turn = assistant). Caps like the head contract: 2000 rows, 5 MB."""
    if len(data) > MAX_BYTES:
        raise TrainError(f"Training data is {len(data)} bytes; the limit is {MAX_BYTES} bytes (5 MB).")
    out = []
    for i, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            raise TrainError(f"Training data line {i} is not valid JSON.")
        if isinstance(r, dict) and isinstance(r.get("messages"), list) and r["messages"]:
            m = r["messages"]
            if not all(isinstance(x, dict) and x.get("role") in ("system", "user", "assistant") and isinstance(x.get("content"), str) and x["content"].strip() for x in m):
                raise TrainError(f"Row {i}: messages need a role (system|user|assistant) and non-empty string content.")
            if m[-1]["role"] != "assistant" or not any(x["role"] == "user" for x in m):
                raise TrainError(f"Row {i}: messages must contain a user turn and end with the assistant turn to learn.")
        elif isinstance(r, dict) and isinstance(r.get("prompt"), str) and isinstance(r.get("completion"), str) and r["prompt"].strip() and r["completion"].strip():
            m = [{"role": "user", "content": r["prompt"]}, {"role": "assistant", "content": r["completion"]}]
        else:
            raise TrainError(f'Row {i}: chat fine-tuning rows must be {{"messages":[...]}} or {{"prompt","completion"}}.')
        out.append(m)
        if len(out) > MAX_ROWS:
            raise TrainError(f"Training data has more than {MAX_ROWS} rows; the limit is {MAX_ROWS}.")
    if len(out) < MIN_ROWS:
        raise TrainError(f"Training data has {len(out)} rows; at least {MIN_ROWS} are required.")
    return out


def _chat_hp(hyper):
    h = {str(k): v for k, v in (hyper or {}).items()}

    def num(names, key, cast=int, lo=None, hi=None, d=None):
        v = next((h[n] for n in names if h.get(n) not in (None, "", "auto")), d)
        try:
            v = cast(v)
        except (TypeError, ValueError):
            raise TrainError(f"Hyperparameter {names[0]} must be a number.")
        if lo is not None and not lo <= v <= hi:
            raise TrainError(f"Hyperparameter {names[0]} must be between {lo} and {hi}.")
        return v
    e, b, r, q = CHAT_CAPS["epochs"], CHAT_CAPS["batch"], CHAT_CAPS["rank"], CHAT_CAPS["seq"]
    out = {"epochs": num(("epochCount", "n_epochs", "epochs"), "epochs", int, e[0], e[1], e[2]), "bs": num(("batchSize", "batch_size"), "bs", int, b[0], b[1], b[2]),
           "rank": num(("loraRank", "lora_rank", "rank"), "rank", int, r[0], r[1], r[2]), "seq": num(("maxSequenceLength", "max_seq_length"), "seq", int, q[0], q[1], q[2]),
           "lr": num(("learningRate", "learning_rate"), "lr", float, 1e-6, 1e-2, 2e-4)}
    out["alpha"] = num(("loraAlpha", "lora_alpha"), "alpha", int, 1, 256, 2 * out["rank"])
    mult = h.get("learningRateMultiplier", h.get("learning_rate_multiplier"))
    if mult not in (None, "", "auto"):
        out["lr"] = min(1e-2, out["lr"] * num(("learningRateMultiplier", "learning_rate_multiplier"), "m", float, 0.01, 10.0, 1.0))
    return out


def trainer_mode():
    """-> ("docker", image) | ("venv", python) | (None, why). VYOMI_TRAINER=docker|venv|auto (default auto: docker image if present, else venv python)."""
    import shutil
    import subprocess
    want = os.environ.get("VYOMI_TRAINER", "auto")
    image = os.environ.get("VYOMI_TRAINER_IMAGE", "vyomi-trainer:lora1")
    py = os.environ.get("VYOMI_TRAINER_PYTHON") or os.path.join(TRAINER_DIR, ".venv", "bin", "python")
    if want in ("docker", "auto") and shutil.which("docker"):
        try:
            if subprocess.run(["docker", "image", "inspect", image], capture_output=True, timeout=20).returncode == 0:
                return "docker", image
        except Exception:  # noqa: BLE001
            pass
        if want == "docker":
            return None, f"trainer image {image} not found (build it: docker build -t {image} trainer/)"
    if want in ("venv", "auto") and os.path.exists(py):
        return "venv", py
    return None, ("no trainer available: build the image (docker build -t vyomi-trainer:lora1 trainer/) or create the venv "
                  f"(python -m venv trainer/.venv && trainer/.venv/bin/pip install -r trainer/requirements.txt; set VYOMI_TRAINER_PYTHON)")


def start_chat(job_id, model_id, data, hyper, out_uri, base_id, name):
    cb = chat_base(base_id)
    spec = CHAT_BASES[cb]
    if _ST["bridge"]:
        raise TrainError("Chat-model LoRA training runs on the Mesh / offline appliance, not in the Nano tab: train there and import the GGUF adapter (see ai-nano-training-scope.md section 10).")
    if not spec["fits"]:
        raise TrainError(f"{cb} is too large to LoRA-train on a 4 vCPU / 16 GB Codespace on CPU (fp32/bf16 training state). Trainable chat bases: "
                         f"{', '.join(k for k, v in CHAT_BASES.items() if v['fits'])}.")
    rows = parse_chat_rows(data)
    hp = _chat_hp(hyper)
    mode, how = trainer_mode()
    if mode is None:
        raise TrainError(how, "unavailable")
    import tempfile
    work = tempfile.mkdtemp(prefix=f"vyomi-lora-{job_id}-")
    with open(os.path.join(work, "train.jsonl"), "w") as f:
        for m in rows:
            f.write(json.dumps({"messages": m}) + "\n")
    j = {"id": job_id, "model_id": model_id, "engine": "lora-peft", "taskType": "chat-lora", "status": "Queued", "progress": 0.0, "epoch": 0, "epochs": hp["epochs"],
         "metrics": [], "steps": [], "heldOut": None, "rows": len(rows), "startedAt": _now(), "baseModel": cb, "adapterId": model_id, "_cancel": False, "_out": out_uri,
         "_hp": hp, "_base": base_id, "_cb": cb, "_name": name, "_s3": _ST["s3"], "_work": work, "_mode": (mode, how), "_proc": None,
         "note": (f"LoRA adapter (rank {hp['rank']}) on the open model {cb} ({spec['hf']}), trained by PEFT on CPU. It is not a vendor model; quality = the held-out check below.")}
    _JOBS[job_id] = j
    try:
        ctx = contextvars.copy_context()
        threading.Thread(target=ctx.run, args=(_run_lora, j), daemon=True, name=f"vyomi-lora-{job_id}").start()
    except RuntimeError:
        _finish(j, "Failed", "This substrate cannot run training: no thread support.")
    return _view(j)


def _trainer_argv(j):
    mode, how = j["_mode"]
    hp, spec, work = j["_hp"], CHAT_BASES[j["_cb"]], j["_work"]
    args = ["--base", spec["hf"], "--data", "{w}/train.jsonl", "--out", "{w}/out", "--epochs", str(hp["epochs"]), "--rank", str(hp["rank"]), "--alpha", str(hp["alpha"]),
            "--lr", str(hp["lr"]), "--max-seq", str(hp["seq"]), "--batch", str(hp["bs"]), "--dtype", spec["dtype"], "--events", "{w}/events.jsonl", "--cancel-file", "{w}/cancel"]
    if mode == "docker":
        name = f"vyomi-trainer-{j['id']}"
        j["_cname"] = name
        cache = os.environ.get("VYOMI_TRAINER_HF_CACHE", "vyomi-trainer-hf")
        return ["docker", "run", "--rm", "--name", name, "--memory", os.environ.get("VYOMI_TRAINER_MEMORY", "12g"), "-v", f"{work}:/work", "-v", f"{cache}:/root/.cache/huggingface",
                how, "python", "/opt/trainer/lora_train.py", *[a.replace("{w}", "/work") for a in args], "--llamacpp", "/opt/llama.cpp"]
    llcpp = os.environ.get("VYOMI_LLAMACPP_DIR", os.path.join(TRAINER_DIR, "llama.cpp"))
    return [how, os.path.join(TRAINER_DIR, "lora_train.py"), *[a.replace("{w}", work) for a in args], "--llamacpp", llcpp]


def _run_lora(j):
    import shutil
    import subprocess
    work = j["_work"]
    try:
        argv = _trainer_argv(j)
        j["status"] = "Embedding"          # loading base weights + tokenising (the shared lifecycle vocabulary)
        p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        j["_proc"] = p
        err_tail, done = [], None
        for line in p.stdout:
            line = line.strip()
            try:
                ev = json.loads(line)
            except ValueError:
                err_tail = (err_tail + [line])[-8:]
                continue
            kind = ev.get("event")
            if kind == "status":
                if ev["status"] in ACTIVE:
                    j["status"] = ev["status"]
                if ev.get("note"):
                    j["trainerNote"] = ev["note"]
            elif kind == "step":
                j["steps"] = (j["steps"] + [{"step": ev["step"], "epoch": ev["epoch"], "loss": ev["loss"]}])[-1000:]
                j["progress"] = round(0.05 + 0.85 * ev["step"] / max(1, ev["steps"]), 3)
            elif kind == "epoch":
                j["metrics"].append({"epoch": ev["epoch"], "loss": ev["loss"], "accuracy": ev["accuracy"], "valLoss": ev["valLoss"]})
                j["epoch"] = ev["epoch"]
            elif kind == "done":
                done = ev
            elif kind == "error":
                err_tail.append(ev.get("error", ""))
            if j["_cancel"]:
                break
        if j["_cancel"]:
            _kill(j)
            _finish(j, "Stopped")
            return
        rc = p.wait()
        if rc != 0 or not done:
            _finish(j, "Failed", "Trainer failed: " + (" | ".join(err_tail)[-500:] or f"exit code {rc}"))
            return
        j["heldOut"], j["status"], j["progress"] = done["heldOut"], "Evaluating", 0.95
        with open(os.path.join(work, "out", "adapter.gguf"), "rb") as f:
            blob = f.read()
        _publish_chat(j, blob, done)
        _finish(j, "Completed")
    except Exception as e:  # noqa: BLE001
        _finish(j, "Failed", f"{e.__class__.__name__}: {e}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _kill(j):
    import subprocess
    try:
        open(os.path.join(j["_work"], "cancel"), "w").close()
    except OSError:
        pass
    if j.get("_cname"):
        subprocess.run(["docker", "kill", j["_cname"]], capture_output=True, timeout=30)
    p = j.get("_proc")
    if p and p.poll() is None:
        p.terminate()
        try:
            p.wait(10)
        except Exception:  # noqa: BLE001
            p.kill()


def _publish_chat(j, blob, done):
    mid, st = j["model_id"], j.get("_s3")
    meta = {"modelId": mid, "jobId": j["id"], "task": "chat-lora", "kind": "chat-lora", "name": j.get("_name"), "base": j["_base"], "baseModelId": j["_cb"],
            "hf": CHAT_BASES[j["_cb"]]["hf"], "rank": done["rank"], "alpha": done["alpha"], "rows": done["rows"], "steps": done["steps"], "heldOut": done["heldOut"],
            "adapterBytes": len(blob), "meanStepS": done["meanStepS"], "peakRssMB": done["peakRssMB"], "createdAt": _now(), "format": "gguf-lora-f16", "engine": "lora-peft"}
    if not store_put(MODELS_BUCKET, f"models/{mid}/adapter.gguf", blob, "application/octet-stream", st=st):
        raise RuntimeError("could not write the adapter to the object store")
    store_put(MODELS_BUCKET, f"models/{mid}/meta.json", json.dumps(meta).encode(), st=st)
    j["artifact"] = f"s3://{MODELS_BUCKET}/models/{mid}/adapter.gguf"
    _STORE_OF[mid], _CHAT[mid] = st, meta
    out = j.get("_out")
    m = re.match(r"^s3://([^/]+)/?(.*)$", out or "")
    if m:
        store_put(m.group(1), f"{m.group(2).rstrip('/') + '/' if m.group(2) else ''}{mid}/adapter.gguf", blob, "application/octet-stream", st=st)


def load_chat(model_id):
    m = _CHAT.get(model_id)
    if m is None:
        raw = store_get(MODELS_BUCKET, f"models/{model_id}/meta.json", _STORE_OF.get(model_id))
        if raw:
            try:
                d = json.loads(raw)
            except ValueError:
                return None
            if d.get("kind") == "chat-lora":
                m = _CHAT[model_id] = d
    return m


def is_chat_model(model_id):
    return load_chat(model_id) is not None


def invoke_chat(model_id, messages, system=None, max_tokens=256, temperature=0.7, stop=None) -> dict:
    """Generate with the custom chat model: the BASE open model on the local llama.cpp server with this adapter applied (``lora`` seam in
    core/llm_core). -> llm chat() dict + vyomiTrained / adapterId / baseModel. Raises llm.LlmUnavailable when no backend / adapter is loaded."""
    m = load_chat(model_id)
    if m is None:
        raise TrainError(f"Trained model {model_id} not found.", "notfound")
    blob = store_get(MODELS_BUCKET, f"models/{model_id}/adapter.gguf", _STORE_OF.get(model_id))
    if blob is None:
        raise TrainError(f"The adapter of {model_id} is missing from the object store.", "notfound")
    try:
        path = llm.lora_prepare(model_id, blob)
    except OSError:
        path = f"{model_id}.gguf"          # no writable adapter dir (read-only substrate): resolution by name still works if the server loaded it
    r = llm.chat(messages, system=system, max_tokens=max_tokens, temperature=temperature, stop=stop, model=m["baseModelId"],
                 lora={"name": model_id, "path": path, "scale": 1.0})
    return dict(r, vyomiTrained=True, adapterId=model_id, baseModel=m["baseModelId"])
