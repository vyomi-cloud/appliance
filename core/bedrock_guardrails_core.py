"""Bedrock Guardrails, Dev Simplified (control plane + ApplyGuardrail + Converse guardrailConfig).

Honest scope: a DEV-TESTING stand-in so agents can exercise the guardrail wire (intervention shape, blocked messaging,
assessments, anonymisation, stopReason ``guardrail_intervened``) with boto3. The filters are deterministic and simple:
  - word policy       : exact custom words + a tiny managed PROFANITY list (case-insensitive, word boundary)
  - topic policy      : DENY topics matched when the topic name or any example phrase appears in the text (no semantics)
  - sensitive info    : regex PII (EMAIL, PHONE, US_SSN, CREDIT_DEBIT_CARD_NUMBER, IP_ADDRESS, AWS_ACCESS_KEY, URL) + custom regexes
  - content filters   : keyword lists per category (HATE/INSULTS/SEXUAL/VIOLENCE/MISCONDUCT/PROMPT_ATTACK); confidence from hit count
It is NOT a classifier: real Bedrock detection quality is not reproduced. Contextual grounding / automated reasoning are rejected.
Converse/ConverseStream check the INPUT (last user turn); Converse also checks the OUTPUT. Streaming output is not re-checked.
State is process-local (module dict), keyed by guardrail id.
"""
from __future__ import annotations

import json
import re
import time
import uuid

_G: dict[str, dict] = {}
_ACCT, _REG = "000000000000", "us-east-1"

_PROFANITY = ("damn", "hell", "crap", "shit", "fuck", "bastard", "asshole")
_PII = {
    "EMAIL": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "PHONE": r"(?<!\d)(?:\+?1[ -.]?)?\(?\d{3}\)?[ -.]\d{3}[ -.]\d{4}(?!\d)",
    "US_SOCIAL_SECURITY_NUMBER": r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)",
    "CREDIT_DEBIT_CARD_NUMBER": r"(?<!\d)(?:\d[ -]?){13,16}(?!\d)",
    "IP_ADDRESS": r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)",
    "AWS_ACCESS_KEY": r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
    "URL": r"https?://[^\s]+",
}
_CONTENT = {
    "HATE": ("i hate all", "subhuman", "racial slur", "inferior race"),
    "INSULTS": ("idiot", "moron", "stupid", "dumb", "loser", "pathetic"),
    "SEXUAL": ("explicit sex", "porn", "nude", "erotic"),
    "VIOLENCE": ("kill", "murder", "stab", "shoot", "bomb", "torture"),
    "MISCONDUCT": ("launder money", "steal", "hack into", "counterfeit", "fraud"),
    "PROMPT_ATTACK": ("ignore previous instructions", "ignore all previous", "disregard your instructions", "reveal your system prompt", "you are now dan"),
}
_UNSUPPORTED = ("contextualGroundingPolicyConfig", "automatedReasoningPolicyConfig", "crossRegionConfig")
_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}


class GErr(Exception):
    def __init__(self, code, msg, status):
        super().__init__(msg)
        self.code, self.msg, self.status = code, msg, status


def _j(status, doc):
    return {"status": status, "headers": {"content-type": "application/json"}, "body": json.dumps(doc).encode()}


def _err(e):
    return {"status": e.status, "headers": {"content-type": "application/json", "x-amzn-errortype": e.code}, "body": json.dumps({"message": e.msg}).encode()}


def _validate(p):
    for k in _UNSUPPORTED:
        if p.get(k):
            raise GErr("ValidationException", f"{k} is not supported by the Dev Simplified guardrail", 400)
    for k in ("name", "blockedInputMessaging", "blockedOutputsMessaging"):
        if not isinstance(p.get(k), str) or not p[k]:
            raise GErr("ValidationException", f"{k} is required", 400)
    for f in (p.get("contentPolicyConfig") or {}).get("filtersConfig") or []:
        if f.get("type") not in _CONTENT:
            raise GErr("ValidationException", f"Unknown content filter type {f.get('type')!r}", 400)
    for e in (p.get("sensitiveInformationPolicyConfig") or {}).get("piiEntitiesConfig") or []:
        if e.get("type") not in _PII:
            raise GErr("ValidationException", f"PII entity type {e.get('type')!r} is not supported by the Dev Simplified guardrail "
                       f"(supported: {', '.join(sorted(_PII))})", 400)
        if e.get("action") not in ("BLOCK", "ANONYMIZE", "NONE"):
            raise GErr("ValidationException", "piiEntitiesConfig.action must be BLOCK, ANONYMIZE or NONE", 400)
    for r in (p.get("sensitiveInformationPolicyConfig") or {}).get("regexesConfig") or []:
        try:
            re.compile(r.get("pattern", ""))
        except re.error:
            raise GErr("ValidationException", f"Invalid regex pattern in {r.get('name')!r}", 400)


def _view(g, version):
    p = g["draft"] if version == "DRAFT" else g["versions"][version]
    out = {"name": p["name"], "description": p.get("description", ""), "guardrailId": g["id"], "guardrailArn": g["arn"], "version": version,
           "status": "READY", "createdAt": g["created"], "updatedAt": g["updated"],
           "blockedInputMessaging": p["blockedInputMessaging"], "blockedOutputsMessaging": p["blockedOutputsMessaging"]}
    if p.get("topicPolicyConfig"):
        out["topicPolicy"] = {"topics": p["topicPolicyConfig"].get("topicsConfig", [])}
    if p.get("contentPolicyConfig"):
        out["contentPolicy"] = {"filters": p["contentPolicyConfig"].get("filtersConfig", [])}
    if p.get("wordPolicyConfig"):
        out["wordPolicy"] = {"words": p["wordPolicyConfig"].get("wordsConfig", []), "managedWordLists": p["wordPolicyConfig"].get("managedWordListsConfig", [])}
    if p.get("sensitiveInformationPolicyConfig"):
        s = p["sensitiveInformationPolicyConfig"]
        out["sensitiveInformationPolicy"] = {"piiEntities": s.get("piiEntitiesConfig", []), "regexes": s.get("regexesConfig", [])}
    return out


def _find(gid):
    gid = gid.split("/")[-1]
    g = _G.get(gid)
    if not g:
        raise GErr("ResourceNotFoundException", f"Guardrail {gid} not found", 404)
    return g


def evaluate(policy: dict, text: str, source: str) -> dict:
    """-> {action, text, assessment, blocked}. Pure function over one guardrail policy dict."""
    assess: dict = {}
    blocked, anonymised, out = False, False, text
    low = text.lower()
    topics = []
    for t in (policy.get("topicPolicyConfig") or {}).get("topicsConfig") or []:
        needles = [t["name"].lower()] + [e.lower() for e in t.get("examples") or []]
        if any(n and n in low for n in needles):
            topics.append({"name": t["name"], "type": t.get("type", "DENY"), "action": "BLOCKED", "detected": True})
    if topics:
        assess["topicPolicy"] = {"topics": topics}
        blocked = True
    flt = []
    for f in (policy.get("contentPolicyConfig") or {}).get("filtersConfig") or []:
        strength = f.get("inputStrength" if source == "INPUT" else "outputStrength", "HIGH")
        if strength == "NONE":
            continue
        hits = sum(1 for w in _CONTENT[f["type"]] if w in low)
        if hits:
            conf = "HIGH" if hits >= 3 else "MEDIUM" if hits == 2 else "LOW"
            if _RANK[conf] >= 4 - _RANK[strength]:        # strength HIGH blocks LOW+ confidence; LOW blocks only HIGH confidence
                flt.append({"type": f["type"], "confidence": conf, "filterStrength": strength, "action": "BLOCKED", "detected": True})
    if flt:
        assess["contentPolicy"] = {"filters": flt}
        blocked = True
    wp = policy.get("wordPolicyConfig") or {}
    cw = [{"match": w["text"], "action": "BLOCKED", "detected": True} for w in wp.get("wordsConfig") or []
          if re.search(r"(?<!\w)" + re.escape(w["text"]) + r"(?!\w)", text, re.I)]
    mw = []
    if any(m.get("type") == "PROFANITY" for m in wp.get("managedWordListsConfig") or []):
        mw = [{"match": w, "type": "PROFANITY", "action": "BLOCKED", "detected": True} for w in _PROFANITY if re.search(rf"(?<!\w){w}(?!\w)", low)]
    if cw or mw:
        assess["wordPolicy"] = {k: v for k, v in (("customWords", cw), ("managedWordLists", mw)) if v}
        blocked = True
    sp = policy.get("sensitiveInformationPolicyConfig") or {}
    pii, rgx = [], []
    for e in sp.get("piiEntitiesConfig") or []:
        for m in re.finditer(_PII[e["type"]], text):
            act = e["action"]
            if act == "NONE":
                pii.append({"match": m.group(0), "type": e["type"], "action": "NONE", "detected": True})
                continue
            pii.append({"match": m.group(0), "type": e["type"], "action": "BLOCKED" if act == "BLOCK" else "ANONYMIZED", "detected": True})
            if act == "BLOCK":
                blocked = True
            else:
                out, anonymised = out.replace(m.group(0), "{" + e["type"] + "}"), True
    for r in sp.get("regexesConfig") or []:
        for m in re.finditer(r["pattern"], text):
            act = r["action"]
            rgx.append({"name": r["name"], "match": m.group(0), "regex": r["pattern"], "action": "BLOCKED" if act == "BLOCK" else "ANONYMIZED", "detected": True})
            if act == "BLOCK":
                blocked = True
            else:
                out, anonymised = out.replace(m.group(0), "{" + r["name"] + "}"), True
    if pii or rgx:
        assess["sensitiveInformationPolicy"] = {k: v for k, v in (("piiEntities", pii), ("regexes", rgx)) if v}
    if blocked:
        msg = policy["blockedInputMessaging" if source == "INPUT" else "blockedOutputsMessaging"]
        return {"action": "GUARDRAIL_INTERVENED", "text": msg, "assessment": assess, "blocked": True}
    return {"action": "GUARDRAIL_INTERVENED" if anonymised else "NONE", "text": out, "assessment": assess, "blocked": False}


def resolve_policy(gid: str, version: str) -> dict:
    g = _find(gid)
    p = g["draft"] if version == "DRAFT" else g["versions"].get(str(version))
    if p is None:
        raise GErr("ResourceNotFoundException", f"Guardrail {g['id']} version {version} not found", 404)
    return p


def apply_guardrail(gid, version, p):
    if p.get("source") not in ("INPUT", "OUTPUT"):
        raise GErr("ValidationException", "source must be INPUT or OUTPUT", 400)
    cont = p.get("content")
    if not isinstance(cont, list) or not cont:
        raise GErr("ValidationException", "content: at least one block is required", 400)
    pol = resolve_policy(gid, version)
    texts = []
    for b in cont:
        if "image" in b:
            raise GErr("ValidationException", "image content is not supported by the Dev Simplified guardrail", 400)
        t = (b.get("text") or {}).get("text")
        if not isinstance(t, str):
            raise GErr("ValidationException", "each content block needs text.text", 400)
        texts.append(t)
    outputs, assessments, action, blocked = [], [], "NONE", False
    for t in texts:
        r = evaluate(pol, t, p["source"])
        if r["action"] != "NONE":
            action = "GUARDRAIL_INTERVENED"
            outputs.append({"text": r["text"]})
        blocked = blocked or r["blocked"]
        if r["assessment"]:
            assessments.append(r["assessment"])
    n = sum(len(t) for t in texts) // 1000 + 1
    doc = {"usage": {"topicPolicyUnits": n if pol.get("topicPolicyConfig") else 0, "contentPolicyUnits": n if pol.get("contentPolicyConfig") else 0,
                     "wordPolicyUnits": n if pol.get("wordPolicyConfig") else 0,
                     "sensitiveInformationPolicyUnits": n if pol.get("sensitiveInformationPolicyConfig") else 0,
                     "sensitiveInformationPolicyFreeUnits": 0, "contextualGroundingPolicyUnits": 0},
           "action": action, "outputs": outputs, "assessments": assessments}
    if action != "NONE":
        doc["actionReason"] = "Guardrail blocked." if blocked else "Guardrail modified the content."
    return doc


def converse_check(cfg: dict, text: str, source: str):
    """For Converse guardrailConfig. -> None (pass) or evaluate() result; raises GErr when the guardrail is unknown."""
    if not isinstance(cfg, dict) or not cfg.get("guardrailIdentifier") or not cfg.get("guardrailVersion"):
        raise GErr("ValidationException", "guardrailConfig requires guardrailIdentifier and guardrailVersion", 400)
    r = evaluate(resolve_policy(cfg["guardrailIdentifier"], str(cfg["guardrailVersion"])), text, source)
    return None if r["action"] == "NONE" else r


def handles(path: str) -> bool:
    return bool(re.match(r"^/guardrails?(/|$)", path))


def dispatch(method, path, query, body):
    method = method.upper()
    path = re.sub(r"/{2,}", "/", "/" + path.strip("/"))
    try:
        p = json.loads(body) if body else {}
    except ValueError:
        return _err(GErr("ValidationException", "Malformed JSON", 400))
    query = query or {}
    try:
        m = re.match(r"^/guardrail/([^/]+)/version/([^/]+)/apply$", path)
        if m:
            if method != "POST":
                raise GErr("UnknownOperationException", "method not allowed", 405)
            return _j(200, apply_guardrail(m.group(1), m.group(2), p))
        if path == "/guardrails":
            if method == "POST":
                _validate(p)
                gid = uuid.uuid4().hex[:12]
                now = time.time()
                g = {"id": gid, "arn": f"arn:aws:bedrock:{_REG}:{_ACCT}:guardrail/{gid}", "draft": p, "versions": {}, "created": now, "updated": now}
                _G[gid] = g
                return _j(202, {"guardrailId": gid, "guardrailArn": g["arn"], "version": "DRAFT", "createdAt": now})
            if method == "GET":
                ident = (query.get("guardrailIdentifier") or "").split("/")[-1]
                items = []
                for g in _G.values():
                    if ident and g["id"] != ident:
                        continue
                    items.append(_view(g, "DRAFT"))
                    if ident:
                        items += [_view(g, v) for v in g["versions"]]
                keep = ("status", "name", "description", "version", "createdAt", "updatedAt")
                return _j(200, {"guardrails": [{"id": i["guardrailId"], "arn": i["guardrailArn"], **{k: i[k] for k in keep}} for i in items]})
        m = re.match(r"^/guardrails/([^/]+)$", path)
        if m:
            g = _find(m.group(1))
            if method == "GET":
                v = query.get("guardrailVersion", "DRAFT")
                if v != "DRAFT" and v not in g["versions"]:
                    raise GErr("ResourceNotFoundException", f"Guardrail {g['id']} version {v} not found", 404)
                return _j(200, _view(g, v))
            if method == "PUT":
                _validate(p)
                g["draft"], g["updated"] = p, time.time()
                return _j(202, {"guardrailId": g["id"], "guardrailArn": g["arn"], "version": "DRAFT", "updatedAt": g["updated"]})
            if method == "POST":       # CreateGuardrailVersion (snapshot of DRAFT)
                v = str(len(g["versions"]) + 1)
                g["versions"][v] = json.loads(json.dumps(g["draft"]))
                return _j(202, {"guardrailId": g["id"], "version": v})
            if method == "DELETE":
                del _G[g["id"]]
                return _j(202, {})
        raise GErr("UnknownOperationException", f"Unsupported guardrail operation: {method} {path}", 404)
    except GErr as e:
        return _err(e)
