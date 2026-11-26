import json
import os
import re
import urllib.request

import boto3

EP = os.environ["AWS_ENDPOINT_URL"].rstrip("/")


def http(method, path, body=None):
    req = urllib.request.Request(EP + path, method=method, data=json.dumps(body).encode() if body is not None else None, headers={"content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=300).read())


sim = http("GET", "/api/terraform/export/bundle?format=json&mode=sim")
real = http("GET", "/api/terraform/export/bundle?format=json&mode=real")
have = sim["summary"]["by_type"]
print("exported", sim["summary"]["resources"], "resources:", ", ".join("%s x%d" % (k.replace("aws_", ""), v) for k, v in sorted(have.items())))
for need, n in (("aws_dynamodb_table", 3), ("aws_lambda_function", 3), ("aws_sfn_state_machine", 1), ("aws_kms_key", 1), ("aws_sns_topic", 1), ("aws_sqs_queue", 1)):
    assert have.get(need, 0) >= n, "the export is missing %s (found %d)" % (need, have.get(need, 0))

# 1. Read the warnings the export gives for a real account.
print("warnings for a real account:")
for w in real["portability"]:
    print("  [%s] %s %s" % (w["severity"], w["code"], w.get("resource", "")))
codes = {w["code"] for w in real["portability"]}
assert "unique-name" in codes, "S3 bucket names are global: the export must warn about it"

# 2. The error that matters: literal simulator account ids left inside policies the earlier chapters wrote.
literal = [(f, i + 1) for f, t in real["files"].items() for i, line in enumerate(t.split("\n")) if "123456789012" in line]
assert literal and any(w["severity"] == "error" for w in real["portability"]), "the literal account id in the least-privilege policies must be flagged as an error"
print("literal simulator account id found at:", ", ".join("%s:%d" % x for x in literal[:5]), "(%d places)" % len(literal))
for f, t in real["files"].items():
    real["files"][f] = t.replace("123456789012", "${data.aws_caller_identity.current.account_id}") if "123456789012" in t and f != "versions.tf" else t
if 'data "aws_caller_identity"' not in "\n".join(real["files"].values()):
    real["files"]["data.tf"] = real["files"].get("data.tf", "") + '\ndata "aws_caller_identity" "current" {}\n'
assert not any("123456789012" in t for t in real["files"].values()), "the account id must be parameterised everywhere"
print("fixed: the account id now comes from data.aws_caller_identity, so the same files apply in any account")
os.makedirs("terraform-export", exist_ok=True)
for name, text in real["files"].items():
    open(os.path.join("terraform-export", name), "w").write(text)
print("wrote", len(real["files"]), "files to ./terraform-export (review them; on a real account run `tofu init && tofu plan`, never apply blind)")

# 3. Re-import into the simulator: the exported files must describe exactly what is running.
bundle = {"files": sim["files"], "binaries": sim["binaries"]}
plan = http("POST", "/api/terraform/plan", bundle)
assert plan["ok"] and not plan["errors"], plan["errors"]
changes = [i for i in plan["items"] if i["action"] != "exists"]
assert not changes, "a fresh export must plan to no changes, but: %s" % [(i["address"], i["action"]) for i in changes]
print("re-import plan: %d resources, 0 changes (the files match the running stack)" % len(plan["items"]))

# 4. Lose an environment, rebuild it from the files, compare.
ddb = boto3.client("dynamodb")
before = ddb.describe_table(TableName="facilities-assets")["Table"]["KeySchema"]
ddb.delete_table(TableName="facilities-assets")
plan = http("POST", "/api/terraform/plan", bundle)
create = [i["address"] for i in plan["items"] if i["action"] == "create"]
assert create == ["aws_dynamodb_table.facilities_assets"], "exactly the deleted table must be planned for creation, got %s" % create
http("POST", "/api/terraform/apply", bundle)
after = ddb.describe_table(TableName="facilities-assets")["Table"]["KeySchema"]
assert after == before, "the rebuilt table must have the same key schema"
plan = http("POST", "/api/terraform/plan", bundle)
assert all(i["action"] == "exists" for i in plan["items"]), "after the rebuild everything must exist again"
rows = ddb.scan(TableName="facilities-assets")["Count"]
assert rows == 0, "Terraform rebuilds infrastructure, not data"
print("rebuilt facilities-assets from the files: same key schema, plan is clean again; data rows restored:", rows, "(restore data from a backup, not from Terraform)")

# 5. What the export does not cover: say it out loud.
uncovered = {}
bd, ac = boto3.client("bedrock"), boto3.client("bedrock-agentcore-control")
for label, call in (("Bedrock guardrails", lambda: bd.list_guardrails()["guardrails"]),
                    ("AgentCore gateways", lambda: ac.list_gateways()["items"]),
                    ("AgentCore memories", lambda: ac.list_memories()["memories"]),
                    ("AgentCore runtimes", lambda: ac.list_agent_runtimes()["agentRuntimes"]),
                    ("Bedrock knowledge bases", lambda: boto3.client("bedrock-agent").list_knowledge_bases()["knowledgeBaseSummaries"])):
    try:
        n = len(call())
    except Exception:
        n = 0
    if n:
        uncovered[label] = n
exported_types = set(have)
assert not {"aws_bedrock_guardrail", "aws_bedrockagent_knowledge_base"} & exported_types, "unexpected coverage claim"
print("NOT in the Terraform export (rebuild with the chapter scripts or add as your own modules):", uncovered or "nothing found")
print("ship-it verified")
