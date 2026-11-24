# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Cloud-neutral infrastructure graph for the import/export console: nodes, dependency edges, containment groups, and a
per-resource-type availability verdict (supported / planned / not possible in Vyomi), plus the real-cloud portability report."""
from __future__ import annotations

import re
from typing import Any

from core.tf_export import hcl
from core.tf_export.core import Ctx, registered

# What Vyomi can never do, with the reason shown in the console. Everything else not exported yet is "planned".
NOT_POSSIBLE: dict[str, str] = {
    "aws_cloudfront_distribution": "Needs a global edge network; Vyomi runs on one machine.",
    "aws_directconnect_connection": "Needs physical network links to a real data centre.",
    "aws_shield_protection": "DDoS protection operates on the real provider's network edge.",
    "aws_route53domains_registered_domain": "Registers a real domain with a registrar.",
    "aws_acm_certificate_validation": "Needs a public CA and real DNS to validate ownership.",
    "aws_organizations_account": "Creates real, billable accounts.",
    "aws_vpn_connection": "Needs a real remote peer to terminate the tunnel.",
    "aws_wafv2_web_acl_association": "Edge/regional WAF enforcement is not simulated.",
}

_SERVICE = [("aws_vpc", "vpc"), ("aws_subnet", "vpc"), ("aws_internet_gateway", "vpc"), ("aws_route_table", "vpc"),
            ("aws_security_group", "vpc"), ("aws_s3_", "s3"), ("aws_iam_", "iam"), ("aws_lambda_", "lambda"),
            ("aws_api_gateway_", "apigateway"), ("aws_db_", "rds"), ("aws_secretsmanager_", "secretsmanager"),
            ("aws_dynamodb_", "dynamodb"), ("aws_sqs_", "sqs"), ("aws_sns_", "sns"), ("aws_cloudwatch_event_", "eventbridge"),
            ("aws_kms_", "kms"), ("aws_sfn_", "stepfunctions"), ("aws_ecr_", "ecr"), ("aws_backup_", "backup"),
            ("aws_instance", "ec2"), ("aws_key_pair", "ec2"), ("aws_ebs_volume", "ec2"), ("aws_volume_attachment", "ec2"),
            ("aws_cloudwatch_", "cloudwatch")]
_NETWORK_CHILDREN = {"aws_subnet", "aws_internet_gateway", "aws_route_table", "aws_security_group"}
_ADDR = re.compile(r"\b(aws_[a-z0-9_]+\.[A-Za-z0-9_\-]+)\.")


def service_of(rtype: str) -> str:
    return next((s for prefix, s in _SERVICE if rtype.startswith(prefix)), rtype.split("_")[1] if "_" in rtype else rtype)


def supported_types() -> set[str]:
    """Resource types the exporter writes today (derived from the registered exporters' source)."""
    import inspect
    found: set[str] = set()
    for _o, _n, fn in registered():
        found |= set(re.findall(r'"(aws_[a-z0-9_]+)"', inspect.getsource(inspect.getmodule(fn))))
    return found


def classify(types: list[str]) -> dict[str, dict[str, str]]:
    """Availability of each Terraform resource type in Vyomi: supported | planned | not_possible (with the reason)."""
    sup = supported_types()
    out = {}
    for t in types:
        if t in NOT_POSSIBLE:
            out[t] = {"status": "not_possible", "reason": NOT_POSSIBLE[t]}
        elif t in sup:
            out[t] = {"status": "supported", "reason": ""}
        else:
            out[t] = {"status": "planned", "reason": "Not simulated or exported yet."}
    return out


def _refs(v: Any, acc: set[str]) -> None:
    if isinstance(v, hcl.Ref):
        acc.update(_ADDR.findall(v.expr))
    elif isinstance(v, dict):
        for x in v.values():
            _refs(x, acc)
    elif isinstance(v, (list, tuple)):
        for x in v:
            _refs(x, acc)


def build_graph(ctx: Ctx) -> dict[str, Any]:
    addrs = {f"{r.type}.{r.name}" for r in ctx.resources}
    nodes, edges, groups = [], [], []
    verdict = classify(sorted({r.type for r in ctx.resources}))
    vpc_group = {}
    for r in ctx.resources:
        if r.type == "aws_vpc":
            vpc_group[f"{r.type}.{r.name}"] = f"group.{r.name}"
            groups.append({"id": f"group.{r.name}", "kind": "vpc", "label": (r.attrs.get("tags") or {}).get("Name") or r.name,
                           "cidr": r.attrs.get("cidr_block")})
    for r in ctx.resources:
        nid = f"{r.type}.{r.name}"
        refs: set[str] = set()
        _refs(r.attrs, refs)
        for b in r.blocks:
            _refs(b[1], refs)
            for c in (b[2] if len(b) > 2 else []):
                _refs(c[1], refs)
        refs.discard(nid)
        group = next((vpc_group[x] for x in sorted(refs) if x in vpc_group), None) if r.type in _NETWORK_CHILDREN else None
        nodes.append({"id": nid, "type": r.type, "service": service_of(r.type), "label": r.name, "group": group,
                      "status": verdict[r.type]["status"]})
        for x in sorted(refs):
            if x not in addrs or (group is not None and vpc_group.get(x) == group):
                continue  # containment inside a VPC is drawn as nesting, not as an edge
            edges.append({"from": nid, "to": x})
    return {"groups": groups, "nodes": nodes, "edges": edges, "availability": verdict}


def portability(ctx: Ctx, files: dict[str, str], real_cloud: bool) -> list[dict[str, str]]:
    """What a user must know before applying the export to a real account."""
    out: list[dict[str, str]] = []
    text = "\n".join(files.values())
    if "123456789012" in text:
        out.append({"severity": "error", "code": "account-id",
                    "message": "Contains the simulator's account id 123456789012. Export with mode=real to use the caller's account."})
    for r in ctx.resources:
        if r.type == "aws_s3_bucket":
            out.append({"severity": "warn", "code": "unique-name", "resource": f"{r.type}.{r.name}",
                        "message": f"S3 bucket name '{r.attrs.get('bucket')}' is global; it may already be taken in AWS."})
        if r.type == "aws_db_instance":
            out.append({"severity": "warn", "code": "cost", "resource": f"{r.type}.{r.name}",
                        "message": "A real RDS instance is billed per hour. Run `tofu plan` first and set a real password variable."})
    for name in ctx.variables:
        out.append({"severity": "warn", "code": "secret", "message": f"Variable '{name}' holds a simulator value; set a real one."})
    if ctx.files_bin:
        out.append({"severity": "info", "code": "code", "message": "Lambda code is bundled under lambda/; check runtimes exist in the target region."})
    out.append({"severity": "info", "code": "defaults",
                "message": "Attributes Vyomi does not model use the real cloud's own defaults and may differ from what you saw here."})
    return out
