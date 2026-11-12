# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""CloudFormation registry: public extensions, activation, modules, type configuration, publisher registration — substrate-independent.

Adds to core/cloudformation_core (Query-protocol XML): a PUBLIC catalog (the AWS-published resource types the engine provisions + third-party
extensions published by Vyomi's own SaaS-partner simulators, publisher `vyomi.cloud`), ListTypes with Visibility/Type/Filters.Category/PublisherId/
TypeNamePrefix, ActivateType / DeactivateType (with TypeNameAlias, AutoUpdate, LoggingConfig, ExecutionRoleArn), DescribeType / ListTypeVersions
for any of them, SetTypeConfiguration for activated types, RegisterPublisher / DescribePublisher / PublishType.

MODULES ARE REAL: an activated `Vyomi::...::MODULE` type is expanded into its resources when a template that uses it is parsed (CreateStack /
change sets / StackSets), with the module's Parameters bound from the resource Properties and its resources prefixed by the logical id, so
the stack provisions real SQS queues / S3 buckets. Activated third-party HOOKS reuse the existing hook engine.

Honest limits: third-party RESOURCE types can be activated and described (schema) but have no handler, so a stack using one fails with an
unsupported-resource-type error; type configuration is stored and returned but only hooks read it; publisher verification is simulated
(VERIFIED when a ConnectionArn is supplied). State: `store.registry`.
"""
from __future__ import annotations

import copy
import json
import re
import time

PUB_ID = "7f3c9d1e5b2a48c6a0d1e2f3b4c5d6e7"      # Vyomi's verified publisher (the SaaS-partner simulators)
PUB_NAME = "Vyomi Cloud"
AWS_PUB = "AWS"
_MODULE_RE = re.compile(r"^[A-Za-z0-9]{2,64}::[A-Za-z0-9]{2,64}::[A-Za-z0-9]{2,64}(::[A-Za-z0-9]{2,64})?$")
_CONN_RE = re.compile(r"^arn:aws[-a-z]*:(codestar-connections|codeconnections):[a-z0-9-]+:\d{12}:connection/[0-9a-f-]{36}$")
_ROLE_RE = re.compile(r"^arn:aws[-a-z]*:iam::\d{12}:role/.+$")

# third-party catalog published by Vyomi's SaaS-partner simulators
CATALOG = {
    "Vyomi::Shop::Order": {"kind": "RESOURCE", "desc": "A Vyomi Shop order (SaaS partner resource).",
                           "schema": {"typeName": "Vyomi::Shop::Order", "properties": {"Sku": {"type": "string"}, "Quantity": {"type": "integer"}},
                                      "required": ["Sku"], "primaryIdentifier": ["/properties/OrderId"]}},
    "Vyomi::Auth::User": {"kind": "RESOURCE", "desc": "A Vyomi Auth user (SaaS partner resource).",
                          "schema": {"typeName": "Vyomi::Auth::User", "properties": {"Email": {"type": "string"}}, "required": ["Email"]}},
    "Vyomi::Messaging::QueuePair::MODULE": {
        "kind": "MODULE", "desc": "An SQS queue with its dead-letter queue.",
        "template": {"Parameters": {"VisibilityTimeout": {"Type": "Number", "Default": 30}},
                     "Resources": {"Dlq": {"Type": "AWS::SQS::Queue", "Properties": {}},
                                   "Queue": {"Type": "AWS::SQS::Queue", "Properties": {"VisibilityTimeout": {"Ref": "VisibilityTimeout"}}}}}},
    "Vyomi::Storage::LogBucket::MODULE": {
        "kind": "MODULE", "desc": "An S3 bucket for application logs.",
        "template": {"Parameters": {},
                     "Resources": {"Bucket": {"Type": "AWS::S3::Bucket", "Properties": {}}}}},
    "Vyomi::Guard::RequiredTags": {"kind": "HOOK", "desc": "Fails stacks that are missing required tags (reuses the hook engine)."},
}


def _c():
    try:
        from core import cloudformation_core as m
    except ImportError:  # Pyodide flat layout
        import cloudformation_core as m  # type: ignore
    return m


def _reg(store) -> dict:
    r = getattr(store, "registry", None)
    if r is None:
        r = {}
        store.registry = r
    for k, v in (("activated", {}), ("config", {}), ("publisher", None), ("published", {})):
        r.setdefault(k, v)
    return r


def _arn(store, kind, name, public=False, account=True) -> str:
    c = _c()
    acct = "" if public else store.account_id
    return f"arn:aws:cloudformation:{c.REGION}:{acct}:type/{kind.lower()}/{name.replace('::', '-')}"


def _public_arn(store, name) -> str:
    return _arn(store, CATALOG[name]["kind"] if name in CATALOG else "resource", name, public=True)


def _entry(store, name):
    """(kind, publisher_id, publisher_name, desc) for a public type name, else None."""
    c = _c()
    if name in CATALOG:
        return CATALOG[name]["kind"], PUB_ID, PUB_NAME, CATALOG[name]["desc"]
    if name in c.RESOURCE_TYPES:
        return "RESOURCE", AWS_PUB, "Amazon Web Services", c._TYPE_DESCRIPTIONS.get(name, f"{name} resource provider")
    pub = _reg(store)["published"].get(name)
    if pub:
        return pub["kind"], pub["publisher_id"], "You", pub.get("desc", "")
    return None


def _all_public(store):
    c = _c()
    names = list(c.RESOURCE_TYPES) + list(CATALOG) + list(_reg(store)["published"])
    return sorted(dict.fromkeys(names))


def _find_by_arn_or_name(store, params):
    """Resolve Arn / PublicTypeArn / TypeName (+Type) -> catalog name."""
    c = _c()
    arn = c._p(params, "Arn") or c._p(params, "PublicTypeArn") or c._p(params, "TypeArn")
    name = c._p(params, "TypeName")
    if arn:
        m = re.search(r":type/(?:resource|module|hook)/(.+?)(?:/\d+)?$", arn)
        if m:
            slug = m.group(1)
            for n in _all_public(store) + list(_reg(store)["activated"]):
                if n.replace("::", "-") == slug:
                    return n
            for rec in _reg(store)["activated"].values():
                if rec["alias"].replace("::", "-") == slug:
                    return rec["name"]
        raise c.CfnError("TypeNotFoundException", f"The type {arn} cannot be found.", 404)
    return name


def _summary_xml(store, name, activated_rec=None, public=True):
    c = _c()
    e = _entry(store, name)
    kind, pid, pname, desc = e if e else ("RESOURCE", "", "", "")
    act = activated_rec is not None or (name in c.RESOURCE_TYPES)
    shown = activated_rec["alias"] if activated_rec else name
    arn = _arn(store, kind, shown) if activated_rec else _public_arn(store, name)
    return ("<member>" + c._el("Type", kind) + c._el("TypeName", shown) + c._el("DefaultVersionId", "00000001") +
            c._el("TypeArn", arn) + c._el("LastUpdated", c._now_iso()) + c._el("Description", desc) +
            c._el("PublisherId", pid) + c._el("PublisherName", pname) + c._el("OriginalTypeName", name if activated_rec else "") +
            c._el("PublisherIdentity", "AWS_Marketplace" if pid != AWS_PUB else "") + c._el("LatestPublicVersion", "1.0.0") +
            c._el("IsActivated", "true" if act else "false") + "</member>")


def _list_types(orig):
    def fn(store, params, stores):
        c = _c()
        vis = c._p(params, "Visibility", "PRIVATE")   # AWS default
        typ = c._p(params, "Type") or "RESOURCE"
        cat = c._p(params, "Filters.Category")
        pid = c._p(params, "Filters.PublisherId")
        prefix = c._p(params, "Filters.TypeNamePrefix")
        if vis not in ("PUBLIC", "PRIVATE"):
            raise c.CfnError("ValidationError", "Visibility must be PUBLIC or PRIVATE.", 400)
        if typ and typ not in ("RESOURCE", "MODULE", "HOOK"):
            raise c.CfnError("ValidationError", "Type must be RESOURCE, MODULE or HOOK.", 400)
        if cat and cat not in ("REGISTERED", "ACTIVATED", "THIRD_PARTY", "AWS_TYPES"):
            raise c.CfnError("ValidationError", "Filters.Category is invalid.", 400)
        reg = _reg(store)
        if vis == "PRIVATE" and typ == "HOOK" and not cat:
            return orig(store, params, stores)
        out = []
        if vis == "PUBLIC":
            for n in _all_public(store):
                kind, p_id, _, _ = _entry(store, n)
                if cat == "AWS_TYPES" and p_id != AWS_PUB or cat == "THIRD_PARTY" and p_id == AWS_PUB:
                    continue
                if cat in ("ACTIVATED",) and n not in {r["name"] for r in reg["activated"].values()}:
                    continue
                if cat == "REGISTERED":
                    continue
                if kind != typ:
                    continue
                if (pid and p_id != pid) or (prefix and not n.startswith(prefix)):
                    continue
                out.append(_summary_xml(store, n))
        else:
            if cat in ("", "ACTIVATED"):
                for rec in reg["activated"].values():
                    if (not typ or rec["kind"] == typ) and (not prefix or rec["alias"].startswith(prefix)):
                        out.append(_summary_xml(store, rec["name"], rec))
        return c._envelope("ListTypes", "<TypeSummaries>" + "".join(out) + "</TypeSummaries>")
    return fn


def _activate(store, params, stores):
    c = _c()
    reg = _reg(store)
    kind_in = c._p(params, "Type")
    name = _find_by_arn_or_name(store, params)
    if not name:
        raise c.CfnError("ValidationError", "Specify PublicTypeArn or Type + TypeName + PublisherId.", 400)
    e = _entry(store, name)
    if not e or (kind_in and e[0] != kind_in):
        raise c.CfnError("TypeNotFoundException", f"The public type {name} cannot be found.", 404)
    if e[1] == AWS_PUB:
        raise c.CfnError("CFNRegistryException", f"{name} is published by AWS and is always available; it cannot be activated.", 400)
    pid_in = c._p(params, "PublisherId")
    if pid_in and pid_in != e[1]:
        raise c.CfnError("TypeNotFoundException", f"The type {name} is not published by {pid_in}.", 404)
    alias = c._p(params, "TypeNameAlias") or name
    if e[0] == "MODULE" and not alias.endswith("::MODULE"):
        raise c.CfnError("ValidationError", "A module alias must end with ::MODULE.", 400)
    if not _MODULE_RE.match(alias):
        raise c.CfnError("ValidationError", f"TypeNameAlias {alias} is not a valid type name (Org::Service::Name).", 400)
    role = c._p(params, "ExecutionRoleArn")
    if role and not _ROLE_RE.match(role):
        raise c.CfnError("ValidationError", "ExecutionRoleArn must be an IAM role ARN.", 400)
    if alias in reg["activated"] and reg["activated"][alias]["name"] != name:
        raise c.CfnError("CFNRegistryException", f"Alias {alias} is already used by another activated type.", 400)
    rec = reg["activated"].get(alias) or {"alias": alias, "name": name, "kind": e[0], "activated": time.time()}
    rec.update({"auto_update": c._bool(c._p(params, "AutoUpdate", "true")), "execution_role": role,
                "log_role": c._p(params, "LoggingConfig.LogRoleArn"), "log_group": c._p(params, "LoggingConfig.LogGroupName")})
    reg["activated"][alias] = rec
    if e[0] == "HOOK" and alias not in store.hooks:
        now = c._now_iso()
        store.hooks[alias] = {"type_name": alias, "description": e[3], "failure_mode": "WARN", "target_operations": [], "target_stacks": "ALL",
                              "required_tags": [], "enabled": False, "created_time": now, "last_updated_time": now}
    store.persist()
    return c._envelope("ActivateType", c._el("Arn", _arn(store, e[0], alias)))


def _deactivate(store, params, stores):
    c = _c()
    reg = _reg(store)
    alias = c._p(params, "TypeName")
    arn = c._p(params, "Arn")
    if arn:
        alias = next((a for a, r in reg["activated"].items() if _arn(store, r["kind"], a) == arn), "")
    rec = reg["activated"].get(alias)
    if not rec:
        raise c.CfnError("TypeNotFoundException", f"The type {alias or arn} is not activated in this account.", 404)
    if rec["kind"] == "MODULE" and _module_in_use(store, alias):
        raise c.CfnError("CFNRegistryException", f"Module {alias} is used by an existing stack and cannot be deactivated.", 400)
    del reg["activated"][alias]
    reg["config"].pop(alias, None)
    if rec["kind"] == "HOOK":
        store.hooks.pop(alias, None)
    store.persist()
    return c._envelope("DeactivateType")


def _module_in_use(store, alias) -> bool:
    for st in store.stacks.values():
        if st.get("status", "").startswith("DELETE_COMPLETE"):
            continue
        if alias in str(st.get("template_body", "")):
            return True
    return False


def _describe_type(orig):
    def fn(store, params, stores):
        c = _c()
        reg = _reg(store)
        if c._p(params, "Type") == "HOOK" and c._p(params, "TypeName") in store.hooks and not c._p(params, "Arn"):
            return orig(store, params, stores)
        name_in = c._p(params, "TypeName")
        arn = c._p(params, "Arn") or c._p(params, "PublicTypeArn")
        activated = reg["activated"].get(name_in)
        if activated is None and arn:
            activated = next((r for a, r in reg["activated"].items() if _arn(store, r["kind"], a) == arn), None)
        if activated:
            name = activated["name"]
        else:
            name = _find_by_arn_or_name(store, params) if (arn or name_in in CATALOG or name_in in _reg(store)["published"]) else name_in
        e = _entry(store, name) if name else None
        if name in _c().RESOURCE_TYPES and not activated and not arn:
            return orig(store, params, stores)
        if not e:
            return orig(store, params, stores)
        kind, pid, pname, desc = e
        cat = CATALOG.get(name) or {}
        schema = json.dumps(cat.get("schema") or ({"typeName": name, "description": desc, **({"Parameters": cat["template"]["Parameters"], "Resources": list(cat["template"]["Resources"])} if cat.get("template") else {})}))
        shown = activated["alias"] if activated else name
        cfg = reg["config"].get(shown)
        body = (c._el("Arn", _arn(store, kind, shown) if activated else _public_arn(store, name)) + c._el("Type", kind) + c._el("TypeName", shown) +
                c._el("DefaultVersionId", "00000001") + c._el("IsDefaultVersion", "true") + c._el("Description", desc) + c._el("Schema", schema) +
                c._el("ProvisioningType", "FULLY_MUTABLE" if kind == "RESOURCE" else "NON_PROVISIONABLE") + c._el("DeprecatedStatus", "LIVE") +
                c._el("Visibility", "PRIVATE" if activated else "PUBLIC") + c._el("PublisherId", pid) + c._el("OriginalTypeName", name if activated else "") +
                c._el("OriginalTypeArn", _public_arn(store, name) if activated else "") + c._el("LatestPublicVersion", "1.0.0") +
                c._el("IsActivated", "true" if (activated or pid == AWS_PUB) else "false") + c._el("LastUpdated", c._now_iso()) +
                c._el("TimeCreated", c._now_iso()))
        if activated:
            body += c._el("AutoUpdate", "true" if activated["auto_update"] else "false") + c._el("ExecutionRoleArn", activated["execution_role"])
            if activated["log_role"] or activated["log_group"]:
                body += "<LoggingConfig>" + c._el("LogRoleArn", activated["log_role"]) + c._el("LogGroupName", activated["log_group"]) + "</LoggingConfig>"
        if cfg:
            body += c._el("ConfigurationAlias", "default")
        return c._envelope("DescribeType", body)
    return fn


def _list_versions(store, params, stores):
    c = _c()
    reg = _reg(store)
    n = c._p(params, "TypeName")
    name = reg["activated"][n]["name"] if n in reg["activated"] else (n if n else _find_by_arn_or_name(store, params))
    e = _entry(store, name)
    if not e and name not in store.hooks:
        raise c.CfnError("TypeNotFoundException", f"The type {name} cannot be found.", 404)
    kind = e[0] if e else "HOOK"
    return c._envelope("ListTypeVersions", "<TypeVersionSummaries><member>" + c._el("Type", kind) + c._el("TypeName", name) + c._el("VersionId", "00000001") +
                       c._el("IsDefaultVersion", "true") + c._el("Arn", _public_arn(store, name) + "/00000001") +
                       c._el("TimeCreated", c._now_iso()) + c._el("Description", e[3] if e else "") + "</member></TypeVersionSummaries>")


def _set_config(orig):
    def fn(store, params, stores):
        c = _c()
        reg = _reg(store)
        name = c._p(params, "TypeName")
        if name in store.hooks or name not in reg["activated"]:
            if name in store.hooks:
                return orig(store, params, stores)
            if _entry(store, name) is None:
                raise c.CfnError("TypeNotFoundException", f"The type {name or c._p(params, 'TypeArn')} cannot be found.", 404)
            raise c.CfnError("CFNRegistryException", f"The type {name} is not activated in this account; activate it first.", 400)
        raw = c._p(params, "Configuration")
        try:
            json.loads(raw)
        except Exception:
            raise c.CfnError("ValidationError", "Configuration must be valid JSON.", 400)
        reg["config"][name] = raw
        store.persist()
        return c._envelope("SetTypeConfiguration", c._el("ConfigurationArn", f"arn:aws:cloudformation:{c.REGION}:{store.account_id}:type-configuration/{reg['activated'][name]['kind'].lower()}/{name.replace('::', '-')}/default"))
    return fn


def _batch_describe_configs(store, params, stores):
    c = _c()
    reg = _reg(store)
    i, out, errs = 1, [], []
    while f"TypeConfigurationIdentifiers.member.{i}.TypeName" in params:
        n = params[f"TypeConfigurationIdentifiers.member.{i}.TypeName"]
        if n in reg["config"]:
            out.append("<member>" + c._el("TypeName", n) + c._el("Configuration", reg["config"][n]) + c._el("Alias", "default") +
                       c._el("LastUpdated", c._now_iso()) + "</member>")
        else:
            errs.append("<member><ErrorCode>ConfigurationNotFound</ErrorCode><ErrorMessage>No configuration for " + c._xe(n) + "</ErrorMessage></member>")
        i += 1
    return c._envelope("BatchDescribeTypeConfigurations", "<TypeConfigurations>" + "".join(out) + "</TypeConfigurations><Errors>" + "".join(errs) + "</Errors>")


def _register_publisher(store, params, stores):
    c = _c()
    reg = _reg(store)
    if not c._bool(c._p(params, "AcceptTermsAndConditions", "false")) and not reg["publisher"]:
        raise c.CfnError("ValidationError", "You must accept the publisher terms and conditions (AcceptTermsAndConditions=true).", 400)
    conn = c._p(params, "ConnectionArn")
    if conn and not _CONN_RE.match(conn):
        raise c.CfnError("ValidationError", "ConnectionArn must be a CodeConnections connection ARN.", 400)
    if not reg["publisher"]:
        pid = __import__("hashlib").sha256(("pub" + store.account_id).encode()).hexdigest()[:32]
        reg["publisher"] = {"id": pid, "status": "VERIFIED" if conn else "UNVERIFIED",
                            "identity": ("GitHub" if conn else "AWS_Marketplace"), "connection": conn, "registered": time.time()}
    elif conn:
        reg["publisher"].update({"connection": conn, "status": "VERIFIED", "identity": "GitHub"})
    store.persist()
    return c._envelope("RegisterPublisher", c._el("PublisherId", reg["publisher"]["id"]))


def _describe_publisher(store, params, stores):
    c = _c()
    pub = _reg(store)["publisher"]
    pid = c._p(params, "PublisherId") or (pub["id"] if pub else "")
    if pid == PUB_ID:
        return c._envelope("DescribePublisher", c._el("PublisherId", PUB_ID) + c._el("PublisherStatus", "VERIFIED") + c._el("IdentityProvider", "AWS_Marketplace") +
                           c._el("PublisherProfile", "https://vyomi.cloud"))
    if pid == AWS_PUB:
        return c._envelope("DescribePublisher", c._el("PublisherId", AWS_PUB) + c._el("PublisherStatus", "VERIFIED") + c._el("IdentityProvider", "AWS_Marketplace"))
    if not pub or pid != pub["id"]:
        raise c.CfnError("CFNRegistryException", "This account is not registered as a publisher." if not pid else f"Publisher {pid} not found.", 400)
    return c._envelope("DescribePublisher", c._el("PublisherId", pub["id"]) + c._el("PublisherStatus", pub["status"]) + c._el("IdentityProvider", pub["identity"]) +
                       c._el("PublisherProfile", pub.get("connection") or ""))


def _publish_type(store, params, stores):
    c = _c()
    reg = _reg(store)
    if not reg["publisher"]:
        raise c.CfnError("CFNRegistryException", "Register as a publisher (RegisterPublisher) before publishing a type.", 400)
    name = c._p(params, "TypeName")
    h = store.hooks.get(name)
    if not h:
        raise c.CfnError("TypeNotFoundException", f"Only private types registered in this account can be published; {name or 'the type'} was not found.", 404)
    ver = c._p(params, "PublicVersionNumber", "1.0.0")
    if not re.match(r"^\d+\.\d+\.\d+$", ver):
        raise c.CfnError("ValidationError", "PublicVersionNumber must be MAJOR.MINOR.PATCH.", 400)
    reg["published"][name] = {"kind": "HOOK", "publisher_id": reg["publisher"]["id"], "desc": h.get("description", ""), "version": ver}
    store.persist()
    return c._envelope("PublishType", c._el("PublicTypeArn", _arn(store, "hook", name, public=True) + "/" + ver))


# ── module expansion (real): runs when a template is parsed ─────────────────────────────
def _subst(node, binds: dict, local: set, prefix: str):
    if isinstance(node, dict):
        if len(node) == 1 and "Ref" in node:
            r = node["Ref"]
            if r in binds:
                return copy.deepcopy(binds[r])
            if r in local:
                return {"Ref": prefix + r}
        if len(node) == 1 and "Fn::GetAtt" in node:
            ga = node["Fn::GetAtt"]
            if isinstance(ga, list) and ga and ga[0] in local:
                return {"Fn::GetAtt": [prefix + ga[0]] + ga[1:]}
        return {k: _subst(v, binds, local, prefix) for k, v in node.items()}
    if isinstance(node, list):
        return [_subst(v, binds, local, prefix) for v in node]
    return node


def expand_modules(doc: dict, store) -> dict:
    res = doc.get("Resources")
    if not isinstance(res, dict) or not any(isinstance(v, dict) and str(v.get("Type", "")).endswith("::MODULE") for v in res.values()):
        return doc
    c = _c()
    reg = _reg(store)
    out = {}
    for lid, r in res.items():
        t = str(r.get("Type", "")) if isinstance(r, dict) else ""
        if not t.endswith("::MODULE"):
            out[lid] = r
            continue
        rec = reg["activated"].get(t)
        if not rec or rec["kind"] != "MODULE":
            raise c.CfnError("ValidationError", f"Template format error: module {t} is not activated in this account (resource {lid}).", 400)
        tpl = CATALOG[rec["name"]]["template"]
        props = r.get("Properties") or {}
        decl = tpl.get("Parameters", {})
        for k in props:
            if k not in decl:
                raise c.CfnError("ValidationError", f"Template format error: module {t} has no parameter {k} (resource {lid}).", 400)
        binds = {k: props.get(k, d.get("Default")) for k, d in decl.items()}
        local = set(tpl["Resources"])
        for rid, rv in tpl["Resources"].items():
            out[lid + rid] = _subst(rv, binds, local, lid)
        # Fn::GetAtt/Ref against the module resource id itself resolve to the module's first resource
    if len(out) > 500:
        raise c.CfnError("ValidationError", "Template exceeds the 500 resource limit after module expansion.", 400)
    doc = dict(doc)
    doc["Resources"] = out
    return doc


def install(actions: dict) -> None:
    actions["ListTypes"] = _list_types(actions["ListTypes"])
    actions["DescribeType"] = _describe_type(actions["DescribeType"])
    actions["SetTypeConfiguration"] = _set_config(actions["SetTypeConfiguration"])
    actions.update({"ActivateType": _activate, "DeactivateType": _deactivate, "ListTypeVersions": _list_versions,
                    "BatchDescribeTypeConfigurations": _batch_describe_configs, "RegisterPublisher": _register_publisher,
                    "DescribePublisher": _describe_publisher, "PublishType": _publish_type})
