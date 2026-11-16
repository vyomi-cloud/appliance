# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Vyomi chat-model import (T2): a LoRA adapter GGUF trained elsewhere (Mesh, the user's machine) becomes a servable custom chat model.

Shared by Bedrock Custom Model Import (CreateModelImportJob ...), Vertex Model Registry ``models:upload`` and the Azure custom-model registration
(Vyomi extension). Cloud cores stay thin: they validate their own wire shape, call ``import_from_uri`` and keep their own records.

Artifacts (read from the simulated object store; ``s3://bucket/dir/`` or ``gs://bucket/dir/``):
  adapter.gguf        LoRA adapter in GGUF (llama.cpp ``convert_lora_to_gguf.py``); magic + header are validated; cap 50 MB
  adapter_meta.json   {"base_model": "<id from BASES>", "rank": 8, "alpha": 16, "base_quant": "Q8_0"?}  (rank/alpha must agree with the GGUF)

Base models are the ones Nano can serve with wllama (llama.cpp WASM, CPU): ``BASES``. The base GGUF itself is downloaded by the browser on
first use (Hugging Face, cached in OPFS); it is NOT stored in the simulated object store. Default quant: 135M -> Q8_0 (the adapter was trained on f16
weights; measured 30/30 on the spike task vs 28/30 on Q4_K_M), 360M -> Q4_K_M; ``base_quant`` in adapter_meta.json picks the other.

Serving: Nano only (wllama in the console tab, reached through the llm_core async seam: ``llm_core.set_custom_backend``). Mesh/offline accept
and store imports (same wire, same records) but declare that serving needs the browser; see docs/architecture/v4.0/branches/ai-nanoimport.md.
Honest labelling: every answer is ``vyomiTrained``/``vyomiImported``: a small open model + your LoRA adapter, not a vendor model.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import struct
import time

try:
    from core import training_core as tc
    from core import llm_core as llm
except ImportError:  # Pyodide flat layout
    import training_core as tc  # type: ignore
    import llm_core as llm  # type: ignore

MAX_ADAPTER_BYTES = 50 * 1024 * 1024
MAX_META_BYTES = 64 * 1024
IMPORT_PREFIX = "imports/"            # in tc.MODELS_BUCKET; deliberately NOT under models/ (those are heads and have their own rehydration)
ADAPTER_FILE, META_FILE = "adapter.gguf", "adapter_meta.json"
ID_PREFIX = "vyomi.import."

# Bases Nano can serve through wllama. n_embd is checked against the adapter's lora_a input width, so a 360M adapter cannot be loaded on 135M.
_HF = "https://huggingface.co/bartowski/SmolLM2-{n}-Instruct-GGUF/resolve/main/SmolLM2-{n}-Instruct-{q}.gguf"
BASES = {
    "smollm2-135m-instruct": {"name": "SmolLM2 135M Instruct", "arch": "llama", "n_embd": 576, "default_quant": "Q8_0", "license": "Apache-2.0",
                              "quants": {"Q8_0": {"size": 144811360, "file": "SmolLM2-135M-Instruct-Q8_0.gguf", "url": _HF.format(n="135M", q="Q8_0")},
                                         "Q4_K_M": {"size": 105454432, "file": "SmolLM2-135M-Instruct-Q4_K_M.gguf", "url": _HF.format(n="135M", q="Q4_K_M")}}},
    "smollm2-360m-instruct": {"name": "SmolLM2 360M Instruct", "arch": "llama", "n_embd": 960, "default_quant": "Q4_K_M", "license": "Apache-2.0",
                              "quants": {"Q4_K_M": {"size": 270590880, "file": "SmolLM2-360M-Instruct-Q4_K_M.gguf", "url": _HF.format(n="360M", q="Q4_K_M")},
                                         "Q8_0": {"size": 386405280, "file": "SmolLM2-360M-Instruct-Q8_0.gguf", "url": _HF.format(n="360M", q="Q8_0")}}},
}
_BASE_ALIAS = {"smollm2-135m": "smollm2-135m-instruct", "smollm2-360m": "smollm2-360m-instruct",
               "huggingfacetb/smollm2-135m-instruct": "smollm2-135m-instruct", "huggingfacetb/smollm2-360m-instruct": "smollm2-360m-instruct"}


class ImportErr(Exception):
    """Validation / precondition failure; ``kind`` is validation | notfound | conflict | unavailable (adapters map it to their cloud's error)."""

    def __init__(self, msg, kind="validation"):
        super().__init__(msg)
        self.kind = kind


_REG: dict[str, dict] = {}          # model id -> record (meta + adapter bytes cache lives in _BYTES)
_BYTES: dict[str, bytes] = {}
_STORE_OF: dict[str, object] = {}
_ST = {"loaded": False}


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def canon_base(b):
    b = re.sub(r"^arn:.*foundation-model/", "", str(b or "")).strip().lower()
    return _BASE_ALIAS.get(b, b)


def is_import_id(model):
    return isinstance(model, str) and model.startswith(ID_PREFIX)


# ───────────── GGUF header ─────────────
_SCALAR = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}


class _R:
    def __init__(self, b):
        self.b, self.p = b, 0

    def take(self, n):
        if self.p + n > len(self.b):
            raise ImportErr("The adapter is not a valid GGUF file: it is truncated.")
        v = self.b[self.p:self.p + n]
        self.p += n
        return v

    def u32(self):
        return struct.unpack("<I", self.take(4))[0]

    def u64(self):
        return struct.unpack("<Q", self.take(8))[0]

    def string(self):
        n = self.u64()
        if n > 1 << 20:
            raise ImportErr("The adapter is not a valid GGUF file: oversized string in the header.")
        return self.take(n).decode("utf-8", "replace")

    def value(self, t):
        if t in _SCALAR:
            f = _SCALAR[t]
            return struct.unpack(f, self.take(struct.calcsize(f)))[0]
        if t == 8:
            return self.string()
        if t == 9:
            et, n = self.u32(), self.u64()
            if n > 1 << 22:
                raise ImportErr("The adapter is not a valid GGUF file: oversized array in the header.")
            out = [self.value(et) for _ in range(n)] if et in _SCALAR or et == 8 else None
            if out is None:
                raise ImportErr("The adapter is not a valid GGUF file: unsupported array type in the header.")
            return out if n <= 64 else None
        raise ImportErr("The adapter is not a valid GGUF file: unknown metadata type.")


def parse_gguf_adapter(data: bytes) -> dict:
    """Validate a GGUF LoRA adapter header and return {arch, alpha, rank, n_embd, tensors}. Raises ImportErr with a user-facing reason."""
    if len(data) < 24 or data[:4] != b"GGUF":
        raise ImportErr(f"{ADAPTER_FILE} is not a GGUF file (missing the GGUF magic). Convert the PEFT adapter with llama.cpp convert_lora_to_gguf.py.")
    r = _R(data)
    r.take(4)
    ver = r.u32()
    if ver not in (2, 3):
        raise ImportErr(f"Unsupported GGUF version {ver} (expected 2 or 3).")
    n_t, n_kv = r.u64(), r.u64()
    if n_t == 0 or n_t > 100000 or n_kv > 100000:
        raise ImportErr("The adapter GGUF holds no tensors." if n_t == 0 else "The adapter GGUF header is implausible.")
    kv = {}
    for _ in range(n_kv):
        k = r.string()
        kv[k] = r.value(r.u32())
    if kv.get("general.type") != "adapter" or kv.get("adapter.type") != "lora":
        raise ImportErr(f"{ADAPTER_FILE} is a GGUF file but not a LoRA adapter (general.type={kv.get('general.type')!r}, adapter.type={kv.get('adapter.type')!r}). "
                           "A merged/full model is not an adapter; use llama.cpp convert_lora_to_gguf.py.")
    ranks, embds = set(), set()
    for _ in range(n_t):
        name = r.string()
        nd = r.u32()
        dims = [r.u64() for _ in range(nd)]
        r.u32()
        r.u64()
        if name.endswith(".lora_a") and nd == 2:
            embds.add(dims[0])
            ranks.add(dims[1])
    if not ranks:
        raise ImportErr("The adapter GGUF has no lora_a tensors.")
    if len(ranks) > 1:
        raise ImportErr("The adapter mixes several LoRA ranks; one uniform rank is required.")
    return {"arch": kv.get("general.architecture"), "alpha": kv.get("adapter.lora.alpha"), "rank": next(iter(ranks)), "n_embd": max(embds), "tensors": n_t}


def validate_artifacts(adapter: bytes, meta_raw: bytes) -> dict:
    """-> normalised record fields {base, rank, alpha, adapterSha256, adapterBytes, arch}. Raises ImportErr."""
    if meta_raw is None or not len(meta_raw):
        raise ImportErr(f"{META_FILE} is missing. Put {ADAPTER_FILE} and {META_FILE} ({{\"base_model\",\"rank\",\"alpha\"}}) in the model data location.")
    if len(meta_raw) > MAX_META_BYTES:
        raise ImportErr(f"{META_FILE} is larger than {MAX_META_BYTES // 1024} KB.")
    try:
        meta = json.loads(meta_raw)
        if not isinstance(meta, dict):
            raise ValueError
    except ValueError:
        raise ImportErr(f"{META_FILE} is not a JSON object.") from None
    if adapter is None or not len(adapter):
        raise ImportErr(f"{ADAPTER_FILE} is missing or empty.")
    if len(adapter) > MAX_ADAPTER_BYTES:
        raise ImportErr(f"{ADAPTER_FILE} is {len(adapter) // (1024 * 1024)} MB; the limit is {MAX_ADAPTER_BYTES // (1024 * 1024)} MB.")
    base = canon_base(meta.get("base_model"))
    if not base:
        raise ImportErr(f"{META_FILE}: base_model is required (one of {', '.join(sorted(BASES))}).")
    if base not in BASES:
        raise ImportErr(f"{META_FILE}: base_model '{meta.get('base_model')}' is not a model Vyomi can serve here. Supported bases: {', '.join(sorted(BASES))}.")
    for k in ("rank", "alpha"):
        if not isinstance(meta.get(k), (int, float)) or isinstance(meta.get(k), bool) or meta[k] <= 0:
            raise ImportErr(f"{META_FILE}: {k} must be a positive number.")
    g = parse_gguf_adapter(adapter)
    if g["arch"] != BASES[base]["arch"]:
        raise ImportErr(f"The adapter is for architecture '{g['arch']}' but {base} is '{BASES[base]['arch']}'.")
    if int(meta["rank"]) != g["rank"]:
        raise ImportErr(f"{META_FILE} says rank {meta['rank']} but the adapter GGUF has rank {g['rank']}.")
    if g["alpha"] is not None and abs(float(g["alpha"]) - float(meta["alpha"])) > 1e-6:
        raise ImportErr(f"{META_FILE} says alpha {meta['alpha']} but the adapter GGUF has alpha {g['alpha']}.")
    if g["n_embd"] != BASES[base]["n_embd"]:
        raise ImportErr(f"The adapter was trained for a model with hidden size {g['n_embd']}, not {base} ({BASES[base]['n_embd']}). Wrong base model?")
    quant = meta.get("base_quant") or BASES[base]["default_quant"]
    if quant not in BASES[base]["quants"]:
        raise ImportErr(f"{META_FILE}: base_quant '{quant}' is not available for {base} (one of {', '.join(BASES[base]['quants'])}).")
    return {"base": base, "baseQuant": quant, "rank": g["rank"], "alpha": float(meta["alpha"]), "adapterSha256": hashlib.sha256(adapter).hexdigest(),
            "adapterBytes": len(adapter), "arch": g["arch"]}


# ───────────── registry + object store ─────────────
def _key(mid, f):
    return f"{IMPORT_PREFIX}{mid}/{f}"


def register(model_id, name, adapter: bytes, meta_raw: bytes, source=None, st=None, extra=None) -> dict:
    """Validate and persist an imported model (adapter + meta in the object store). Idempotent per id (overwrites)."""
    v = validate_artifacts(adapter, meta_raw)
    if not tc.store_put(tc.MODELS_BUCKET, _key(model_id, ADAPTER_FILE), adapter, "application/octet-stream", st=st):
        # no object store bound (unit use): keep it in memory only
        pass
    name = tc._derived_name(name, v["base"])        # Llama naming rule (no Llama base is importable today; the rule is applied for when one is)
    rec = {"modelId": model_id, "name": name or model_id, "vyomiLicense": tc._license_of(v["base"]) or {"license": BASES[v["base"]]["license"]}, "createdAt": _now(), "source": source, "engine": "wllama", "kind": "chat-lora",
           "baseModelUrl": BASES[v["base"]]["quants"][v["baseQuant"]]["url"], **v, **(extra or {})}
    tc.store_put(tc.MODELS_BUCKET, _key(model_id, "meta.json"), json.dumps(rec).encode(), st=st)
    _REG[model_id] = rec
    _BYTES[model_id] = adapter
    _STORE_OF[model_id] = st or tc._ST["s3"]
    return public(rec)


def public(rec):
    return {k: v for k, v in rec.items()}


def _load_all():
    """After a reload the adapters are still in the simulated object store: rebuild the registry."""
    st = tc._ST["s3"]
    if st is None or _ST["loaded"] == id(st):
        return
    _ST["loaded"] = id(st)
    try:
        if not st.bucket_exists(tc.MODELS_BUCKET):
            return
        r = tc._s3().list_objects_v2(st, tc.MODELS_BUCKET, {"list-type": "2", "prefix": IMPORT_PREFIX, "max-keys": "1000"})
        for k in re.findall(rb"<Key>(" + re.escape(IMPORT_PREFIX).encode() + rb"[^<]+/meta\.json)</Key>", r.body or b""):
            raw = tc.store_get(tc.MODELS_BUCKET, k.decode(), st)
            if raw:
                rec = json.loads(raw)
                if rec.get("modelId") and rec["modelId"] not in _REG:
                    _REG[rec["modelId"]] = rec
                    _STORE_OF[rec["modelId"]] = st
    except Exception:  # noqa: BLE001 - rehydration is best effort
        pass


def persisted_models():
    _load_all()
    return [public(r) for r in _REG.values()]


def get(model_id):
    _load_all()
    r = _REG.get(model_id)
    return public(r) if r else None


def has_model(model_id):
    _load_all()
    return model_id in _REG


def adapter_bytes(model_id):
    b = _BYTES.get(model_id)
    if b is None and model_id in _REG:
        b = _BYTES[model_id] = tc.store_get(tc.MODELS_BUCKET, _key(model_id, ADAPTER_FILE), _STORE_OF.get(model_id))
    return b


def adapter_b64(model_id):
    b = adapter_bytes(model_id)
    return base64.b64encode(b).decode() if b else None


def delete_model(model_id):
    _REG.pop(model_id, None)
    _BYTES.pop(model_id, None)
    st = _STORE_OF.pop(model_id, None) or tc._ST["s3"]
    if st is not None and st.bucket_exists(tc.MODELS_BUCKET):
        for f in (ADAPTER_FILE, "meta.json"):
            tc._s3().delete_object(st, tc.MODELS_BUCKET, _key(model_id, f), {}, {})


def import_from_uri(model_id, name, uri, source=None, st=None, extra=None) -> dict:
    """Read ``<uri>/adapter.gguf`` + ``<uri>/adapter_meta.json`` from the simulated object store and register the model."""
    b, k = tc.split_uri(uri)
    pre = k if k.endswith("/") or not k else k + "/"
    scheme = "gs" if uri.startswith("gs://") else "s3"
    try:
        adapter = tc.read_uri(f"{scheme}://{b}/{pre}{ADAPTER_FILE}")
    except tc.TrainError:
        raise ImportErr(f"Could not read {ADAPTER_FILE} at {scheme}://{b}/{pre}: object or bucket not found.", "notfound") from None
    try:
        meta = tc.read_uri(f"{scheme}://{b}/{pre}{META_FILE}")
    except tc.TrainError:
        raise ImportErr(f"Could not read {META_FILE} at {scheme}://{b}/{pre}: object or bucket not found.", "notfound") from None
    return register(model_id, name, adapter, meta, source or uri, st=st, extra=extra)


def base_spec(model_id):
    """What the browser needs to serve the model: base GGUF url/size/file + adapter sha."""
    r = _REG.get(model_id)
    if not r:
        return None
    q = BASES[r["base"]]["quants"][r["baseQuant"]]
    return {"base": r["base"], "url": q["url"], "file": q["file"], "size": q["size"], "quant": r["baseQuant"], "adapterSha256": r["adapterSha256"]}
