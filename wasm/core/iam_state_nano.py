"""Nano host adapters for the faithful-IAM engine: engine `state` + calling principal from the IN-BROWSER store registry.

Pure Python (stdlib + core.iam_engine + core.iam_state_adapters), Pyodide-safe: no fastapi / socket / sqlite3. Vendored to wasm/core by
wasm/build_cores.py and mounted next to core/iam_engine by wasm/nano-iam-hook.js on the first request of a space whose enforcement is
not `off`. The Mesh equivalent is core/iam_state_adapters.py (AWS shapes are shared from there: one definition, identical behaviour);
GCP and Azure are built here from the Nano registry (core/nano_registry.get()):

  AWS    reg["iam"]      InMemoryIamStore            users / access keys / groups / roles / managed + inline policies
  GCP    reg["gcp_iam"]  InMemoryIamStore (+ gcp_*)  gcp_iam_policies {resource: policy}, gcp_deny_policies, gcp_custom_roles, gcp_service_accounts
  Azure  reg["az_arm"].state  ARM records            roleAssignments / roleDefinitions / denyAssignments; reg["az_graph"] group membership

Catalogs are lazy on Nano (never at boot). What the evaluators read from disk on Mesh is handed over here instead:
  * GCP `state["catalog"]` (roles -> permissions) is built from the preloaded gcp/<service>.json files named by the roles actually bound;
    a basic role (owner/editor/viewer) needs every service. `gcp/_methods.json` is needed by the request map.
  * Azure `state["builtin_roles"]` comes from azure/_roles.json.
When something is not loaded yet a `NeedCatalogs` is raised (a CatalogUnavailable listing EVERY missing catalog); the JS hook prefetches them
all, `preload()`s and retries (see nano_bridge.check)."""
from __future__ import annotations

import json
import re
import sys

from core.iam_engine import catalog_loader
from core import iam_state_adapters as _A

# Re-exported so the bridge has one import: identical to Mesh.
aws_access_key_id, aws_principal, aws_state = _A.aws_access_key_id, _A.aws_principal, _A.aws_state
gcp_member, _h, _jwt_claims = _A.gcp_member, _A._h, _A._jwt_claims

_BASIC_ROLES = ("roles/owner", "roles/editor", "roles/viewer", "roles/browser")


class NeedCatalogs(catalog_loader.CatalogUnavailable):
    """Several catalogs are missing at once (`needs` = [[cloud, service], ...]); `need` stays the first, for single-need callers."""

    def __init__(self, needs):
        super().__init__(needs[0][0], needs[0][1])
        self.needs = [list(n) for n in needs]


def _have(cloud, service):
    try:
        catalog_loader.load(cloud, service)
        return True
    except catalog_loader.CatalogUnavailable:
        return False


def _require(*pairs):
    missing = [[c, s] for c, s in pairs if not _have(c, s)]
    if missing:
        raise NeedCatalogs(missing)


def on_preload(cloud, service, text):
    """Called after catalog_loader.preload. The bundled engine modules read some catalogs from disk (core/iam_catalog/**), which does not exist
    in Pyodide: mirror gcp/_methods.json (the GCP request map) into the in-memory FS, and feed map_azure's action-casing table from the
    preloaded text instead of its glob (which, with no provider catalog on disk, would re-glob and re-parse on EVERY request: ~5 ms)."""
    if cloud == "azure":
        try:
            from core.iam_engine import map_azure
            cat = text if isinstance(text, str) else bytes(text).decode("utf-8")
            d = json.loads(cat)
            map_azure._CAT.setdefault("", "")          # non-empty: `_catalog()` never rebuilds from disk
            for k in list(d.get("actions", {})) + list(d.get("dataActions", {})):
                map_azure._CAT.setdefault(k.lower(), k)
        except Exception:
            pass
        return
    if cloud == "gcp" and service == "_methods" and sys.platform == "emscripten":
        import os
        os.makedirs("/core/iam_catalog/gcp", exist_ok=True)
        with open("/core/iam_catalog/gcp/_methods.json", "w", encoding="utf-8") as f:
            f.write(text if isinstance(text, str) else bytes(text).decode("utf-8"))
        try:
            from core.iam_engine import map_gcp
            if not map_gcp._STATE.get("by_method"):
                map_gcp._STATE.clear()
        except Exception:
            pass


# ----------------------------------------------------------------------------- GCP
def gcp_principal(headers) -> dict:
    """x-cloudlearn-principal (test / console override) > Bearer JWT `email` claim > the project owner ("root").
    Opaque `ya29.` access tokens carry no identity in Nano (the token endpoint keeps no token table): they act as `root`."""
    raw = _h(headers, "x-cloudlearn-principal") or _jwt_claims(headers).get("email") or ""
    return gcp_member(raw)


def _gcp_stems(roles, known):
    """Catalog stems needed to resolve `roles` (role id prefix == catalog stem; a basic or unknown-prefix role needs them all)."""
    stems, everything = set(), [s for s in known if not s.startswith("_")]
    for r in roles:
        if r in _BASIC_ROLES:
            return everything
        if r.startswith("roles/"):
            p = r[6:].split(".", 1)[0]
            if p in known:
                stems.add(p)
            else:
                return everything
    return sorted(stems)


_cat_cache = {}


def _gcp_catalog(stems):
    cats = [(s, catalog_loader.load("gcp", s)) for s in stems]
    key = tuple((s, id(c)) for s, c in cats)
    if key in _cat_cache:
        return _cat_cache[key]
    roles, perms = {}, set()
    for _s, d in cats:
        perms.update((d.get("permissions") or {}).keys())
        for r, v in (d.get("roles") or {}).items():
            roles.setdefault(r, set()).update(v.get("permissions") or [])
    for v in roles.values():
        perms.update(v)
    out = {"roles": {r: sorted(v) for r, v in roles.items()}, "permissions": sorted(perms)}
    _cat_cache.clear()
    _cat_cache[key] = out
    return out


def gcp_state(reg, known=None) -> dict:
    st = reg.get("gcp_iam")
    pols = getattr(st, "gcp_iam_policies", None) or {}
    allow = {k: {"bindings": [dict(b) for b in (p.get("bindings") or [])]} for k, p in pols.items() if isinstance(p, dict)}
    deny = {}
    for ap, d in (getattr(st, "gcp_deny_policies", None) or {}).items():
        lst = [v for v in (d.values() if isinstance(d, dict) else d or []) if isinstance(v, dict)]
        if lst:
            deny[ap.replace("%2F", "/").replace("%2f", "/")] = lst
    custom = {n: r for n, r in (getattr(st, "gcp_custom_roles", None) or {}).items() if isinstance(r, dict)}
    # buckets belong to the (single) project that has a policy; with several projects nothing is inferred (no false inheritance)
    projects = sorted({k.split("/")[1] for k in allow if k.startswith("projects/") and k.count("/") == 1})
    hier = {}
    if len(projects) == 1:
        for b in (getattr(reg.get("gcs"), "buckets", None) or {}):
            hier["projects/_/buckets/" + b] = "projects/" + projects[0]
    roles = {b.get("role") for p in allow.values() for b in p["bindings"] if b.get("role")}
    state = {"cloud": "gcp", "allow_policies": allow, "deny_policies": deny, "custom_roles": custom, "hierarchy": hier}
    stems = _gcp_stems(sorted(r for r in roles if r not in custom), known if known is not None else _known("gcp"))
    _require(*[("gcp", x) for x in stems])
    if stems:
        state["catalog"] = _gcp_catalog(stems)
    return state


# ----------------------------------------------------------------------------- Azure
_AZ_T = ("microsoft.authorization/roleassignments", "microsoft.authorization/roledefinitions", "microsoft.authorization/denyassignments")


def azure_principal(headers, query="", path="") -> dict:
    """x-cloudlearn-principal > SharedKey account key > SAS query > Bearer JWT `oid` | `appid` | `sub`; groups from the `groups` claim.
    No identity -> the subscription owner ("root"). SharedKey / SAS: same rules as core/iam_state_adapters.azure_principal (storage data plane)."""
    if not _h(headers, "x-cloudlearn-principal") and _A._storage_path(path):
        from core.iam_engine import azure_sas as _sas
        acct = _sas.parse_shared_key(_h(headers, "authorization"))
        if acct:
            return {"object_id": "sharedkey:" + acct, "type": "sharedkey", "account": acct, "groups": []}
        from urllib.parse import parse_qs
        q = {k.lower(): v[0] for k, v in parse_qs(query or "", keep_blank_values=True).items() if v}
        if _sas.is_sas(q):
            return {"object_id": "sas:" + (q.get("skoid") or q.get("sv", "")), "type": "sas", "account": "",
                    "sas": {k: q[k] for k in _A._SAS_KEYS if k in q}, "groups": []}
    c = _jwt_claims(headers)
    raw = _h(headers, "x-cloudlearn-principal") or c.get("oid") or c.get("appid") or c.get("azp") or c.get("sub") or ""
    if not raw:
        return {"object_id": "root", "type": "root", "groups": []}
    typ = "ServicePrincipal" if (c.get("idtyp") == "app" or (c.get("appid") and not c.get("oid"))) else "User"
    return {"object_id": raw, "type": typ, "groups": [g for g in (c.get("groups") or []) if isinstance(g, str)]}


def _scope_of(rec):
    p = rec.get("properties") or {}
    return p.get("scope") or rec.get("_scope") or (rec.get("id") or "").rsplit("/providers/Microsoft.Authorization/", 1)[0] or "/"


def azure_state(reg) -> dict:
    arm = reg.get("az_arm")
    out = {"cloud": "azure", "role_assignments": [], "role_definitions": [], "deny_assignments": [], "groups": {}, "data_scopes": {}}
    for rec in list((getattr(arm, "state", None) or {}).values()):
        if not isinstance(rec, dict):
            continue
        t = str(rec.get("_type") or rec.get("type") or "").lower()
        p = rec.get("properties") or {}
        if t in _A._AZ_DATA and rec.get("id") and rec.get("name"):     # data-plane names (blob account, OpenAI account, SQL server ...) inherit from the ARM resource
            out["data_scopes"][_A._AZ_DATA[t] % str(rec["name"]).lower()] = rec["id"]
        if t == _AZ_T[0]:
            out["role_assignments"].append({"id": rec.get("id") or rec.get("name") or "", "principal_id": p.get("principalId") or "",
                                            "principal_type": p.get("principalType"), "scope": _scope_of(rec),
                                            "role_definition_id": p.get("roleDefinitionId") or p.get("roleName") or "",
                                            "condition": p.get("condition"), "condition_version": p.get("conditionVersion")})
        elif t == _AZ_T[1]:
            out["role_definitions"].append(rec)                      # ARM shape: {name, properties:{roleName, permissions:[..]}}
        elif t == _AZ_T[2]:
            out["deny_assignments"].append({"id": rec.get("id") or rec.get("name") or "", "scope": _scope_of(rec),
                                            "principals": p.get("principals") or [], "exclude_principals": p.get("excludePrincipals") or [],
                                            "permissions": p.get("permissions") or [], "is_system_protected": bool(p.get("isSystemProtected")),
                                            "do_not_apply_to_child_scopes": bool(p.get("doNotApplyToChildScopes"))})
    g = reg.get("az_graph")
    for gid, members in (getattr(g, "group_members", None) or {}).items():
        out["groups"][gid] = sorted(members)
    ds = out["data_scopes"]
    first = next((v for k, v in ds.items() if k.startswith("/cognitiveservices/")), None)
    m = re.match(r"^(/subscriptions/[^/]+)", str(first or ""), re.I)
    if m:
        ds["/cognitiveservices/_"] = m.group(1)           # an OpenAI request whose account cannot be told: authorize at the subscription
    _require(("azure", "_roles"))
    out["builtin_roles"] = _assigned_builtin_roles(out["role_assignments"])
    return out


_role_idx = {}


def _assigned_builtin_roles(assignments):
    """The built-in roles the store's assignments reference (by GUID, full id or roleName), not all ~490: azure_eval.resolve_role scans the
    mapping linearly per assignment and lower-cases every key, which is ~50x slower in Pyodide (measured 5 ms/request with all of them)."""
    roles = catalog_loader.load("azure", "_roles")["roles"]
    if _role_idx.get("\0src") is not roles:
        _role_idx.clear()
        _role_idx["\0src"] = roles
        for gid, d in roles.items():
            _role_idx[gid.lower()] = gid
            _role_idx.setdefault((d.get("roleName") or "").lower(), gid)
    out = {}
    for a in assignments:
        gid = _role_idx.get(str(a.get("role_definition_id") or "").split("/")[-1].lower())
        if gid:
            out[gid] = roles[gid]
    return out


# ----------------------------------------------------------------------------- one entry point
_KNOWN = {}


def set_known(manifest_catalogs):
    """{cloud: [service stems available in this bundle]} (the manifest); lets the GCP adapter name the catalogs it needs."""
    _KNOWN.clear()
    _KNOWN.update({c: sorted(v) for c, v in (manifest_catalogs or {}).items()})


def _known(cloud):
    return _KNOWN.get(cloud) or []


def state_and_principal(cloud, headers, query="", reg=None):
    """(state, principal) from the in-browser registry. Raises NeedCatalogs when catalogs must be fetched first."""
    if reg is None:
        from core import nano_registry
        reg = nano_registry.get()
    if cloud == "aws":
        s = reg["iam"]
        return aws_state(s), aws_principal(headers, query, s)
    if cloud == "gcp":
        _require(("gcp", "_methods"))
        st = gcp_state(reg)
        return st, gcp_principal(headers)
    return azure_state(reg), azure_principal(headers, query)
