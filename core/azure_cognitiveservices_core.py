"""Azure AI Services / Cognitive Services core (``Microsoft.CognitiveServices``) — substrate-independent.

Speaks the ARM control-plane REST API of the ``cognitiveservices`` resource provider
(azure-rest-api-specs ``specification/cognitiveservices/resource-manager``, api-version 2024-10-01), so the
native ``azure-mgmt-cognitiveservices`` / ``armcognitiveservices`` /
``com.azure.resourcemanager.cognitiveservices`` SDKs and ``az cognitiveservices`` / ``az rest`` work unchanged.

NO fastapi / azure-sdk / socket / subprocess imports → loads under Pyodide, so the SAME file runs offline and
in Nano. It does not own a store: it mutates the ARM resource map the dispatchers already keep
(``{lower-cased resource id: record}``), which is space-scoped and persisted by the existing seams.
Deployments, commitment plans, RAI policies, private-endpoint connections and keys live INSIDE their parent
account (underscore keys, never serialised to clients), so the cost model counts one resource per account.

Resource types
    Microsoft.CognitiveServices/accounts   (+ deployments, commitmentPlans, raiPolicies, listKeys,
                                              regenerateKey, listSkus, usages, models, privateLinkResources,
                                              privateEndpointConnections)
    Microsoft.CognitiveServices/deletedAccounts      (soft-delete; restore via ``properties.restore``; purge)
    Microsoft.CognitiveServices/commitmentPlans      (subscription-level list)
    Subscription / location scope: skus, checkDomainAvailability, locations/{loc}/{models, usages,
        commitmentTiers, checkSkuAvailability, resourceGroups/{rg}/deletedAccounts/{name}}
Errors use the ARM shape ``{"error":{"code","message"}}``.

``dispatch`` returns ``{"status","headers","body","lro","rid","verb"}``; the caller adds the
Azure-AsyncOperation headers when ``lro`` is true.  The service is control-plane only: model inference
(data plane) is not served.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone

NAMESPACE = "Microsoft.CognitiveServices"
API_VERSION = "2024-10-01"
DEFAULT_LOCATION = "eastus"

# kind → (allowed sku names, default sku, tier map)
KINDS: dict[str, tuple] = {
    "CognitiveServices": (("S0",), "S0"),
    "AIServices": (("S0",), "S0"),
    "OpenAI": (("S0",), "S0"),
    "TextAnalytics": (("F0", "S", "S0", "S1", "S2", "S3", "S4"), "S"),
    "ComputerVision": (("F0", "S1"), "S1"),
    "CustomVision.Training": (("F0", "S0"), "S0"),
    "CustomVision.Prediction": (("F0", "S0"), "S0"),
    "Face": (("F0", "S0"), "S0"),
    "FormRecognizer": (("F0", "S0"), "S0"),
    "ContentSafety": (("F0", "S0"), "S0"),
    "SpeechServices": (("F0", "S0"), "S0"),
    "TextTranslation": (("F0", "S1", "S2", "S3", "S4"), "S1"),
    "LUIS": (("F0", "S0"), "S0"),
    "QnAMaker.v2": (("F0", "S0"), "S0"),
    "ImmersiveReader": (("S0",), "S0"),
    "Personalizer": (("F0", "S0"), "S0"),
    "AnomalyDetector": (("F0", "S0"), "S0"),
    "HealthInsights": (("F0", "S0"), "S0"),
    "ContentModerator": (("F0", "S0"), "S0"),
}
# kinds that must have a custom sub-domain (token auth / OpenAI endpoint)
NEEDS_SUBDOMAIN = {"OpenAI", "AIServices", "ContentSafety", "FormRecognizer", "ComputerVision", "Face", "TextAnalytics",
                   "HealthInsights", "ImmersiveReader"}
ENDPOINT_HOST = {"OpenAI": "openai.azure.com"}
DEFAULT_HOST = "cognitiveservices.azure.com"

DEPLOY_SKUS = ("Standard", "GlobalStandard", "ProvisionedManaged", "GlobalProvisionedManaged", "DataZoneStandard",
               "GlobalBatch", "DeveloperTier")
QUOTA_LIMIT = 1000          # thousands of tokens-per-minute per deployment sku (per account)

# (format, name, version, max capacity, capabilities)
MODELS = [
    ("OpenAI", "gpt-4o", "2024-05-13", 450, ("chatCompletion", "assistants", "jsonObjectResponse")),
    ("OpenAI", "gpt-4o", "2024-08-06", 450, ("chatCompletion", "assistants", "jsonObjectResponse", "jsonSchemaResponse")),
    ("OpenAI", "gpt-4o", "2024-11-20", 450, ("chatCompletion", "assistants", "jsonObjectResponse", "jsonSchemaResponse")),
    ("OpenAI", "gpt-4o-mini", "2024-07-18", 1000, ("chatCompletion", "assistants", "jsonObjectResponse")),
    ("OpenAI", "gpt-4", "turbo-2024-04-09", 80, ("chatCompletion",)),
    ("OpenAI", "gpt-35-turbo", "0125", 1000, ("chatCompletion",)),
    ("OpenAI", "o1", "2024-12-17", 100, ("chatCompletion", "reasoning")),
    ("OpenAI", "o3-mini", "2025-01-31", 1000, ("chatCompletion", "reasoning")),
    ("OpenAI", "text-embedding-ada-002", "2", 1000, ("embeddings",)),
    ("OpenAI", "text-embedding-3-small", "1", 1000, ("embeddings",)),
    ("OpenAI", "text-embedding-3-large", "1", 1000, ("embeddings",)),
    ("OpenAI", "dall-e-3", "3.0", 2, ("imageGenerations",)),
    ("OpenAI", "whisper", "001", 3, ("audioTranscriptions",)),
    ("OpenAI", "tts", "001", 3, ("audioSpeech",)),
]
MODEL_KINDS = ("OpenAI", "AIServices")

TIERS = {                       # commitment tiers by kind (list pricing, USD)
    "TextAnalytics": [("Web", "T1", "Commitment 1M Text Records", 1000000, 1000.0)],
    "SpeechServices": [("Web", "STT-T1", "Speech to text, 2000 hours", 2000, 1000.0)],
    "ComputerVision": [("Web", "OCR-T1", "OCR, 1M transactions", 1000000, 1000.0)],
    "FormRecognizer": [("Web", "DI-T1", "Document Intelligence, 500K pages", 500000, 500.0)],
}


class _E(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _view(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _ok(body=None, status=200, headers=None, lro=False, rid="", verb=""):
    return {"status": status, "headers": headers or {}, "body": body, "lro": lro, "rid": rid, "verb": verb}


def _err(status, code, message):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}},
            "lro": False, "rid": "", "verb": ""}


def _to_bool(v):
    return v if isinstance(v, bool) else str(v).strip().lower() in ("true", "1", "yes", "on")


def _to_int(v, default=None):
    if isinstance(v, bool):
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _sysdata():
    return {"createdBy": "cloudlearn@vyomi.local", "createdByType": "User", "createdAt": _now(),
            "lastModifiedBy": "cloudlearn@vyomi.local", "lastModifiedByType": "User", "lastModifiedAt": _now()}


def _canon(sub, rg, chain, names):
    seg = ["/subscriptions/" + sub] + (["resourceGroups/" + rg] if rg else []) + ["providers", NAMESPACE]
    for i, t in enumerate(chain):
        seg.append(t)
        if i < len(names):
            seg.append(names[i])
    return "/".join(seg)


def _not_found(kind, name, rg):
    return _E(404, "ResourceNotFound",
              f"The Resource '{NAMESPACE}/{kind}/{name}' under resource group '{rg}' was not found. "
              "For more details please go to https://aka.ms/ARMResourceNotFoundFix")


def _canon_kind(kind):
    for k in KINDS:
        if k.lower() == str(kind or "").lower():
            return k
    return None


def _secret(*parts):
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:32]


# ── accounts ─────────────────────────────────────────────────────────────────
def _accounts(state, sub=None):
    t = f"{NAMESPACE}/accounts".lower()
    return [r for r in state.values() if str(r.get("_type", "")).lower() == t and (sub is None or r.get("_sub") == sub)]


def _subdomain_taken(state, sub_domain, except_id=None):
    for r in _accounts(state) + [g for g in state.values() if str(g.get("_type", "")).lower() == f"{NAMESPACE}/deletedaccounts".lower()]:
        if r["id"].lower() == (except_id or "").lower():
            continue
        if str(r.get("properties", {}).get("customSubDomainName") or "").lower() == sub_domain.lower():
            return True
    return False


def _name_problem(name):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{1,63}", name or ""):
        return ("InvalidResourceName", f"The resource name '{name}' is invalid. It must be 2-64 characters of letters, "
                                       "digits, hyphens and underscores and start with a letter or digit.")
    return None


def _subdomain_problem(sd):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,62}[A-Za-z0-9]", sd or ""):
        return f"The custom subdomain name '{sd}' is invalid. Use 2-64 letters, digits and hyphens; it must not start or end with a hyphen."
    return None


def _endpoint(kind, loc, sd):
    host = ENDPOINT_HOST.get(kind, DEFAULT_HOST)
    return f"https://{sd}.{host}/" if sd else f"https://{loc}.api.cognitive.microsoft.com/"


def _endpoints(kind, loc, sd):
    ep = _endpoint(kind, loc, sd)
    if kind == "OpenAI":
        return {"OpenAI Language Model Instance API": ep, "OpenAI Dall-E API": ep, "OpenAI Whisper API": ep}
    if kind == "AIServices" and sd:
        return {"AI Foundry API": f"https://{sd}.services.ai.azure.com/", "OpenAI Language Model Instance API": f"https://{sd}.openai.azure.com/",
                "Content Safety": ep, "Computer Vision": ep, "Speech Services": ep, "Text Translation": ep}
    return {kind: ep}


def _capabilities(kind):
    caps = [{"name": "VirtualNetworks"}, {"name": "CustomerManagedKey"}] if kind in NEEDS_SUBDOMAIN else []
    if kind in MODEL_KINDS:
        caps.append({"name": "FinetuneModels" if kind == "OpenAI" else "ModelSelection"})
    return caps


def _tier(sku):
    return "Free" if sku.upper().startswith("F") else "Standard"


def _new_account(rid, name, sub, rg, payload):
    kind = _canon_kind(payload.get("kind"))
    if not payload.get("kind"):
        raise _E(400, "InvalidParameter", "The 'kind' property is required.")
    if kind is None:
        raise _E(400, "InvalidParameter", f"The account kind '{payload.get('kind')}' is not supported. "
                                          f"Supported kinds: {', '.join(sorted(KINDS))}.")
    loc = payload.get("location")
    if not loc:
        raise _E(400, "LocationRequired", "The location property is required for this definition.")
    skus, default_sku = KINDS[kind]
    sku = (payload.get("sku") or {}).get("name") or default_sku
    if sku not in skus:
        raise _E(400, "InvalidSku", f"The sku '{sku}' is not available for kind '{kind}'. Available skus: {', '.join(skus)}.")
    pay = payload.get("properties") or {}
    sd = pay.get("customSubDomainName") or ""
    if sd:
        prob = _subdomain_problem(sd)
        if prob:
            raise _E(400, "InvalidSubdomainName", prob)
    return sd, kind, loc, sku, pay


def _build_account(rid, name, sub, rg, payload, kind, loc, sku, sd, pay, restore_from=None):
    props = {
        "endpoint": _endpoint(kind, loc, sd), "internalId": uuid.uuid5(uuid.NAMESPACE_URL, rid).hex,
        "dateCreated": _now(), "callRateLimit": {"renewalPeriod": 60, "count": 30 if sku.startswith("F") else 1000, "rules": []},
        "endpoints": _endpoints(kind, loc, sd), "capabilities": _capabilities(kind), "provisioningState": "Succeeded",
        "publicNetworkAccess": pay.get("publicNetworkAccess") or "Enabled", "disableLocalAuth": _to_bool(pay.get("disableLocalAuth", False)),
        "networkAcls": pay.get("networkAcls") or {"defaultAction": "Allow", "ipRules": [], "virtualNetworkRules": []},
        "privateEndpointConnections": [], "isMigrated": False,
        "skuChangeInfo": {"countOfDowngrades": 0, "countOfUpgradesAfterDowngrades": 0},
    }
    if sd:
        props["customSubDomainName"] = sd
    for opt in ("apiProperties", "encryption", "userOwnedStorage", "restrictOutboundNetworkAccess", "allowedFqdnList",
                "dynamicThrottlingEnabled", "storedCompletionsDisabled", "networkInjections"):
        if opt in pay:
            props[opt] = pay[opt]
    rec = {"id": rid, "name": name, "type": f"{NAMESPACE}/accounts", "kind": kind, "location": loc,
           "etag": '"' + uuid.uuid4().hex + '"', "sku": {"name": sku, "tier": _tier(sku)}, "tags": payload.get("tags") or {},
           "properties": props, "systemData": _sysdata(),
           "_type": f"{NAMESPACE}/accounts", "_sub": sub, "_rg": rg, "_created": _now(),
           "_keys": {"key1": _secret(rid, "key1", uuid.uuid4()), "key2": _secret(rid, "key2", uuid.uuid4())},
           "_deployments": {}, "_plans": {}, "_rai": {}, "_pec": {}, "_projects": {}}
    if restore_from:
        rec["_deployments"] = restore_from.get("_deployments") or {}
        rec["_plans"] = restore_from.get("_plans") or {}
        rec["_rai"] = restore_from.get("_rai") or {}
        rec["_keys"] = restore_from.get("_keys") or rec["_keys"]
    _apply_identity(rec, payload)
    return rec


def _apply_identity(rec, payload):
    ident = payload.get("identity")
    if not ident:
        return
    t = ident.get("type") or "None"
    out = {"type": t}
    if "SystemAssigned" in t:
        out["principalId"] = str(uuid.uuid5(uuid.NAMESPACE_URL, rec["id"] + "#p"))
        out["tenantId"] = "00000000-0000-0000-0000-000000000000"
    if "UserAssigned" in t:
        out["userAssignedIdentities"] = {k: {"principalId": str(uuid.uuid5(uuid.NAMESPACE_URL, k + "#p")),
                                              "clientId": str(uuid.uuid5(uuid.NAMESPACE_URL, k + "#c"))}
                                          for k in (ident.get("userAssignedIdentities") or {})}
    if t == "None":
        rec.pop("identity", None)
    else:
        rec["identity"] = out


def _deleted_id(sub, loc, rg, name):
    return f"/subscriptions/{sub}/providers/{NAMESPACE}/locations/{loc}/resourceGroups/{rg}/deletedAccounts/{name}"


def _deleted_view(rec):
    return {"id": rec["id"], "name": rec["name"], "type": f"{NAMESPACE}/deletedAccounts", "location": rec["location"],
            "properties": dict(rec["properties"])}


def _put_account(state, sub, rg, rid, name, payload, method):
    rec = state.get(rid.lower())
    if method == "PATCH":
        if rec is None:
            raise _not_found("accounts", name, rg)
        _patch_account(state, rec, payload)
        return rec, False
    prob = _name_problem(name)
    if prob:
        raise _E(400, prob[0], prob[1])
    if rec is not None:
        if payload.get("kind") and _canon_kind(payload["kind"]) != rec["kind"]:
            raise _E(409, "AccountKindImmutable", f"The kind of account '{name}' cannot be changed after creation.")
        _patch_account(state, rec, payload)
        return rec, False
    sd, kind, loc, sku, pay = _new_account(rid, name, sub, rg, payload)
    gone = state.get(_deleted_id(sub, loc, rg, name).lower())
    restore = _to_bool(pay.get("restore", False))
    if gone is not None and not restore:
        raise _E(409, "FlagMustBeSetForRestore",
                 f"An existing resource with ID '{rid}' has been soft-deleted. To restore the resource, you must specify "
                 "'restore' to be 'true' in the property. If you don't want to restore existing resource, please purge it first.")
    if restore and gone is None:
        raise _E(404, "ResourceNotFound", f"No soft-deleted account '{name}' was found to restore.")
    if sd and _subdomain_taken(state, sd, except_id=gone["id"] if gone else None):
        raise _E(409, "CustomDomainInUse", f"The custom domain name '{sd}' is already in use. Choose a different name.")
    if kind in NEEDS_SUBDOMAIN and kind in ("OpenAI", "AIServices") and not sd:
        sd = name.lower()                               # Azure derives it for the new AI/OpenAI accounts
        if _subdomain_taken(state, sd):
            raise _E(409, "CustomDomainInUse", f"The custom domain name '{sd}' is already in use. Choose a different name.")
    rec = _build_account(rid, name, sub, rg, payload, kind, loc, sku, sd, pay, restore_from=gone if restore else None)
    if gone is not None:
        state.pop(gone["id"].lower(), None)
    state[rid.lower()] = rec
    return rec, True


def _patch_account(state, rec, payload):
    if isinstance(payload.get("tags"), dict):
        rec["tags"] = payload["tags"]
    new_sku = (payload.get("sku") or {}).get("name")
    if new_sku and new_sku != rec["sku"]["name"]:
        if new_sku not in KINDS[rec["kind"]][0]:
            raise _E(400, "InvalidSku", f"The sku '{new_sku}' is not available for kind '{rec['kind']}'.")
        info = rec["properties"]["skuChangeInfo"]
        order = list(KINDS[rec["kind"]][0])
        if order.index(new_sku) < order.index(rec["sku"]["name"]):
            info["countOfDowngrades"] += 1
            info["lastChangeDate"] = _now()
        rec["sku"] = {"name": new_sku, "tier": _tier(new_sku)}
    pay = payload.get("properties") or {}
    p = rec["properties"]
    if pay.get("customSubDomainName") and pay["customSubDomainName"] != p.get("customSubDomainName"):
        if p.get("customSubDomainName"):
            raise _E(409, "CustomDomainImmutable", "The custom subdomain name cannot be changed once set.")
        if _subdomain_problem(pay["customSubDomainName"]):
            raise _E(400, "InvalidSubdomainName", _subdomain_problem(pay["customSubDomainName"]))
        if _subdomain_taken(state, pay["customSubDomainName"], except_id=rec["id"]):
            raise _E(409, "CustomDomainInUse", f"The custom domain name '{pay['customSubDomainName']}' is already in use.")
        p["customSubDomainName"] = pay["customSubDomainName"]
        p["endpoint"] = _endpoint(rec["kind"], rec["location"], p["customSubDomainName"])
        p["endpoints"] = _endpoints(rec["kind"], rec["location"], p["customSubDomainName"])
    if pay.get("publicNetworkAccess"):
        if pay["publicNetworkAccess"] not in ("Enabled", "Disabled"):
            raise _E(400, "InvalidParameter", "publicNetworkAccess must be 'Enabled' or 'Disabled'.")
        p["publicNetworkAccess"] = pay["publicNetworkAccess"]
    if "disableLocalAuth" in pay:
        p["disableLocalAuth"] = _to_bool(pay["disableLocalAuth"])
    if pay.get("networkAcls") is not None:
        p["networkAcls"] = pay["networkAcls"]
    for opt in ("apiProperties", "encryption", "userOwnedStorage", "restrictOutboundNetworkAccess", "allowedFqdnList",
                "dynamicThrottlingEnabled", "storedCompletionsDisabled"):
        if opt in pay:
            p[opt] = pay[opt]
    _apply_identity(rec, payload)
    rec["etag"] = '"' + uuid.uuid4().hex + '"'
    rec["systemData"]["lastModifiedAt"] = _now()


def _delete_account(state, rec):
    state.pop(rec["id"].lower(), None)
    did = _deleted_id(rec["_sub"], rec["location"], rec["_rg"], rec["name"])
    props = dict(rec["properties"])
    props.update({"deletionDate": _now(), "scheduledPurgeDate": _now(), "accountId": rec["id"]})
    state[did.lower()] = {"id": did, "name": rec["name"], "type": f"{NAMESPACE}/deletedAccounts", "location": rec["location"],
                          "properties": props, "_type": f"{NAMESPACE}/deletedAccounts", "_sub": rec["_sub"], "_rg": None,
                          "_deployments": rec.get("_deployments"), "_plans": rec.get("_plans"), "_rai": rec.get("_rai"),
                          "_keys": rec.get("_keys")}


def _account_view(rec):
    out = _view(rec)
    out["properties"] = dict(rec["properties"])
    out["properties"]["privateEndpointConnections"] = [dict(v) for v in rec.get("_pec", {}).values()]
    return out


# ── deployments / commitment plans / RAI policies ────────────────────────────
def _find_model(fmt, name, version):
    for m in MODELS:
        if m[0].lower() == str(fmt or "").lower() and m[1].lower() == str(name or "").lower() and (not version or m[2] == version):
            return m
    return None


def _model_obj(m):
    return {"format": m[0], "name": m[1], "version": m[2]}


def _deployment_view(acct, d):
    return {"id": f"{acct['id']}/deployments/{d['name']}", "name": d["name"], "type": f"{NAMESPACE}/accounts/deployments",
            "etag": d["etag"], "sku": d["sku"], "properties": d["properties"], "systemData": d["systemData"]}


def _deployment_ops(acct, rest, method, payload):
    deps = acct["_deployments"]
    if not rest:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": [_deployment_view(acct, d) for d in deps.values()]})
    name = rest[0]
    key = name.lower()
    rid = f"{acct['id']}/deployments/{name}"
    if len(rest) == 2 and rest[1].lower() == "skus" and method == "GET":
        if key not in deps:
            raise _E(404, "DeploymentNotFound", f"The Deployment '{name}' was not found.")
        return _ok({"value": [{"resourceType": "Microsoft.CognitiveServices/accounts/deployments", "sku": {"name": s, "capacity": {"minimum": 1, "maximum": QUOTA_LIMIT, "step": 1, "default": 1}}}
                              for s in DEPLOY_SKUS[:3]]})
    if method == "GET":
        if key not in deps:
            raise _E(404, "DeploymentNotFound", f"The Deployment '{name}' under account '{acct['name']}' was not found.")
        return _ok(_deployment_view(acct, deps[key]))
    if method in ("PUT", "PATCH"):
        if acct["kind"] not in MODEL_KINDS:
            raise _E(400, "InvalidParameter", f"Deployments are only supported on OpenAI and AIServices accounts, not '{acct['kind']}'.")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._~-]{0,63}", name):
            raise _E(400, "InvalidResourceName", f"The deployment name '{name}' is invalid.")
        old = deps.get(key)
        pay = payload.get("properties") or {}
        model_in = pay.get("model") or (old or {}).get("properties", {}).get("model")
        if not model_in:
            raise _E(400, "InvalidParameter", "properties.model is required.")
        m = _find_model(model_in.get("format") or "OpenAI", model_in.get("name"), model_in.get("version"))
        if m is None:
            raise _E(400, "DeploymentModelNotSupported",
                     f"The model '{model_in.get('name')}' version '{model_in.get('version')}' is not available for deployment.")
        sku = dict((old or {}).get("sku") or {"name": "Standard", "capacity": 1})
        sku.update({k: v for k, v in (payload.get("sku") or {}).items() if v is not None})
        if sku.get("name") not in DEPLOY_SKUS:
            raise _E(400, "InvalidSku", f"The deployment sku '{sku.get('name')}' is invalid. Use one of {', '.join(DEPLOY_SKUS)}.")
        cap = _to_int(sku.get("capacity"), 1)
        used = sum(x["sku"].get("capacity", 0) for k, x in deps.items() if k != key and x["sku"].get("name") == sku["name"]
                   and x["properties"]["model"]["name"] == m[1])
        if cap < 1 or used + cap > min(QUOTA_LIMIT, m[3]) :
            raise _E(400, "InsufficientQuota",
                     f"This operation require {cap} new capacity in quota 'Tokens Per Minute (thousands) - {m[1]}', which is bigger "
                     f"than the current available capacity {max(0, min(QUOTA_LIMIT, m[3]) - used)}. The current quota usage is {used} and the quota limit is {min(QUOTA_LIMIT, m[3])} for quota 'Tokens Per Minute (thousands) - {m[1]}'.")
        sku["capacity"] = cap
        caps = {c: "true" for c in m[4]}
        d = {"name": name, "etag": '"' + uuid.uuid4().hex + '"', "sku": sku, "systemData": (old or {}).get("systemData") or _sysdata(),
             "properties": {"model": _model_obj(m), "provisioningState": "Succeeded", "capabilities": caps,
                            "rateLimits": [{"key": "request", "renewalPeriod": 10, "count": cap * 6},
                                           {"key": "token", "renewalPeriod": 60, "count": cap * 1000}],
                            "versionUpgradeOption": pay.get("versionUpgradeOption") or (old or {}).get("properties", {}).get("versionUpgradeOption") or "OnceNewDefaultVersionAvailable",
                            "raiPolicyName": pay.get("raiPolicyName") or "Microsoft.DefaultV2", "currentCapacity": cap}}
        d["systemData"]["lastModifiedAt"] = _now()
        deps[key] = d
        return _ok(_deployment_view(acct, d), 200 if old else 201, lro=True, rid=rid, verb="put")
    if method == "DELETE":
        if key not in deps:
            return _ok(None, 204)
        del deps[key]
        return _ok(None, 200, lro=True, rid=rid, verb="delete")
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _plan_view(acct, p):
    return {"id": f"{acct['id']}/commitmentPlans/{p['name']}", "name": p["name"], "type": f"{NAMESPACE}/accounts/commitmentPlans",
            "etag": p["etag"], "properties": p["properties"], "systemData": p["systemData"]}


def _plan_ops(acct, rest, method, payload):
    plans = acct["_plans"]
    if not rest:
        return _ok({"value": [_plan_view(acct, p) for p in plans.values()]})
    name = rest[0]
    key = name.lower()
    rid = f"{acct['id']}/commitmentPlans/{name}"
    if method == "GET":
        if key not in plans:
            raise _E(404, "CommitmentPlanNotFound", f"The commitment plan '{name}' was not found.")
        return _ok(_plan_view(acct, plans[key]))
    if method in ("PUT", "PATCH"):
        pay = payload.get("properties") or {}
        old = plans.get(key)
        tiers = TIERS.get(acct["kind"])
        if not tiers and acct["kind"] not in ("AIServices", "CognitiveServices"):
            raise _E(400, "CommitmentPlanNotSupported", f"Commitment plans are not available for kind '{acct['kind']}'.")
        cur = dict(pay.get("current") or (old or {}).get("properties", {}).get("current") or {})
        if not cur and tiers:
            cur = {"tier": tiers[0][1], "count": 1}
        props = {"hostingModel": pay.get("hostingModel") or "Web", "planType": pay.get("planType") or (tiers[0][1] if tiers else "TA"),
                 "current": cur, "autoRenew": _to_bool(pay.get("autoRenew", False)), "provisioningIssues": [],
                 "commitmentPlanGuid": str(uuid.uuid5(uuid.NAMESPACE_URL, rid))}
        if pay.get("next"):
            props["next"] = pay["next"]
        plans[key] = {"name": name, "etag": '"' + uuid.uuid4().hex + '"', "properties": props, "systemData": _sysdata()}
        return _ok(_plan_view(acct, plans[key]), 200 if old else 201)
    if method == "DELETE":
        if key not in plans:
            return _ok(None, 204)
        del plans[key]
        return _ok(None, 200, lro=True, rid=rid, verb="delete")
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _rai_view(acct, r):
    return {"id": f"{acct['id']}/raiPolicies/{r['name']}", "name": r["name"], "type": f"{NAMESPACE}/accounts/raiPolicies",
            "etag": r["etag"], "properties": r["properties"], "systemData": r["systemData"]}


def _rai_ops(acct, rest, method, payload):
    pols = acct["_rai"]
    builtin = {"Microsoft.Default": "Default", "Microsoft.DefaultV2": "Default"}
    if not rest:
        items = [{"id": f"{acct['id']}/raiPolicies/{n}", "name": n, "type": f"{NAMESPACE}/accounts/raiPolicies",
                  "properties": {"type": "SystemManaged", "mode": "Blocking", "basePolicyName": n, "contentFilters": []}}
                 for n in builtin]
        return _ok({"value": items + [_rai_view(acct, r) for r in pols.values()]})
    name = rest[0]
    key = name.lower()
    if method == "GET":
        if name in builtin:
            return _ok({"id": f"{acct['id']}/raiPolicies/{name}", "name": name, "type": f"{NAMESPACE}/accounts/raiPolicies",
                        "properties": {"type": "SystemManaged", "mode": "Blocking", "basePolicyName": name, "contentFilters": []}})
        if key not in pols:
            raise _E(404, "RaiPolicyNotFound", f"The RAI policy '{name}' was not found.")
        return _ok(_rai_view(acct, pols[key]))
    if method == "PUT":
        pay = payload.get("properties") or {}
        old = pols.get(key)
        pols[key] = {"name": name, "etag": '"' + uuid.uuid4().hex + '"', "systemData": _sysdata(),
                     "properties": {"type": "UserManaged", "mode": pay.get("mode") or "Blocking",
                                    "basePolicyName": pay.get("basePolicyName") or "Microsoft.Default",
                                    "contentFilters": pay.get("contentFilters") or []}}
        return _ok(_rai_view(acct, pols[key]), 200 if old else 201, lro=True, rid=f"{acct['id']}/raiPolicies/{name}", verb="put")
    if method == "DELETE":
        pols.pop(key, None)
        return _ok(None, 200, lro=True, rid=f"{acct['id']}/raiPolicies/{name}", verb="delete")
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _pec_ops(acct, rest, method, payload):
    pecs = acct["_pec"]
    if not rest:
        return _ok({"value": list(pecs.values())})
    name = rest[0]
    if method == "GET":
        if name.lower() not in pecs:
            raise _E(404, "PrivateEndpointConnectionNotFound", f"The private endpoint connection '{name}' was not found.")
        return _ok(pecs[name.lower()])
    if method == "PUT":
        pay = payload.get("properties") or {}
        conn = {"id": f"{acct['id']}/privateEndpointConnections/{name}", "name": name,
                "type": f"{NAMESPACE}/accounts/privateEndpointConnections", "location": acct["location"],
                "properties": {"provisioningState": "Succeeded", "privateEndpoint": pay.get("privateEndpoint") or {},
                               "privateLinkServiceConnectionState": pay.get("privateLinkServiceConnectionState") or {"status": "Approved"},
                               "groupIds": ["account"]}}
        existed = name.lower() in pecs
        pecs[name.lower()] = conn
        return _ok(conn, 200 if existed else 201, lro=True, rid=conn["id"], verb="put")
    if method == "DELETE":
        pecs.pop(name.lower(), None)
        return _ok(None, 200, lro=True, rid=f"{acct['id']}/privateEndpointConnections/{name}", verb="delete")
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _usages(acct):
    out = [{"name": {"value": "TotalCalls", "localizedValue": "Total Calls"}, "unit": "Count", "currentValue": 0,
            "limit": 0 if acct["sku"]["name"].startswith("F") else 0, "quotaPeriod": "P30D", "status": "Included"}]
    if acct["kind"] in MODEL_KINDS:
        out = []
        for m in MODELS:
            used = sum(d["sku"].get("capacity", 0) for d in acct["_deployments"].values() if d["properties"]["model"]["name"] == m[1])
            out.append({"name": {"value": f"OpenAI.Standard.{m[1]}", "localizedValue": f"Tokens Per Minute (thousands) - {m[1]}"},
                        "unit": "Count", "currentValue": used, "limit": min(QUOTA_LIMIT, m[3]), "status": "Included"})
    return out


def _account_ops(state, rec, rest, method, payload, query):
    r0 = rest[0].lower()
    if r0 == "listkeys" and method == "POST":
        if rec["properties"].get("disableLocalAuth"):
            raise _E(400, "BadRequest", "Local authentication is disabled for this account; keys cannot be listed.")
        return _ok(dict(rec["_keys"]))
    if r0 == "regeneratekey" and method == "POST":
        kn = str(payload.get("keyName") or "").lower()
        if kn not in ("key1", "key2"):
            raise _E(400, "InvalidParameter", "keyName must be 'Key1' or 'Key2'.")
        rec["_keys"][kn] = _secret(rec["id"], kn, uuid.uuid4())
        return _ok(dict(rec["_keys"]))
    if r0 in ("skus", "listskus") and method == "GET":
        return _ok({"value": [{"resourceType": "accounts", "sku": {"name": s, "tier": _tier(s)}} for s in KINDS[rec["kind"]][0]]})
    if r0 == "usages" and method == "GET":
        return _ok({"value": _usages(rec)})
    if r0 == "models" and method == "GET":
        if rec["kind"] not in MODEL_KINDS:
            return _ok({"value": []})
        return _ok({"value": [_model_item(m, rec["kind"]) for m in MODELS]})
    if r0 == "deployments":
        return _deployment_ops(rec, rest[1:], method, payload)
    if r0 == "commitmentplans":
        return _plan_ops(rec, rest[1:], method, payload)
    if r0 == "raipolicies":
        return _rai_ops(rec, rest[1:], method, payload)
    if r0 == "privateendpointconnections":
        return _pec_ops(rec, rest[1:], method, payload)
    if r0 == "privatelinkresources" and method == "GET":
        pl = {"id": f"{rec['id']}/privateLinkResources/account", "name": "account",
              "type": f"{NAMESPACE}/accounts/privateLinkResources",
              "properties": {"groupId": "account", "requiredMembers": ["default"],
                             "requiredZoneNames": ["privatelink.cognitiveservices.azure.com"]}}
        return _ok({"value": [pl]})
    raise _E(404, "ResourceTypeNotSupported", f"The resource type '{NAMESPACE}/accounts/{rest[0]}' is not supported.")


def _model_item(m, kind="OpenAI"):
    return {"kind": kind, "skuName": "S0", "isDefaultVersion": True, "maxCapacity": m[3],
            "model": {"format": m[0], "name": m[1], "version": m[2], "lifecycleStatus": "GenerallyAvailable",
                      "capabilities": {c: "true" for c in m[4]},
                      "skus": [{"name": s, "usageName": f"OpenAI.{s}.{m[1]}", "capacity": {"maximum": m[3], "default": min(m[3], 30)}}
                               for s in DEPLOY_SKUS[:3]],
                      "maxCapacity": m[3]}}


# ── subscription / location scope ───────────────────────────────────────────
def _check_domain(state, sub, payload):
    sd = payload.get("subdomainName") or ""
    prob = _subdomain_problem(sd)
    if prob:
        return _ok({"isSubdomainAvailable": False, "reason": "Invalid", "subdomainName": sd, "type": payload.get("type"), "kind": payload.get("kind")} | {"message": prob})
    if _subdomain_taken(state, sd):
        return _ok({"isSubdomainAvailable": False, "reason": "NotAvailable", "subdomainName": sd, "type": payload.get("type"),
                    "kind": payload.get("kind")})
    return _ok({"isSubdomainAvailable": True, "subdomainName": sd, "type": payload.get("type"), "kind": payload.get("kind")})


def _check_sku(payload, loc):
    kind = _canon_kind(payload.get("kind"))
    if kind is None:
        raise _E(400, "InvalidParameter", f"The account kind '{payload.get('kind')}' is not supported.")
    out = []
    for s in payload.get("skus") or []:
        ok = s in KINDS[kind][0]
        item = {"kind": kind, "type": payload.get("type") or "Microsoft.CognitiveServices/accounts", "skuName": s, "skuAvailable": ok}
        if not ok:
            item.update({"reason": "SkuNotAvailable", "message": f"Sku '{s}' is not available for kind '{kind}' in {loc}."})
        out.append(item)
    return _ok({"value": out})


def _deleted_ops(state, sub, chain, method):
    gones = [r for r in state.values() if str(r.get("_type", "")).lower() == f"{NAMESPACE}/deletedAccounts".lower() and r.get("_sub") == sub]
    if len(chain) == 1:                                    # deletedAccounts (subscription list)
        return _ok({"value": [_deleted_view(r) for r in gones]})
    # locations/{loc}/resourceGroups/{rg}/deletedAccounts/{name}
    rg_name, name = chain[3], chain[5]
    rec = state.get(_deleted_id(sub, chain[1], rg_name, name).lower())
    if rec is None:
        rec = next((r for r in gones if r["name"].lower() == name.lower()), None)
    if rec is None:
        raise _E(404, "DeletedAccountNotFound", f"Soft-deleted account '{name}' was not found.")
    if method == "GET":
        return _ok(_deleted_view(rec))
    if method == "DELETE":
        state.pop(rec["id"].lower(), None)
        return _ok(None, 200, lro=True, rid=rec["id"], verb="purge")
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _location_ops(state, sub, chain, method, payload):
    loc = chain[1]
    what = chain[2].lower() if len(chain) > 2 else ""
    if what == "models" and method == "GET":
        return _ok({"value": [_model_item(m, k) for k in MODEL_KINDS for m in MODELS]})
    if what == "usages" and method == "GET":
        return _ok({"value": [{"name": {"value": "OpenAI.Standard.gpt-4o", "localizedValue": "Tokens Per Minute (thousands) - gpt-4o"},
                               "unit": "Count", "currentValue": 0, "limit": 450, "status": "Included"}]})
    if what == "commitmenttiers" and method == "GET":
        return _ok({"value": [{"kind": k, "skuName": "S0" if k != "TextAnalytics" else "S", "hostingModel": t[0], "planType": t[1],
                               "tier": t[2], "maxCount": 10, "quota": {"quantity": t[3], "unit": "Units"},
                               "cost": {"commitmentMonthlyFee": {"amount": t[4], "unit": "USD"}, "overageFee": {"amount": 1.0, "unit": "USD"}}}
                              for k, ts in TIERS.items() for t in ts]})
    if what == "checkskuavailability" and method == "POST":
        return _check_sku(payload, loc)
    if what == "resourcegroups" and len(chain) == 6 and chain[4].lower() == "deletedaccounts":
        return _deleted_ops(state, sub, chain, method)
    if what == "resourcegroups" and len(chain) == 6:
        pass
    raise _E(404, "ResourceTypeNotSupported", f"The resource type '{NAMESPACE}/{'/'.join(chain)}' is not supported.")


def _list_accounts(state, sub, rg):
    items = []
    for rec in _accounts(state, sub):
        if rg is not None and (rec.get("_rg") or "").lower() != rg.lower():
            continue
        items.append(_account_view(rec))
    return _ok({"value": items})


def dispatch(state, method, sub, rg, chain, names, payload=None, query=None, base=""):
    """Handle one ``Microsoft.CognitiveServices`` ARM request (``chain`` = tokens after the namespace)."""
    method = (method or "GET").upper()
    payload = payload if isinstance(payload, dict) else {}
    try:
        return _dispatch(state, method, sub, rg, list(chain), payload, query or {})
    except _E as e:
        return _err(e.status, e.code, e.message)


def _dispatch(state, method, sub, rg, chain, payload, query):
    low = chain[0].lower()
    if low == "checkdomainavailability":
        if method != "POST":
            return _err(405, "MethodNotAllowed", "POST required.")
        return _check_domain(state, sub, payload)
    if low == "skus":
        if method != "GET":
            return _err(405, "MethodNotAllowed", "GET required.")
        return _ok({"value": [{"resourceType": "accounts", "name": s, "tier": _tier(s), "kind": k,
                               "locations": ["EASTUS", "WESTUS", "WESTEUROPE"], "restrictions": []}
                              for k, (skus, _) in KINDS.items() for s in skus]})
    if low == "deletedaccounts":
        return _deleted_ops(state, sub, chain, method)
    if low == "locations":
        if len(chain) < 3:
            return _err(404, "ResourceTypeNotSupported", f"The resource type '{NAMESPACE}/{'/'.join(chain)}' is not supported.")
        return _location_ops(state, sub, chain, method, payload)
    if low == "commitmentplans" and len(chain) == 1:
        items = [_plan_view(a, p) for a in _accounts(state, sub) for p in a["_plans"].values()]
        return _ok({"value": items})
    if low != "accounts":
        return _err(404, "ResourceTypeNotSupported", f"The resource type '{NAMESPACE}/{chain[0]}' is not supported.")
    if len(chain) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _list_accounts(state, sub, rg)
    name = chain[1]
    rid = _canon(sub, rg, ["accounts"], [name])
    rec = state.get(rid.lower())
    rest = chain[2:]
    if rest:
        if rec is None:
            raise _not_found("accounts", name, rg)
        return _account_ops(state, rec, rest, method, payload, query)
    if method == "GET":
        if rec is None:
            raise _not_found("accounts", name, rg)
        return _ok(_account_view(rec))
    if method in ("PUT", "PATCH"):
        if rg is None:
            return _err(400, "InvalidResourceId", "Cognitive Services accounts must be created in a resource group.")
        rec, created = _put_account(state, sub, rg, rid, name, payload, method)
        return _ok(_account_view(rec), 201 if created else 200, lro=True, rid=rid, verb=method.lower())
    if method == "DELETE":
        if rec is None:
            return _ok(None, 204)
        _delete_account(state, rec)
        return _ok(None, 200, lro=True, rid=rid, verb="delete")
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def resource_types():
    return [("accounts", API_VERSION)]
