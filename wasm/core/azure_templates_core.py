# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Azure "Export template" engine (Nano / dev_server / unified-ingress core, pure Python).

Real ARM ``POST /subscriptions/{sub}/resourcegroups/{rg}/exportTemplate`` takes
``{"resources": ["*" | resourceId...], "options": "IncludeParameterDefaultValue,IncludeComments"}``
and returns ``{"template": {...ARM...}}``. This module builds that template from the resources
the ARM store really holds, then DETERMINISTICALLY decompiles the same template to Bicep and
to Terraform (``azapi_resource`` form), the three tabs of the portal's Export template blade.

Limits (stated in the capability registry): read-only/system properties are dropped by a fixed
list, not by each RP's real schema; Terraform output uses the ``azapi`` provider's generic
resource (not hand-mapped ``azurerm_*`` resources); dependsOn/child-resource nesting is flat.
"""
from __future__ import annotations

import re

SCHEMA = "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#"
_DROP_PROPS = {"provisioningState", "creationDate", "createdAt", "lastModifiedAt", "etag"}
_SECRET = re.compile(r"(password|clientsecret|secretkey|connectionstring|primarykey|secondarykey|accountkey|sastoken)", re.I)
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_EXPR = re.compile(r"^\[(?!\[)(.*)\]$", re.S)
_PARAM = re.compile(r"parameters\('([^']+)'\)")


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


def build_template(records: list[dict], api_versions: dict[str, str], include_params: bool = True) -> dict:
    """ARM template from stored resource views (dicts with id/name/type/location/tags/properties...)."""
    params, resources = {}, []
    for r in sorted(records, key=lambda x: str(x.get("id", "")).lower()):
        rtype = r.get("type") or ""
        name = r.get("name", "")
        pname = f"{_sym(name)}_name"
        res = {"type": rtype, "apiVersion": api_versions.get(rtype.lower(), "2023-01-01"),
               "name": f"[parameters('{pname}')]" if include_params else name}
        if include_params:
            params[pname] = {"defaultValue": name, "type": "string"}
        for k in ("location", "kind", "sku", "identity", "tags", "extendedLocation"):
            if r.get(k) not in (None, {}, ""):
                res[k] = _clean(r[k])
        props = _clean(r.get("properties") or {})
        if props:
            res["properties"] = props
        resources.append(res)
    t = {"$schema": SCHEMA, "contentVersion": "1.0.0.0"}
    if include_params:
        t["parameters"] = params
    t["variables"] = {}
    t["resources"] = resources
    return t


def _res_sym(name: str) -> str:
    m = _EXPR.match(name)
    if m:
        pm = _PARAM.fullmatch(m.group(1).strip())
        name = pm.group(1) if pm else name
    return re.sub(r"_name$", "", _sym(name))


# ── Bicep ────────────────────────────────────────────────────────────────────────────────
def _bq(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n") + "'"


def _bval(v, ind=0) -> str:
    pad, pad2 = "  " * ind, "  " * (ind + 1)
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "null"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        m = _EXPR.match(v)
        if m:
            pm = _PARAM.fullmatch(m.group(1).strip())
            return pm.group(1) if pm else m.group(1).strip()
        return _bq(v)
    if isinstance(v, list):
        if not v:
            return "[]"
        return "[\n" + "\n".join(f"{pad2}{_bval(x, ind + 1)}" for x in v) + f"\n{pad}]"
    if not v:
        return "{}"
    lines = [f"{pad2}{k if _IDENT.match(k) else _bq(k)}: {_bval(x, ind + 1)}" for k, x in v.items()]
    return "{\n" + "\n".join(lines) + f"\n{pad}}}"


def to_bicep(template: dict) -> str:
    out = []
    for pname, p in (template.get("parameters") or {}).items():
        line = f"param {pname} {p.get('type', 'string')}"
        if "defaultValue" in p:
            line += f" = {_bval(p['defaultValue'])}"
        out.append(line)
    if out:
        out.append("")
    for r in template.get("resources", []):
        body = {k: v for k, v in r.items() if k not in ("type", "apiVersion")}
        out.append(f"resource {_res_sym(r['name'])} '{r['type']}@{r['apiVersion']}' = {_bval(body)}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


# ── Terraform (azapi) ────────────────────────────────────────────────────────────────────
def _hq(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("${", "$${") + '"'


def _hval(v, ind=0) -> str:
    pad, pad2 = "  " * ind, "  " * (ind + 1)
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "null"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        m = _EXPR.match(v)
        if m:
            pm = _PARAM.fullmatch(m.group(1).strip())
            if pm:
                return f"var.{pm.group(1)}"
        return _hq(v)
    if isinstance(v, list):
        if not v:
            return "[]"
        return "[\n" + ",\n".join(f"{pad2}{_hval(x, ind + 1)}" for x in v) + f"\n{pad}]"
    if not v:
        return "{}"
    lines = [f"{pad2}{k if _IDENT.match(k) else _hq(k)} = {_hval(x, ind + 1)}" for k, x in v.items()]
    return "{\n" + "\n".join(lines) + f"\n{pad}}}"


def to_terraform(template: dict, subscription: str, rg: str) -> str:
    out = ["terraform {", "  required_providers {", "    azapi = {", '      source = "Azure/azapi"', "    }", "  }", "}", ""]
    for pname, p in (template.get("parameters") or {}).items():
        out.append(f'variable "{pname}" {{\n  type    = string\n  default = {_hval(p.get("defaultValue", ""))}\n}}\n')
    for r in template.get("resources", []):
        lines = [f'  type      = {_hq(r["type"] + "@" + r["apiVersion"])}',
                 f'  name      = {_hval(r["name"])}',
                 f'  parent_id = "/subscriptions/{subscription}/resourceGroups/{rg}"']
        if r.get("location"):
            lines.append(f'  location  = {_hq(r["location"])}')
        if r.get("tags"):
            lines.append(f'  tags      = {_hval(r["tags"], 1)}')
        body = {k: v for k, v in r.items() if k in ("properties", "sku", "kind", "identity")}
        if body:
            lines.append(f'  body      = {_hval(body, 1)}')
        out.append(f'resource "azapi_resource" "{_res_sym(r["name"])}" {{\n' + "\n".join(lines) + "\n}\n")
    return "\n".join(out).rstrip() + "\n"


def export_group(state: dict, sub: str, rg: str, resources, api_versions: dict, include_params: bool = True) -> dict:
    """The exportTemplate action. ``resources`` = ["*"] or resource ids. Body = ARM
    ``ResourceGroupExportResult`` plus Vyomi's ``bicep``/``terraform`` renderings (a Vyomi
    extension — real Azure renders those in the portal client)."""
    want = None if (not resources or "*" in resources) else {str(x).lower() for x in resources}
    recs = []
    for key, r in state.items():
        if not isinstance(r, dict) or r.get("_sub") != sub or (r.get("_rg") or "").lower() != rg.lower():
            continue
        t = (r.get("_type") or "").lower()
        if "/" not in t or t == "microsoft.resources/resourcegroups" or t.startswith(("microsoft.authorization", "microsoft.security", "microsoft.insights")):
            continue
        if want is not None and str(r.get("id") or key).lower() not in want:
            continue
        recs.append({**{k: v for k, v in r.items() if not k.startswith("_")}, "type": r.get("_type")})
    if want is not None and not recs:
        return {"status": 404, "body": {"error": {"code": "ResourceNotFound", "message": "None of the requested resources are in this resource group."}}}
    tpl = build_template(recs, api_versions, include_params)
    return {"status": 200, "body": {"template": tpl, "bicep": to_bicep(tpl), "terraform": to_terraform(tpl, sub, rg)}}
