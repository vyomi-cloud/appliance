# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Amazon Bedrock Data Automation (BDA): blueprints, projects, InvokeDataAutomationAsync / InvokeDataAutomation / GetDataAutomationStatus, on the
REAL wire shapes (bedrock-data-automation = rest-json, bedrock-data-automation-runtime = JSON 1.1 target AmazonBedrockKeystoneRuntimeService).

THUMB RULE: no OSS library implements this control plane, so blueprints/projects/jobs are thin records in the persisted account bag. Every
BEHAVIOUR runs on engines that already exist: document text via core/knowledge_core.parse_document (pure-Python pypdf/docx/xlsx/pptx parsers),
image reading and field extraction via the local VISION model (core/llm_core role "vision": SmolVLM-500M behind llama.cpp, Mesh only), JSON-schema
constrained decoding via the seam's response_format (llama.cpp compiles the blueprint to a grammar), S3 in/out via core/s3_object_core.

HONEST SCOPE (also reported in every result.json under "vyomi")
  - Quality is that of a SMALL open model, not the managed service: transcription of clean scans/screenshots is usable, dense layouts, tables,
    handwriting and small print are not. There are NO confidence scores, bounding boxes, layout elements, or per-page geometry.
  - Documents: PDF/DOCX/XLSX/PPTX/CSV/HTML/MD/TXT with a text layer are extracted without a model; scanned PDFs have no OCR (no PDF rasteriser is
    available), so a scan-only PDF fails with a ClientError. Images (png/jpeg/gif/webp) are read by the vision model (needs Mesh, not Nano).
  - Audio and video are rejected (ClientError). Libraries, blueprint optimisation, EventBridge notifications, KMS encryption and PII detection
    settings are accepted/stored but not executed.
  - Custom output (blueprints): every field of the blueprint schema is extracted by one constrained-JSON model call per blueprint; with several blueprints a
    model call picks the matching class first. Values come back as typed JSON (string/number/integer/boolean/array/object) or null.
"""
from __future__ import annotations

import base64
import json
import re
import sys
import threading
import time
import uuid
from urllib.parse import unquote

_ACCT, _REG = "123456789012", "us-east-1"
TARGET_PREFIX = "AmazonBedrockKeystoneRuntimeService"
_BOUND = [None]
_MEM: dict = {}
_ASSET_TYPES = {"png": "image", "jpg": "image", "jpeg": "image", "gif": "image", "webp": "image",
                "pdf": "document", "docx": "document", "xlsx": "document", "pptx": "document", "csv": "document", "html": "document",
                "htm": "document", "md": "document", "txt": "document"}
_JT = {"string", "number", "integer", "boolean", "array", "object"}
_NAME = re.compile(r"^[a-zA-Z0-9-_]{1,128}$")
_PROFILE = re.compile(r"^arn:aws[a-z-]*:bedrock:[a-z0-9-]*:[0-9]{12}:data-automation-profile/(us|eu|apac|us-gov)\.data-automation-v1$")
_CTRL = re.compile(r"^/(blueprints|data-automation-projects|data-automation-libraries|getBlueprintOptimizationStatus|invokeBlueprintOptimizationAsync)(/|$)")
_TAGP = re.compile(r"^/(tagResource|untagResource|listTagsForResource)$")


class BErr(Exception):
    def __init__(self, code, msg, status):
        super().__init__(msg)
        self.code, self.msg, self.status = code, msg, status


def _bad(m):
    return BErr("ValidationException", m, 400)


def _nf(m):
    return BErr("ResourceNotFoundException", m, 404)


def bind(store):
    if store is not None and hasattr(store, "account"):
        _BOUND[0] = store


def _st() -> dict:
    s = _BOUND[0]
    d = s.account.setdefault("bedrock_bda", {}) if s is not None else _MEM
    for k in ("blueprints", "projects", "jobs", "tags"):
        d.setdefault(k, {})
    return d


def _persist():
    s = _BOUND[0]
    try:
        if s is not None and hasattr(s, "persist"):
            s.persist()
    except Exception:  # noqa: BLE001
        pass


def _ts(t=None):
    return float(t if t is not None else time.time())


def _j(status, doc, ct="application/json"):
    return {"status": status, "headers": {"content-type": ct}, "body": json.dumps(doc).encode()}


def _err(e, json11=False):
    return {"status": e.status, "headers": {"content-type": "application/x-amz-json-1.1" if json11 else "application/json", "x-amzn-errortype": e.code},
            "body": json.dumps({"__type": e.code, "message": e.msg}).encode()}


def handles(path: str, body: bytes = b"", headers: dict | None = None) -> bool:
    """Control-plane REST paths, the runtime JSON target, and (shared with Bedrock) the tag calls when the ARN is a BDA resource."""
    if (headers or {}).get("x-amz-target", "").startswith(TARGET_PREFIX):
        return True
    p = re.sub(r"/{2,}", "/", "/" + path.strip("/"))
    if _CTRL.match(p):
        return True
    if _TAGP.match(p):
        try:
            return bool(re.search(r":(blueprint|data-automation-project|data-automation-library)/", str(json.loads(body or b"{}").get("resourceARN", ""))))
        except ValueError:
            return False
    return False


# ───────────────────────── blueprints ─────────────────────────
def _validate_schema(raw):
    try:
        sch = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        raise _bad("schema: must be a valid JSON document (a blueprint JSON schema)")
    if not isinstance(sch, dict) or not isinstance(sch.get("properties"), dict) or not sch["properties"]:
        raise _bad("schema: a blueprint needs a non-empty 'properties' object (field name -> {type, inferenceType, instruction})")
    for name, f in sch["properties"].items():
        if not isinstance(f, dict):
            raise _bad(f"schema.properties.{name}: must be an object")
        t = f.get("type")
        if f.get("$ref"):
            continue
        if t not in _JT:
            raise _bad(f"schema.properties.{name}.type: must be one of {sorted(_JT)}")
        if f.get("inferenceType") not in (None, "explicit", "inferred"):
            raise _bad(f"schema.properties.{name}.inferenceType: must be explicit or inferred")
    return sch


def _bp_view(b, version=None, stage=None):
    out = {"blueprintArn": b["arn"], "schema": b["schema"], "type": b["type"], "creationTime": b["created"], "lastModifiedTime": b["modified"],
           "blueprintName": b["name"], "blueprintStage": stage or b["stage"]}
    if version:
        out["blueprintVersion"] = version
    if b.get("kmsKeyId"):
        out["kmsKeyId"] = b["kmsKeyId"]
    return out


def _find_bp(arn):
    arn = unquote(arn)
    key = re.sub(r"^.*:blueprint/", "", arn)
    b = _st()["blueprints"].get(key)
    if not b:
        raise _nf(f"Blueprint {arn} was not found.")
    return b


def _blueprints(method, path, query, p):
    st = _st()["blueprints"]
    if path in ("/blueprints", "/blueprints/"):
        if method == "PUT":                                  # CreateBlueprint
            name, typ = p.get("blueprintName"), p.get("type")
            if not isinstance(name, str) or not _NAME.match(name):
                raise _bad("blueprintName: must match [a-zA-Z0-9-_]{1,128}")
            if typ not in ("DOCUMENT", "IMAGE", "AUDIO", "VIDEO"):
                raise _bad("type: must be DOCUMENT, IMAGE, AUDIO or VIDEO")
            if p.get("blueprintStage") not in (None, "DEVELOPMENT", "LIVE"):
                raise _bad("blueprintStage: must be DEVELOPMENT or LIVE")
            _validate_schema(p.get("schema"))
            if any(b["name"] == name for b in st.values()):
                raise BErr("ConflictException", f"A blueprint named {name} already exists.", 409)
            bid = uuid.uuid4().hex[:12]
            now = _ts()
            b = {"id": bid, "arn": f"arn:aws:bedrock:{_REG}:{_ACCT}:blueprint/{bid}", "name": name, "type": typ, "stage": p.get("blueprintStage") or "DEVELOPMENT",
                 "schema": p["schema"] if isinstance(p["schema"], str) else json.dumps(p["schema"]), "created": now, "modified": now, "versions": {},
                 "kmsKeyId": (p.get("encryptionConfiguration") or {}).get("kmsKeyId")}
            st[bid] = b
            _st()["tags"][b["arn"]] = {t["key"]: t["value"] for t in p.get("tags") or [] if isinstance(t, dict) and "key" in t}
            _persist()
            return _j(201, {"blueprint": _bp_view(b)})
        if method == "POST":                                 # ListBlueprints
            items = [b for b in st.values() if (not p.get("blueprintStageFilter") or p["blueprintStageFilter"] in ("ALL", b["stage"]))]
            items.sort(key=lambda b: b["created"])
            rows = [{"blueprintArn": b["arn"], "creationTime": b["created"], "lastModifiedTime": b["modified"], "blueprintName": b["name"],
                     "blueprintStage": b["stage"]} for b in items]
            return _j(200, _page(rows, p, "blueprints"))
    m = re.match(r"^/blueprints/(.+?)(/versions|/copy-stage)?/?$", unquote(path))
    if not m:
        raise BErr("UnknownOperationException", f"Unsupported operation: {method} {path}", 404)
    b = _find_bp(m.group(1))
    sub = m.group(2)
    if sub == "/versions" and method == "POST":              # CreateBlueprintVersion: freeze the current schema as the next numbered version
        v = str(len(b["versions"]) + 1)
        b["versions"][v] = {"schema": b["schema"], "created": _ts()}
        _persist()
        return _j(201, {"blueprint": _bp_view(b, v)})
    if sub == "/copy-stage":
        raise BErr("ValidationException", "CopyBlueprintStage is not supported by Vyomi (blueprints have one editable stage plus numbered versions).", 400)
    if method == "POST":                                     # GetBlueprint
        v = p.get("blueprintVersion")
        if v and v not in b["versions"]:
            raise _nf(f"Blueprint version {v} was not found.")
        out = _bp_view(b, v)
        if v:
            out["schema"] = b["versions"][v]["schema"]
        return _j(200, {"blueprint": out})
    if method == "PUT":                                      # UpdateBlueprint
        if "schema" in p:
            _validate_schema(p["schema"])
            b["schema"] = p["schema"] if isinstance(p["schema"], str) else json.dumps(p["schema"])
        if p.get("blueprintStage") in ("DEVELOPMENT", "LIVE"):
            b["stage"] = p["blueprintStage"]
        b["modified"] = _ts()
        _persist()
        return _j(200, {"blueprint": _bp_view(b)})
    if method == "DELETE":
        if any(b["arn"] == (x.get("blueprintArn")) for pr in _st()["projects"].values()
               for x in ((pr.get("customOutputConfiguration") or {}).get("blueprints") or [])):
            raise BErr("ConflictException", "The blueprint is used by a project; remove it from the project first.", 409)
        st.pop(b["id"], None)
        _st()["tags"].pop(b["arn"], None)
        _persist()
        return _j(200, {})
    raise BErr("UnknownOperationException", f"Unsupported operation: {method} {path}", 404)


# ───────────────────────── projects ─────────────────────────
def _find_pr(arn):
    arn = unquote(arn)
    pr = _st()["projects"].get(re.sub(r"^.*:data-automation-project/", "", arn))
    if not pr:
        raise _nf(f"Data automation project {arn} was not found.")
    return pr


def _pr_view(pr):
    out = {k: pr[k] for k in ("projectArn", "projectName", "projectStage", "projectType", "status") if pr.get(k)}
    out["creationTime"], out["lastModifiedTime"] = pr["created"], pr["modified"]
    for k in ("projectDescription", "standardOutputConfiguration", "customOutputConfiguration", "overrideConfiguration", "dataAutomationLibraryConfiguration"):
        if pr.get(k) is not None:
            out[k] = pr[k]
    if pr.get("kmsKeyId"):
        out["kmsKeyId"] = pr["kmsKeyId"]
    return out


def _check_project_bodies(p):
    soc = p.get("standardOutputConfiguration")
    if not isinstance(soc, dict):
        raise _bad("standardOutputConfiguration: required")
    for bp in (p.get("customOutputConfiguration") or {}).get("blueprints") or []:
        if not isinstance(bp, dict) or not bp.get("blueprintArn"):
            raise _bad("customOutputConfiguration.blueprints: each needs blueprintArn")
        _find_bp(bp["blueprintArn"])


def _projects(method, path, query, p):
    st = _st()["projects"]
    if path in ("/data-automation-projects", "/data-automation-projects/"):
        if method == "PUT":                                  # CreateDataAutomationProject
            name = p.get("projectName")
            if not isinstance(name, str) or not _NAME.match(name):
                raise _bad("projectName: must match [a-zA-Z0-9-_]{1,128}")
            if p.get("projectStage") not in (None, "DEVELOPMENT", "LIVE") or p.get("projectType") not in (None, "ASYNC", "SYNC"):
                raise _bad("projectStage must be DEVELOPMENT or LIVE; projectType ASYNC or SYNC")
            _check_project_bodies(p)
            if any(x["projectName"] == name for x in st.values()):
                raise BErr("ConflictException", f"A project named {name} already exists.", 409)
            pid = uuid.uuid4().hex[:12]
            now = _ts()
            pr = {"id": pid, "projectArn": f"arn:aws:bedrock:{_REG}:{_ACCT}:data-automation-project/{pid}", "projectName": name,
                  "projectStage": p.get("projectStage") or "DEVELOPMENT", "projectType": p.get("projectType") or "ASYNC", "status": "COMPLETED",
                  "created": now, "modified": now, "kmsKeyId": (p.get("encryptionConfiguration") or {}).get("kmsKeyId")}
            for k in ("projectDescription", "standardOutputConfiguration", "customOutputConfiguration", "overrideConfiguration", "dataAutomationLibraryConfiguration"):
                if k in p:
                    pr[k] = p[k]
            st[pid] = pr
            _st()["tags"][pr["projectArn"]] = {t["key"]: t["value"] for t in p.get("tags") or [] if isinstance(t, dict) and "key" in t}
            _persist()
            return _j(201, {"projectArn": pr["projectArn"], "projectStage": pr["projectStage"], "status": "COMPLETED"})
        if method == "POST":                                 # ListDataAutomationProjects
            items = sorted(st.values(), key=lambda x: x["created"])
            if p.get("projectStageFilter") in ("DEVELOPMENT", "LIVE"):
                items = [x for x in items if x["projectStage"] == p["projectStageFilter"]]
            bf = (p.get("blueprintFilter") or {}).get("blueprintArn")
            if bf:
                items = [x for x in items if any(b.get("blueprintArn") == bf for b in (x.get("customOutputConfiguration") or {}).get("blueprints") or [])]
            rows = [{"projectArn": x["projectArn"], "creationTime": x["created"], "projectStage": x["projectStage"], "projectName": x["projectName"],
                     "status": x["status"]} for x in items]
            return _j(200, _page(rows, p, "projects"))
    m = re.match(r"^/data-automation-projects/(.+?)/?$", unquote(path))
    if not m:
        raise BErr("UnknownOperationException", f"Unsupported operation: {method} {path}", 404)
    pr = _find_pr(m.group(1))
    if method == "POST":                                     # GetDataAutomationProject
        return _j(200, {"project": _pr_view(pr)})
    if method == "PUT":                                      # UpdateDataAutomationProject
        _check_project_bodies(dict({"standardOutputConfiguration": pr.get("standardOutputConfiguration") or {}}, **p))
        for k in ("projectDescription", "standardOutputConfiguration", "customOutputConfiguration", "overrideConfiguration", "dataAutomationLibraryConfiguration"):
            if k in p:
                pr[k] = p[k]
        if p.get("projectStage") in ("DEVELOPMENT", "LIVE"):
            pr["projectStage"] = p["projectStage"]
        pr["modified"] = _ts()
        _persist()
        return _j(200, {"projectArn": pr["projectArn"], "projectStage": pr["projectStage"], "status": "COMPLETED"})
    if method == "DELETE":
        st.pop(pr["id"], None)
        _st()["tags"].pop(pr["projectArn"], None)
        _persist()
        return _j(200, {})
    raise BErr("UnknownOperationException", f"Unsupported operation: {method} {path}", 404)


def _page(rows, p, key):
    try:
        mx = int(p.get("maxResults") or 100)
        off = int(p.get("nextToken") or 0)
    except (TypeError, ValueError):
        raise _bad("Invalid maxResults/nextToken")
    out = {key: rows[off:off + mx]}
    if off + mx < len(rows):
        out["nextToken"] = str(off + mx)
    return out


def _tags(path, p):
    arn = p.get("resourceARN")
    if not arn:
        raise _bad("resourceARN: required")
    bag = _st()["tags"].setdefault(arn, {})
    if path == "/tagResource":
        bag.update({t["key"]: t["value"] for t in p.get("tags") or []})
        _persist()
        return _j(200, {})
    if path == "/untagResource":
        for k in p.get("tagKeys") or []:
            bag.pop(k, None)
        _persist()
        return _j(200, {})
    return _j(200, {"tags": [{"key": k, "value": v} for k, v in bag.items()]})


# ───────────────────────── processing (the engines) ─────────────────────────
def _llm():
    try:
        from core import llm_core as m
    except ImportError:
        import llm_core as m  # type: ignore
    return m


def _s3():
    try:
        from core import s3_object_core as m
    except ImportError:
        import s3_object_core as m  # type: ignore
    return m


def _kcore():
    try:
        from core import knowledge_core as m
    except ImportError:
        import knowledge_core as m  # type: ignore
    return m


class _JobErr(Exception):
    def __init__(self, kind, msg):
        super().__init__(msg)
        self.kind, self.msg = kind, msg


def _split_uri(uri):
    m = re.match(r"^s3://([^/]+)/?(.*)$", uri or "")
    if not m:
        raise _bad("S3 URI must be of the form s3://bucket/key")
    return m.group(1), m.group(2)


def _img_part(raw, ext):
    fmt = {"jpg": "jpeg"}.get(ext, ext)
    return {"type": "image_url", "image_url": {"url": f"data:image/{fmt};base64,{base64.b64encode(raw).decode()}"}}


def _vision(raw, ext, prompt, max_tokens=500, schema=None):
    llm = _llm()
    if not llm.role_endpoint("vision") or not llm.role_available("vision"):
        raise _JobErr("ClientError", "No vision model is served: images need the Mesh vision pack (SmolVLM via llama.cpp). Nano and plain offline runtimes cannot read images.")
    msgs = [{"role": "user", "content": [{"type": "text", "text": prompt}, _img_part(raw, ext)]}]
    try:
        r = llm.chat(msgs, max_tokens=max_tokens, temperature=0.0, role="vision",
                     response_format={"type": "json_schema", "schema": schema, "name": "blueprint"} if schema else None)
    except (llm.LlmUnavailable, llm.LlmStructuredError) as e:
        raise _JobErr("ServiceError", f"The vision model could not answer: {e}")
    return r


def _text_chat(prompt, schema, max_tokens=700):
    llm = _llm()
    if llm._state.get("afn") and not llm._state.get("fn") and not llm.role_endpoint("reasoning") and not llm._endpoint():
        raise _JobErr("ServiceError", "On Nano the only chat model is the in-browser WebLLM, which cannot be called from a background job: custom (blueprint) output needs Mesh. Standard output of text documents still works.")
    try:
        return llm.chat([{"role": "user", "content": prompt}], max_tokens=max_tokens, temperature=0.0,
                        response_format={"type": "json_schema", "schema": schema, "name": "blueprint"})
    except (llm.LlmUnavailable, llm.LlmStructuredError) as e:
        raise _JobErr("ServiceError", f"No local model could extract the blueprint fields ({e}). Start the local LLM (Mesh AI pack).")


def _bp_json_schema(sch):
    """Blueprint schema (field -> {type, instruction, inferenceType}) -> a plain JSON schema where every field may be null (absent in the asset)."""
    props, lines = {}, []
    for name, f in sch["properties"].items():
        t = f.get("type") or "string"
        js = {"type": [t, "null"]}
        if t == "array":
            js["items"] = f.get("items") if isinstance(f.get("items"), dict) and f["items"].get("type") in _JT else {"type": "string"}
        if t == "object":
            js["additionalProperties"] = True
        props[name] = js
        lines.append(f"- {name} ({t}{', inferred' if f.get('inferenceType') == 'inferred' else ''}): {f.get('instruction') or f.get('description') or name}")
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}, "\n".join(lines)


def _extract_fields(sch, raw, ext, text, bp_name):
    js, lines = _bp_json_schema(sch)
    prompt = (f"Extract these fields from the {'image' if raw is not None and not text else 'document'} ({sch.get('class') or bp_name}). "
              f"Answer with one JSON object. Use null for a field that is not present. Fields:\n{lines}")
    if text:
        r = _text_chat(prompt + "\n\nDocument text:\n" + text[:6000], js)
    else:
        r = _vision(raw, ext, prompt, 600, js)
    try:
        val = json.loads(r["text"])
    except ValueError:
        raise _JobErr("ServiceError", "The model returned a field set that is not valid JSON.")
    return val, r


def _doc_text(name, ext, raw):
    kc = _kcore()
    try:
        return kc.parse_document(f"{name}", raw, markdown_tables=True)
    except Exception as e:  # noqa: BLE001
        raise _JobErr("ClientError", f"Could not read the document {name}: {e}")


def _vyomi(engine, extra=None):
    return dict({"engine": engine, "quality": "small open model output, not the managed Bedrock Data Automation service; no confidence scores, "
                                              "bounding boxes or layout elements", "confidenceAvailable": False}, **(extra or {}))


def _process_asset(name, raw, project, req_blueprints, routing_doc_image=False):
    """-> (modality, standard_result_dict, custom_status, custom_result_dict|None). Raises _JobErr."""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    kind = _ASSET_TYPES.get(ext)
    if kind is None:
        raise _JobErr("ClientError", f"Unsupported asset type .{ext or '?'}: Vyomi reads png/jpeg/gif/webp images and pdf/docx/xlsx/pptx/csv/html/md/txt documents (audio and video are not supported).")
    ovr = (project or {}).get("overrideConfiguration") or {}
    route = (ovr.get("modalityRouting") or {}).get({"jpg": "jpeg"}.get(ext, ext))
    modality = route if route in ("IMAGE", "DOCUMENT") else ("IMAGE" if kind == "image" else "DOCUMENT")
    if route in ("AUDIO", "VIDEO"):
        raise _JobErr("ClientError", "Audio and video processing is not supported.")
    text, engine = "", "none"
    meta = {"asset_id": 0, "semantic_modality": modality, "s3_key": name}
    std: dict
    if kind == "document":
        text = _doc_text(name, ext, raw)
        if not text.strip():
            raise _JobErr("ClientError", "The document has no text layer and Vyomi has no OCR for scanned PDFs (no page rasteriser). Provide a text-layer PDF or an image.")
        engine = "knowledge_core.parse_document (no model)"
        pages = [text]
        std = {"metadata": dict(meta, number_of_pages=len(pages)), "document": {"representation": {"text": text, "markdown": text},
               "statistics": {"element_count": 0, "table_count": 0, "figure_count": 0, "word_count": len(text.split())}},
               "pages": [{"page_index": 0, "representation": {"text": text, "markdown": text}}], "elements": []}
        vm = _vyomi(engine)
    else:
        gen = ((((project or {}).get("standardOutputConfiguration") or {}).get("image") or {}).get("generativeField") or {}).get("state") != "DISABLED"
        r1 = _vision(raw, ext, "Transcribe all the text visible in this image exactly, one line per text line. If there is no text, answer with nothing.", 700)
        text = (r1["text"] or "").strip()
        lines = [x for x in text.splitlines() if x.strip()]
        summary = ""
        if gen:
            r2 = _vision(raw, ext, "Describe this image in one or two sentences.", 120)
            summary = (r2["text"] or "").strip()
        engine = r1.get("model") or "vision"
        if modality == "DOCUMENT":
            std = {"metadata": dict(meta, number_of_pages=1), "document": {"representation": {"text": text, "markdown": text}, **({"summary": summary} if summary else {}),
                   "statistics": {"element_count": 0, "table_count": 0, "figure_count": 0, "word_count": len(text.split())}},
                   "pages": [{"page_index": 0, "representation": {"text": text, "markdown": text}}], "elements": []}
        else:
            std = {"metadata": dict(meta), "image": {"summary": summary, "text_lines": [{"id": f"line_{i}", "text": ln, "granularity": "LINE"} for i, ln in enumerate(lines)],
                   "representation": {"text": text}}}
        vm = _vyomi(engine)
    std["vyomi"] = vm
    # custom output: blueprints from the project and/or the request
    bps = []
    for ref in list(((project or {}).get("customOutputConfiguration") or {}).get("blueprints") or []) + list(req_blueprints or []):
        arn = ref.get("blueprintArn")
        b = _find_bp(arn)
        ver = ref.get("blueprintVersion") or ref.get("version")
        sch = json.loads(b["versions"][ver]["schema"] if ver and ver in b["versions"] else b["schema"])
        if b["type"] in ("DOCUMENT", "IMAGE") and b["type"] != modality:     # a blueprint only applies to its own modality
            continue
        bps.append((b, ver, sch))
    if not bps:
        return modality, std, None, None
    chosen = bps[0]
    if len(bps) > 1:                                           # pick the matching class with one constrained call
        names = [x[0]["name"] for x in bps]
        js = {"type": "object", "properties": {"blueprint": {"type": "string", "enum": names + ["none"]}}, "required": ["blueprint"], "additionalProperties": False}
        pick = f"Which blueprint matches this asset? Options: {', '.join(names)}, or none.\nBlueprints:\n" + "\n".join(
            f"- {x[0]['name']}: {x[2].get('description') or x[2].get('class') or ''}" for x in bps)
        if text:
            r = _text_chat(pick + "\n\nAsset text:\n" + text[:3000], js, 40)
        else:
            r = _vision(raw, ext, pick, 40, js)
        try:
            nm = json.loads(r["text"]).get("blueprint")
        except ValueError:
            nm = None
        chosen = next((x for x in bps if x[0]["name"] == nm), None)
        if chosen is None:
            return modality, std, "NO_MATCH", {"matched_blueprint": None, "vyomi": _vyomi(engine)}
    b, ver, sch = chosen
    val, r = _extract_fields(sch, raw if kind == "image" else None, ext, text if kind == "document" else "", b["name"])
    custom = {"matched_blueprint": {"arn": b["arn"], "name": b["name"], **({"version": ver} if ver else {}), "confidence": None},
              "document_class": {"type": sch.get("class") or b["name"]}, "split_document": {"page_indices": [0]}, "inference_result": val,
              "explainability_info": [{k: {"success": v is not None, "confidence": None, "value": v}} for k, v in val.items()],
              "vyomi": _vyomi(r.get("model") or engine)}
    return modality, std, "MATCH", custom


# ───────────────────────── runtime ─────────────────────────
def _validate_invoke(p, sync=False):
    if not _PROFILE.match(str(p.get("dataAutomationProfileArn") or "")):
        raise _bad("dataAutomationProfileArn: must be a data automation profile ARN, e.g. arn:aws:bedrock:us-east-1:123456789012:data-automation-profile/us.data-automation-v1")
    dac = p.get("dataAutomationConfiguration")
    pr = None
    if dac is not None:
        if not isinstance(dac, dict) or not dac.get("dataAutomationProjectArn"):
            raise _bad("dataAutomationConfiguration.dataAutomationProjectArn: required")
        try:
            pr = _find_pr(dac["dataAutomationProjectArn"])
        except BErr:
            raise _bad(f"The data automation project {dac['dataAutomationProjectArn']} does not exist.")
    for b in p.get("blueprints") or []:
        try:
            _find_bp(b.get("blueprintArn", ""))
        except BErr:
            raise _bad(f"The blueprint {b.get('blueprintArn')} does not exist.")
    return pr


def _read(s3, uri):
    bk, key = _split_uri(uri)
    if not s3.bucket_exists(bk):
        raise _JobErr("ClientError", f"The input bucket {bk} does not exist.")
    g = _s3().get_object(s3, bk, key, {}, {})
    if g.status != 200:
        raise _JobErr("ClientError", f"The input object s3://{bk}/{key} does not exist or is not readable.")
    return key.rsplit("/", 1)[-1], g.body


def _run_job(s3, jid):
    st = _st()["jobs"][jid]
    st["status"] = "InProgress"
    t0 = time.time()
    try:
        name, raw = _read(s3, st["input"])
        pr = _find_pr(st["project"]) if st.get("project") else None
        modality, std, cstat, custom = _process_asset(name, raw, pr, st.get("blueprints"))
        ob, op = _split_uri(st["output"])
        pre = f"{op.rstrip('/') + '/' if op else ''}{jid}/"
        put = lambda k, d: _s3().put_object(s3, ob, k, json.dumps(d).encode(), {"content-type": "application/json"})
        seg = {"segment_index": 0, "standard_output_path": f"s3://{ob}/{pre}0/standard_output/0/result.json"}
        put(f"{pre}0/standard_output/0/result.json", std)
        if cstat:
            seg["custom_output_status"] = cstat
            if custom is not None:
                seg["custom_output_path"] = f"s3://{ob}/{pre}0/custom_output/0/result.json"
                put(f"{pre}0/custom_output/0/result.json", custom)
        meta = {"job_id": jid, "job_status": "PROCESSED", "semantic_modality": modality, "blueprint": None,
                "job_submission_time": _iso(st["submitted"]), "job_completion_time": _iso(), "job_duration_in_seconds": round(time.time() - t0, 3),
                "output_metadata": [{"asset_id": 0, "asset_input_path": st["input"], "segment_metadata": [seg]}]}
        put(f"{pre}job_metadata.json", meta)
        st.update(status="Success", completed=time.time(), outputUri=f"s3://{ob}/{pre}job_metadata.json")
    except _JobErr as e:
        st.update(status=e.kind, errorType=e.kind, errorMessage=e.msg, completed=time.time())
    except BErr as e:
        st.update(status="ClientError", errorType="ValidationException", errorMessage=e.msg, completed=time.time())
    except Exception as e:  # noqa: BLE001
        st.update(status="ServiceError", errorType="InternalServerException", errorMessage=f"{type(e).__name__}: {e}", completed=time.time())
    _persist()


def _iso(t=None):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t if t is not None else time.time()))


def _threads_ok():
    return sys.platform != "emscripten"


def _runtime(s3, op, p):
    if op == "InvokeDataAutomationAsync":
        ic, oc = p.get("inputConfiguration"), p.get("outputConfiguration")
        if not isinstance(ic, dict) or not ic.get("s3Uri") or not isinstance(oc, dict) or not oc.get("s3Uri"):
            raise _bad("inputConfiguration.s3Uri and outputConfiguration.s3Uri are required")
        _split_uri(ic["s3Uri"]), _split_uri(oc["s3Uri"])
        pr = _validate_invoke(p)
        if pr is None and not p.get("blueprints"):
            raise _bad("Provide dataAutomationConfiguration (a project) or blueprints.")
        if not s3.bucket_exists(_split_uri(oc["s3Uri"])[0]):
            raise _bad(f"The output bucket {_split_uri(oc['s3Uri'])[0]} does not exist.")
        jid = uuid.uuid4().hex
        _st()["jobs"][jid] = {"status": "Created", "input": ic["s3Uri"], "output": oc["s3Uri"], "project": pr["projectArn"] if pr else None,
                              "blueprints": [{"blueprintArn": b["blueprintArn"], "blueprintVersion": b.get("version")} for b in p.get("blueprints") or []],
                              "submitted": time.time()}
        arn = f"arn:aws:bedrock:{_REG}:{_ACCT}:data-automation-invocation/{jid}"
        _st()["jobs"][jid]["arn"] = arn
        if _threads_ok():
            threading.Thread(target=_run_job, args=(s3, jid), daemon=True).start()
        else:
            _run_job(s3, jid)
        _persist()
        return {"invocationArn": arn}
    if op == "GetDataAutomationStatus":
        arn = p.get("invocationArn") or ""
        j = _st()["jobs"].get(arn.rsplit("/", 1)[-1])
        if not j:
            raise _nf(f"Invocation {arn} was not found.")
        out = {"status": j["status"], "jobSubmissionTime": j["submitted"]}
        if j.get("outputUri"):
            out["outputConfiguration"] = {"s3Uri": j["outputUri"]}
        if j.get("completed"):
            out["jobCompletionTime"] = j["completed"]
            out["jobDurationInSeconds"] = int(j["completed"] - j["submitted"])
        if j.get("errorMessage"):
            out["errorType"], out["errorMessage"] = j.get("errorType"), j["errorMessage"]
        return out
    if op == "InvokeDataAutomation":
        ic = p.get("inputConfiguration") or {}
        pr = _validate_invoke(p, True)
        try:
            if ic.get("bytes") is not None:
                raw = ic["bytes"] if isinstance(ic["bytes"], (bytes, bytearray)) else base64.b64decode(ic["bytes"])
                name = "input." + _sniff(bytes(raw))
            elif ic.get("s3Uri"):
                name, raw = _read(s3, ic["s3Uri"])
            else:
                raise _bad("inputConfiguration needs bytes or s3Uri")
            modality, std, cstat, custom = _process_asset(name, bytes(raw), pr, [{"blueprintArn": b["blueprintArn"], "version": b.get("version")} for b in p.get("blueprints") or []])
        except _JobErr as e:
            raise BErr("ValidationException" if e.kind == "ClientError" else "InternalServerException", e.msg, 400 if e.kind == "ClientError" else 500)
        seg = {"standardOutput": json.dumps(std)}
        if cstat:
            seg["customOutputStatus"] = cstat
            if custom is not None:
                seg["customOutput"] = json.dumps(custom)
        return {"semanticModality": modality, "outputSegments": [seg]}
    raise BErr("UnknownOperationException", f"Unsupported operation: {op}", 400)


def _sniff(b):
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if b[:3] == b"\xff\xd8\xff":
        return "jpg"
    if b[:4] == b"GIF8":
        return "gif"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "webp"
    if b[:4] == b"%PDF":
        return "pdf"
    if b[:2] == b"PK":
        return "docx"
    return "txt"


def dispatch(s3, method, path, query, headers, body):
    """-> wire response dict {status, headers, body}. Control plane by path, runtime by X-Amz-Target."""
    bind(s3)
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    tgt = headers.get("x-amz-target", "")
    try:
        try:
            p = json.loads(body) if body else {}
            if not isinstance(p, dict):
                raise ValueError
        except ValueError:
            raise _bad("Malformed JSON")
        if tgt.startswith(TARGET_PREFIX):
            op = tgt.split(".", 1)[-1]
            if op in ("TagResource", "UntagResource", "ListTagsForResource"):
                out = json.loads(_tags("/" + op[0].lower() + op[1:], p)["body"])
            else:
                out = _runtime(s3, op, p)
            return _j(200, out, "application/x-amz-json-1.1")
        path = re.sub(r"/{2,}", "/", "/" + path.strip("/"))
        if _TAGP.match(path):
            return _tags(path, p)
        if path.startswith("/blueprints"):
            return _blueprints(method.upper(), path, query or {}, p)
        if path.startswith("/data-automation-projects"):
            return _projects(method.upper(), path, query or {}, p)
        raise BErr("ValidationException", "This Bedrock Data Automation operation is not supported by Vyomi (libraries and blueprint optimisation are not implemented).", 400)
    except BErr as e:
        return _err(e, bool(tgt))
