"""IAM: customer-managed policies, roles (+ inline policies, managed-policy attachments)."""
from __future__ import annotations

import json
import urllib.parse

from core.tf_export import hcl
from core.tf_export.core import Ctx, exporter, tags_of


def _doc(d):
    if isinstance(d, str):
        d = json.loads(urllib.parse.unquote(d))
    return d


def _paged(fn, key, **kw):
    out, marker = [], None
    while True:
        r = fn(**kw, **({"Marker": marker} if marker else {}))
        out += r.get(key, [])
        if not r.get("IsTruncated"):
            return out
        marker = r.get("Marker")


@exporter(20, "iam-policies")
def export_policies(ctx: Ctx) -> None:
    iam = ctx.c["iam"]
    for p in _paged(iam.list_policies, "Policies", Scope="Local"):
        arn = p["Arn"]
        doc = iam.get_policy_version(PolicyArn=arn, VersionId=p["DefaultVersionId"])["PolicyVersion"]["Document"]
        attrs = {"name": p["PolicyName"], "path": None if p.get("Path", "/") == "/" else p["Path"],
                 "description": p.get("Description") or None, "policy": hcl.jsonencode(_doc(doc))}
        ctx.add("aws_iam_policy", arn, p["PolicyName"], attrs, file="iam.tf")


@exporter(21, "iam-roles")
def export_roles(ctx: Ctx) -> None:
    iam = ctx.c["iam"]
    roles = [r for r in _paged(iam.list_roles, "Roles") if not r.get("Path", "/").startswith("/aws-service-role/")]
    for r in roles:  # reserve first: other resources (and inline policies) reference roles by ARN
        ctx.reserve("aws_iam_role", r["Arn"], r["RoleName"])
    for r in roles:
        name = r["RoleName"]
        full = iam.get_role(RoleName=name)["Role"]
        attrs = {"name": name, "path": None if r.get("Path", "/") == "/" else r["Path"],
                 "assume_role_policy": hcl.jsonencode(_doc(full["AssumeRolePolicyDocument"])),
                 "description": full.get("Description") or None,
                 "max_session_duration": full.get("MaxSessionDuration") if full.get("MaxSessionDuration") not in (None, 3600) else None,
                 "tags": tags_of(full.get("Tags")) or None}
        addr = ctx.add("aws_iam_role", r["Arn"], name, attrs, file="iam.tf")
        role_name = hcl.Ref(f"{addr}.name")
        for pname in _paged(iam.list_role_policies, "PolicyNames", RoleName=name):
            doc = iam.get_role_policy(RoleName=name, PolicyName=pname)["PolicyDocument"]
            ctx.add("aws_iam_role_policy", f"{name}/{pname}", f"{name}_{pname}",
                    {"name": pname, "role": role_name, "policy": hcl.jsonencode(_doc(doc))}, file="iam.tf")
        for a in _paged(iam.list_attached_role_policies, "AttachedPolicies", RoleName=name):
            ctx.add("aws_iam_role_policy_attachment", f"{name}/{a['PolicyArn']}", f"{name}_{a['PolicyName']}",
                    {"role": role_name, "policy_arn": ctx.ref("aws_iam_policy", a["PolicyArn"], "arn")}, file="iam.tf")
