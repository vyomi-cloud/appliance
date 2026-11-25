import json

from botocore.exceptions import ClientError

import iamkit
import vymodels
from iamkit import allow

iamkit.enforce("enforce")
arn = lambda m: "arn:aws:bedrock:us-east-1::foundation-model/" + m
p = iamkit.principal("agent-model-caller", [allow("bedrock:InvokeModel", [arn(vymodels.CHAT_MODEL), arn(vymodels.EMBED_MODEL)])])
rt = iamkit.client("bedrock-runtime", p)
req = dict(modelId=vymodels.CHAT_MODEL, messages=[{"role": "user", "content": [{"text": "Reply with the single word OK."}]}])

since = iamkit.last_audit_id()
try:
    rt.converse(**req)
    first = "allowed"
except ClientError as e:
    first = e.response["Error"]["Code"]
missing = iamkit.denied(p, since)
print("first call:", first, "| the audit log says the policy is missing:", [a for a, _ in missing])
assert first != "allowed" and missing, "the deliberately thin policy must be refused and the audit log must say why"

added = iamkit.settle(p, lambda: rt.converse(**req))
print("settled by granting:", [(s["Action"][0]) for s in added])
assert rt.converse(**req)["stopReason"], "the model call must work with the settled policy"

# Least privilege means the policy is also NARROW: another model, and any control-plane action, stay refused.
since = iamkit.last_audit_id()
for label, call in (("other model", lambda: rt.invoke_model(modelId="vyomi.not-granted", body=json.dumps({"inputText": "x"}))),
                    ("create guardrail", lambda: iamkit.client("bedrock", p).create_guardrail(name="x", blockedInputMessaging="a", blockedOutputsMessaging="b"))):
    try:
        call()
        raise AssertionError(label + " must be refused")
    except ClientError as e:
        assert e.response["Error"]["Code"] in ("AccessDenied", "AccessDeniedException", "403"), e
        print("refused as intended:", label)
print("audit trail holds", len([r for r in iamkit.audit(p) if r["decision"] == "deny"]), "denials and",
      len([r for r in iamkit.audit(p) if r["decision"] == "allow"]), "allows for", p["name"])
print("least-privilege model caller verified")
