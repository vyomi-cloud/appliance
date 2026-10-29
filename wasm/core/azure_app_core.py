"""Azure Container Apps core (``Microsoft.App``) — substrate-independent.

Speaks the ARM control-plane REST API of the ``app`` resource provider
(azure-rest-api-specs ``specification/app``, api-version 2024-03-01), so the native
``azure-mgmt-appcontainers`` / ``armappcontainers`` / ``com.azure.resourcemanager.appcontainers``
SDKs and ``az containerapp`` / ``az rest`` work unchanged against it.

NO fastapi / azure-sdk / socket / subprocess imports → loads under Pyodide, so the SAME file
runs offline and in Nano. It does not own a store: it mutates the ARM resource map the
dispatchers already keep (``{lower-cased resource id: record}``), which is space-scoped and
persisted by the existing seams (offline ``azure_arm_state``; Nano ``az_arm`` via
core/nano_persist). Revisions, replicas, auth configs, Dapr components, storages,
certificates and job executions live INSIDE their parent record (underscore keys, never
serialised to clients) so the cost model counts one resource per app/environment/job.

Resource types
    Microsoft.App/managedEnvironments  (+ daprComponents, storages, certificates, workloadProfileStates)
    Microsoft.App/containerApps        (+ revisions, replicas, authConfigs, listSecrets, start, stop,
                                          getAuthToken, listCustomHostNameAnalysis)
    Microsoft.App/jobs                 (+ executions, start, stop, listSecrets)
Errors use the ARM shape ``{"error":{"code","message"}}``.

``dispatch`` returns ``{"status","headers","body","lro","rid","verb"}``; the caller adds the
Azure-AsyncOperation headers when ``lro`` is true and records the activity/CloudSim event.

An optional runtime hook (``RUNTIME``) lets the offline appliance run each revision's image
as a real container on the Pro/Max Docker backend; without it (Nano, Free/Lite) the service
is control-plane only and replicas are reported as simulated.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

NAMESPACE = "Microsoft.App"
API_VERSION = "2024-03-01"
DEFAULT_LOCATION = "eastus"
DEFAULT_IMAGE = "mcr.microsoft.com/k8se/quickstart:latest"
TYPES = ("managedenvironments", "containerapps", "jobs")
# Consumption plan cpu → allowed memory (Gi); Azure requires memory == 2 × cpu on Consumption.
CPU_CHOICES = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5, 3.75, 4.0)
ACTIVE_REVISIONS_MODES = ("Single", "Multiple")
TRANSPORTS = ("auto", "http", "http2", "tcp")
TRIGGER_TYPES = ("Manual", "Schedule", "Event")
MAX_REPLICAS_LIMIT = 1000

# Offline container runtime (set by the server on the Pro/Max Docker backend).
# RUNTIME["start"](app_id, revision, image, env, port) -> {"id","host","port"} | None
# RUNTIME["stop"](handle) -> None.  None → control plane only.
RUNTIME: dict = {"start": None, "stop": None}


def configure_runtime(start=None, stop=None):
    RUNTIME["start"], RUNTIME["stop"] = start, stop


class _E(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _h(*parts, n=8):
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:n]


def _view(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _ok(body=None, status=200, headers=None, lro=False, rid="", verb=""):
    return {"status": status, "headers": headers or {}, "body": body, "lro": lro, "rid": rid, "verb": verb}


def _err(status, code, message):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}},
            "lro": False, "rid": "", "verb": ""}


def _merge(a, b):
    out = dict(a)
    for k, v in (b or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


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


def _as_float(v, field):
    try:
        return float(v)
    except (TypeError, ValueError):
        raise _E(400, "InvalidParameterValueInContainerTemplate",
                 f"The following field(s) are either invalid or missing. Invalid value: \"{v}\": {field} must be a number.")


def _mem_gi(v):
    m = re.fullmatch(r"\s*([0-9.]+)\s*(Gi|Mi)?\s*", str(v))
    if not m:
        raise _E(400, "InvalidParameterValueInContainerTemplate",
                 f"The following field(s) are either invalid or missing. Invalid value: \"{v}\": memory must look like '1Gi'.")
    n = float(m.group(1))
    return n / 1024.0 if m.group(2) == "Mi" else n


def _to_int(v, default=None):
    """Console forms submit every field as a string."""
    if isinstance(v, bool):
        return default
    try:
        return int(v) if not isinstance(v, float) else int(v)
    except (TypeError, ValueError):
        return default


def _to_bool(v):
    return v if isinstance(v, bool) else str(v).strip().lower() in ("true", "1", "yes", "on")


def _fmt_gi(n):
    return ("%g" % n) + "Gi"


# ── validation + normalisation ───────────────────────────────────────────────
def _norm_containers(items, what="containers", require=True):
    items = items if isinstance(items, list) else []
    if require and not items:
        raise _E(400, "ContainerAppInvalidTemplate",
                 "The following field(s) are either invalid or missing. Field 'template.containers' is required and must contain at least one container.")
    out, seen = [], set()
    for i, c in enumerate(items):
        if not isinstance(c, dict) or not c.get("image"):
            raise _E(400, "InvalidParameterValueInContainerTemplate",
                     f"The following field(s) are either invalid or missing. Field 'template.{what}[{i}].image' is required.")
        c = dict(c)
        c.setdefault("name", re.sub(r"[^a-z0-9-]", "-", c["image"].rsplit("/", 1)[-1].split(":")[0].lower()).strip("-") or "app")
        if c["name"] in seen:
            raise _E(400, "InvalidParameterValueInContainerTemplate",
                     f"The following field(s) are either invalid or missing. Duplicate container name '{c['name']}'.")
        seen.add(c["name"])
        res = dict(c.get("resources") or {})
        cpu = _as_float(res.get("cpu", 0.5), f"template.{what}[{i}].resources.cpu")
        if cpu not in CPU_CHOICES:
            raise _E(400, "InvalidParameterValueInContainerTemplate",
                     f"The following field(s) are either invalid or missing. Invalid value: \"{res.get('cpu')}\": "
                     f"Total CPU {cpu} is not valid; use one of {', '.join('%g' % x for x in CPU_CHOICES)}.")
        mem = _mem_gi(res["memory"]) if res.get("memory") else cpu * 2
        if abs(mem - cpu * 2) > 1e-6:
            raise _E(400, "ContainerAppInvalidResourceTotal",
                     f"The total CPU and memory for the container group must follow a 1:2 ratio on the Consumption plan "
                     f"(cpu {cpu:g} requires memory {_fmt_gi(cpu * 2)}), got '{_fmt_gi(mem)}'.")
        res["cpu"], res["memory"] = cpu, _fmt_gi(mem)
        res.setdefault("ephemeralStorage", _fmt_gi(round(cpu * 2, 2)))
        c["resources"] = res
        c.setdefault("env", [])
        out.append(c)
    return out


def _norm_scale(scale):
    s = dict(scale or {})
    mn, mx = _to_int(s.get("minReplicas", 0)), _to_int(s.get("maxReplicas", 10))
    if not isinstance(mn, int) or not isinstance(mx, int) or mn < 0 or mx < 1 or mx > MAX_REPLICAS_LIMIT or mn > mx:
        raise _E(400, "InvalidParameterValueInContainerTemplate",
                 f"The following field(s) are either invalid or missing. Invalid scale: minReplicas={mn}, maxReplicas={mx} "
                 f"(0 <= minReplicas <= maxReplicas <= {MAX_REPLICAS_LIMIT}).")
    s["minReplicas"], s["maxReplicas"] = mn, mx
    s.setdefault("rules", [])
    return s


def _norm_template(t, require=True):
    t = dict(t or {})
    t["containers"] = _norm_containers(t.get("containers"), "containers", require)
    if t.get("initContainers"):
        t["initContainers"] = _norm_containers(t["initContainers"], "initContainers", False)
    t["scale"] = _norm_scale(t.get("scale"))
    t.setdefault("volumes", [])
    return t


def _norm_ingress(ing, app_name, domain, revisions_mode):
    if not ing:
        return None
    ing = dict(ing)
    ing["external"] = _to_bool(ing.get("external", False))
    ing["transport"] = ing.get("transport") or "Auto"
    if str(ing["transport"]).lower() not in TRANSPORTS:
        raise _E(400, "ContainerAppInvalidIngress", f"Invalid ingress transport '{ing['transport']}'; use auto, http, http2 or tcp.")
    port = _to_int(ing.get("targetPort", 80))
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise _E(400, "ContainerAppInvalidIngress", f"Invalid ingress targetPort '{port}'.")
    ing["targetPort"] = port
    ing["fqdn"] = f"{app_name}.{domain}" if ing["external"] else f"{app_name}.internal.{domain}"
    ing["allowInsecure"] = _to_bool(ing.get("allowInsecure", False))
    ing.setdefault("traffic", [{"latestRevision": True, "weight": 100}])
    total = sum(int(t.get("weight", 0)) for t in ing["traffic"])
    if total != 100:
        raise _E(400, "ContainerAppInvalidTraffic",
                 f"Traffic weights must add up to 100, got {total}.")
    return ing


def _domain_of(env):
    return (env.get("properties") or {}).get("defaultDomain", "example.azurecontainerapps.io")


# ── environments ─────────────────────────────────────────────────────────────
def _new_env(rid, name, sub, rg, payload):
    loc = payload.get("location") or DEFAULT_LOCATION
    uniq = _h(sub, rg, name, n=12)
    pay = payload.get("properties") or {}
    logs = pay.get("appLogsConfiguration") or {"destination": "log-analytics",
                                               "logAnalyticsConfiguration": {"customerId": str(uuid.uuid5(uuid.NAMESPACE_URL, rid))}}
    prof = pay.get("workloadProfiles") or [{"name": "Consumption", "workloadProfileType": "Consumption"}]
    props = {
        "provisioningState": "Succeeded",
        "defaultDomain": f"{_h(name, rg, n=6)}-{uniq[:8]}.{loc}.azurecontainerapps.io",
        "staticIp": "20.%d.%d.%d" % (int(uniq[0:2], 16) % 200 + 1, int(uniq[2:4], 16), int(uniq[4:6], 16) % 250 + 1),
        "appLogsConfiguration": logs,
        "zoneRedundant": bool(pay.get("zoneRedundant", False)),
        "workloadProfiles": prof,
        "infrastructureResourceGroup": f"ME_{name}_{rg}_{loc}",
        "peerAuthentication": {"mtls": {"enabled": False}},
        "peerTrafficConfiguration": {"encryption": {"enabled": False}},
        "eventStreamEndpoint": f"https://{loc}.azurecontainerapps.dev/subscriptions/{sub}/resourceGroups/{rg}/managedEnvironments/{name}/eventstream",
        "customDomainConfiguration": {"customDomainVerificationId": _h(rid, "cdv", n=32).upper()},
    }
    if pay.get("vnetConfiguration"):
        props["vnetConfiguration"] = pay["vnetConfiguration"]
    return {"id": rid, "name": name, "type": f"{NAMESPACE}/managedEnvironments", "location": loc,
            "kind": "Managed", "tags": {}, "properties": props,
            "systemData": _sysdata(), "_type": f"{NAMESPACE}/managedEnvironments", "_sub": sub, "_rg": rg,
            "_created": _now(), "_children": {}}


def _sysdata():
    n = _now()
    return {"createdBy": "vyomi@example.com", "createdByType": "User", "createdAt": n,
            "lastModifiedBy": "vyomi@example.com", "lastModifiedByType": "User", "lastModifiedAt": n}


def _ensure_env(state, sub, rg, env_id, loc):
    """The Azure portal creates the managed environment alongside the first app; do the same
    when no environment is named. An explicit id that does not exist is the real error."""
    if env_id:
        env = state.get(env_id.lower())
        if env is None:
            raise _E(400, "ManagedEnvironmentNotFound",
                     f"The environment '{env_id.rsplit('/', 1)[-1]}' does not exist. Specify a valid environment")
        return env
    name = f"cae-{rg}"[:32].rstrip("-")
    rid = _canon(sub, rg, ["managedEnvironments"], [name])
    env = state.get(rid.lower())
    if env is None:
        env = _new_env(rid, name, sub, rg, {"location": loc})
        state[rid.lower()] = env
    return env


# ── container apps ───────────────────────────────────────────────────────────
def _revision_name(app, suffix):
    return f"{app}--{suffix}"


def _make_revision(app_rec, tmpl, suffix, mode):
    name = _revision_name(app_rec["name"], suffix)
    ing = (app_rec["properties"].get("configuration") or {}).get("ingress") or {}
    fqdn = ing.get("fqdn") or ""
    rev_fqdn = fqdn.replace(app_rec["name"] + ".", name + ".", 1) if fqdn else ""
    n = _now()
    return {"id": f"{app_rec['id']}/revisions/{name}", "name": name, "type": f"{NAMESPACE}/containerApps/revisions",
            "properties": {"createdTime": n, "lastActiveTime": n, "fqdn": rev_fqdn, "template": tmpl,
                           "active": True, "replicas": 0, "trafficWeight": 0, "provisioningError": "",
                           "healthState": "Healthy", "provisioningState": "Provisioned", "runningState": "Running"},
            "_template_hash": _h(json.dumps(tmpl, sort_keys=True), n=16)}


def _replica_count(rev, app):
    p = rev["properties"]
    if not p["active"] or app["properties"].get("runningStatus") == "Stopped":
        return 0
    sc = (p["template"] or {}).get("scale") or {}
    return max(int(sc.get("minReplicas", 0)), 1) if (p["trafficWeight"] or sc.get("minReplicas")) else 0


def _refresh_revisions(app, start_runtime=True):
    """Recompute traffic weights / replica counts / app-level revision fields."""
    props = app["properties"]
    revs = app["_revisions"]
    ing = (props.get("configuration") or {}).get("ingress")
    latest = props.get("latestRevisionName")
    weights = {r: 0 for r in revs}
    if ing:
        for t in ing.get("traffic") or []:
            tgt = latest if t.get("latestRevision") else t.get("revisionName")
            if t.get("label") and t.get("revisionName") in revs and not t.get("weight"):
                continue
            if tgt in weights:
                weights[tgt] += int(t.get("weight", 0))
    for name, rev in revs.items():
        rev["properties"]["trafficWeight"] = weights.get(name, 0)
        rev["properties"]["replicas"] = _replica_count(rev, app)
    props["latestReadyRevisionName"] = latest
    if start_runtime:
        _sync_runtime(app)


def _sync_runtime(app):
    """Run / stop real containers for the active revisions when a runtime is attached."""
    st, stp = RUNTIME.get("start"), RUNTIME.get("stop")
    if not st:
        return
    handles = app.setdefault("_runtime", {})
    for name, rev in app["_revisions"].items():
        want = rev["properties"]["replicas"] > 0
        if want and name not in handles:
            tmpl = rev["properties"]["template"]
            c = tmpl["containers"][0]
            port = ((app["properties"].get("configuration") or {}).get("ingress") or {}).get("targetPort")
            try:
                h = st(app["id"], name, c["image"], {e.get("name"): e.get("value") for e in c.get("env", []) if e.get("name")}, port)
            except Exception:
                h = None
            if h:
                handles[name] = h
        elif not want and name in handles and stp:
            try:
                stp(handles.pop(name))
            except Exception:
                handles.pop(name, None)


def _stop_runtime(app):
    stp = RUNTIME.get("stop")
    for h in list((app.get("_runtime") or {}).values()):
        if stp:
            try:
                stp(h)
            except Exception:
                pass
    app["_runtime"] = {}


def _app_views(app):
    out = _view(app)
    cfg = out["properties"].get("configuration")
    if cfg and cfg.get("secrets"):                       # GET never returns secret values
        out["properties"] = dict(out["properties"])
        out["properties"]["configuration"] = dict(cfg, secrets=[{"name": s.get("name")} for s in cfg["secrets"]])
    return out


def _put_app(state, sub, rg, rid, name, payload, method):
    existed = state.get(rid.lower())
    pay = payload.get("properties") or {}
    if method == "PATCH":                                  # PATCH updates tags / identity only
        if not existed:
            raise _not_found("containerApps", name, rg)
        if isinstance(payload.get("tags"), dict):
            existed["tags"] = payload["tags"]
        if payload.get("identity"):
            existed["identity"] = payload["identity"]
        return existed
    loc = payload.get("location") or (existed or {}).get("location")
    if not loc:
        raise _E(400, "LocationRequired", "The location property is required for this definition.")
    env_id = pay.get("managedEnvironmentId") or pay.get("environmentId")
    if existed and not env_id:
        env_id = existed["properties"].get("managedEnvironmentId")
    env = _ensure_env(state, sub, rg, env_id, loc)
    domain = _domain_of(env)
    cfg = dict(pay.get("configuration") or {})
    mode = cfg.get("activeRevisionsMode", "Single")
    if mode not in ACTIVE_REVISIONS_MODES:
        raise _E(400, "ContainerAppInvalidConfiguration",
                 f"Invalid activeRevisionsMode '{mode}'; use one of {', '.join(ACTIVE_REVISIONS_MODES)}.")
    cfg["activeRevisionsMode"] = mode
    ing = _norm_ingress(cfg.get("ingress"), name, domain, mode)
    cfg["ingress"] = ing
    secrets = cfg.get("secrets") or []
    for s in secrets:
        if not s.get("name") or ("value" not in s and not s.get("keyVaultUrl")):
            raise _E(400, "ContainerAppSecretInvalid", "Secrets must have a name and a value or keyVaultUrl.")
    cfg["secrets"] = secrets
    cfg.setdefault("registries", [])
    cfg.setdefault("maxInactiveRevisions", 100)
    tmpl = _norm_template(pay.get("template") or ((existed or {}).get("properties") or {}).get("template"))
    for c in tmpl["containers"]:                           # secretRef must resolve
        for e in c.get("env", []):
            if e.get("secretRef") and e["secretRef"] not in {s["name"] for s in secrets}:
                raise _E(400, "ContainerAppSecretRefNotFound",
                         f"Secret '{e['secretRef']}' referenced by env var '{e.get('name')}' was not found.")
    if existed is None:
        uniq = _h(rid, "cdv", n=32).upper()
        rec = {"id": rid, "name": name, "type": f"{NAMESPACE}/containerApps", "location": loc, "tags": {},
               "systemData": _sysdata(), "_type": f"{NAMESPACE}/containerApps", "_sub": sub, "_rg": rg,
               "_created": _now(), "_revisions": {}, "_children": {}, "_runtime": {},
               "properties": {"provisioningState": "Succeeded", "runningStatus": "Running",
                              "customDomainVerificationId": uniq,
                              "outboundIpAddresses": [env["properties"]["staticIp"]],
                              "eventStreamEndpoint": f"https://{loc}.azurecontainerapps.dev/subscriptions/{sub}/resourceGroups/{rg}/containerApps/{name}/eventstream"}}
    else:
        rec = existed
    rec["location"] = loc
    rec["kind"] = payload.get("kind") or rec.get("kind") or "containerapps"
    if isinstance(payload.get("tags"), dict):
        rec["tags"] = payload["tags"]
    if payload.get("identity"):
        ident = dict(payload["identity"])
        if "SystemAssigned" in str(ident.get("type")):
            ident.setdefault("principalId", str(uuid.uuid5(uuid.NAMESPACE_URL, rid + "#p")))
            ident.setdefault("tenantId", "72f988bf-86f1-41af-91ab-2d7cd011db47")
        rec["identity"] = ident
    p = rec["properties"]
    p["managedEnvironmentId"] = env["id"]
    p["environmentId"] = env["id"]
    p["workloadProfileName"] = pay.get("workloadProfileName") or p.get("workloadProfileName") or "Consumption"
    p["configuration"] = cfg
    p["template"] = tmpl
    p["latestRevisionFqdn"] = (ing or {}).get("fqdn", "")
    p["provisioningState"] = "Succeeded"
    rec["_secrets"] = {s["name"]: s.get("value", "") for s in secrets}
    # revision handling: a changed template makes a new revision
    thash = _h(json.dumps(tmpl, sort_keys=True), n=16)
    revs = rec["_revisions"]
    cur = revs.get(p.get("latestRevisionName") or "")
    suffix = tmpl.get("revisionSuffix")
    if suffix and _revision_name(name, suffix) in revs and revs[_revision_name(name, suffix)]["_template_hash"] == thash:
        p["latestRevisionName"] = _revision_name(name, suffix)
    elif cur is None or cur["_template_hash"] != thash or (suffix and _revision_name(name, suffix) != cur["name"]):
        rev = _make_revision(rec, tmpl, suffix or _h(rid, thash, _now(), n=7), mode)
        if rev["name"] in revs:
            raise _E(409, "ContainerAppRevisionSuffixAlreadyExists",
                     f"Revision with suffix '{suffix}' already exists with a different template.")
        revs[rev["name"]] = rev
        p["latestRevisionName"] = rev["name"]
        if mode == "Single":                               # single mode keeps only the latest revision active
            for r in revs.values():
                if r["name"] != rev["name"]:
                    r["properties"]["active"] = False
    elif cur is not None:
        cur["properties"]["template"] = tmpl
    if mode == "Single":
        for r in revs.values():
            r["properties"]["active"] = r["name"] == p["latestRevisionName"]
    _prune_revisions(rec, cfg["maxInactiveRevisions"])
    state[rid.lower()] = rec
    _refresh_revisions(rec)
    return rec


def _prune_revisions(rec, keep):
    revs = rec["_revisions"]
    inactive = [n for n, r in revs.items() if not r["properties"]["active"]]
    for n in inactive[: max(0, len(inactive) - int(keep))]:
        revs.pop(n, None)


def _rev_view(rec, rev):
    out = _view(rev)
    out["properties"] = dict(rev["properties"])
    return out


def _replicas(rec, rev_name):
    rev = rec["_revisions"].get(rev_name)
    if rev is None:
        raise _E(404, "ResourceNotFound", f"Revision '{rev_name}' of container app '{rec['name']}' was not found.")
    n = rev["properties"]["replicas"]
    base = f"{rev_name}-{_h(rev_name, n=9)}"
    cs = rev["properties"]["template"]["containers"]
    out = []
    for i in range(n):
        rn = f"{base}-{_h(rev_name, i, n=5)}"
        out.append({"id": f"{rev['id']}/replicas/{rn}", "name": rn, "type": f"{NAMESPACE}/containerApps/revisions/replicas",
                    "properties": {"createdTime": rev["properties"]["createdTime"], "runningState": "Running",
                                   "runningStateDetails": "Running",
                                   "containers": [{"name": c["name"], "containerId": _h(rn, c["name"], n=32),
                                                   "ready": True, "started": True, "restartCount": 0,
                                                   "runningState": "Running", "runningStateDetails": ""} for c in cs]}})
    return out


def _app_action(state, rec, action, sub, rg, payload, rest, method):
    if action == "listsecrets" and method == "POST":
        return _ok({"value": [{"name": k, "value": v} for k, v in rec["_secrets"].items()]})
    if action in ("start", "stop") and method == "POST":
        rec["properties"]["runningStatus"] = "Running" if action == "start" else "Stopped"
        _refresh_revisions(rec)
        return _ok(_app_views(rec), 200, lro=True, rid=rec["id"], verb=action)
    if action == "getauthtoken":
        return _ok({"properties": {"token": _h(rec["id"], _now(), n=40), "expires": _now()}}, lro=False)
    if action == "listcustomhostnameanalysis":
        return _ok({"hostName": (payload or {}).get("customHostname", ""), "isHostnameAlreadyVerified": False,
                    "customDomainVerificationTest": "Failed", "conflictingContainerAppResourceId": "",
                    "customDomainVerificationFailureInfo": None, "hasConflictOnManagedEnvironment": False,
                    "cnameRecords": [rec["properties"].get("latestRevisionFqdn", "")], "txtRecords": [], "aRecords": []})
    return _err(404, "ResourceTypeNotSupported", f"Action '{action}' is not supported on containerApps.")


def _revision_ops(state, rec, rest, method):
    # rest: [revisionName] | [revisionName, action] | [revisionName, "replicas"] | [revisionName, "replicas", name]
    revs = rec["_revisions"]
    if not rest:
        return _ok({"value": [_rev_view(rec, r) for r in revs.values()]})
    name = rest[0]
    rev = revs.get(name)
    if rev is None:
        raise _E(404, "ResourceNotFound", f"Revision '{name}' of container app '{rec['name']}' was not found.")
    if len(rest) == 1:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Revisions support GET only.")
        return _ok(_rev_view(rec, rev))
    sub = rest[1].lower()
    if sub == "replicas":
        reps = _replicas(rec, name)
        if len(rest) == 2:
            return _ok({"value": reps})
        hit = next((r for r in reps if r["name"] == rest[2]), None)
        if not hit:
            raise _E(404, "ResourceNotFound", f"Replica '{rest[2]}' was not found.")
        return _ok(hit)
    if method != "POST":
        return _err(405, "MethodNotAllowed", f"{sub} requires POST.")
    mode = rec["properties"]["configuration"]["activeRevisionsMode"]
    if sub == "activate":
        rev["properties"]["active"] = True
        rev["properties"]["lastActiveTime"] = _now()
    elif sub == "deactivate":
        if mode == "Single":
            raise _E(400, "ContainerAppRevisionModeSingle",
                     "Revisions cannot be deactivated while the container app is in Single revision mode.")
        rev["properties"]["active"] = False
    elif sub == "restart":
        rev["properties"]["lastActiveTime"] = _now()
    else:
        return _err(404, "ResourceTypeNotSupported", f"Action '{sub}' is not supported on revisions.")
    _refresh_revisions(rec)
    return _ok(None, 200)


# ── jobs ─────────────────────────────────────────────────────────────────────
def _put_job(state, sub, rg, rid, name, payload, method):
    existed = state.get(rid.lower())
    pay = payload.get("properties") or {}
    if method == "PATCH":
        if not existed:
            raise _not_found("jobs", name, rg)
        if isinstance(payload.get("tags"), dict):
            existed["tags"] = payload["tags"]
        return existed
    loc = payload.get("location") or (existed or {}).get("location")
    if not loc:
        raise _E(400, "LocationRequired", "The location property is required for this definition.")
    env_id = pay.get("environmentId") or pay.get("managedEnvironmentId") or ((existed or {}).get("properties") or {}).get("environmentId")
    env = _ensure_env(state, sub, rg, env_id, loc)
    cfg = dict(pay.get("configuration") or {})
    trig = cfg.get("triggerType", "Manual")
    if trig not in TRIGGER_TYPES:
        raise _E(400, "ContainerAppJobInvalidConfiguration", f"Invalid triggerType '{trig}'; use one of {', '.join(TRIGGER_TYPES)}.")
    cfg["triggerType"] = trig
    cfg.setdefault("replicaTimeout", 1800)
    cfg.setdefault("replicaRetryLimit", 0)
    if trig == "Manual":
        cfg["manualTriggerConfig"] = dict({"parallelism": 1, "replicaCompletionCount": 1}, **(cfg.get("manualTriggerConfig") or {}))
    elif trig == "Schedule":
        sc = dict(cfg.get("scheduleTriggerConfig") or {})
        if not sc.get("cronExpression"):
            raise _E(400, "ContainerAppJobInvalidConfiguration", "scheduleTriggerConfig.cronExpression is required for Schedule jobs.")
        cfg["scheduleTriggerConfig"] = dict({"parallelism": 1, "replicaCompletionCount": 1}, **sc)
    cfg.setdefault("secrets", [])
    cfg.setdefault("registries", [])
    tmpl = _norm_template(pay.get("template") or ((existed or {}).get("properties") or {}).get("template"))
    tmpl.pop("scale", None)
    rec = existed or {"id": rid, "name": name, "type": f"{NAMESPACE}/jobs", "tags": {}, "systemData": _sysdata(),
                      "_type": f"{NAMESPACE}/jobs", "_sub": sub, "_rg": rg, "_created": _now(), "_executions": [],
                      "_children": {}}
    rec["location"] = loc
    if isinstance(payload.get("tags"), dict):
        rec["tags"] = payload["tags"]
    rec["properties"] = {"provisioningState": "Succeeded", "environmentId": env["id"],
                         "workloadProfileName": pay.get("workloadProfileName") or "Consumption",
                         "configuration": cfg, "template": tmpl, "outboundIpAddresses": [env["properties"]["staticIp"]],
                         "eventStreamEndpoint": f"https://{loc}.azurecontainerapps.dev/subscriptions/{sub}/resourceGroups/{rg}/jobs/{name}/eventstream"}
    rec["_secrets"] = {s["name"]: s.get("value", "") for s in cfg["secrets"]}
    state[rid.lower()] = rec
    return rec


def _job_view(rec):
    out = _view(rec)
    cfg = out["properties"].get("configuration") or {}
    if cfg.get("secrets"):
        out["properties"] = dict(out["properties"])
        out["properties"]["configuration"] = dict(cfg, secrets=[{"name": s.get("name")} for s in cfg["secrets"]])
    return out


def _execution(rec, template=None):
    n = len(rec["_executions"]) + 1
    name = f"{rec['name']}-{_h(rec['id'], n, n=7)}"
    now = _now()
    ex = {"id": f"{rec['id']}/executions/{name}", "name": name, "type": f"{NAMESPACE}/jobs/executions",
          "properties": {"status": "Succeeded", "startTime": now, "endTime": now,
                         "template": template or rec["properties"]["template"]}}
    rec["_executions"].append(ex)
    return ex


def _job_ops(state, rec, rest, method, payload):
    a = rest[0].lower()
    if a == "start" and method == "POST":
        tmpl = _norm_template(payload.get("template"), False) if payload.get("template") else None
        if tmpl is not None and not tmpl.get("containers"):
            tmpl = None
        ex = _execution(rec, tmpl)
        return _ok({"name": ex["name"], "id": ex["id"]}, 202, lro=True, rid=rec["id"], verb="start")
    if a == "stop" and method == "POST":
        return _ok(None, 202, lro=True, verb="stop", rid=rec["id"])
    if a == "listsecrets" and method == "POST":
        return _ok({"value": [{"name": k, "value": v} for k, v in rec["_secrets"].items()]})
    if a == "executions":
        ex = rec["_executions"]
        if len(rest) == 1:
            return _ok({"value": ex[::-1]})
        hit = next((e for e in ex if e["name"] == rest[1]), None)
        if hit is None:
            raise _E(404, "ResourceNotFound", f"Job execution '{rest[1]}' was not found.")
        if len(rest) == 3 and rest[2].lower() == "stop" and method == "POST":
            return _ok(None, 202)
        return _ok(hit)
    return _err(404, "ResourceTypeNotSupported", f"Action '{rest[0]}' is not supported on jobs.")


# ── environment children ────────────────────────────────────────────────────
def _child_ops(rec, ctype, rest, method, payload, rid_prefix):
    """Generic nested child CRUD (daprComponents, storages, certificates, authConfigs) kept in the parent."""
    store = rec["_children"].setdefault(ctype, {})
    full = f"{NAMESPACE}/{rec['type'].split('/', 1)[1]}/{ctype}"
    if not rest:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _ok({"value": list(store.values())})
    name = rest[0]
    cid = f"{rec['id']}/{ctype}/{name}"
    if method == "GET":
        if name not in store:
            raise _E(404, "ResourceNotFound", f"The Resource '{full}/{name}' was not found.")
        return _ok(store[name])
    if method in ("PUT", "PATCH"):
        pr = dict(payload.get("properties") or {})
        if ctype == "daprComponents":
            if not pr.get("componentType"):
                raise _E(400, "InvalidRequest", "properties.componentType is required.")
            pr.setdefault("version", "v1")
            pr.setdefault("metadata", [])
            pr.setdefault("scopes", [])
        if ctype == "storages":
            af = pr.get("azureFile") or {}
            if not (af.get("accountName") and af.get("shareName")):
                raise _E(400, "InvalidRequest", "properties.azureFile.accountName and shareName are required.")
            pr["azureFile"] = {"accountName": af["accountName"], "shareName": af["shareName"],
                               "accessMode": af.get("accessMode", "ReadWrite")}
        if ctype == "authConfigs":
            pr.setdefault("platform", {"enabled": False})
            pr.setdefault("globalValidation", {"unauthenticatedClientAction": "RedirectToLoginPage"})
        if ctype == "certificates":
            pr.setdefault("provisioningState", "Succeeded")
            pr.setdefault("subjectName", name)
            pr.setdefault("thumbprint", _h(cid, n=40).upper())
            pr.pop("value", None)
        cur = store.get(name)
        if cur and method == "PATCH":
            pr = _merge(cur["properties"], pr)
        store[name] = {"id": cid, "name": name, "type": f"{NAMESPACE}/{rec['type'].split('/', 1)[1]}/{ctype}",
                       "properties": pr, "systemData": _sysdata()}
        return _ok(store[name], 200)
    if method == "DELETE":
        had = store.pop(name, None)
        return _ok(None, 200 if had else 204)
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


def _env_ops(state, rec, rest, method, payload):
    sub = rest[0].lower()
    if sub in ("daprcomponents", "storages", "certificates"):
        ctype = {"daprcomponents": "daprComponents", "storages": "storages", "certificates": "certificates"}[sub]
        return _child_ops(rec, ctype, rest[1:], method, payload, rec["id"])
    if sub == "workloadprofilestates":
        ws = rec["properties"].get("workloadProfiles") or []
        return _ok({"value": [{"id": f"{rec['id']}/workloadProfileStates/{w['name']}", "name": w["name"],
                               "type": f"{NAMESPACE}/managedEnvironments/workloadProfileStates",
                               "properties": {"minimumCount": 0, "maximumCount": 0, "currentCount": 0}} for w in ws]})
    if sub == "getauthtoken" and method == "POST":
        return _ok({"properties": {"token": _h(rec["id"], _now(), n=40), "expires": _now()}})
    return _err(404, "ResourceTypeNotSupported", f"'{rest[0]}' is not supported on managedEnvironments.")


# ── dispatch ────────────────────────────────────────────────────────────────
def _list(state, sub, rg, tname, view):
    items = []
    for rec in state.values():
        if str(rec.get("_type", "")).lower() != f"{NAMESPACE}/{tname}".lower() or rec.get("_sub") != sub:
            continue
        if rg is not None and (rec.get("_rg") or "").lower() != rg.lower():
            continue
        items.append(view(rec))
    return _ok({"value": items})


def dispatch(state, method, sub, rg, chain, names, payload=None, query=None):
    """Handle one ``Microsoft.App`` ARM request.

    ``chain``  = path tokens after the namespace, e.g. ``["containerApps", "web", "revisions", "web--abc"]``
    ``state``  = the ARM resource map (lower-cased id → record).
    """
    method = (method or "GET").upper()
    payload = payload if isinstance(payload, dict) else {}
    try:
        return _dispatch(state, method, sub, rg, list(chain), payload)
    except _E as e:
        return _err(e.status, e.code, e.message)


def _dispatch(state, method, sub, rg, chain, payload):
    tname = chain[0]
    low = tname.lower()
    if low not in TYPES:
        return _err(404, "ResourceTypeNotSupported", f"The resource type '{NAMESPACE}/{tname}' is not supported.")
    canon = {"managedenvironments": "managedEnvironments", "containerapps": "containerApps", "jobs": "jobs"}[low]
    view = {"managedenvironments": _view, "containerapps": _app_views, "jobs": _job_view}[low]
    if len(chain) == 1:                                    # collection list
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        return _list(state, sub, rg, canon, view)
    name = chain[1]
    rid = _canon(sub, rg, [canon], [name])
    rec = state.get(rid.lower())
    rest = chain[2:]
    if rest:                                               # sub-resource / action
        if rec is None or str(rec.get("_type", "")).lower() != f"{NAMESPACE}/{canon}".lower():
            raise _not_found(canon, name, rg)
        r0 = rest[0].lower()
        if low == "containerapps":
            if r0 == "revisions":
                return _revision_ops(state, rec, rest[1:], method)
            if r0 == "authconfigs":
                return _child_ops(rec, "authConfigs", rest[1:], method, payload, rec["id"])
            return _app_action(state, rec, r0, sub, rg, payload, rest, method)
        if low == "jobs":
            return _job_ops(state, rec, rest, method, payload)
        return _env_ops(state, rec, rest, method, payload)
    if method == "GET":
        if rec is None:
            raise _not_found(canon, name, rg)
        return _ok(view(rec))
    if method in ("PUT", "PATCH"):
        if rg is None:
            return _err(400, "InvalidResourceId", "Container Apps resources must be created in a resource group.")
        if low == "managedenvironments":
            bad = not re.fullmatch(r"[A-Za-z0-9][-A-Za-z0-9_]{0,59}", name)
        else:
            bad = not re.fullmatch(r"[a-z]([-a-z0-9]{0,30}[a-z0-9])?", name) or "--" in name
        if bad:
            return _err(400, "ContainerAppInvalidName",
                        f"Invalid ContainerApp name '{name}'. A name must consist of lower case alphanumeric characters or '-', "
                        "start with an alphabetic character, and end with an alphanumeric character and cannot have '--'. "
                        "The length must not be more than 32 characters.")
        existed = rec is not None
        if low == "managedenvironments":
            if method == "PATCH":
                if not rec:
                    raise _not_found(canon, name, rg)
                if isinstance(payload.get("tags"), dict):
                    rec["tags"] = payload["tags"]
            else:
                if rec is None:
                    rec = _new_env(rid, name, sub, rg, payload)
                    state[rid.lower()] = rec
                else:
                    if isinstance(payload.get("tags"), dict):
                        rec["tags"] = payload["tags"]
                    if (payload.get("properties") or {}).get("appLogsConfiguration"):
                        rec["properties"]["appLogsConfiguration"] = payload["properties"]["appLogsConfiguration"]
                    if (payload.get("properties") or {}).get("workloadProfiles"):
                        rec["properties"]["workloadProfiles"] = payload["properties"]["workloadProfiles"]
        elif low == "containerapps":
            rec = _put_app(state, sub, rg, rid, name, payload, method)
        else:
            rec = _put_job(state, sub, rg, rid, name, payload, method)
        return _ok(view(rec), 200 if existed else 201, lro=True, rid=rid, verb=method.lower())
    if method == "DELETE":
        if rec is None:
            return _ok(None, 204)
        if low == "managedenvironments":
            users = [r for r in state.values() if str(r.get("_type", "")).lower() in (f"{NAMESPACE}/containerapps".lower(), f"{NAMESPACE}/jobs".lower())
                     and str((r.get("properties") or {}).get("environmentId", "")).lower() == rid.lower()]
            if users:
                raise _E(409, "ManagedEnvironmentHasContainerApps",
                         f"Cannot delete managed environment '{name}': it still contains {len(users)} container app(s)/job(s). "
                         "Delete them first.")
        if low == "containerapps":
            _stop_runtime(rec)
        state.pop(rid.lower(), None)
        return _ok(None, 200, rid=rid, verb="delete")
    return _err(405, "MethodNotAllowed", f"{method} not allowed.")


# ── catalog helpers shared with the dispatchers / console ───────────────────
def resource_types():
    return [("managedEnvironments", API_VERSION), ("containerApps", API_VERSION), ("jobs", API_VERSION)]


def location_operation(path_tail, op_id):
    """Microsoft.App/locations/{loc}/operationResults|operationStatuses/{id} → completed."""
    return {"id": path_tail, "name": op_id, "status": "Succeeded", "startTime": _now(), "endTime": _now()}
