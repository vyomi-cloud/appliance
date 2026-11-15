# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
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
    # ai-approvals lane: more regex-detectable entity types (context-anchored where a bare pattern would over-match)
    "AWS_SECRET_KEY": r"(?<![A-Za-z0-9/+=])[A-Za-z0-9/+=]{40}(?![A-Za-z0-9/+=])(?<=[/+=0-9])",
    "MAC_ADDRESS": r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b",
    "CREDIT_DEBIT_CARD_CVV": r"(?i)(?<=cvv )\d{3,4}|(?<=cvc )\d{3,4}|(?<=cvv: )\d{3,4}|(?<=cvv:)\d{3,4}",
    "CREDIT_DEBIT_CARD_EXPIRY": r"(?<!\d)(?:0[1-9]|1[0-2])/(?:\d{2}|\d{4})(?!\d)",
    "US_BANK_ROUTING_NUMBER": r"(?i)(?<=routing number )\d{9}|(?<=routing: )\d{9}|(?<=routing )\d{9}",
    "US_BANK_ACCOUNT_NUMBER": r"(?i)(?<=account number )\d{8,17}|(?<=account: )\d{8,17}|(?<=acct )\d{8,17}",
    "US_PASSPORT_NUMBER": r"(?i)(?<=passport )[A-Z]?\d{8,9}|(?<=passport: )[A-Z]?\d{8,9}",
    "PASSWORD": r"(?i)(?<=password is )\S+|(?<=password: )\S+|(?<=password=)\S+",
    "USERNAME": r"(?i)(?<=username is )\S+|(?<=username: )\S+|(?<=username=)\S+",
    "PIN": r"(?i)(?<=pin is )\d{4,8}|(?<=pin: )\d{4,8}",
    "VEHICLE_IDENTIFICATION_NUMBER": r"\b(?=[A-HJ-NPR-Z0-9]*\d)[A-HJ-NPR-Z0-9]{17}\b",
    "AGE": r"(?i)\b\d{1,3}(?= years? old\b)|(?<=age )\d{1,3}\b|(?<=aged )\d{1,3}\b",
    "ADDRESS": r"\b\d{1,6}\s+(?:[A-Z][a-z]+\s){1,3}(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Way)\b\.?",
    "NAME": r"(?:\b(?:Mr|Mrs|Ms|Miss|Dr)\.?\s+[A-Z][a-z]+(?:\s[A-Z][a-z]+)?)|(?<=my name is )[A-Z][a-z]+(?:\s[A-Z][a-z]+)?|(?<=I am )[A-Z][a-z]+\s[A-Z][a-z]+",
}
_CONTENT = {
    "HATE": ("i hate all", "subhuman", "racial slur", "inferior race"),
    "INSULTS": ("idiot", "moron", "stupid", "dumb", "loser", "pathetic"),
    "SEXUAL": ("explicit sex", "porn", "nude", "erotic"),
    "VIOLENCE": ("kill", "murder", "stab", "shoot", "bomb", "torture"),
    "MISCONDUCT": ("launder money", "steal", "hack into", "counterfeit", "fraud"),
    "PROMPT_ATTACK": ("ignore previous instructions", "ignore all previous", "disregard your instructions", "reveal your system prompt", "you are now dan"),
}
_UNSUPPORTED = ("automatedReasoningPolicyConfig", "crossRegionConfig")
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
    _validate_grounding(p)
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


def _validate_grounding(p):
    for f in (p.get("contextualGroundingPolicyConfig") or {}).get("filtersConfig") or []:
        if f.get("type") not in ("GROUNDING", "RELEVANCE"):
            raise GErr("ValidationException", f"Unknown contextual grounding filter type {f.get('type')!r} (GROUNDING or RELEVANCE)", 400)
        t = f.get("threshold")
        if not isinstance(t, (int, float)) or not 0 <= t <= 0.99:
            raise GErr("ValidationException", "contextualGroundingPolicyConfig threshold must be a number in [0, 0.99]", 400)


# ── contextual grounding (ai-approvals lane) ─────────────────────────────────────────────────────────────
# Scores in [0,1]. GROUNDING = how much of the answer (guard_content) is supported by grounding_source; RELEVANCE = how well the answer
# addresses the query. Method: content-word coverage per sentence (+ numbers must appear in the source) blended with embedding cosine
# through the llm seam (core/llm_core.embed: the real embedding model when the AI pack is up, the deterministic hash embedding otherwise).
# It is a deterministic scorer, not Bedrock's trained classifier: thresholds behave the same shape, absolute scores will differ.
_STOP = frozenset("a an the and or of to in on at for from by with is are was were be been being it its this that these those as if then than "
                  "so do does did has have had will would can could should may might not no yes i you he she we they them his her our your their "
                  "there here what which who whom when where why how about into over under per via also very just more most some any all".split())


def _words(t):
    return [w for w in re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", t.lower()) if w not in _STOP and len(w) > 1]


def _stem(w):
    for suf in ("ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) > len(suf) + 2:
            return w[:-len(suf)]
    return w


def _cos(a, b):
    try:
        from core import llm_core
        v = llm_core.embed([a, b])["vectors"]
        x, y = v[0], v[1]
        return max(0.0, sum(i * j for i, j in zip(x, y)) / ((sum(i * i for i in x) ** .5) * (sum(j * j for j in y) ** .5) or 1))
    except Exception:
        return 0.0


def grounding_score(answer, source):
    src = {_stem(w) for w in _words(source)}
    src_nums = set(re.findall(r"\d+(?:\.\d+)?", source))
    sents = [x for x in re.split(r"(?<=[.!?])\s+|\n+", answer) if _words(x)] or [answer]
    scores = []
    for sent in sents:
        ws = [_stem(w) for w in _words(sent)]
        cov = sum(1 for w in ws if w in src) / (len(ws) or 1)
        nums = set(re.findall(r"\d+(?:\.\d+)?", sent))
        if nums and not nums <= src_nums:       # a figure the source never states: ungrounded however many other words match
            cov *= 0.3
        scores.append(cov)
    lex = sum(scores) / len(scores)
    return round(max(0.0, min(1.0, lex if lex < 0.5 else 0.5 * lex + 0.5 * max(lex, _cos(answer, source)))), 2)


def relevance_score(answer, query):
    qw = {_stem(w) for w in _words(query)}
    aw = {_stem(w) for w in _words(answer)}
    ov = len(qw & aw) / (len(qw) or 1)
    return round(max(0.0, min(1.0, max(ov, _cos(answer, query)))), 2)


def evaluate_grounding(policy, blocks):
    """blocks: [(text, qualifiers)]. -> (assessment or None, blocked)."""
    cfg = (policy.get("contextualGroundingPolicyConfig") or {}).get("filtersConfig") or []
    q = lambda name: " ".join(t for t, quals in blocks if name in quals)   # noqa: E731
    src, qry, ans = q("grounding_source"), q("query"), q("guard_content")
    if not cfg or not ans:
        return None, False
    out, blocked = [], False
    for f in cfg:
        if f["type"] == "GROUNDING" and src:
            sc = grounding_score(ans, src)
        elif f["type"] == "RELEVANCE" and qry:
            sc = relevance_score(ans, qry)
        else:
            continue
        hit = sc < f["threshold"]
        blocked = blocked or hit
        out.append({"type": f["type"], "threshold": f["threshold"], "score": sc, "action": "BLOCKED" if hit else "NONE", "detected": hit})
    return ({"contextualGroundingPolicy": {"filters": out}} if out else None), blocked


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
    if p.get("contextualGroundingPolicyConfig"):
        out["contextualGroundingPolicy"] = {"filters": p["contextualGroundingPolicyConfig"].get("filtersConfig", [])}
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
    texts, blocks = [], []
    for b in cont:
        if "image" in b:
            raise GErr("ValidationException", "image content is not supported by the Dev Simplified guardrail", 400)
        t = (b.get("text") or {}).get("text")
        if not isinstance(t, str):
            raise GErr("ValidationException", "each content block needs text.text", 400)
        quals = (b.get("text") or {}).get("qualifiers") or []
        blocks.append((t, quals))
        if "grounding_source" in quals or "query" in quals:   # grounding inputs are context, not content to filter
            continue
        texts.append(t)
    outputs, assessments, action, blocked = [], [], "NONE", False
    if p["source"] == "OUTPUT":
        ga, gb = evaluate_grounding(pol, blocks)
        if ga:
            assessments.append(ga)
        if gb:
            action, blocked = "GUARDRAIL_INTERVENED", True
            outputs.append({"text": pol["blockedOutputsMessaging"]})
    for t in texts:
        if blocked and outputs:
            break
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
                     "sensitiveInformationPolicyFreeUnits": 0, "contextualGroundingPolicyUnits": n if pol.get("contextualGroundingPolicyConfig") else 0},
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
