"""Part C: ValidatePolicy catalog-provable codes, analyzeIamPolicy deny rules (extension), Azure custom role checks (extension)."""
import os, sys, json
sys.path[:0] = [os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "core")]
from core.iam_engine import access_analyzer as aa, analyze_azure as az, analyze_gcp as gc


def _codes(doc, t="IDENTITY_POLICY"):
    return {(f["issueCode"], f["findingType"]) for f in aa.validate_policy(doc, t)}


def test_validate_policy_new_codes():
    d = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": ["s3:GetObject", "s3:Get*", "s3:GetObject"],
         "Resource": ["arn:aws:s3:us-east-1::bkt", "arn:aws:sqs:::q", "arn:aws:s3:::bkt"],
         "Condition": {"StringEquals": {"s3:BogusKey": "x", "s3:ResourceAccount": "1", "aws:RequestTag/Team": "a"}}}]}
    c = _codes(d)
    assert ("INVALID_ARN_REGION", "ERROR") in c and ("UNSUPPORTED_RESOURCE_FOR_ACTION", "ERROR") in c and ("UNSUPPORTED_ACTION_FOR_RESOURCE", "ERROR") in c
    assert ("INVALID_CONDITION_KEY", "ERROR") in c and ("REDUNDANT_ACTION", "SUGGESTION") in c
    msgs = [f["findingDetails"] for f in aa.validate_policy(d)]
    assert not any("s3:ResourceAccount" in m for m in msgs) and not any("aws:RequestTag" in m for m in msgs)       # valid keys are not flagged


def test_validate_policy_clean_policy_has_no_new_findings():
    d = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": ["s3:GetObject", "s3:ListBucket"], "Resource": ["arn:aws:s3:::bkt", "arn:aws:s3:::bkt/*"]}]}
    assert not any(code in ("INVALID_ARN_REGION", "UNSUPPORTED_RESOURCE_FOR_ACTION", "INVALID_CONDITION_KEY", "REDUNDANT_ACTION") for code, _ in _codes(d))
    # ListBucket on the object ARN: proven mismatch by the catalog; GetObject on bucket ARN likewise
    bad = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "s3:ListBucket", "Resource": "arn:aws:s3:::bkt/*"}]}
    assert ("UNSUPPORTED_ACTION_FOR_RESOURCE", "ERROR") in _codes(bad)


def test_gcp_analyze_deny_policies():
    state = {"allow_policies": {"projects/p": {"bindings": [{"role": "roles/viewer", "members": ["user:a@x.com"]}]}},
             "deny_policies": {}}
    out = gc.analyze_iam_policy("projects/p", {"analysisQuery.identitySelector.identity": "user:a@x.com", "analysisQuery.options.includeDenyPolicies": "true"}, state)
    assert out["vyomiDenyAnalysis"]["denyRules"] == [] and "note" in out["vyomiDenyAnalysis"]
    plain = gc.analyze_iam_policy("projects/p", {"analysisQuery.identitySelector.identity": "user:a@x.com"}, state)
    assert "vyomiDenyAnalysis" not in plain                            # off by default: native response unchanged


def test_azure_custom_role_checks():
    body = {"properties": {"roleName": "r", "assignableScopes": [], "permissions": [{"actions": ["Microsoft.Storage/storageAccounts/read", "Microsoft.Storage/*/read",
            "Microsoft.Authorization/roleAssignments/write", "Microsoft.Storage/nosuchop/read"], "notActions": ["Microsoft.Compute/virtualMachines/delete"], "dataActions": []}]}}
    out = az.check_custom_role(body, {})
    codes = {f["issueCode"] for f in out["findings"]}
    assert {"MISSING_ASSIGNABLE_SCOPES", "REDUNDANT_ACTION", "PRIVILEGE_ESCALATION", "NOT_ACTION_NO_EFFECT"} <= codes and out["result"] == "FAIL"
    owner = az.check_custom_role({"properties": {"assignableScopes": ["/"], "permissions": [{"actions": ["*"]}]}}, {})
    assert any(f["issueCode"] == "WILDCARD_OWNER_EQUIVALENT" for f in owner["findings"])
    ref = {"properties": {"permissions": [{"actions": ["Microsoft.Storage/*/read"]}]}}
    nn = az.check_custom_role({"properties": {"assignableScopes": ["/"], "permissions": [{"actions": ["Microsoft.Storage/storageAccounts/read", "Microsoft.Storage/storageAccounts/write"]}]}, "reference": ref}, {})
    assert nn["noNewAccess"] == {"result": "FAIL", "newAccess": ["Microsoft.Storage/storageAccounts/write"]}
