"""Host adapters: build the faithful-IAM engine `state` dict and resolve the calling principal from the Mesh stores / request.

The engine (core/iam_engine) never imports a store (contract); everything store-shaped lives here. Functions take the stores
explicitly so they are unit-testable; the `*_from_host()` helpers bind them to the live appliance stores."""
from __future__ import annotations

import base64
import json
import re
from urllib.parse import parse_qs, unquote

# ----------------------------------------------------------------------------- request -> plain dict


def http_request_from(request, body: bytes = b"", principal=None) -> dict:
    """Starlette Request -> the plain http_request dict the gate and the op-maps consume."""
    return {"method": request.method, "path": request.scope.get("path", ""),
            "query": request.scope.get("query_string", b"").decode("latin-1"),
            "headers": {k.lower(): v for k, v in request.headers.items()},
            "host": request.headers.get("host", ""), "body": body, "principal": principal}


def _h(headers, name):
    for k, v in (headers or {}).items():
        if str(k).lower() == name:
            return v
    return ""


def _jwt_claims(headers) -> dict:
    auth = _h(headers, "authorization")
    if not auth.lower().startswith("bearer "):
        return {}
    parts = auth.split(None, 1)[1].strip().split(".")
    if len(parts) != 3:
        return {}
    try:
        pad = "=" * (-len(parts[1]) % 4)
        c = json.loads(base64.urlsafe_b64decode(parts[1] + pad))
        return c if isinstance(c, dict) else {}
    except Exception:
        return {}


# ----------------------------------------------------------------------------- AWS
_CRED_RE = re.compile(r"Credential=([^/,\s]+)/")


def aws_access_key_id(headers, query="") -> str:
    form = _h(headers, "x-vyomi-form-akid")        # set only by aws_resolve() from a verified multipart form; never trusted from the wire
    if form:
        return form
    auth = _h(headers, "authorization")
    m = _CRED_RE.search(auth)
    if m:
        return m.group(1)
    if auth.startswith("AWS ") and ":" in auth:            # SigV2
        return auth[4:].split(":", 1)[0].strip()
    q = parse_qs(query or "")
    for key in ("X-Amz-Credential", "AWSAccessKeyId"):
        if q.get(key):
            return unquote(q[key][0]).split("/", 1)[0]
    return ""


def _form_post_akid(headers, body) -> str:
    """Access key id carried by a browser-based S3 POST (multipart form field `x-amz-credential` or `AWSAccessKeyId`): that request is signed
    (by the form's policy), not anonymous."""
    if "multipart/form-data" not in _h(headers, "content-type").lower() or not body:
        return ""
    txt = bytes(body[:65536]).decode("latin-1", "replace")
    m = re.search(r'name="x-amz-credential"\r?\n\r?\n([^/\r\n]+)/', txt, re.I) or re.search(r'name="AWSAccessKeyId"\r?\n\r?\n([^\r\n]+)', txt, re.I)
    return m.group(1).strip() if m else ""


def aws_principal(headers, query, store) -> dict:
    """Access key id -> IAM user, or an assumed-role session (store.extras["sts_sessions"][akid], if the host records them)."""
    acct = getattr(store, "account_id", "") or "000000000000"
    override = _h(headers, "x-cloudlearn-principal")
    if override.startswith("arn:"):
        return {"arn": override, "type": "user" if ":user/" in override else "role", "account": acct}
    akid = aws_access_key_id(headers, query)
    key = (getattr(store, "access_keys", {}) or {}).get(akid)
    if key:
        u = (store.users or {}).get(key.get("user_name"))
        if u:
            # policies / boundary / groups come from aws_state()["principals"][arn] (documents, not ARNs): do not shadow them here
            return {"arn": u["arn"], "type": "user", "account": acct, "tags": u.get("tags") or {}, "access_key_id": akid}
    sess = ((getattr(store, "extras", {}) or {}).get("sts_sessions") or {}).get(akid)
    if sess:
        role = (store.roles or {}).get(sess.get("role_name") or "") or {}
        arn = f"arn:aws:sts::{acct}:assumed-role/{sess.get('role_name')}/{sess.get('session_name', 'session')}"
        return {"arn": arn, "type": "role", "account": acct, "role_arn": role.get("arn"),
                "session_policy": sess.get("session_policy"), "access_key_id": akid}
    return {"arn": "", "type": "unknown", "account": acct, "access_key_id": akid}


def _policy_doc(store, arn):
    """Default-version document of a managed policy (AWS-managed ones are materialised on first use by iam_core)."""
    p = (store.policies or {}).get(arn)
    if p is None:
        try:
            from core import iam_core
            p = iam_core._aws_managed_policy(store, arn)
        except Exception:
            p = None
    if not p:
        return None
    v = (p.get("versions") or {}).get(p.get("default_version_id") or "v1") or {}
    return v.get("document") or p.get("document")


def _entity_policies(store, ent):
    """Identity policies of a user/group/role record: inline documents + attached managed policy documents."""
    out = [{"id": f"inline:{n}", "document": d} for n, d in sorted((ent.get("inline_policies") or {}).items())]
    for arn in ent.get("attached_policies") or []:
        d = _policy_doc(store, arn)
        if d:
            out.append({"id": arn, "document": d})
    return out


def aws_state(store) -> dict:
    """Engine `state` (core/iam_engine/aws_eval.py): principals{arn: {policies, boundary, groups, tags}}, groups{name: {policies}},
    scps/rcps (org policies, one level per org unit - flat here), resource_policies (fed by the host per service; empty = identity-only)."""
    principals, groups = {}, {}
    for name, g in (store.groups or {}).items():
        groups[name] = {"policies": _entity_policies(store, g)}
    for name, u in (store.users or {}).items():
        b = _policy_doc(store, u.get("permissions_boundary")) if u.get("permissions_boundary") else None
        principals[u["arn"]] = {"policies": _entity_policies(store, u), "boundary": [b] if b else [],
                                "groups": [g for g in (u.get("groups") or []) if g in groups], "tags": u.get("tags") or {}}
    for name, r in (store.roles or {}).items():
        b = _policy_doc(store, r.get("permissions_boundary")) if r.get("permissions_boundary") else None
        rec = {"policies": _entity_policies(store, r), "boundary": [b] if b else [], "tags": r.get("tags") or {}}
        principals[r["arn"]] = rec
        principals[r["arn"].replace(":role/", ":assumed-role/", 1) if ":role/" in r["arn"] else r["arn"]] = rec
    scps = []   # an SCP restricts only once attached to a target; the store does not model attachment yet, so none are applied (open issue)
    for o in (getattr(store, "org_policies", {}) or {}).values():
        if isinstance(o, dict) and o.get("type") == "SERVICE_CONTROL_POLICY" and o.get("targets"):
            try:
                scps.append([json.loads(o.get("content") or "{}")])
            except Exception:
                pass
    out = {"cloud": "aws", "account": getattr(store, "account_id", ""), "principals": principals, "groups": groups,
           "scps": scps, "rcps": [], "resource_policies": {}, "resource_tags": {}}
    try:    # resource-based policies + attached SCP/RCP levels (core/iam_resource_policies.py); never blocks the identity-only path
        from core import iam_resource_policies as _rp
        out.update(_rp.aws_state_extras(store))
    except Exception:
        pass
    return out


_S3_VHOST = re.compile(r"^(?P<b>[^.]+(?:\.[^.]+)*?)\.s3[.-](?!accesspoint)")


def s3_bucket_of(hr, buckets) -> str:
    """Bucket an UNSIGNED request addresses, or "" when it is not an S3 request for an existing bucket (console pages, assets, health ...)."""
    host = _h(hr.get("headers"), "host").split(":")[0].lower()
    m = _S3_VHOST.match(host) if host else None
    if m and m.group("b") in buckets:
        return m.group("b")
    first = unquote(str(hr.get("path") or "").lstrip("/").split("/", 1)[0])
    return first if first and first in buckets else ""


def aws_anonymous(hr, store, buckets):
    """(state, principal) for an unsigned request addressed to an existing S3 bucket (faithful: principal "*" = anonymous, only a bucket /
    access-point policy can allow it), else None (ungated: console pages, static assets, unknown buckets which real S3 answers 404 anyway).
    OPTIONS (CORS preflight, evaluated against the bucket CORS rules, not IAM) and the bucket-less root are never gated. Sets hr["service_hint"]."""
    if str(hr.get("method") or "").upper() == "OPTIONS" or str(hr.get("path") or "/") == "/":
        return None
    if not s3_bucket_of(hr, buckets):
        return None
    hr["service_hint"] = "s3"
    acct = getattr(store, "account_id", "") or "000000000000"
    return aws_state(store), {"arn": "", "type": "anonymous", "account": acct}


def aws_resolve(hr, settings=None):
    """The AWS half of the host gate: None = not gated, else (state, principal). Signed requests (header, presigned query, JSON target)
    resolve the signer; a browser form POST resolves the key id from its form fields; everything else addressed to an existing bucket is
    anonymous. settings["anonymousS3"] == "allow" restores the pre-v4.1 behaviour (unsigned traffic never gated)."""
    h, q = hr.get("headers") or {}, hr.get("query") or ""
    h.pop("x-vyomi-form-akid", None)
    if not (aws_access_key_id(h, q) or "x-amz-target" in h):
        akid = _form_post_akid(h, hr.get("body"))
        if akid:
            h["x-vyomi-form-akid"] = akid
    if aws_access_key_id(h, q) or "x-amz-target" in h:
        return state_and_principal("aws", h, q, None)
    if (settings or {}).get("anonymousS3") == "allow":
        return None
    from core.appliance_stores import iam_store, s3_store
    return aws_anonymous(hr, iam_store(), _dict_keys(getattr(s3_store(), "buckets", None)))


def _dict_keys(m):
    try:
        return set(m or {})
    except Exception:
        return set()


# ----------------------------------------------------------------------------- GCP

def gcp_member(raw: str) -> dict:
    raw = (raw or "").strip()
    if not raw or raw == "root":
        return {"member": "root", "type": "root"}
    if ":" in raw:
        return {"member": raw, "type": raw.split(":", 1)[0]}
    if raw.endswith("gserviceaccount.com"):
        return {"member": "serviceAccount:" + raw, "type": "serviceAccount"}
    return {"member": "user:" + raw, "type": "user"}


def _bearer(headers) -> str:
    auth = _h(headers, "authorization")
    return auth.split(None, 1)[1].strip() if auth.lower().startswith("bearer ") and len(auth.split(None, 1)) == 2 else ""


def gcp_token_principal(headers, iamc_store=None, sts_tokens=None):
    """Identity behind an OPAQUE `ya29.` bearer token, or None. Two sources, both written at issuance: the IAM Credentials core
    (generateAccessToken records sha256(token) -> service-account email, core/gcp_iamcredentials_core.remember_token) and the
    Security Token Service exchange of Workload/Workforce Identity Federation (`gcp_sts_tokens`: token -> principal + attributes)."""
    tok = _bearer(headers)
    if not tok.startswith("ya29."):
        return None
    if sts_tokens:
        t = sts_tokens.get(tok)
        if isinstance(t, dict) and t.get("exp", 0) >= __import__("time").time():
            prov = str(t.get("provider") or "")
            pool = prov.split("/providers/", 1)[0] if "/providers/" in prov else ""
            out = {"member": t.get("principal") or "", "type": "principal"}
            if pool:
                out["pool"] = "iam.googleapis.com/" + pool
            if t.get("attributes"):
                out["attributes"] = {"attribute." + k: v for k, v in t["attributes"].items()}
            if out["member"]:
                return out
    if iamc_store is not None:
        try:
            from core import gcp_iamcredentials_core as _ic
        except ImportError:                      # Pyodide flat layout
            import gcp_iamcredentials_core as _ic
        who = _ic.principal_for_token(iamc_store, tok)
        if who:
            return gcp_member(who)
    return None


def gcp_principal(headers, space, iamc_store=None, sts_tokens=None) -> dict:
    raw = _h(headers, "x-cloudlearn-principal")
    if not raw:
        tp = gcp_token_principal(headers, iamc_store, sts_tokens)
        if tp:
            return tp
        c = _jwt_claims(headers)
        raw = c.get("email") or ""
    return gcp_member(raw or str((space or {}).get("active_principal") or "root"))


def _gcp_point(key: str) -> str:
    """Policy / attachment-point key -> bare resource path ('cloudresourcemanager.googleapis.com%2Fprojects%2Fp' -> 'projects/p')."""
    k = unquote(str(key or "")).strip("/")
    return k.split("googleapis.com/", 1)[1] if "googleapis.com/" in k else k


HIERARCHY_KEY = "gcp_iam_hierarchy"     # optional per-space / registry config: {"parents": {child: parent}, "groups": {"group:g@x": ["user:a@x"]}}


def _rm_parent(p) -> str:
    """Resource Manager parent (a "folders/1" string or the project's {"type","id"}) -> "folders/1" / "organizations/2"."""
    if isinstance(p, dict):
        t, i = str(p.get("type") or "").lower(), str(p.get("id") or "")
        return ({"folder": "folders", "organization": "organizations"}.get(t, t + "s") + "/" + i) if t and i else ""
    return str(p or "").strip("/")


def _group_member(raw: str, group_emails: set) -> str:
    raw = str(raw or "").strip()
    if ":" in raw and raw.split(":", 1)[0] in ("user", "group", "serviceAccount", "domain"):
        return raw
    if raw.endswith("gserviceaccount.com"):
        return "serviceAccount:" + raw
    return ("group:" if raw in group_emails else "user:") + raw


def gcp_hierarchy_extras(rm, config=None) -> dict:
    """Hierarchy, groups and Principal Access Boundary for the engine, from the Resource Manager store `rm` (gcp_rm: projects with
    parent, folders, Cloud Identity groups + memberships, PAB policies + bindings), plus an optional config document
    (HIERARCHY_KEY) that fills what the store does not hold: {"parents": {"projects/p": "folders/1", "folders/1": "organizations/2"},
    "groups": {"group:eng@x.com": ["user:a@x.com", "group:sub@x.com"]}}. The store wins over the config; both are optional.
    Returns {"hierarchy", "groups", "pab_policies", "pab_bindings", "project_aliases"} (project_aliases: projects/<number> -> projects/<id>)."""
    cfg = config if isinstance(config, dict) else {}
    hier: dict = {}
    aliases: dict = {}
    for pid, p in (getattr(rm, "projects", None) or {}).items():
        if not isinstance(p, dict):
            continue
        par = _rm_parent(p.get("parent"))
        if par:
            hier["projects/" + pid] = par
        num = str(p.get("name") or "").rsplit("/", 1)[-1]
        if num and num != pid:
            aliases["projects/" + num] = "projects/" + pid
    for fname, f in (getattr(rm, "folders", None) or {}).items():
        if isinstance(f, dict) and f.get("state", "ACTIVE") != "DELETED":
            par = _rm_parent(f.get("parent"))
            if par:
                hier[str(f.get("name") or fname)] = par
    for child, par in (cfg.get("parents") or {}).items():
        if isinstance(child, str) and isinstance(par, str):
            hier.setdefault(_gcp_point(child), _gcp_point(par))
    groups: dict = {}
    glist = getattr(rm, "groups", None) or {}
    emails = {g["groupKey"]["id"] for g in glist.values() if isinstance(g, dict) and (g.get("groupKey") or {}).get("id")}
    for gname, g in glist.items():
        email = ((g or {}).get("groupKey") or {}).get("id")
        if not email:
            continue
        mem = []
        for mn, m in (getattr(rm, "group_memberships", None) or {}).items():
            if mn.startswith(gname + "/memberships/") and isinstance(m, dict):
                mid = (m.get("preferredMemberKey") or {}).get("id")
                if mid:
                    mem.append(_group_member(mid, emails))
        groups["group:" + email] = mem
    for g, mem in (cfg.get("groups") or {}).items():
        if isinstance(mem, (list, tuple)):
            have = groups.setdefault(g, [])
            have.extend(x for x in mem if x not in have)
    pols = {n: dict(p) for n, p in (getattr(rm, "pab_policies", None) or {}).items() if isinstance(p, dict)}
    binds = [dict(b) for b in (getattr(rm, "pab_bindings", None) or {}).values() if isinstance(b, dict)]
    orgs = sorted(n for n in (getattr(rm, "organizations", None) or {}))
    return {"hierarchy": hier, "groups": groups, "pab_policies": pols, "pab_bindings": binds, "project_aliases": aliases, "organizations": orgs}


def _canon(point: str, aliases: dict) -> str:
    """projects/<number>[/...] -> projects/<id>[/...] so a policy attached by project number applies to requests naming the id."""
    for a, real in aliases.items():
        if point == a or point.startswith(a + "/"):
            return real + point[len(a):]
    return point


def apply_hierarchy(state: dict, extras: dict) -> dict:
    """Merge gcp_hierarchy_extras() into an engine state (project-number aliases canonicalised in policy keys and PAB resources)."""
    al = extras.get("project_aliases") or {}
    if al:
        for k in ("allow_policies", "deny_policies"):
            state[k] = {_canon(pt, al): v for pt, v in (state.get(k) or {}).items()}
        for pol in (extras.get("pab_policies") or {}).values():
            for r in ((pol.get("details") or {}).get("rules") or pol.get("rules") or []):
                r["resources"] = [_canon(_gcp_point(x) if "googleapis.com/" in str(x) else str(x).strip("/"), al) for x in r.get("resources") or []]
    state["hierarchy"] = dict(state.get("hierarchy") or {}, **extras.get("hierarchy", {}))
    # Every Vyomi project belongs to the one Vyomi-wide organization (core/gcp_resourcemanager_core.py): a project that is named by a
    # policy or is a parent here but has no recorded parent hangs off it, so organization-level bindings and boundaries reach it.
    orgs = extras.get("organizations") or []
    if orgs:
        hier = state["hierarchy"]
        projs = {k for k in (state.get("allow_policies") or {}) if k.startswith("projects/") and k.count("/") == 1}
        projs |= {v for v in hier.values() if v.startswith("projects/") and v.count("/") == 1}
        for pk in projs:
            if pk != "projects/_" and pk not in hier:
                hier[pk] = orgs[0]
    state["groups"] = dict(state.get("groups") or {}, **extras.get("groups", {}))
    if extras.get("pab_policies"):
        state["pab_policies"] = extras["pab_policies"]
        state["pab_bindings"] = extras.get("pab_bindings") or []
    return state


def gcp_state(iam_state, store=None, project=None, rm=None, config=None) -> dict:
    """Engine `state` (core/iam_engine/gcp_eval.py): allow_policies {attachment_point: policy}, deny_policies {point: [policy]},
    custom_roles, hierarchy. Sources: the v4 IAM core slot (`store`: gcp_iam_policies / gcp_deny_policies / gcp_custom_roles, the
    authoritative records) and the pre-v4 `gcp_iam_state` view ({"policies": {project: policy}}) merged under it (store wins).
    `project` (the space's project id) parents every Cloud Storage resource ('projects/_/...'), so project-level bindings are inherited."""
    st = iam_state if isinstance(iam_state, dict) else {}
    allow: dict = {}
    for k, p in (st.get("policies") or {}).items():
        if isinstance(p, dict) and isinstance(p.get("bindings"), list):
            allow["projects/" + k if "/" not in k else _gcp_point(k)] = p
    for k, p in (getattr(store, "gcp_iam_policies", None) or {}).items():
        if isinstance(p, dict):
            allow[_gcp_point(k)] = p
    deny: dict = {}
    for k, pols in (getattr(store, "gcp_deny_policies", None) or {}).items():
        lst = [v for v in (pols or {}).values() if isinstance(v, dict)] if isinstance(pols, dict) else list(pols or [])
        if lst:
            deny[_gcp_point(k)] = lst
    out = {"cloud": "gcp", "allow_policies": allow, "deny_policies": deny, "custom_roles": dict(getattr(store, "gcp_custom_roles", None) or {}),
           "service_accounts": st.get("service_accounts") or {}, "hierarchy": {}}
    if project:
        out["hierarchy"]["projects/_"] = "projects/" + project
    if rm is not None or config:
        apply_hierarchy(out, gcp_hierarchy_extras(rm, config))
    return out


# ----------------------------------------------------------------------------- Azure
_AZ = {"microsoft.authorization/roleassignments": "role_assignments",
       "microsoft.authorization/roledefinitions": "role_definitions",
       "microsoft.authorization/denyassignments": "deny_assignments"}


_SAS_KEYS = ("sv", "sp", "se", "st", "sr", "ss", "srt", "spr", "sig", "si", "skoid", "sktid", "tn", "sip", "spk", "epk", "srk", "erk")


def azure_principal(headers, space, query="", graph=None, path="") -> dict:
    """Who is calling. Order: X-Cloudlearn-Principal (explicit override) > `Authorization: SharedKey <acct>:<sig>` (account key: type
    "sharedkey") > a SAS query (`sig=` + `sp/se/...`: type "sas") > bearer claims (oid / appid / sub) > the space's active principal.
    `graph` (the Entra directory store, optional) resolves a UPN or an application (client) id to the object id role assignments use,
    and supplies group membership (state["groups"], see azure_state). `path` limits SharedKey / SAS detection to Storage data-plane requests
    (a `sig=` query on any other service is not a storage SAS); empty = unknown, treated as storage."""
    raw = _h(headers, "x-cloudlearn-principal")
    if not raw and _storage_path(path):
        try:
            from core.iam_engine import azure_sas as _sas
        except Exception:
            _sas = None
        if _sas is not None:
            acct = _sas.parse_shared_key(_h(headers, "authorization"))
            if acct:
                return {"object_id": "sharedkey:" + acct, "type": "sharedkey", "account": acct, "groups": []}
            q = {k.lower(): v[0] for k, v in parse_qs(query or "", keep_blank_values=True).items() if v}
            if _sas.is_sas(q):
                tok = {k: q[k] for k in _SAS_KEYS if k in q}
                return {"object_id": "sas:" + (q.get("skoid") or q.get("sv", "")), "type": "sas", "account": "", "sas": tok, "groups": []}
    if not raw:
        c = _jwt_claims(headers)
        raw = c.get("oid") or c.get("appid") or c.get("sub") or ""
    raw = raw or str((space or {}).get("active_principal") or "root")
    if graph is not None and raw != "root":
        raw = _graph_object_id(graph, raw)
    return {"object_id": raw, "type": "root" if raw == "root" else "user", "groups": []}


_STORAGE_PATH = re.compile(r"^(?:/_wire)?/azure-data/(?:blob|queue|queue-core|table|tableroot)(?:/|$)", re.I)


def _storage_path(path) -> bool:
    return not path or bool(_STORAGE_PATH.match(str(path)))


def _graph_object_id(graph, ident):
    """UPN / mail -> user object id, application (client) id -> service principal object id; anything else unchanged."""
    try:
        low = str(ident).lower()
        for uid, u in (getattr(graph, "users", None) or {}).items():
            if low in (str(uid).lower(), str(u.get("userPrincipalName", "")).lower(), str(u.get("mail") or "").lower()):
                return uid
        for sid, sp in (getattr(graph, "service_principals", None) or {}).items():
            if low == str(sp.get("appId", "")).lower():
                return sid
    except Exception:
        pass
    return ident


def azure_groups(graph) -> dict:
    """{group object id: [member object ids]} from the Entra directory store (transitive expansion is the engine's)."""
    out = {}
    try:
        for gid in (getattr(graph, "groups", None) or {}):
            out[gid] = sorted(str(m) for m in (getattr(graph, "group_members", None) or {}).get(gid, ()))
    except Exception:
        pass
    return out


# ARM type -> the data-plane resource prefix core/iam_engine/map_azure.py reports (so data actions inherit from the ARM resource's scope)
_AZ_DATA = {"microsoft.storage/storageaccounts": "/%s", "microsoft.keyvault/vaults": "/vaults/%s",
            "microsoft.servicebus/namespaces": "/namespaces/%s", "microsoft.documentdb/databaseaccounts": "/databaseAccounts/%s",
            "microsoft.appconfiguration/configurationstores": "/configurationStores/%s",
            "microsoft.cognitiveservices/accounts": "/cognitiveservices/%s", "microsoft.sql/servers": "/sql/%s"}
_RA_TAIL = re.compile(r"/providers/microsoft\.authorization/(?:roleassignments|denyassignments)/[^/]+$", re.I)


def _arm_scope(rec) -> str:
    props = rec.get("properties") or {}
    sc = props.get("scope") or ""
    if not sc:                       # ARM extension resource: the scope is the id minus its Microsoft.Authorization tail
        sc = _RA_TAIL.sub("", str(rec.get("id") or ""))
    return sc or "/"


def _flat_assignment(rec) -> dict:
    """ARM roleAssignment record ({id, name, properties:{principalId, roleDefinitionId, scope, condition}}) -> the engine's flat shape."""
    props = rec.get("properties") or {}
    return {"id": rec.get("id") or rec.get("name") or "", "principal_id": props.get("principalId") or rec.get("principalId") or "",
            "principal_type": props.get("principalType") or "", "role_definition_id": props.get("roleDefinitionId") or rec.get("roleDefinition") or "",
            "scope": _arm_scope(rec), "condition": props.get("condition"), "condition_version": props.get("conditionVersion")}


def _flat_deny(rec) -> dict:
    """ARM denyAssignment record ({properties:{denyAssignmentName, scope, permissions, principals, excludePrincipals, ...}})."""
    props = rec.get("properties") or {}
    return {"id": rec.get("id") or rec.get("name") or "", "scope": _arm_scope(rec),
            "principals": props.get("principals") or [], "exclude_principals": props.get("excludePrincipals") or [],
            "permissions": props.get("permissions") or [], "is_system_protected": bool(props.get("isSystemProtected")),
            "do_not_apply_to_child_scopes": bool(props.get("doNotApplyToChildScopes"))}


def azure_openai_account(arm_resources, path, headers) -> str:
    """Which Cognitive Services account does a bare `/openai/...` data-plane request address? (The simulator host carries no account;
    a real endpoint is `<account>.openai.azure.com`.) Order: an `api-key` equal to one account's key, the account that owns the
    `/deployments/<name>` in the path, the only account there is. '' when it cannot be told (the gate then falls back to scopes that
    cover every account: subscription / management group / root)."""
    accts = [r for r in (arm_resources or {}).values() if isinstance(r, dict)
             and str(r.get("_type") or r.get("type") or "").lower() == "microsoft.cognitiveservices/accounts"]
    key = _h(headers, "api-key")
    if key:
        for r in accts:
            if key in [str(v) for v in (r.get("_keys") or {}).values()]:
                return str(r.get("name") or "")
    m = re.search(r"/deployments/([^/?]+)", str(path or ""))
    if m:
        want = m.group(1).lower()
        for r in (arm_resources or {}).values():
            if isinstance(r, dict) and str(r.get("_type") or r.get("type") or "").lower() == "microsoft.cognitiveservices/accounts/deployments" \
                    and str(r.get("name") or "").split("/")[-1].lower() == want:
                mm = re.search(r"/accounts/([^/]+)/deployments/", str(r.get("id") or ""), re.I)
                if mm:
                    return mm.group(1)
    names = [str(r.get("name") or "") for r in accts]
    return names[0] if len(names) == 1 else ""


def azure_state(arm_resources, rbac_store=None, graph=None) -> dict:
    """Engine `state` (core/iam_engine/azure_eval.py). `arm_resources`: the flat ARM record map of the Azure space (role assignments, custom
    role definitions and deny assignments are ARM resources there, in ARM shape: properties.principalId ... -> flattened here).
    `rbac_store`: the Azure RBAC core slot (core/azure_iam_core.py: {name, principalId, roleDefinition, scope, kind, denyActions}), if present."""
    out = {"cloud": "azure", "role_assignments": [], "role_definitions": [], "deny_assignments": [], "data_scopes": {}, "storage_accounts": {},
           "groups": azure_groups(graph), "management_groups": {}, "subscriptions": {}}
    accounts = []
    for rec in (arm_resources or {}).values():
        if not isinstance(rec, dict):
            continue
        t = str(rec.get("_type") or rec.get("type") or "").lower()
        if t in _AZ_DATA and rec.get("id") and rec.get("name"):
            out["data_scopes"][_AZ_DATA[t] % str(rec["name"]).lower()] = rec["id"]
        if t == "microsoft.storage/storageaccounts" and rec.get("name"):
            accounts.append(rec)
            props = rec.get("properties") or {}
            out["storage_accounts"][str(rec["name"]).lower()] = {"allowSharedKeyAccess": props.get("allowSharedKeyAccess", True) is not False}
        elif t == "microsoft.management/managementgroups" and rec.get("name"):       # not served by any store today; fed when one models them
            parent = (((rec.get("properties") or {}).get("details") or {}).get("parent") or {}).get("id") or ""
            out["management_groups"][str(rec["name"])] = parent.rsplit("/", 1)[-1] or None
        elif t == "microsoft.management/managementgroups/subscriptions" and rec.get("name"):
            out["subscriptions"][str(rec["name"])] = str(rec.get("id") or "").split("/managementGroups/")[-1].split("/")[0] or None
        if t == "microsoft.authorization/roleassignments":
            out["role_assignments"].append(_flat_assignment(rec))
        elif t == "microsoft.authorization/roledefinitions":
            if str((rec.get("properties") or {}).get("type") or "CustomRole").lower() != "builtinrole":
                out["role_definitions"].append(rec)
        elif t == "microsoft.authorization/denyassignments":
            out["deny_assignments"].append(_flat_deny(rec))
    ds = out["data_scopes"]                    # an OpenAI request whose account cannot be told: authorize at the subscription that holds accounts
    first = next((v for k, v in ds.items() if k.startswith("/cognitiveservices/")), None)
    m = re.match(r"^(/subscriptions/[^/]+)", str(first or ""), re.I)
    if m:
        ds["/cognitiveservices/_"] = m.group(1)
    if accounts and "/_default" not in out["data_scopes"]:     # the root Storage wire carries no account name: the sole account, else the first one's subscription
        arm_ids = sorted(str(a["id"]) for a in accounts if a.get("id"))
        if len(arm_ids) == 1:
            out["data_scopes"]["/_default"] = arm_ids[0]
        elif arm_ids:
            out["data_scopes"]["/_default"] = re.sub(r"(?i)/resourceGroups/.*$", "", arm_ids[0])
    for a in (getattr(rbac_store, "_azure_role_assignments", None) or {}).values():
        if not isinstance(a, dict):
            continue
        if a.get("kind") == "deny":
            out["deny_assignments"].append({"id": a.get("name", ""), "scope": a.get("scope") or "/", "principals": [{"id": a.get("principalId", ""), "type": "User"}],
                                            "permissions": [{"actions": list(a.get("denyActions") or [])}]})
        else:
            out["role_assignments"].append({"id": a.get("name", ""), "principal_id": a.get("principalId", ""),
                                            "role_definition_id": a.get("roleDefinition", ""), "scope": a.get("scope") or "/"})
    return out


# ----------------------------------------------------------------------------- live host binding

def state_and_principal(cloud, headers, query="", space=None, path=""):
    """(state, principal) from the live appliance stores. Runs the store lookups as `cloud`'s request provider (the stores are
    space-scoped per provider), so it also works outside a request (the /api/iam/<cloud>/evaluate view)."""
    if cloud == "aws":
        return _live("aws", headers, query, space)
    from core import app_context
    tok = app_context.REQUEST_PROVIDER.set(cloud)
    try:
        return _live(cloud, headers, query, space, path)
    finally:
        app_context.REQUEST_PROVIDER.reset(tok)


def _live(cloud, headers, query, space, path=""):
    if cloud == "aws":
        from core.appliance_stores import iam_store
        s = iam_store()
        return aws_state(s), aws_principal(headers, query, s)
    if cloud == "gcp":
        from core import app_context          # (`space or app_context.STATE` below: was unbound when the caller passed an empty space)
        from core.app_context import gcp_iam_state
        store, project, appliance_stores = None, None, None
        try:
            from core import appliance_stores, gcp_project
            store = appliance_stores.net_new_core_stores().get("gcp_iam")
            project = gcp_project.current().get("projectId") or gcp_project.DEFAULT_PROJECT_ID
        except Exception:
            pass
        rm = None
        try:
            rm = appliance_stores.net_new_core_stores().get("gcp_rm")
        except Exception:
            pass     # no Resource Manager store: hierarchy comes from the optional config alone
        iamc = None
        try:
            from core import gcp_iamcredentials_core
            iamc = gcp_iamcredentials_core.shared_store()
        except Exception:
            pass
        sts = getattr(store, "gcp_sts_tokens", None) if store is not None else None
        return gcp_state(gcp_iam_state, store, project, rm, ((space or app_context.STATE).get(HIERARCHY_KEY))), gcp_principal(headers, space, iamc, sts)
    try:
        from providers import azure_services      # the live ARM record map of the Azure space (resolved for the request's provider)
        arm = azure_services._state
    except Exception:
        from core.app_context import azure_state_dict
        arm = azure_state_dict()
    rbac = None
    try:
        from core import appliance_stores
        rbac = appliance_stores.net_new_core_stores().get("iam")
    except Exception:
        pass
    graph = None
    try:
        from core import appliance_stores
        graph = appliance_stores.graph_store()
    except Exception:
        pass
    return azure_state(arm, rbac, graph), azure_principal(headers, space, query, graph, path)
