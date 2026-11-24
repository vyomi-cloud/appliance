#!/usr/bin/env python3
"""Generate core/iam_engine/aws_routes_data.py: the wire-route tables map_aws.py needs, derived from botocore's service models.

botocore is a GENERATION-time dependency only (the generated module is plain data; map_aws.py imports nothing third-party).
Usage:  <python with botocore> scripts/gen_iam_aws_routes.py
"""
import json
import os
import re
import sys

from botocore.session import get_session

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAT = os.path.join(ROOT, "core", "iam_catalog", "aws")
OUT = os.path.join(ROOT, "core", "iam_engine", "aws_routes_data.py")

# IAM prefix -> botocore models that carry its API operations (the IAM prefix is not always the botocore name)
MODELS = {
    "apigateway": ["apigateway", "apigatewayv2"], "backup": ["backup"], "bedrock": ["bedrock", "bedrock-agent", "bedrock-runtime", "bedrock-agent-runtime", "bedrock-data-automation", "bedrock-data-automation-runtime"],
    "bedrock-agentcore": ["bedrock-agentcore", "bedrock-agentcore-control"], "ce": ["ce"], "cloudformation": ["cloudformation", "cloudcontrol"],
    "cloudtrail": ["cloudtrail"], "cloudwatch": ["cloudwatch", "cloudwatchomni"], "cognito-idp": ["cognito-idp"], "dynamodb": ["dynamodb", "dynamodbstreams"],
    "ec2": ["ec2"], "ecr": ["ecr"], "eks": ["eks"], "elasticloadbalancing": ["elb", "elbv2"], "events": ["events", "eventbridgev2"], "execute-api": ["apigatewaymanagementapi"],
    "iam": ["iam", "iam-toolbox"], "imagebuilder": ["imagebuilder"], "kinesis": ["kinesis"], "kms": ["kms"], "lambda": ["lambda", "lambda-core", "lambda-microvms", "lambda-web"], "logs": ["logs"],
    "networkmanager": ["networkmanager"], "organizations": ["organizations"], "rds": ["rds"], "redshift": ["redshift"], "route53": ["route53"],
    "s3": ["s3", "s3control"], "secretsmanager": ["secretsmanager"], "securityhub": ["securityhub"], "sns": ["sns"], "sqs": ["sqs"],
    "ssm": ["ssm"], "states": ["stepfunctions"], "sts": ["sts"], "tag": ["resourcegroupstaggingapi"], "wafv2": ["wafv2"],
}
# SigV4 signing names that differ from the IAM prefix
SIGNING_EXTRA = {"monitoring": "cloudwatch", "email": "ses", "states": "states", "bedrock-runtime": "bedrock", "bedrock-agent-runtime": "bedrock",
                 "bedrock-agent": "bedrock", "s3-outposts": "s3", "s3-object-lambda": "s3", "tagging": "tag", "execute-api": "execute-api",
                 "application-autoscaling": "application-autoscaling", "dynamodb": "dynamodb", "elasticloadbalancing": "elasticloadbalancing",
                 "bedrock-agentcore": "bedrock-agentcore", "aws-marketplace": "aws-marketplace", "cloudcontrolapi": "cloudformation"}


def split_uri(uri):
    path, _, q = uri.partition("?")
    lits = []
    for part in [p for p in q.split("&") if p]:
        k, eq, v = part.partition("=")
        if v.startswith("{") and v.endswith("}"):
            continue          # bound to an input member, not a literal
        if k == "x-id":
            continue          # SDK-added tag, not guaranteed on the wire
        lits.append([k, v if eq else None])
    return path, lits


def main():
    sess = get_session()
    out = {"prefixes": {}, "signing": dict(SIGNING_EXTRA), "targets": {}}
    for prefix in sorted(os.path.basename(f)[:-5] for f in os.listdir(CAT) if f.endswith(".json")):
        ent = {"ops": [], "rest": [], "query": False, "target": []}
        for mname in MODELS.get(prefix, []):
            m = sess.get_service_model(mname)
            md = m.metadata
            sign = md.get("signingName") or md.get("endpointPrefix")
            out["signing"].setdefault(sign, prefix)
            if md.get("endpointPrefix"):
                out["signing"].setdefault(md["endpointPrefix"], prefix)
            if md.get("targetPrefix"):
                out["targets"][md["targetPrefix"]] = prefix
                ent["target"].append(md["targetPrefix"])
            proto = md.get("protocol")
            if "query" in (md.get("protocols") or [proto]) or proto in ("query", "ec2"):
                ent["query"] = True
            for op in m.operation_names:
                om = m.operation_model(op)
                ent["ops"].append(op)
                if proto in ("rest-json", "rest-xml"):
                    http = om.http
                    path, lits = split_uri(http["requestUri"])
                    rq, rh = [], []
                    shape = om.input_shape
                    if shape is not None:
                        for name in shape.required_members:
                            mem = shape.members[name]
                            loc = mem.serialization.get("location")
                            if loc == "querystring":
                                rq.append(mem.serialization.get("name", name))
                            elif loc == "header":
                                rh.append(mem.serialization.get("name", name).lower())
                    ent["rest"].append({"op": op, "m": http["method"], "p": path, "lq": lits, "rq": rq, "rh": rh, "mdl": mname})
        ent["ops"] = sorted(set(ent["ops"]))
        out["prefixes"][prefix] = ent
    out["botocore"] = __import__("botocore").__version__
    body = json.dumps(out, separators=(",", ":"), sort_keys=True)
    with open(OUT, "w") as f:
        f.write('"""GENERATED by scripts/gen_iam_aws_routes.py from botocore %s service models; do not edit by hand."""\nimport json\n\nROUTES = json.loads(%r)\n' % (out["botocore"], body))
    print("wrote", OUT, len(body), "bytes;", sum(len(p["rest"]) for p in out["prefixes"].values()), "REST routes")


if __name__ == "__main__":
    main()
