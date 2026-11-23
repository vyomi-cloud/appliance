"""GCP Infrastructure Manager core (config.googleapis.com v1) - substrate-independent.

Speaks the REST shape of the real **Infrastructure Manager API**:
    projects/{p}/locations/{l}/deployments[/{d}]                    create (?deploymentId=) / get / list / patch / delete
    projects/{p}/locations/{l}/deployments/{d}/revisions[/{r}]      get / list
    projects/{p}/locations/{l}/deployments/{d}/revisions/{r}/resources[/{id}]
    projects/{p}/locations/{l}/previews[/{id}]                      create (?previewId=) / get / list / delete
    projects/{p}/locations/{l}/operations/{id}                      get (every mutation returns a long-running operation)
Errors use the Google shape {"error":{"code","message","status"}}.

NO fastapi / socket / subprocess imports, so the SAME file runs on the appliance and in Nano (Pyodide).

How "apply" works - an honest state machine, not a Terraform binary: the blueprint's HCL is parsed
(`parse_hcl`), and every resource of a type the simulator understands is created through the SAME native
Google REST APIs the console and the SDKs use (the `call` hook the wire router passes in). Supported:
google_storage_bucket, google_pubsub_topic, google_pubsub_subscription, google_compute_network,
google_compute_subnetwork, google_compute_firewall. Anything else is reported explicitly per resource
(state FAILED-free, but listed under `applyResults.vyomiUnsupported` and in the revision's stateDetail);
it is never silently dropped and never pretended to be created. Apply is idempotent: a resource that
already exists is reported `unchanged`. Operations complete synchronously (no timer thread), so every
operation is returned already `done`.

Blueprint sources: `terraformBlueprint.gcsSource` ("gs://bucket/object.tf", read from the simulator's own
Cloud Storage) or the Vyomi extension `terraformBlueprint.vyomiFiles` ({"main.tf": "..."}). gitSource is
not fetched (the simulator makes no network calls) and is rejected with FAILED_PRECONDITION.
"""
from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import quote


# --------------------------------------------------------------------------- store
class InfraManagerStore:
    """Public dict attrs only -> persisted/synced by core/nano_persist."""

    def __init__(self):
        self.deployments: dict = {}   # full name -> Deployment resource
        self.revisions: dict = {}     # full name -> Revision resource
        self.previews: dict = {}      # full name -> Preview resource
        self.operations: dict = {}    # full name -> Operation
        self.resources: dict = {}     # full revision name -> [Resource ...]
        self.files: dict = {}         # full deployment name -> {filename: text} (the active blueprint)


_SHARED = None


def shared_store() -> InfraManagerStore:
    global _SHARED
    if _SHARED is None:
        _SHARED = InfraManagerStore()
    return _SHARED


@dataclass
class IMResponse:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = "application/json"


class _E(Exception):
    def __init__(self, status, gcp_status, message):
        super().__init__(message)
        self.status, self.gcp_status, self.message = status, gcp_status, message


def _err(status, gcp_status, message):
    return IMResponse(status=status, body=json.dumps({"error": {"code": status, "message": message, "status": gcp_status}}).encode())


def _json(status, obj):
    return IMResponse(status=status, body=json.dumps(obj).encode())


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# --------------------------------------------------------------------------- HCL (the subset exports and hand-written configs use)
class _Ref(str):
    """An unresolved reference expression such as google_compute_network.vpc.id or var.project_id."""


_TOK = re.compile(r'''
    (?P<ws>[ \t\r]+)
  | (?P<nl>\n)
  | (?P<cm>\#[^\n]*|//[^\n]*|/\*.*?\*/)
  | (?P<heredoc><<-?[A-Z_][A-Z0-9_]*)
  | (?P<str>"(?:\\.|[^"\\])*")
  | (?P<num>-?\d+(?:\.\d+)?(?![A-Za-z_]))
  | (?P<id>[A-Za-z_][A-Za-z0-9_\-]*(?:\.[A-Za-z_*0-9][A-Za-z0-9_\-]*|\[[^\]]*\])*)
  | (?P<p>[{}\[\](),=:?+*/%<>!&|.-]+)
''', re.X | re.S)


def _tokens(text):
    pos, out = 0, []
    while pos < len(text):
        m = _TOK.match(text, pos)
        if not m:
            raise ValueError("HCL syntax error near %r" % text[pos:pos + 30])
        kind = m.lastgroup
        if kind == "heredoc":   # <<EOT ... EOT
            tag = m.group().lstrip("<-")
            end = re.compile(r"^[ \t]*%s[ \t]*$" % tag, re.M).search(text, m.end())
            if not end:
                raise ValueError("unterminated heredoc %s" % tag)
            body = text[m.end():end.start()].lstrip("\n")
            out.append(("str", body))
            pos = end.end()
            continue
        if kind == "str":
            try:
                out.append(("str", json.loads(m.group())))
            except Exception:
                out.append(("str", m.group()[1:-1]))
        elif kind == "p":
            for ch in m.group():   # split punctuation clusters into single chars, but keep => and == etc. unneeded
                out.append(("p", ch))
        elif kind not in ("ws", "cm"):
            out.append((kind, m.group()))
        pos = m.end()
    return out


class _Parser:
    def __init__(self, toks):
        self.t, self.i = toks, 0

    def peek(self):
        j = self.i
        while j < len(self.t) and self.t[j][0] == "nl":
            j += 1
        return self.t[j] if j < len(self.t) else (None, None)

    def skip_nl(self):
        while self.i < len(self.t) and self.t[self.i][0] == "nl":
            self.i += 1

    def next(self):
        self.skip_nl()
        if self.i >= len(self.t):
            raise ValueError("unexpected end of file")
        tok = self.t[self.i]
        self.i += 1
        return tok

    def expect(self, ch):
        k, v = self.next()
        if v != ch:
            raise ValueError("expected %r, found %r" % (ch, v))

    def body(self, until_brace):
        attrs, blocks = {}, []
        while True:
            k, v = self.peek()
            if k is None:
                if until_brace:
                    raise ValueError("missing closing brace")
                return attrs, blocks
            if v == "}" and until_brace:
                self.next()
                return attrs, blocks
            k, name = self.next()
            if k not in ("id", "str"):
                raise ValueError("unexpected %r" % (name,))
            k2, v2 = self.peek()
            if v2 in ("=", ":") and k2 == "p":
                self.next()
                attrs[name] = self.value()
            else:
                labels = []
                while self.peek()[0] in ("str", "id") and self.peek()[1] != "{":
                    labels.append(self.next()[1])
                self.expect("{")
                a, b = self.body(True)
                blocks.append({"type": name, "labels": labels, "attrs": a, "blocks": b})

    def value(self):
        v = self.primary()
        # swallow simple operators / conditional / splat so a later attribute still parses
        while self.peek()[0] == "p" and self.peek()[1] in "+*/%<>!&|-.":
            self.next()
            self.primary()
            v = _Ref("expr")
        return v

    def primary(self):
        k, v = self.next()
        if k == "str":
            return v
        if k == "num":
            return float(v) if "." in v else int(v)
        if k == "id":
            if v in ("true", "false"):
                return v == "true"
            if v == "null":
                return None
            if self.peek() == ("p", "("):   # function call: keep as an unresolved expression
                self.next()
                depth = 1
                while depth:
                    kk, vv = self.next()
                    depth += (vv == "(") - (vv == ")") if kk == "p" else 0
                return _Ref(v + "(...)")
            return _Ref(v)
        if v == "[":
            xs = []
            while self.peek()[1] != "]":
                xs.append(self.value())
                if self.peek()[1] == ",":
                    self.next()
            self.next()
            return xs
        if v == "{":
            d = {}
            while self.peek()[1] != "}":
                kk, key = self.next()
                if self.peek()[1] in ("=", ":"):
                    self.next()
                d[key] = self.value()
                if self.peek()[1] == ",":
                    self.next()
            self.next()
            return d
        if v == "(":
            x = self.value()
            self.expect(")")
            return x
        raise ValueError("unexpected %r" % (v,))


def parse_hcl(text):
    """-> {"resources":[{type,name,attrs,blocks}], "variables":{name:{default,...}}, "locals":{...}}"""
    attrs, blocks = _Parser(_tokens(text)).body(False)
    out = {"resources": [], "variables": {}, "locals": {}, "data": []}
    for b in blocks:
        t, lab = b["type"], b["labels"]
        if t == "resource" and len(lab) == 2:
            out["resources"].append({"type": lab[0], "name": lab[1], "attrs": b["attrs"], "blocks": b["blocks"]})
        elif t == "variable" and lab:
            out["variables"][lab[0]] = b["attrs"]
        elif t == "locals":
            out["locals"].update(b["attrs"])
        elif t == "data" and len(lab) == 2:
            out["data"].append({"type": lab[0], "name": lab[1]})
    return out


# --------------------------------------------------------------------------- resource handlers (native Google REST)
def _enc(s):
    return quote(str(s), safe="")


def _sub_blocks(res, name):
    return [b for b in res["blocks"] if b["type"] == name]


class _Ctx:
    """Resolves references against variables and already-applied resources."""

    def __init__(self, project, variables, inputs):
        self.project, self.vars, self.applied = project, {}, {}
        for k, spec in variables.items():
            d = spec.get("default")
            self.vars[k] = d if not isinstance(d, _Ref) else None
        for k, v in (inputs or {}).items():
            self.vars[k] = v["inputValue"] if isinstance(v, dict) and "inputValue" in v else v
        self.vars.setdefault("project_id", project)

    def val(self, x):
        if isinstance(x, _Ref):
            s = str(x)
            m = re.match(r"^var\.([A-Za-z0-9_\-]+)$", s)
            if m:
                return self.vars.get(m.group(1))
            m = re.match(r"^(google_[a-z0-9_]+)\.([A-Za-z0-9_\-]+)\.([a-z_]+)$", s)
            if m:
                rec = self.applied.get((m.group(1), m.group(2)))
                if rec is None:
                    raise _E(400, "INVALID_ARGUMENT", "Reference to undeclared or unapplied resource: %s" % s)
                return rec["attrs"].get(m.group(3), rec["attrs"].get("id"))
            if s.startswith("local."):
                return None
            raise _E(400, "INVALID_ARGUMENT", "Unsupported expression: %s" % s)
        if isinstance(x, list):
            return [self.val(i) for i in x]
        if isinstance(x, dict):
            return {k: self.val(v) for k, v in x.items()}
        if isinstance(x, str) and "${" in x:
            return re.sub(r"\$\{\s*var\.([A-Za-z0-9_\-]+)\s*\}", lambda m: str(self.vars.get(m.group(1), "")), x)
        return x


def _ok(r):
    return 200 <= r[0] < 300


def _h_bucket(c, res, call, project, a):
    name = a["name"]
    if _ok(call("GET", "/storage/v1/b/%s" % _enc(name))):
        return "unchanged", {"id": name, "name": name, "self_link": "https://www.googleapis.com/storage/v1/b/%s" % name, "url": "gs://%s" % name}
    body = {"name": name, "location": a.get("location") or "US"}
    if a.get("storage_class"):
        body["storageClass"] = a["storage_class"]
    if a.get("uniform_bucket_level_access"):
        body["iamConfiguration"] = {"uniformBucketLevelAccess": {"enabled": True}}
    if a.get("labels"):
        body["labels"] = a["labels"]
    s, j = call("POST", "/storage/v1/b?project=%s" % _enc(project), body)
    if s >= 300:
        raise _E(s, "FAILED_PRECONDITION", "create bucket %s: %s" % (name, _msg(j)))
    return "created", {"id": name, "name": name, "self_link": "https://www.googleapis.com/storage/v1/b/%s" % name, "url": "gs://%s" % name}


def _topic_full(project, name):
    return name if str(name).startswith("projects/") else "projects/%s/topics/%s" % (project, name)


def _h_topic(c, res, call, project, a):
    name = a["name"]
    full = "projects/%s/topics/%s" % (project, name)
    attrs = {"id": full, "name": name}
    if _ok(call("GET", "/v1/%s" % full)):
        return "unchanged", attrs
    body = {}
    if a.get("labels"):
        body["labels"] = a["labels"]
    s, j = call("PUT", "/v1/%s" % full, body)
    if s >= 300:
        raise _E(s, "FAILED_PRECONDITION", "create topic %s: %s" % (name, _msg(j)))
    return "created", attrs


def _h_sub(c, res, call, project, a):
    name = a["name"]
    full = "projects/%s/subscriptions/%s" % (project, name)
    attrs = {"id": full, "name": name}
    if _ok(call("GET", "/v1/%s" % full)):
        return "unchanged", attrs
    body = {"topic": _topic_full(project, a.get("topic", ""))}
    if a.get("ack_deadline_seconds"):
        body["ackDeadlineSeconds"] = int(a["ack_deadline_seconds"])
    s, j = call("PUT", "/v1/%s" % full, body)
    if s >= 300:
        raise _E(s, "FAILED_PRECONDITION", "create subscription %s: %s" % (name, _msg(j)))
    return "created", attrs


def _net_link(project, v):
    v = str(v or "default")
    if v.startswith("projects/") or v.startswith("http"):
        return v.split("/compute/v1/")[-1]
    return "projects/%s/global/networks/%s" % (project, v)


def _h_network(c, res, call, project, a):
    name = a["name"]
    base = "/compute/v1/projects/%s/global/networks" % _enc(project)
    attrs = {"id": "projects/%s/global/networks/%s" % (project, name), "name": name, "self_link": "projects/%s/global/networks/%s" % (project, name)}
    if _ok(call("GET", "%s/%s" % (base, _enc(name)))):
        return "unchanged", attrs
    body = {"name": name, "autoCreateSubnetworks": bool(a.get("auto_create_subnetworks", True))}
    if a.get("routing_mode"):
        body["routingConfig"] = {"routingMode": a["routing_mode"]}
    s, j = call("POST", base, body)
    if s >= 300:
        raise _E(s, "FAILED_PRECONDITION", "create network %s: %s" % (name, _msg(j)))
    return "created", attrs


def _h_subnet(c, res, call, project, a):
    name, region = a["name"], (a.get("region") or "us-central1").split("/")[-1]
    base = "/compute/v1/projects/%s/regions/%s/subnetworks" % (_enc(project), _enc(region))
    attrs = {"id": "projects/%s/regions/%s/subnetworks/%s" % (project, region, name), "name": name,
             "self_link": "projects/%s/regions/%s/subnetworks/%s" % (project, region, name)}
    if _ok(call("GET", "%s/%s" % (base, _enc(name)))):
        return "unchanged", attrs
    body = {"name": name, "ipCidrRange": a.get("ip_cidr_range"), "network": _net_link(project, a.get("network"))}
    s, j = call("POST", base, body)
    if s >= 300:
        raise _E(s, "FAILED_PRECONDITION", "create subnetwork %s: %s" % (name, _msg(j)))
    return "created", attrs


def _h_firewall(c, res, call, project, a):
    name = a["name"]
    base = "/compute/v1/projects/%s/global/firewalls" % _enc(project)
    attrs = {"id": "projects/%s/global/firewalls/%s" % (project, name), "name": name, "self_link": "projects/%s/global/firewalls/%s" % (project, name)}
    if _ok(call("GET", "%s/%s" % (base, _enc(name)))):
        return "unchanged", attrs
    body = {"name": name, "network": _net_link(project, a.get("network")), "direction": a.get("direction") or "INGRESS"}
    for tf, api in (("source_ranges", "sourceRanges"), ("target_tags", "targetTags"), ("source_tags", "sourceTags"), ("destination_ranges", "destinationRanges")):
        if a.get(tf):
            body[api] = list(a[tf])
    for kind, key in (("allow", "allowed"), ("deny", "denied")):
        rules = []
        for b in _sub_blocks(res, kind):
            r = {"IPProtocol": c.val(b["attrs"].get("protocol", "all"))}
            if b["attrs"].get("ports"):
                r["ports"] = [str(p) for p in c.val(b["attrs"]["ports"])]
            rules.append(r)
        if rules:
            body[key] = rules
    if a.get("priority") is not None:
        body["priority"] = int(a["priority"])
    s, j = call("POST", base, body)
    if s >= 300:
        raise _E(s, "FAILED_PRECONDITION", "create firewall %s: %s" % (name, _msg(j)))
    return "created", attrs


def _del(call, path):
    return call("DELETE", path)


HANDLERS = {
    "google_storage_bucket": (_h_bucket, 20, lambda p, a: "/storage/v1/b/%s" % _enc(a["name"])),
    "google_pubsub_topic": (_h_topic, 30, lambda p, a: "/v1/projects/%s/topics/%s" % (p, _enc(a["name"]))),
    "google_pubsub_subscription": (_h_sub, 31, lambda p, a: "/v1/projects/%s/subscriptions/%s" % (p, _enc(a["name"]))),
    "google_compute_network": (_h_network, 1, lambda p, a: "/compute/v1/projects/%s/global/networks/%s" % (p, _enc(a["name"]))),
    "google_compute_subnetwork": (_h_subnet, 2, lambda p, a: "/compute/v1/projects/%s/regions/%s/subnetworks/%s" % (p, _enc((a.get("region") or "us-central1").split("/")[-1]), _enc(a["name"]))),
    "google_compute_firewall": (_h_firewall, 3, lambda p, a: "/compute/v1/projects/%s/global/firewalls/%s" % (p, _enc(a["name"]))),
}
SUPPORTED_TYPES = sorted(HANDLERS)


def _msg(j):
    try:
        return (j.get("error") or {}).get("message") or json.dumps(j)[:200]
    except Exception:
        return "request failed"


def _order(resources):
    """Dependency order: by type tier, stable by address (references only ever point to a lower tier here)."""
    return sorted(resources, key=lambda r: (HANDLERS.get(r["type"], (None, 99))[1], r["type"], r["name"]))


# --------------------------------------------------------------------------- engine
def _blueprint_files(store, blueprint, call):
    bp = blueprint or {}
    if bp.get("vyomiFiles"):
        return dict(bp["vyomiFiles"])
    gs = (bp.get("gcsSource") or {}).get("source")
    if gs:
        m = re.match(r"^gs://([^/]+)/(.+)$", gs)
        if not m:
            raise _E(400, "INVALID_ARGUMENT", "gcsSource.source must be gs://bucket/object (got %r)." % gs)
        s, j = call("GET", "/storage/v1/b/%s/o/%s?alt=media" % (_enc(m.group(1)), _enc(m.group(2))), raw=True)
        if s >= 300:
            raise _E(400, "INVALID_ARGUMENT", "Could not read %s from Cloud Storage: %s" % (gs, _msg(j) if isinstance(j, dict) else "not found"))
        text = j if isinstance(j, str) else json.dumps(j)
        return {m.group(2).split("/")[-1]: text}
    if bp.get("gitSource"):
        raise _E(400, "FAILED_PRECONDITION", "gitSource is not supported: the simulator makes no network calls. Use gcsSource (gs://bucket/main.tf) or paste the configuration.")
    raise _E(400, "INVALID_ARGUMENT", "terraformBlueprint needs a source (gcsSource, or vyomiFiles inline configuration).")


def _parse_files(files):
    merged = {"resources": [], "variables": {}, "locals": {}, "data": []}
    for fn in sorted(files):
        if not fn.endswith(".tf"):
            continue
        try:
            p = parse_hcl(files[fn])
        except ValueError as e:
            raise _E(400, "INVALID_ARGUMENT", "%s: %s" % (fn, e))
        for k in ("resources", "data"):
            merged[k] += p[k]
        merged["variables"].update(p["variables"])
        merged["locals"].update(p["locals"])
    return merged


def plan(project, files, inputs, call):
    """-> (items, unsupported). items: [{address,type,name,action}] with action create|unchanged."""
    cfg = _parse_files(files)
    c = _Ctx(project, cfg["variables"], inputs)
    items, unsupported = [], []
    for r in _order(cfg["resources"]):
        addr = "%s.%s" % (r["type"], r["name"])
        if r["type"] not in HANDLERS:
            unsupported.append({"address": addr, "type": r["type"], "reason": "Resource type %s is not applied by the Vyomi simulator." % r["type"]})
            continue
        # the existence probe only needs the concrete name (and region); references to not-yet-created resources stay unresolved
        def lit(key):
            try:
                return c.val(r["attrs"].get(key))
            except _E:
                return None
        nm = lit("name")
        exists = False
        if nm:
            path = HANDLERS[r["type"]][2](lit("project") or project, {"name": nm, "region": lit("region")})
            exists = _ok(call("GET", path))
        items.append({"address": addr, "type": r["type"], "name": r["name"], "action": "unchanged" if exists else "create"})
    return items, unsupported


def apply_config(project, files, inputs, call):
    """Create every supported resource through the native APIs. Returns (results, unsupported, error)."""
    cfg = _parse_files(files)
    c = _Ctx(project, cfg["variables"], inputs)
    results, unsupported, error = [], [], None
    for r in _order(cfg["resources"]):
        addr = "%s.%s" % (r["type"], r["name"])
        if r["type"] not in HANDLERS:
            unsupported.append({"address": addr, "type": r["type"], "reason": "Resource type %s is not applied by the Vyomi simulator." % r["type"]})
            continue
        try:
            attrs = {k: c.val(v) for k, v in r["attrs"].items()}
            if not attrs.get("name"):
                raise _E(400, "INVALID_ARGUMENT", "%s: name is required." % addr)
            proj = attrs.get("project") or project
            action, out = HANDLERS[r["type"]][0](c, r, call, proj, attrs)
            c.applied[(r["type"], r["name"])] = {"attrs": out}
            results.append({"address": addr, "type": r["type"], "id": out["id"], "action": action, "state": "RECONCILED",
                            "_del": HANDLERS[r["type"]][2](proj, attrs) if action == "created" else None})
        except _E as e:
            results.append({"address": addr, "type": r["type"], "id": "", "action": "failed", "state": "FAILED", "error": e.message})
            error = "%s: %s" % (addr, e.message)
            break
    return results, unsupported, error


# --------------------------------------------------------------------------- REST
def _op_name(project, loc):
    return "projects/%s/locations/%s/operations/operation-im-%s" % (project, loc, secrets.token_hex(8))


def _make_op(store, project, loc, verb, target, response):
    name = _op_name(project, loc)
    ts = _now()
    op = {"name": name, "metadata": {"@type": "type.googleapis.com/google.cloud.config.v1.OperationMetadata", "createTime": ts, "endTime": ts,
                                     "target": target, "verb": verb, "requestedCancellation": False, "apiVersion": "v1"},
          "done": True, "response": dict(response, **{"@type": "type.googleapis.com/google.cloud.config.v1.%s" % response.get("_kind", "Deployment")})}
    op["response"].pop("_kind", None)
    store.operations[name] = op
    return op


def _fail_op(store, project, loc, verb, target, code, message):
    name = _op_name(project, loc)
    ts = _now()
    op = {"name": name, "metadata": {"@type": "type.googleapis.com/google.cloud.config.v1.OperationMetadata", "createTime": ts, "endTime": ts, "target": target, "verb": verb},
          "done": True, "error": {"code": code, "message": message}}
    store.operations[name] = op
    return op


def _valid_id(i, what):
    if not re.match(r"^[a-z]([a-z0-9-]{0,61}[a-z0-9])?$", i or ""):
        raise _E(400, "INVALID_ARGUMENT", "Invalid %s '%s': must start with a lowercase letter and contain only lowercase letters, digits and hyphens (max 63)." % (what, i))


def _run_revision(store, dep_name, project, loc, files, inputs, call, action):
    dep = store.deployments[dep_name]
    n = dep.get("_seq", 0) + 1
    dep["_seq"] = n
    rev_name = "%s/revisions/r-%06d" % (dep_name, n)
    ts = _now()
    results, unsupported, error = apply_config(project, files, inputs, call)
    ok = error is None
    detail = ""
    if unsupported:
        detail = "%d resource(s) not applied (unsupported by the simulator): %s" % (len(unsupported), ", ".join(u["address"] for u in unsupported))
    rev = {"name": rev_name, "createTime": ts, "updateTime": _now(), "action": action, "state": "APPLIED" if ok else "FAILED",
           "applyResults": {"content": "gs://vyomi-im-%s/%s/%s" % (project, dep_name.split("/")[-1], rev_name.split("/")[-1]),
                            "outputs": {},
                            "vyomiResources": [{k: v for k, v in r.items() if not k.startswith("_")} for r in results],
                            "vyomiUnsupported": unsupported},
           "stateDetail": error or detail, "tfVersion": "1.5.7", "build": "projects/%s/locations/%s/builds/vyomi-%s" % (project, loc, secrets.token_hex(4)),
           "logs": "gs://vyomi-im-%s/%s/%s/logs" % (project, dep_name.split("/")[-1], rev_name.split("/")[-1])}
    if not ok:
        rev["errorCode"] = "APPLY_BUILD_RUN_FAILED"
        rev["errorLogs"] = error
    store.revisions[rev_name] = rev
    res_rows = []
    for r in results:
        res_rows.append({"name": "%s/resources/%s" % (rev_name, r["address"].replace(".", "-")), "terraformInfo": {"address": r["address"], "type": r["type"], "id": r["id"]},
                         "intent": "CREATE" if r["action"] == "created" else "RECONCILE", "state": r["state"], "vyomiAction": r["action"]})
    for u in unsupported:
        res_rows.append({"name": "%s/resources/%s" % (rev_name, u["address"].replace(".", "-")), "terraformInfo": {"address": u["address"], "type": u["type"], "id": ""},
                         "intent": "CREATE", "state": "PLANNED", "vyomiAction": "unsupported", "vyomiNote": u["reason"]})
    store.resources[rev_name] = res_rows
    dep["latestRevision"] = rev_name
    dep["updateTime"] = rev["updateTime"]
    dep["state"] = "ACTIVE" if ok else "FAILED"
    dep["stateDetail"] = rev["stateDetail"]
    if ok:
        dep.pop("errorCode", None)
        dep.pop("errorLogs", None)
    else:
        dep["errorCode"] = "REVISION_FAILED"
        dep["errorLogs"] = rev["logs"]
    dep["_created"] = sorted(set(dep.get("_created", [])) | {r["_del"] for r in results if r.get("_del")})
    dep["_created_order"] = [r["_del"] for r in results if r.get("_del")] + [x for x in dep.get("_created_order", []) if x not in {r["_del"] for r in results if r.get("_del")}]
    return rev, ok, error


def _public(d):
    return {k: v for k, v in d.items() if not k.startswith("_")}


def _create_deployment(store, project, loc, dep_id, payload, call):
    _valid_id(dep_id, "deployment id")
    name = "projects/%s/locations/%s/deployments/%s" % (project, loc, dep_id)
    if name in store.deployments and store.deployments[name].get("state") != "DELETED":
        raise _E(409, "ALREADY_EXISTS", "Deployment '%s' already exists." % name)
    sa = payload.get("serviceAccount")
    if not sa:
        raise _E(400, "INVALID_ARGUMENT", "serviceAccount is required: Infrastructure Manager runs Terraform as this service account (projects/PROJECT/serviceAccounts/EMAIL).")
    bp = payload.get("terraformBlueprint") or {}
    files = _blueprint_files(store, bp, call)
    ts = _now()
    dep = {"name": name, "createTime": ts, "updateTime": ts, "labels": payload.get("labels") or {}, "state": "CREATING", "serviceAccount": sa,
           "terraformBlueprint": {k: v for k, v in bp.items() if k != "vyomiFiles"}, "tfVersion": "1.5.7"}
    if bp.get("vyomiFiles"):
        dep["terraformBlueprint"]["vyomiFiles"] = sorted(bp["vyomiFiles"])
    for k in ("workerPool", "importExistingResources", "quotaValidation", "annotations", "tfVersionConstraint"):
        if k in payload:
            dep[k] = payload[k]
    store.deployments[name] = dep
    store.files[name] = files
    rev, ok, error = _run_revision(store, name, project, loc, files, bp.get("inputValues"), call, "CREATE")
    return _make_op(store, project, loc, "create", name, dict(_public(dep), _kind="Deployment"))


def _update_deployment(store, project, loc, dep_id, payload, mask, call):
    name = "projects/%s/locations/%s/deployments/%s" % (project, loc, dep_id)
    dep = store.deployments.get(name)
    if not dep or dep.get("state") == "DELETED":
        raise _E(404, "NOT_FOUND", "Deployment '%s' was not found." % name)
    fields = [m.strip() for m in (mask or "").split(",") if m.strip()] or [k for k in payload if k != "name"]
    files, inputs = store.files.get(name, {}), (dep["terraformBlueprint"].get("inputValues"))
    for f in fields:
        if f in ("labels", "annotations"):
            dep[f] = payload.get(f) or {}
        elif f == "serviceAccount":
            dep["serviceAccount"] = payload.get(f) or dep["serviceAccount"]
        elif f.startswith("terraformBlueprint") or f == "terraformBlueprint":
            bp = payload.get("terraformBlueprint") or {}
            files = _blueprint_files(store, bp, call)
            dep["terraformBlueprint"] = {k: v for k, v in bp.items() if k != "vyomiFiles"}
            if bp.get("vyomiFiles"):
                dep["terraformBlueprint"]["vyomiFiles"] = sorted(bp["vyomiFiles"])
            inputs = bp.get("inputValues")
            store.files[name] = files
    if any(f.startswith("terraformBlueprint") for f in fields):
        _run_revision(store, name, project, loc, files, inputs, call, "UPDATE")
    else:
        dep["updateTime"] = _now()
    return _make_op(store, project, loc, "update", name, dict(_public(dep), _kind="Deployment"))


def _delete_deployment(store, project, loc, dep_id, query, call):
    name = "projects/%s/locations/%s/deployments/%s" % (project, loc, dep_id)
    dep = store.deployments.get(name)
    if not dep or dep.get("state") == "DELETED":
        raise _E(404, "NOT_FOUND", "Deployment '%s' was not found." % name)
    abandon = str(query.get("deletePolicy", "DELETE")).upper() == "ABANDON"
    failed = []
    if not abandon:
        for path in dep.get("_created_order", []):   # newest first == reverse dependency order
            s, j = call("DELETE", path)
            if s >= 300 and s != 404:
                failed.append("%s: %s" % (path, _msg(j)))
    if failed:
        dep["state"] = "FAILED"
        dep["errorCode"] = "DELETE_BUILD_RUN_FAILED"
        dep["stateDetail"] = "; ".join(failed)
        return _fail_op(store, project, loc, "delete", name, 9, dep["stateDetail"])
    del store.deployments[name]
    store.files.pop(name, None)
    for rn in [r for r in store.revisions if r.startswith(name + "/")]:
        store.revisions.pop(rn)
        store.resources.pop(rn, None)
    return _make_op(store, project, loc, "delete", name, {"_kind": "Deployment", "name": name, "state": "DELETED"})


def _create_preview(store, project, loc, pid, payload, call):
    _valid_id(pid, "preview id")
    name = "projects/%s/locations/%s/previews/%s" % (project, loc, pid)
    if name in store.previews:
        raise _E(409, "ALREADY_EXISTS", "Preview '%s' already exists." % name)
    bp = payload.get("terraformBlueprint") or {}
    inputs = bp.get("inputValues")
    ts = _now()
    pv = {"name": name, "createTime": ts, "labels": payload.get("labels") or {}, "state": "CREATING", "deployment": payload.get("deployment", ""),
          "previewMode": payload.get("previewMode") or "DEFAULT", "serviceAccount": payload.get("serviceAccount", ""), "terraformBlueprint": {k: v for k, v in bp.items() if k != "vyomiFiles"}}
    try:
        files = _blueprint_files(store, bp, call)
        if not bp and payload.get("deployment"):
            files = store.files.get(payload["deployment"]) or {}
        items, unsupported = plan(project, files, inputs, call)
        pv["state"] = "SUCCEEDED"
        pv["previewArtifacts"] = {"content": "gs://vyomi-im-%s/previews/%s/plan" % (project, pid), "artifacts": "gs://vyomi-im-%s/previews/%s/artifacts" % (project, pid)}
        pv["logs"] = "gs://vyomi-im-%s/previews/%s/logs" % (project, pid)
        pv["vyomiPlan"] = {"resources": items, "unsupported": unsupported,
                           "summary": {"create": sum(1 for i in items if i["action"] == "create"), "unchanged": sum(1 for i in items if i["action"] == "unchanged"), "unsupported": len(unsupported)}}
    except _E as e:
        pv["state"] = "FAILED"
        pv["errorStatus"] = {"code": 3 if e.status == 400 else 9, "message": e.message}
    store.previews[name] = pv
    return _make_op(store, project, loc, "create", name, dict(pv, _kind="Preview"))


def _page(items, query, key):
    try:
        size = int(query.get("pageSize") or 0) or len(items)
    except ValueError:
        size = len(items)
    start = int(query.get("pageToken") or 0) if str(query.get("pageToken") or "0").isdigit() else 0
    chunk = items[start:start + size]
    out = {key: chunk}
    if start + size < len(items):
        out["nextPageToken"] = str(start + size)
    return out


def _filter(items, query):
    f = (query.get("filter") or "").strip()
    m = re.match(r'^(?:state|labels\.[\w-]+)\s*=\s*"?([^"]+)"?$', f)
    if m:
        key, val = f.split("=", 1)[0].strip(), m.group(1)
        if key == "state":
            return [i for i in items if i.get("state") == val]
        return [i for i in items if (i.get("labels") or {}).get(key.split(".", 1)[1]) == val]
    return items


def dispatch(store, method, path, query=None, headers=None, body=b"", call=None):
    """`call(method, path, body=None, raw=False) -> (status, json_or_text)` goes through the SAME native router every SDK and the console use."""
    query = query or {}
    method = method.upper()
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        return _err(400, "INVALID_ARGUMENT", "Invalid JSON payload received.")
    if not isinstance(payload, dict):
        payload = {}
    p = path.split("?", 1)[0]
    for pre in ("/v1alpha2", "/v1"):
        if p.startswith(pre + "/"):
            p = p[len(pre):]
            break
    segs = [s for s in p.strip("/").split("/") if s]
    if len(segs) < 4 or segs[0] != "projects" or segs[2] != "locations":
        return _err(404, "NOT_FOUND", "Unknown path: %s" % path)
    project, loc = segs[1], segs[3]
    kind = segs[4] if len(segs) > 4 else ""
    try:
        if kind == "operations" and len(segs) == 6 and method == "GET":
            op = store.operations.get("/".join(segs))
            if not op:
                raise _E(404, "NOT_FOUND", "Operation '%s' was not found." % "/".join(segs))
            return _json(200, op)
        if kind == "operations" and len(segs) == 5 and method == "GET":
            ops = [o for n, o in sorted(store.operations.items()) if n.startswith("projects/%s/locations/%s/" % (project, loc))]
            return _json(200, _page(ops, query, "operations"))
        if kind == "deployments":
            if len(segs) == 5:
                if method == "POST":
                    return _json(200, _create_deployment(store, project, loc, query.get("deploymentId", ""), payload, call))
                if method == "GET":
                    pre = "projects/%s/locations/%s/deployments/" % (project, loc)
                    rows = [_public(d) for n, d in sorted(store.deployments.items()) if (loc == "-" or n.startswith(pre)) and n.startswith("projects/%s/locations/" % project)]
                    return _json(200, _page(_filter(rows, query), query, "deployments"))
            dname = "projects/%s/locations/%s/deployments/%s" % (project, loc, segs[5]) if len(segs) > 5 else ""
            if len(segs) == 6:
                if method == "GET":
                    d = store.deployments.get(dname)
                    if not d:
                        raise _E(404, "NOT_FOUND", "Resource '%s' was not found" % dname)
                    return _json(200, _public(d))
                if method == "PATCH":
                    return _json(200, _update_deployment(store, project, loc, segs[5], payload, query.get("updateMask", ""), call))
                if method == "DELETE":
                    return _json(200, _delete_deployment(store, project, loc, segs[5], query, call))
            if dname not in store.deployments:
                raise _E(404, "NOT_FOUND", "Resource '%s' was not found" % dname)
            if len(segs) >= 7 and segs[6] == "revisions":
                if len(segs) == 7 and method == "GET":
                    rows = [v for n, v in sorted(store.revisions.items(), reverse=True) if n.startswith(dname + "/revisions/")]
                    return _json(200, _page(rows, query, "revisions"))
                rname = "%s/revisions/%s" % (dname, segs[7]) if len(segs) > 7 else ""
                if len(segs) == 8 and method == "GET":
                    r = store.revisions.get(rname)
                    if not r:
                        raise _E(404, "NOT_FOUND", "Resource '%s' was not found" % rname)
                    return _json(200, r)
                if len(segs) >= 9 and segs[8] == "resources" and method == "GET":
                    rows = store.resources.get(rname)
                    if rows is None:
                        raise _E(404, "NOT_FOUND", "Resource '%s' was not found" % rname)
                    if len(segs) == 9:
                        return _json(200, _page(rows, query, "resources"))
                    for r in rows:
                        if r["name"] == "%s/resources/%s" % (rname, segs[9]):
                            return _json(200, r)
                    raise _E(404, "NOT_FOUND", "Resource not found.")
        if kind == "previews":
            if len(segs) == 5:
                if method == "POST":
                    return _json(200, _create_preview(store, project, loc, query.get("previewId", ""), payload, call))
                if method == "GET":
                    pre = "projects/%s/locations/%s/previews/" % (project, loc)
                    rows = [v for n, v in sorted(store.previews.items()) if n.startswith(pre)]
                    return _json(200, _page(rows, query, "previews"))
            if len(segs) == 6:
                nm = "projects/%s/locations/%s/previews/%s" % (project, loc, segs[5])
                if method == "GET":
                    if nm not in store.previews:
                        raise _E(404, "NOT_FOUND", "Resource '%s' was not found" % nm)
                    return _json(200, store.previews[nm])
                if method == "DELETE":
                    if nm not in store.previews:
                        raise _E(404, "NOT_FOUND", "Resource '%s' was not found" % nm)
                    del store.previews[nm]
                    return _json(200, _make_op(store, project, loc, "delete", nm, {"_kind": "Preview", "name": nm}))
    except _E as e:
        return _err(e.status, e.gcp_status, e.message)
    return _err(404, "NOT_FOUND", "Unknown path: %s" % path)


PATH_RE = re.compile(r"^/v1(alpha2)?/projects/[^/]+/locations/[^/]+/(deployments|previews)([/:?]|$)|^/v1(alpha2)?/projects/[^/]+/locations/[^/]+/operations/operation-im-[0-9a-f]+$")


def handles(path):
    return bool(PATH_RE.match(path.split("?", 1)[0]))
