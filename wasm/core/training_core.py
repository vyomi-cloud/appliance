# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
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
_PUBLIC = ("engine", "taskType", "status", "progress", "epoch", "epochs", "metrics", "heldOut", "rows", "artifact", "startedAt", "endedAt", "note")


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
    return b in TRAINABLE_EMBEDDERS or b.startswith(HEAD_PREFIX)


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
        data = store_get(b, k, _ST["gcs"])
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
    st = _STORE_OF.pop(model_id, None) or _ST["s3"]
    if st is not None and st.bucket_exists(MODELS_BUCKET):
        for k in ("head.json", "meta.json"):
            _s3().delete_object(st, MODELS_BUCKET, f"models/{model_id}/{k}", {}, {})


def has_model(model_id):
    return load_head(model_id) is not None


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
