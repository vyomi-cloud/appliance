"""vyomi-endurance AWS stage 5 (serverless) regressions F100-F107 found by the Terraform estate.

    PYTHONPATH=. python3 tests/conformance/test_endurance_aws_serverless_core.py
"""
import json
import types

from core import lambda_core as lam, apigateway_core as gw, iam_core as iam, stepfunctions_core as sfn
from core.iam_store import InMemoryIamStore

F = "/2015-03-31/functions"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  [PASS] {name}")


def run():
    s = types.SimpleNamespace()

    def call(m, p, b=b"", q=None):
        return lam.dispatch(s, m, p, q or {}, {}, b if isinstance(b, bytes) else json.dumps(b).encode())

    def j(r):
        return json.loads(r.body) if r.body else {}

    # F100 AWS-managed policies exist without being created
    st = InMemoryIamStore()
    iam.dispatch(st, {"Action": "CreateRole", "RoleName": "r", "AssumeRolePolicyDocument": "{}"})
    arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
    r = iam.dispatch(st, {"Action": "AttachRolePolicy", "RoleName": "r", "PolicyArn": arn})
    _check("F100 AttachRolePolicy accepts an AWS-managed policy ARN", r.status == 200)
    r = iam.dispatch(st, {"Action": "GetPolicy", "PolicyArn": arn})
    _check("F100 GetPolicy resolves it", r.status == 200 and "AWSLambdaBasicExecutionRole" in r.body)
    r = iam.dispatch(st, {"Action": "AttachRolePolicy", "RoleName": "r", "PolicyArn": "arn:aws:iam::123456789012:policy/nope"})
    _check("F100 a customer policy that does not exist is still NoSuchEntity", r.status == 404)

    src = "def handler(e, c):\n    return {}\n"
    code = {"ZipFile": src}
    # F101 no code-signing config attached -> 200 without an ARN
    call("POST", F, {"FunctionName": "fa", "Runtime": "python3.12", "Handler": "index.handler", "Role": "arn:aws:iam::123456789012:role/r",
                     "Code": code, "Publish": True, "KMSKeyArn": "arn:aws:kms:us-east-1:123456789012:key/k1",
                     "Environment": {"Variables": {}}})
    r = call("GET", f"{F}/fa/code-signing-config")
    _check("F101 GetFunctionCodeSigningConfig with none attached is 200 and has no ARN",
           r.status == 200 and "CodeSigningConfigArn" not in j(r))
    cfgr = j(call("GET", f"{F}/fa"))
    cfg = cfgr["Configuration"]
    _check("F102 Publish=true on CreateFunction publishes version 1", "1" in lam._find_fn(s, "fa")["versions"])
    _check("F103 KMSKeyArn round-trips", cfg.get("KMSKeyArn", "").endswith("key/k1"))
    _check("F104 empty Environment is omitted", "Environment" not in cfg)
    call("PUT", f"{F}/fa/concurrency", {"ReservedConcurrentExecutions": 5})
    _check("F105 GetFunction reports Concurrency", j(call("GET", f"{F}/fa"))["Concurrency"]["ReservedConcurrentExecutions"] == 5)
    call("POST", f"{F}/fa/aliases", {"Name": "live", "FunctionVersion": "1"})
    al = j(call("GET", f"{F}/fa/aliases/live"))
    _check("F105 alias without routing has no RoutingConfig", "RoutingConfig" not in al)
    # F106 permission is scoped to a qualifier
    call("POST", f"{F}/fa/policy", {"StatementId": "u", "Action": "lambda:InvokeFunctionUrl", "Principal": "*",
                                    "FunctionUrlAuthType": "NONE"}, {"Qualifier": "live"})
    _check("F106 GetPolicy?Qualifier=live returns the qualified statement",
           call("GET", f"{F}/fa/policy", q={"Qualifier": "live"}).status == 200
           and call("GET", f"{F}/fa/policy").status == 404)
    # F107 ESM accepts an ARN, reports epoch LastModified; event invoke config LastModified epoch
    r = call("POST", "/2015-03-31/event-source-mappings", {"FunctionName": "arn:aws:lambda:us-east-1:123456789012:function:fa",
             "EventSourceArn": "arn:aws:sqs:us-east-1:123456789012:q", "BatchSize": 5, "MaximumBatchingWindowInSeconds": 2})
    m = j(r)
    _check("F107 CreateEventSourceMapping by function ARN", r.status == 202 and m["FunctionName"] == "fa")
    _check("F107 ESM LastModified is an epoch number and batching window echoes",
           isinstance(m["LastModified"], float) and m["MaximumBatchingWindowInSeconds"] == 2)
    e = j(call("PUT", f"{F}/fa/event-invoke-config", {"MaximumRetryAttempts": 1}))
    _check("F107 event-invoke-config LastModified is an epoch number", isinstance(e["LastModified"], float))

    # F108 API Gateway v1 timestamps are epoch numbers; stage tags persist
    def gcall(m, p, b=b""):
        return gw.dispatch(s, m, p, {}, {}, b if isinstance(b, bytes) else json.dumps(b).encode())
    api = j(gcall("POST", "/restapis", {"name": "x"}))
    _check("F108 CreateRestApi createdDate is a JSON number", isinstance(api["createdDate"], float))
    k = j(gcall("POST", "/apikeys", {"name": "k"}))
    _check("F108 CreateApiKey createdDate is a JSON number", isinstance(k["createdDate"], float))
    dep = j(gcall("POST", f"/restapis/{api['id']}/deployments", {}))
    stg = j(gcall("POST", f"/restapis/{api['id']}/stages", {"stageName": "prod", "deploymentId": dep["id"], "tags": {"a": "b"}}))
    _check("F108 stage tags persist from CreateStage", stg["tags"] == {"a": "b"})

    # F109 Step Functions ARNs use the simulator account
    ss = sfn.StepFunctionsStore()
    r = sfn.dispatch(ss, "AWSStepFunctions.CreateStateMachine", {"name": "m", "roleArn": "arn:aws:iam::123456789012:role/s",
                     "definition": json.dumps({"StartAt": "A", "States": {"A": {"Type": "Succeed"}}})})
    _check("F109 state machine ARN account is 123456789012", ":123456789012:stateMachine:m" in r.body["stateMachineArn"])
    print("Endurance aws-serverless regressions: ALL GREEN")


if __name__ == "__main__":
    run()
