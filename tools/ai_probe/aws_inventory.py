#!/usr/bin/env python3
"""Phase 0 (AI enterprise plan): AWS operation inventory = the denominator of "100% conformance".

Reads the official botocore service models (pinned by the installed botocore version) for the in-scope services and writes
aws_inventory.csv: service, operation, in_scope (default 'yes', owner flips non-goals), core_mentions (how many core/*.py files
mention the operation name: a CRUDE signal that something handles it, NOT proof; contract tests replace it).

usage: python3 aws_inventory.py <path-to-core-dir> <out.csv>
"""
import csv, sys, re, pathlib, botocore, botocore.session

SERVICES = {  # botocore service name -> plan components
    "bedrock": "C2,C6,C8,C10,C11", "bedrock-runtime": "C2,C10,C11", "bedrock-agent": "C3,C6", "bedrock-agent-runtime": "C3,C6,C11",
    "bedrock-agentcore-control": "C3,C4,C8,C9", "bedrock-agentcore": "C3,C4,C9", "cognito-idp": "C1,C13", "cognito-identity": "C1",
    "wafv2": "C1", "opensearchserverless": "C6,C12", "opensearch": "C6,C12", "stepfunctions": "C5", "cloudtrail": "C13",
    "cloudwatch": "C8", "logs": "C8", "xray": "C8", "lambda": "C7", "dynamodb": "C5,C7", "kms": "C13", "sns": "C2,C12", "sqs": "C12",
    "events": "C12", "s3": "C12", "timestream-write": "C7", "timestream-query": "C7", "textract": "C12", "comprehend": "C12",
}
core_dir, out = pathlib.Path(sys.argv[1]), sys.argv[2]
blob = {p: p.read_text(errors="ignore") for p in core_dir.rglob("*.py")}
sess = botocore.session.get_session()
rows = []
for svc, comps in SERVICES.items():
    try:
        m = sess.get_service_model(svc)
    except Exception as e:
        rows.append((svc, "(service model not found in this botocore)", "?", 0, comps)); continue
    for op in sorted(m.operation_names):
        pat = re.compile(r"\b" + re.escape(op) + r"\b|\b" + re.escape(re.sub(r"(?<!^)(?=[A-Z])", "_", op).lower()) + r"\b")
        n = sum(1 for t in blob.values() if pat.search(t))
        rows.append((svc, op, "yes", n, comps))
with open(out, "w", newline="") as f:
    w = csv.writer(f); w.writerow(["service", "operation", "in_scope", "core_mentions", "components"]); w.writerows(rows)
tot = {}
for s, o, i, n, c in rows:
    t = tot.setdefault(s, [0, 0]); t[0] += 1; t[1] += 1 if n else 0
print(f"botocore {botocore.__version__}")
print(f"{'service':28} {'ops':>5} {'mentioned in core':>18}")
for s, (a, b) in tot.items(): print(f"{s:28} {a:5d} {b:18d}")
print(f"{'TOTAL':28} {sum(a for a,b in tot.values()):5d} {sum(b for a,b in tot.values()):18d}")
