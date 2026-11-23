#!/usr/bin/env python3
"""Generate the IAM permission catalog for the services Vyomi simulates (design: docs/architecture/v4.0/IAM-FAITHFUL-DESIGN.md).

    python3 scripts/gen_iam_catalog.py aws          # fetch AWS Service Reference for the in-scope prefixes
    python3 scripts/gen_iam_catalog.py aws --offline-check   # validate the committed files only (no network; used by tests)

Permission IDs are copied VERBATIM from the vendor source (rule: catalog IDs are read-only; Vyomi data lives in the `vyomi` block that
the engine adds at load time, never in the ID). Output: core/iam_catalog/<cloud>/<service>.json, deterministic (sorted, no timestamps)
so a refresh shows up as a reviewable diff.

AWS source: https://servicereference.us-east-1.amazonaws.com/ (official, machine-readable: actions, access levels, resource types,
condition keys and the API-operation -> authorized-action map that drives the request->permission contract)."""
import json, os, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AWS_INDEX = "https://servicereference.us-east-1.amazonaws.com/"

# IAM service prefixes of the AWS services in the v4 console registry (consoles/src/aws/services/registry.js) and the cross-service
# prefixes their policies use. Add a prefix when a service is added (appliance rule 13 / IAM onboarding gate).
AWS_PREFIXES = ["s3", "dynamodb", "ec2", "ecr", "eks", "lambda", "rds", "apigateway", "execute-api", "iam", "sts", "kms",
                "secretsmanager", "sqs", "sns", "events", "logs", "cloudwatch", "cloudformation", "bedrock", "bedrock-agentcore",
                "ssm", "states", "kinesis", "redshift", "securityhub", "ce", "imagebuilder", "networkmanager", "backup",
                "elasticloadbalancing", "route53", "cognito-idp", "wafv2", "cloudtrail", "organizations", "tag"]


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "vyomi-iam-catalog"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def _level(p):
    if p.get("IsPermissionManagement"): return "permissions"
    if p.get("IsTaggingOnly"): return "tagging"
    if p.get("IsList"): return "list"
    if p.get("IsWrite"): return "write"
    return "read"


def aws_service(entry):
    d = _get(entry["url"])
    acts = {}
    for a in d.get("Actions", []):
        p = (a.get("Annotations") or {}).get("Properties", {})
        acts[a["Name"]] = {"l": _level(p), "r": sorted({r["Name"] for r in a.get("Resources", [])}),
                           "k": sorted(a.get("ActionConditionKeys", [])), **({"d": 1} if p.get("IsDataPlane") else {})}
    ops = {}
    for o in d.get("Operations", []):
        names = sorted({x["Name"] for x in o.get("AuthorizedActions", []) if x.get("Service") == d["Name"]})
        if names: ops[o["Name"]] = names
    return {"cloud": "aws", "service": d["Name"], "name": d.get("ServiceName", ""), "version": d.get("Version", ""),
            "actions": dict(sorted(acts.items())),
            "resources": {r["Name"]: sorted(r.get("ARNFormats", [])) for r in sorted(d.get("Resources", []), key=lambda r: r["Name"])},
            "conditionKeys": {k["Name"]: (k.get("Types") or [""])[0] for k in sorted(d.get("ConditionKeys", []), key=lambda k: k["Name"])},
            "operations": dict(sorted(ops.items()))}


def gen_aws():
    idx = {e["service"]: e for e in _get(AWS_INDEX)}
    out = os.path.join(ROOT, "core", "iam_catalog", "aws"); os.makedirs(out, exist_ok=True)
    total = 0
    for pre in AWS_PREFIXES:
        if pre not in idx:
            print("  !! not in the AWS Service Reference:", pre); continue
        doc = aws_service(idx[pre]); total += len(doc["actions"])
        with open(os.path.join(out, pre + ".json"), "w") as f:
            json.dump(doc, f, indent=0, sort_keys=False, separators=(",", ":")); f.write("\n")
        print(f"  {pre:22} {len(doc['actions']):5} actions {len(doc['operations']):5} operations")
    print("aws total actions:", total)


def check(cloud):
    d = os.path.join(ROOT, "core", "iam_catalog", cloud); n = 0
    for f in sorted(os.listdir(d)):
        j = json.load(open(os.path.join(d, f))); assert j["cloud"] == cloud and j["actions"], f; n += len(j["actions"])
    print(cloud, "catalog ok:", n, "permissions")


if __name__ == "__main__":
    cloud = sys.argv[1] if len(sys.argv) > 1 else "aws"
    if "--offline-check" in sys.argv: check(cloud)
    elif cloud == "aws": gen_aws()
    else: sys.exit(f"{cloud}: generator not written yet (see the design doc, phase 0)")
