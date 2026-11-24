# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Azure "Export template" engine (Nano / dev_server / unified-ingress core, pure Python).

Real ARM ``POST /subscriptions/{sub}/resourcegroups/{rg}/exportTemplate`` takes
``{"resources": ["*" | resourceId...], "options": "IncludeParameterDefaultValue,IncludeComments"}``
and returns ``{"template": {...ARM...}}``. This module builds that template from the resources
the ARM store really holds (child resources nested by name, ``dependsOn`` + ``resourceId()`` for every
cross-reference, secrets as ``securestring`` parameters), then DETERMINISTICALLY decompiles the same
template to Bicep and to Terraform (``azurerm_*`` resources via core/azure_tf_core.py; ARM types without
an azurerm mapping fall back to ``azapi_resource`` and are listed in the output).

Limits (stated in the capability registry): read-only/system properties are dropped by a fixed
list, not by each RP's real schema; Bicep output uses symbolic references but flat (no ``parent:``) children.
"""
from __future__ import annotations

import re

try:
    from core import azure_deploy_core as _D
    from core import azure_tf_core as _TF
except ImportError:     # flat import (dev)
    import azure_deploy_core as _D  # type: ignore
    import azure_tf_core as _TF  # type: ignore

SCHEMA = "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#"
_DROP_PROPS = {"provisioningState", "creationDate", "createdAt", "lastModifiedAt", "etag", "resourceGuid", "primaryEndpoints", "secondaryEndpoints",
               "statusOfPrimary", "statusOfSecondary", "primaryLocation", "secondaryLocation", "keyCreationTime", "writeLocations", "readLocations",
               "failoverPolicies", "instanceId", "documentEndpoint", "customerId", "createdDate", "modifiedDate", "nameServers", "numberOfRecordSets",
               "maxNumberOfRecordSets", "maxNumberOfRecordsPerRecordSet", "fullyQualifiedDomainName", "fqdn", "currentKubernetesVersion", "powerState",
               "nodeResourceGroup", "namespaces", "defaultHostName", "enabledHostNames", "hostNames", "repositorySiteName", "usageState",
               "availabilityState", "serviceBusEndpoint", "loginServer", "AppId", "InstrumentationKey", "ConnectionString", "TenantId",
               "principalId", "clientId", "ipAddress", "lastSkuUpdate", "quotaNextResetTime", "dataIngestionStatus", "privateLinkScopedResources",
               "creationTime", "earliestRestoreDate", "currentServiceObjectiveName", "requestedServiceObjectiveName", "currentSku", "databaseId",
               "currentBackupStorageRedundancy", "vyomiAccess", "messagingProtocol", "Name", "lastEnabledTime", "outboundIpAddresses",
               "possibleOutboundIpAddresses", "diskState", "diskSizeBytes", "uniqueId", "timeCreated", "diskIOPSReadWrite", "diskMBpsReadWrite", "staticIp",
               "defaultDomain", "infrastructureResourceGroup", "eventStreamEndpoint", "customDomainVerificationId", "sslPort", "vmId",
               "internalId", "dateCreated", "endpoint", "endpoints", "skuChangeInfo", "callRateLimit", "targetResource", "isMigrated"}
_SECRET = re.compile(r"(password|clientsecret|secretkey|connectionstring|primarykey|secondarykey|accountkey|sastoken)", re.I)
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_EXPR = re.compile(r"^\[(?!\[)(.*)\]$", re.S)
_PARAM = re.compile(r"parameters\('([^']+)'\)")
_SECRET_PARAMS = {"microsoft.sql/servers": "administratorLoginPassword"}
_ZONE_FIELDS = {"A": "ARecords", "AAAA": "AAAARecords", "CNAME": "CNAMERecord", "TXT": "TXTRecords", "MX": "MXRecords", "NS": "NSRecords",
                "PTR": "PTRRecords", "SRV": "SRVRecords", "CAA": "CAARecords"}


def _sym(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_]", "_", str(name))
    if not s or s[0].isdigit():
        s = "r_" + s
    return s


def _clean(v):
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items() if k not in _DROP_PROPS and not k.startswith("_") and not _SECRET.search(k)}
    if isinstance(v, list):
        return [_clean(x) for x in v]
    return v


def _split_id(rid):
    """(type, [name chain]) from a resource id (case preserved)."""
    tail = rid.split("/providers/")[-1].split("/")
    ns, rest = tail[0], tail[1:]
    return ns + "/" + "/".join(rest[0::2]), rest[1::2]


def _q(s):
    return "'" + str(s).replace("'", "''") + "'"


def _break_cycles(dep_map):
    """Drop the back edge of every dependsOn cycle (e.g. NIC <-> VM, which reference each other); the property
    references stay as resourceId() expressions, which ARM does not treat as dependencies."""
    state = {}

    def visit(n, stack):
        state[n] = 1
        for d in sorted(dep_map.get(n, ())):
            if d not in dep_map:
                continue
            if state.get(d) == 1:
                dep_map[n].discard(d)
            elif state.get(d) is None:
                visit(d, stack)
        state[n] = 2
    for n in sorted(dep_map):
        if state.get(n) is None:
            visit(n, [])


def _api_for(rtype):
    for s in _TF.SPECS:
        if s.get("arm") and s["arm"].lower() == rtype.lower():
            return s["api"]
    return "2023-01-01"


def build_template(records: list[dict], api_versions: dict[str, str], include_params: bool = True) -> dict:
    """ARM template from stored resource views (dicts with id/name/type/location/tags/properties...).
    Cross references between exported resources become ``[resourceId(...)]`` + ``dependsOn``."""
    recs = sorted(records, key=lambda x: str(x.get("id", "")).lower())
    entries = []
    for r in recs:
        rid = str(r.get("id") or "")
        if "/providers/" in rid:
            rtype, chain = _split_id(rid)
            if r.get("_arm_type"):
                rtype = r["_arm_type"]
        else:
            rtype, chain = r.get("type") or "", [r.get("name", "")]
        rtype = _TF.canon_type(rtype) if rtype.lower() in _TF.CANON else rtype
        entries.append({"rec": r, "id": rid, "type": rtype, "chain": chain})
    # parameter name for every top-level resource (unique)
    used, top_param = set(), {}
    for e in entries:
        if len(e["chain"]) == 1 and e["type"].lower() != "microsoft.authorization/roleassignments":
            base = f"{_sym(e['chain'][0])}_name"
            if base in used:
                base = f"{_sym(e['type'].split('/', 1)[-1])}_{base}"
            n, i = base, 2
            while n in used:
                n, i = f"{base}{i}", i + 1
            used.add(n)
            top_param[e["id"].lower()] = n
    tops = {e["id"].lower(): e for e in entries if len(e["chain"]) == 1}
    id_expr = {}

    def head(e):
        anc = e if len(e["chain"]) == 1 else next((x for x in entries if len(x["chain"]) == 1 and e["id"].lower().startswith(x["id"].lower() + "/")), None)
        if anc is None:
            return _q(e["chain"][0])
        pn = top_param.get(anc["id"].lower())
        return f"parameters('{pn}')" if (pn and include_params) else _q(anc["chain"][0])

    def name_parts(e):
        return [head(e)] + [_q(c) for c in e["chain"][1:]]
    for e in entries:
        id_expr[e["id"].lower()] = f"resourceId('{e['type']}', " + ", ".join(name_parts(e)) + ")"

    def rewrite(v, self_id, deps):
        if isinstance(v, str):
            k = v.lower()
            if k in id_expr and k != self_id:
                deps.add(k)
                return "[" + id_expr[k] + "]"
            return "[" + v if v.startswith("[") else v
        if isinstance(v, list):
            return [rewrite(x, self_id, deps) for x in v]
        if isinstance(v, dict):
            out = {}
            for kk, x in v.items():
                if kk == "id" and isinstance(x, str) and x.lower().startswith(self_id + "/"):
                    continue
                nk = kk
                if isinstance(kk, str) and kk.lower() in id_expr and kk.lower() != self_id:
                    deps.add(kk.lower())
                    nk = "[" + id_expr[kk.lower()] + "]"
                out[nk] = rewrite(x, self_id, deps)
            return out
        return v
    params, resources, dep_map, res_by_id = {}, [], {}, {}
    for e in entries:
        r, rtype = e["rec"], e["type"]
        deps = set()
        self_id = e["id"].lower()
        res = {"type": rtype, "apiVersion": api_versions.get(rtype.lower()) or _api_for(rtype), "name": None}
        if len(e["chain"]) == 1:
            if rtype.lower() == "microsoft.authorization/roleassignments" or not include_params:
                res["name"] = e["chain"][0]
            else:
                pname = top_param[self_id]
                res["name"] = f"[parameters('{pname}')]"
                params[pname] = {"defaultValue": e["chain"][0], "type": "string"}
        else:
            res["name"] = "[concat(" + ", '/', ".join(name_parts(e)) + ")]" if include_params else "/".join(e["chain"])
            for cand in sorted((x["id"].lower() for x in entries if self_id.startswith(x["id"].lower() + "/")), key=len, reverse=True):
                deps.add(cand)
                break
        for k in ("location", "kind", "sku", "identity", "tags", "extendedLocation", "zones"):
            if r.get(k) not in (None, {}, "", []):
                val = _clean(r[k])
                if k == "identity" and isinstance(val, dict) and val.get("type") in (None, "None"):
                    continue
                res[k] = rewrite(val, self_id, deps)
        props = _clean(r.get("properties") or {})
        if rtype.lower() == "microsoft.network/virtualnetworks":
            props.pop("subnets", None)
            if not props.get("virtualNetworkPeerings"):
                props.pop("virtualNetworkPeerings", None)
        if rtype.lower() == "microsoft.authorization/roleassignments":
            scope = (r.get("properties") or {}).get("scope") or ""
            props.pop("scope", None)
            props.pop("roleName", None)
            if scope and not re.fullmatch(r"/subscriptions/[^/]+/resourceGroups/[^/]+", scope, re.I):
                if scope.lower() in id_expr:
                    res["scope"] = "[" + id_expr[scope.lower()] + "]"
                    deps.add(scope.lower())
                else:
                    res["scope"] = scope
        sec = _SECRET_PARAMS.get(rtype.lower())
        if sec and include_params and props.get("administratorLogin"):
            pname = f"{top_param[self_id][:-5]}_{sec}"
            params[pname] = {"type": "securestring"}
            props[sec] = f"[parameters('{pname}')]"
        props = rewrite(props, self_id, deps)
        if props:
            res["properties"] = props
        dep_map[self_id] = {d for d in deps if d in id_expr}
        res_by_id[self_id] = res
        resources.append(res)
    _break_cycles(dep_map)
    for sid, res in res_by_id.items():
        if dep_map[sid]:
            res["dependsOn"] = ["[" + id_expr[d] + "]" for d in sorted(dep_map[sid])]
    t = {"$schema": SCHEMA, "contentVersion": "1.0.0.0"}
    if include_params:
        t["parameters"] = dict(sorted(params.items()))
    t["variables"] = {}
    t["resources"] = resources
    return t


# ── Bicep ────────────────────────────────────────────────────────────────────────────────
def _bq(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("${", "\\${") + "'"


class _BX:
    """ARM expression -> Bicep expression, with symbolic resource references."""

    def __init__(self, ctx, symbols):
        self.ctx, self.symbols = ctx, symbols

    def expr(self, s):
        return self.node(_D.parse_expr(s[1:-1]))

    def node(self, n):
        k = n[0]
        if k == "lit":
            v = n[1]
            return _bq(v) if isinstance(v, str) else ("true" if v is True else "false" if v is False else "null" if v is None else str(v))
        if k == "prop":
            return f"{self.node(n[1])}.{n[2]}"
        if k == "idx":
            return f"{self.node(n[1])}[{self.node(n[2])}]"
        name, args = n[1], n[2]
        low = name.lower()
        if low in ("parameters", "variables") and args[0][0] == "lit":
            return str(args[0][1])
        if low in ("resourceid", "subscriptionresourceid"):
            try:
                rid = _D.ev(self.ctx, n)
                if str(rid).lower() in self.symbols:
                    return f"{self.symbols[str(rid).lower()]}.id"
            except _D.TemplateError:
                pass
        if low == "concat":
            parts = ""
            for a in args:
                if a[0] == "lit" and isinstance(a[1], str):
                    parts += a[1].replace("\\", "\\\\").replace("'", "\\'").replace("${", "\\${")
                else:
                    parts += "${" + self.node(a) + "}"
            return "'" + parts + "'"
        return f"{name}(" + ", ".join(self.node(a) for a in args) + ")"


def _bval(v, bx, ind=0) -> str:
    pad, pad2 = "  " * ind, "  " * (ind + 1)
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "null"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        if _D.is_expr(v):
            return bx.expr(v)
        return _bq(v[1:] if v.startswith("[[") else v)
    if isinstance(v, list):
        if not v:
            return "[]"
        return "[\n" + "\n".join(f"{pad2}{_bval(x, bx, ind + 1)}" for x in v) + f"\n{pad}]"
    if not v:
        return "{}"
    lines = []
    for k, x in v.items():
        key = k if _IDENT.match(k) else (f"'${{{bx.expr(k)}}}'" if _D.is_expr(k) else _bq(k))
        lines.append(f"{pad2}{key}: {_bval(x, bx, ind + 1)}")
    return "{\n" + "\n".join(lines) + f"\n{pad}}}"


def _template_steps(template, sub, rg, loc="eastus"):
    ctx = _D.Ctx(sub, rg, template.get("parameters"), template.get("variables"), loc)
    for pn, pd in (template.get("parameters") or {}).items():
        dv = (pd or {}).get("defaultValue")
        try:
            ctx.param_vals[pn] = _D.evaluate(ctx, dv) if dv is not None else ""
        except _D.TemplateError:
            ctx.param_vals[pn] = ""
    return ctx, _D.plan(ctx, template)


def to_bicep(template: dict, sub="00000000-0000-0000-0000-000000000000", rg="rg") -> str:
    ctx, steps = _template_steps(template, sub, rg)
    symbols, used = {}, set()
    for r in steps:
        base = _sym("_".join(str(r["name"]).split("/")[-2:]) if "/" in str(r["name"]) else r["name"])
        n, i = base, 2
        while n in used:
            n, i = f"{base}{i}", i + 1
        used.add(n)
        symbols[r["id"].lower()] = n
    bx = _BX(ctx, symbols)
    out = []
    for pname, p in (template.get("parameters") or {}).items():
        t = {"securestring": "string", "secureObject": "object"}.get(p.get("type", "string"), p.get("type", "string"))
        line = ("@secure()\n" if p.get("type") in ("securestring", "secureObject") else "") + f"param {pname} {t}"
        if "defaultValue" in p:
            line += f" = {_bval(p['defaultValue'], bx)}"
        out.append(line)
    if out:
        out.append("")
    for r in steps:
        ent = r["_ent"]
        body = {k: v for k, v in ent.items() if k not in ("type", "apiVersion", "dependsOn", "resources", "comments", "copy", "condition", "scope") and not k.startswith("_")}
        deps = [symbols[d] for d in sorted(r["deps"]) if d in symbols]
        text = _bval(body, bx)
        if deps:
            text = text[:-1].rstrip() + "\n  dependsOn: [\n" + "\n".join(f"    {d}" for d in deps) + "\n  ]\n}"
        out.append(f"resource {symbols[r['id'].lower()]} '{r['type']}@{r['apiVersion']}' = {text}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


# ── Terraform (azurerm) ───────────────────────────────────────────────────────────────────
def to_terraform(template: dict, subscription: str, rg: str, rg_location: str = None) -> str:
    return _TF.to_terraform(template, subscription, rg, rg_location)


def _dns_records(r):
    out = []
    for key, rs in (r.get("_rs") or {}).items():
        rtype, name = rs.get("_rtype"), rs.get("name")
        if rtype not in _ZONE_FIELDS or (name == "@" and rtype in ("NS", "SOA")):
            continue
        props = {"TTL": rs.get("ttl")}
        if rs.get("records") is not None and not rs.get("target"):
            props[_ZONE_FIELDS[rtype]] = rs["records"]
        out.append({"id": f"{r.get('id')}/{rtype}/{name}", "name": f"{r.get('name')}/{name}", "type": f"Microsoft.Network/dnsZones/{rtype}",
                    "_arm_type": f"Microsoft.Network/dnsZones/{rtype}", "properties": props})
    return out


def _inline_subnets(state, vnet):
    """Subnets that only exist inside the vnet's ``properties.subnets`` (PUT as a child / by a template) have no state record."""
    out = []
    for sn in (vnet.get("properties") or {}).get("subnets") or []:
        sid = str(sn.get("id") or f"{vnet.get('id')}/subnets/{sn.get('name')}")
        if sid.lower() in state:
            continue
        out.append({"id": sid, "name": f"{vnet.get('name')}/{sn.get('name')}", "type": "Microsoft.Network/virtualNetworks/subnets",
                    "_arm_type": "Microsoft.Network/virtualNetworks/subnets", "properties": sn.get("properties") or {}})
    return out


def _rg_location(state, sub, rg):
    for r in state.values():
        if isinstance(r, dict) and str(r.get("_type") or "").lower() == "microsoft.resources/resourcegroups" and (r.get("name") or "").lower() == rg.lower():
            return r.get("location")
    return None


def export_group(state: dict, sub: str, rg: str, resources, api_versions: dict, include_params: bool = True) -> dict:
    """The exportTemplate action. ``resources`` = ["*"] or resource ids. Body = ARM
    ``ResourceGroupExportResult`` plus Vyomi's ``bicep``/``terraform`` renderings (a Vyomi
    extension - real Azure renders those in the portal client)."""
    want = None if (not resources or "*" in resources) else {str(x).lower() for x in resources}
    recs = []
    for key, r in state.items():
        if not isinstance(r, dict) or r.get("_sub") != sub or (r.get("_rg") or "").lower() != rg.lower():
            continue
        t = (r.get("_type") or "").lower()
        if "/" not in t or t == "microsoft.resources/resourcegroups" or t.startswith(("microsoft.security", "microsoft.resources/", "microsoft.insights/eventtypes", "microsoft.insights/diagnosticsettings")):
            continue
        if t.startswith("microsoft.authorization") and (t != "microsoft.authorization/roleassignments" or not (r.get("properties") or {}).get("roleDefinitionId")):
            continue
        if "/__event__/" in str(key):
            continue
        views = [{**{k: v for k, v in r.items() if not k.startswith("_")}, "type": r.get("_type")}]
        if t == "microsoft.network/dnszones":
            views += _dns_records(r)
        if t == "microsoft.network/virtualnetworks":
            views += _inline_subnets(state, r)
        for v in views:
            if want is not None and str(v.get("id") or key).lower() not in want:
                continue
            recs.append(v)
    if want is not None and not recs:
        return {"status": 404, "body": {"error": {"code": "ResourceNotFound", "message": "None of the requested resources are in this resource group."}}}
    tpl = build_template(recs, api_versions, include_params)
    loc = _rg_location(state, sub, rg)
    return {"status": 200, "body": {"template": tpl, "bicep": to_bicep(tpl, sub, rg), "terraform": to_terraform(tpl, sub, rg, loc)}}


def import_terraform(text: str) -> dict:
    """Terraform (azurerm / azapi) -> ARM deployment template + report (see core/azure_tf_core.terraform_to_arm)."""
    return _TF.terraform_to_arm(text)


# ═══════════════════════ move resources (validateMoveResources / moveResources) ═════════════
_NOT_MOVABLE_PREFIX = ("microsoft.resources/", "microsoft.authorization/", "microsoft.security/", "microsoft.insights/eventtypes")


def _walk_replace(o, pat, new):
    if isinstance(o, str):
        return pat.sub(new, o)
    if isinstance(o, list):
        return [_walk_replace(x, pat, new) for x in o]
    if isinstance(o, dict):
        return {k: _walk_replace(v, pat, new) for k, v in o.items()}
    return o


def _walk_strings(o, out):
    if isinstance(o, str):
        out.append(o.lower())
    elif isinstance(o, list):
        for x in o:
            _walk_strings(x, out)
    elif isinstance(o, dict):
        for v in o.values():
            _walk_strings(v, out)


def _is_child(il: str, src_prefix: str) -> bool:
    """A top-level resource id is providers/<ns>/<type>/<name>; anything deeper is a child/extension resource."""
    return len(il[len(src_prefix):].split("providers/", 1)[-1].split("/")) > 3


def _mv_err(status, code, msg):
    return {"status": status, "body": {"error": {"code": code, "message": msg}}}


def move_resources(state: dict, sub: str, rg: str, payload: dict, rg_exists, validate_only: bool = False) -> dict:
    """POST …/resourceGroups/{rg}/validateMoveResources | moveResources.

    Validates (target group exists and differs, same subscription, resources exist in the source group and are
    movable top-level resources, no ARM lock on the resource or either group, no name clash in the target,
    and every resource that references - or is referenced by - a moved one in the source group moves with it),
    then really re-parents the resources: state keys, ids, ``_rg`` and every embedded reference are rewritten,
    child records (ids under the resource) move with their parent. Returns status 204 on success."""
    ids = (payload or {}).get("resources")
    target = str((payload or {}).get("targetResourceGroup") or "")
    if not isinstance(ids, list) or not ids or any(not isinstance(i, str) for i in ids):
        return _mv_err(400, "InvalidRequestContent", "The 'resources' property must be a non-empty list of resource ids.")
    m = re.match(r"^/subscriptions/([^/]+)/resourcegroups/([^/]+)$", target, re.I)
    if not m:
        return _mv_err(400, "InvalidRequestContent", "The 'targetResourceGroup' property must be a resource group id.")
    if m.group(1).lower() != sub.lower() and not (m.group(1).lower() == sub.lower()):
        return _mv_err(400, "InvalidMoveRequest", "Moving resources to another subscription is not supported by this simulator (it models one subscription).")
    trg = m.group(2)
    if trg.lower() == rg.lower():
        return _mv_err(400, "InvalidMoveRequest", "The source and target resource groups must be different.")
    if not rg_exists(trg):
        return _mv_err(404, "ResourceGroupNotFound", f"Resource group '{trg}' could not be found.")
    src_prefix = f"/subscriptions/{sub}/resourcegroups/{rg}/".lower()
    recs = {}
    for k, r in state.items():
        if isinstance(r, dict) and r.get("_sub") == sub and (r.get("_rg") or "").lower() == rg.lower():
            recs[str(r.get("id") or k).lower()] = (k, r)
    moving = {}
    for i in ids:
        il = i.lower()
        if il not in recs:
            return _mv_err(400, "ResourceNotFound", f"The resource '{i}' was not found in resource group '{rg}'.")
        t = str(recs[il][1].get("_type") or "").lower()
        if t.startswith(_NOT_MOVABLE_PREFIX):
            return _mv_err(409, "ResourceNotMovable", f"The resource type '{recs[il][1].get('_type')}' does not support move.")
        if _is_child(il, src_prefix):
            return _mv_err(409, "ResourceNotMovable", f"'{i}' is a child resource; move its parent instead.")
        moving[il] = recs[il]
    # children travel with their parent
    for il in list(moving):
        for cl, kr in recs.items():
            if cl.startswith(il + "/"):
                moving[cl] = kr
    top = [il for il in moving if not any(il.startswith(o + "/") for o in moving)]
    # locks (resource, source group, target group)
    scopes = set(top) | {f"/subscriptions/{sub}/resourcegroups/{rg}".lower(), target.lower()}
    for r in state.values():
        if isinstance(r, dict) and r.get("_lock_scope") in scopes:
            lvl = (r.get("properties") or {}).get("level", "")
            return _mv_err(409, "ScopeLocked", f"The scope '{r.get('_lock_scope')}' has a '{lvl}' lock; remove it before moving resources.")
    # name clash in the target
    for il in top:
        r = moving[il][1]
        for r2 in state.values():
            if isinstance(r2, dict) and (r2.get("_rg") or "").lower() == trg.lower() and r2.get("_sub") == sub \
                    and str(r2.get("_type") or "").lower() == str(r.get("_type") or "").lower() \
                    and str(r2.get("name") or "").lower() == str(r.get("name") or "").lower():
                return _mv_err(409, "ResourceMoveConflict", f"A resource of type '{r.get('_type')}' named '{r.get('name')}' already exists in resource group '{trg}'.")
    # dependency closure: references in either direction must be inside the move set
    top_ids = set(top)
    ref_ids = {il for il, (_, r) in recs.items() if not _is_child(il, src_prefix)}
    for il, (_, r) in recs.items():
        if il not in ref_ids:
            continue
        strs = []
        _walk_strings(r.get("properties"), strs)
        refs = {x for x in ref_ids if x != il and any(s == x or s.startswith(x + "/") for s in strs)}
        if il in top_ids:
            for x in refs - top_ids:
                return _mv_err(409, "MissingMoveDependentResources", f"The resource '{r.get('id')}' references '{recs[x][1].get('id')}', which must be moved together with it.")
        else:
            for x in refs & top_ids:
                return _mv_err(409, "MissingMoveDependentResources", f"The resource '{recs[x][1].get('id')}' is referenced by '{r.get('id')}', which would be left behind; move both together.")
    if validate_only:
        return {"status": 204, "body": None}
    # apply: rewrite ids/refs and re-key
    for il in top:
        old_id = str(moving[il][1].get("id") or "")
        new_id = f"/subscriptions/{sub}/resourceGroups/{trg}/" + old_id[len(src_prefix):]
        pat = re.compile(re.escape(old_id), re.I)
        for cl, (k, r) in list(moving.items()):
            if cl != il and not cl.startswith(il + "/"):
                continue
            state.pop(k, None)
            r2 = _walk_replace(r, pat, new_id)
            r2["_rg"] = trg
            state[str(r2.get("id") or k).lower()] = r2
            moving[cl] = (str(r2.get("id") or k).lower(), r2)
        # references among the other moved resources
        for cl, (k, r) in list(moving.items()):
            if cl != il and not cl.startswith(il + "/"):
                r2 = _walk_replace(r, pat, new_id)
                if r2 is not r:
                    state[k] = r2
                    moving[cl] = (k, r2)
    return {"status": 204, "body": None}
