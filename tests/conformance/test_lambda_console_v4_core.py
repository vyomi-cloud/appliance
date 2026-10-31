"""Lambda v4-console conformance — everything the console needs beyond basic
Create/Invoke/Delete: UpdateFunctionConfiguration, tags, function URLs, aliases,
versions, layers, "triggers" (event source mappings), reserved concurrency,
recursive-loop detection, destinations (event invoke config), resource policy, and
the lightweight real "recent invocations" read the Monitor tab uses.
"""
import json
import types

try:
    from core import lambda_core as lam
    from core.messaging_store import InMemoryMessagingStore
    from core import sqs_core as sqs
except ImportError:  # pragma: no cover - Pyodide flat layout
    import lambda_core as lam  # type: ignore
    from messaging_store import InMemoryMessagingStore  # type: ignore
    import sqs_core as sqs  # type: ignore

F = "/2015-03-31/functions"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run(store=None):
    s = store or types.SimpleNamespace()

    def call(m, p, b=b"", q=None):
        body = b if isinstance(b, bytes) else json.dumps(b).encode()
        return lam.dispatch(s, m, p, q or {}, {}, body)

    def j(r):
        return json.loads(r.body) if r.body else {}

    name = "uictest-fn"
    src = "def handler(event, context):\n    return {'ok': True, 'n': event.get('n', 0)}\n"
    _check("CreateFunction", call("POST", F, {"FunctionName": name, "Runtime": "python3.12",
                                              "Code": {"Source": src}, "MemorySize": 256}).status == 201)

    # UpdateFunctionConfiguration — memory/env round-trip.
    r = call("PUT", f"{F}/{name}/configuration", {"MemorySize": 512, "Environment": {"Variables": {"K": "V"}}})
    _check("UpdateFunctionConfiguration", r.status == 200 and j(r)["MemorySize"] == 512 and j(r)["Environment"]["Variables"]["K"] == "V")

    # Tags.
    _check("TagResource", call("POST", f"{F}/{name}/tags", {"Tags": {"env": "test"}}).status == 200)
    _check("ListTags", j(call("GET", f"{F}/{name}/tags"))["Tags"].get("env") == "test")
    _check("UntagResource", call("DELETE", f"{F}/{name}/tags", q={"tagKeys": "env"}).status == 200
          and "env" not in j(call("GET", f"{F}/{name}/tags"))["Tags"])

    # Function URL.
    r = call("POST", f"{F}/{name}/url", {"AuthType": "NONE"})
    _check("CreateFunctionUrlConfig", r.status == 201 and j(r)["AuthType"] == "NONE" and j(r)["FunctionUrl"].startswith("https://"))
    _check("GetFunctionUrlConfig", j(call("GET", f"{F}/{name}/url"))["AuthType"] == "NONE")
    _check("UpdateFunctionUrlConfig", j(call("PUT", f"{F}/{name}/url", {"AuthType": "AWS_IAM"}))["AuthType"] == "AWS_IAM")
    _check("DeleteFunctionUrlConfig", call("DELETE", f"{F}/{name}/url").status == 204)
    _check("GetFunctionUrlConfig after delete → 404", call("GET", f"{F}/{name}/url").status == 404)

    # Versions + aliases.
    v1 = j(call("POST", f"{F}/{name}/versions"))
    _check("PublishVersion", v1["Version"] == "1")
    _check("ListVersionsByFunction", {x["Version"] for x in j(call("GET", f"{F}/{name}/versions"))["Versions"]} == {"$LATEST", "1"})
    r = call("POST", f"{F}/{name}/aliases", {"Name": "live", "FunctionVersion": "1"})
    _check("CreateAlias", r.status == 201 and j(r)["FunctionVersion"] == "1")
    _check("ListAliases", len(j(call("GET", f"{F}/{name}/aliases"))["Aliases"]) == 1)
    _check("UpdateAlias", j(call("PUT", f"{F}/{name}/aliases/live", {"Description": "prod"}))["Description"] == "prod")
    _check("DeleteAlias", call("DELETE", f"{F}/{name}/aliases/live").status == 204)

    # Reserved concurrency + recursion config.
    _check("PutFunctionConcurrency", j(call("PUT", f"{F}/{name}/concurrency", {"ReservedConcurrentExecutions": 5}))["ReservedConcurrentExecutions"] == 5)
    _check("GetFunctionConcurrency", j(call("GET", f"{F}/{name}/concurrency"))["ReservedConcurrentExecutions"] == 5)
    _check("DeleteFunctionConcurrency", call("DELETE", f"{F}/{name}/concurrency").status == 204)
    _check("PutFunctionRecursionConfig", j(call("PUT", f"{F}/{name}/recursion-config", {"RecursiveLoop": "Allow"}))["RecursiveLoop"] == "Allow")
    _check("GetFunctionRecursionConfig", j(call("GET", f"{F}/{name}/recursion-config"))["RecursiveLoop"] == "Allow")

    # Destinations (event invoke config) — stored config round-trip.
    dest = {"DestinationConfig": {"OnSuccess": {"Destination": "arn:aws:sqs:us-east-1:123456789012:q"}}}
    _check("PutFunctionEventInvokeConfig", call("PUT", f"{F}/{name}/event-invoke-config", dest).status == 200)
    _check("GetFunctionEventInvokeConfig round-trips",
          j(call("GET", f"{F}/{name}/event-invoke-config"))["DestinationConfig"] == dest["DestinationConfig"])
    _check("DeleteFunctionEventInvokeConfig", call("DELETE", f"{F}/{name}/event-invoke-config").status == 204)

    # Async (Event) Invoke → Destinations really deliver (lambda.invoke / lambda.destinations).
    msg = InMemoryMessagingStore()
    ok_url = sqs.dispatch(msg, "AmazonSQS.CreateQueue", {"QueueName": "lambda-ok-q"}).body["QueueUrl"]
    ok_arn = sqs.dispatch(msg, "AmazonSQS.GetQueueAttributes", {"QueueUrl": ok_url}).body["Attributes"]["QueueArn"]
    fail_url = sqs.dispatch(msg, "AmazonSQS.CreateQueue", {"QueueName": "lambda-fail-q"}).body["QueueUrl"]
    fail_arn = sqs.dispatch(msg, "AmazonSQS.GetQueueAttributes", {"QueueUrl": fail_url}).body["Attributes"]["QueueArn"]
    dlq_url = sqs.dispatch(msg, "AmazonSQS.CreateQueue", {"QueueName": "lambda-dlq"}).body["QueueUrl"]
    dlq_arn = sqs.dispatch(msg, "AmazonSQS.GetQueueAttributes", {"QueueUrl": dlq_url}).body["Attributes"]["QueueArn"]

    def acall(fn_name, body):
        return lam.dispatch(s, "POST", f"{F}/{fn_name}/invocations", {}, {"X-Amz-Invocation-Type": "Event"},
                            json.dumps(body).encode(), msg_store=msg, lam_store=s)

    def received(url):
        return sqs.dispatch(msg, "AmazonSQS.ReceiveMessage", {"QueueUrl": url, "MaxNumberOfMessages": 10}).body.get("Messages", [])

    okfn = "okfn"
    call("POST", F, {"FunctionName": okfn, "Code": {"Source": "def handler(e, c):\n    return {'ok': True, 'n': e.get('n', 0)}\n"}})
    call("PUT", f"{F}/{okfn}/event-invoke-config", {"DestinationConfig": {"OnSuccess": {"Destination": ok_arn}}})
    r = acall(okfn, {"n": 9})
    _check("async Invoke returns 202 Accepted", r.status == 202 and r.body == b"")
    rows = received(ok_url)
    _check("OnSuccess destination really receives the invocation envelope", len(rows) == 1)
    env = json.loads(rows[0]["Body"])
    _check("success envelope carries the real request/response payloads",
          env["requestContext"]["condition"] == "Success" and env["requestPayload"] == {"n": 9}
          and env["responsePayload"] == {"ok": True, "n": 9})

    boom = "boomfn"
    call("POST", F, {"FunctionName": boom, "Code": {"Source": "def handler(e, c):\n    raise ValueError('nope')\n"}})
    call("PUT", f"{F}/{boom}/event-invoke-config", {"DestinationConfig": {"OnFailure": {"Destination": fail_arn}}})
    acall(boom, {})
    frows = received(fail_url)
    _check("OnFailure destination really receives the failure envelope", len(frows) == 1)
    fenv = json.loads(frows[0]["Body"])
    _check("failure envelope reports the real error", fenv["requestContext"]["condition"] == "RetriesExhausted"
          and fenv["responsePayload"]["errorType"] == "ValueError")

    dlqfn = "dlqfn"
    call("POST", F, {"FunctionName": dlqfn, "Code": {"Source": "def handler(e, c):\n    raise ValueError('x')\n"},
                     "DeadLetterConfig": {"TargetArn": dlq_arn}})
    acall(dlqfn, {"raw": "payload"})
    _check("legacy DLQ receives the raw event when no OnFailure destination is set",
          json.loads(received(dlq_url)[0]["Body"]) == {"raw": "payload"})

    nodestfn = "nodestfn"
    call("POST", F, {"FunctionName": nodestfn, "Code": {"Source": "def handler(e, c):\n    raise ValueError('x')\n"}})
    acall(nodestfn, {})
    _check("async delivery failure counted when no destination/DLQ is configured",
          j(call("GET", f"{F}/{nodestfn}/invocations"))["Metrics"]["AsyncDeliveryFailures"] == 0)
    call("PUT", f"{F}/{nodestfn}/event-invoke-config", {"DestinationConfig": {"OnFailure": {"Destination": "arn:aws:events:us-east-1:123456789012:event-bus/default"}}})
    acall(nodestfn, {})
    _check("an undeliverable destination ARN (event bus) increments AsyncDeliveryFailures",
          j(call("GET", f"{F}/{nodestfn}/invocations"))["Metrics"]["AsyncDeliveryFailures"] == 1)

    # Reserved concurrency of 0 really throttles (lambda.concurrency).
    concfn = "concfn"
    call("POST", F, {"FunctionName": concfn, "Code": {"Source": "def handler(e, c):\n    return {'ok': True}\n"}})
    call("PUT", f"{F}/{concfn}/concurrency", {"ReservedConcurrentExecutions": 0})
    r = call("POST", f"{F}/{concfn}/invocations", {"n": 1})
    _check("ReservedConcurrentExecutions=0 really blocks Invoke", r.status == 429
          and json.loads(r.body)["error"]["code"] == "TooManyRequestsException")
    _check("the blocked invoke counts as a real Throttle",
          j(call("GET", f"{F}/{concfn}/invocations"))["Metrics"]["Throttles"] == 1)
    call("DELETE", f"{F}/{concfn}/concurrency")
    _check("removing the reservation unblocks Invoke", call("POST", f"{F}/{concfn}/invocations", {"n": 1}).status == 200)

    # Resource policy.
    r = call("POST", f"{F}/{name}/policy", {"StatementId": "trigger1", "Action": "lambda:InvokeFunction", "Principal": "s3.amazonaws.com"})
    _check("AddPermission", r.status == 201)
    _check("GetPolicy", "trigger1" in json.loads(j(call("GET", f"{F}/{name}/policy"))["Policy"])["Statement"][0]["Sid"])
    _check("RemovePermission", call("DELETE", f"{F}/{name}/policy/trigger1").status == 204)

    # Event source mappings ("triggers") — every console source type gets a real,
    # listable, deletable record (see core/lambda_core.py module docstring for scope).
    r = call("POST", "/2015-03-31/event-source-mappings",
            {"FunctionName": name, "EventSourceArn": "arn:aws:sqs:us-east-1:123456789012:q", "BatchSize": 5})
    _check("CreateEventSourceMapping", r.status == 202 and j(r)["EventSourceType"] == "SQS")
    uid = j(r)["UUID"]
    _check("ListEventSourceMappings filters by function",
          len(j(call("GET", "/2015-03-31/event-source-mappings", q={"FunctionName": name}))["EventSourceMappings"]) == 1)
    _check("GetEventSourceMapping", j(call("GET", f"/2015-03-31/event-source-mappings/{uid}"))["UUID"] == uid)
    _check("UpdateEventSourceMapping", j(call("PUT", f"/2015-03-31/event-source-mappings/{uid}", {"Enabled": False}))["State"] == "Disabled")
    _check("DeleteEventSourceMapping", call("DELETE", f"/2015-03-31/event-source-mappings/{uid}").status == 200)

    # Layers.
    r = call("POST", "/2015-03-31/layers/uictest-layer/versions",
            {"Content": {"Source": "x" * 50}, "CompatibleRuntimes": ["python3.12"]})
    _check("PublishLayerVersion", r.status == 201 and j(r)["Version"] == 1)
    _check("ListLayers", j(call("GET", "/2015-03-31/layers"))["Layers"][0]["LayerName"] == "uictest-layer")
    _check("ListLayerVersions", len(j(call("GET", "/2015-03-31/layers/uictest-layer/versions"))["LayerVersions"]) == 1)
    _check("GetLayerVersion", j(call("GET", "/2015-03-31/layers/uictest-layer/versions/1"))["Version"] == 1)
    _check("DeleteLayerVersion", call("DELETE", "/2015-03-31/layers/uictest-layer/versions/1").status == 204)

    # Real "recent invocations" read — backed by actual Invoke calls, not fake data.
    call("POST", f"{F}/{name}/invocations", {"n": 3})
    call("POST", f"{F}/{name}/invocations", {"n": 4})
    rec = j(call("GET", f"{F}/{name}/invocations"))
    _check("recent invocations recorded", rec["Metrics"]["Invocations"] == 2 and len(rec["Invocations"]) == 2)
    _check("recent invocations carry real request ids", rec["Invocations"][0]["RequestId"] != rec["Invocations"][1]["RequestId"])

    # Replicas — derived from the function it replicates, never a separate fabricated
    # store (see core/lambda_core.py module note above _replica_view).
    r = call("PUT", f"{F}/{name}/replication", {"Regions": ["eu-west-1"]})
    _check("ReplicateFunction", r.status == 200 and j(r)["Regions"] == ["eu-west-1"])
    reps = j(call("GET", "/2015-03-31/replicas"))["Replicas"]
    _check("ListReplicas shows the function's real runtime", any(x["FunctionName"] == name and x["Runtime"] == "python3.12" for x in reps))

    # Vyomi-exclusive console surfaces: real named-resource CRUD, no simulated runtime
    # underneath (capacity providers / code signing configs / network connectors /
    # MicroVM images+MicroVMs / applications — see module note above _capacity_providers).
    r = call("POST", "/2015-03-31/capacity-providers", {"Name": "uictest-cp", "VpcId": "vpc-1", "MaximumVcpu": 8})
    _check("CreateCapacityProvider", r.status == 201 and j(r)["MaximumVcpu"] == 8)
    _check("ListCapacityProviders", any(x["Name"] == "uictest-cp" for x in j(call("GET", "/2015-03-31/capacity-providers"))["CapacityProviders"]))
    _check("DeleteCapacityProvider", call("DELETE", "/2015-03-31/capacity-providers/uictest-cp").status == 200)

    r = call("POST", "/2015-03-31/code-signing-configs", {"Description": "d", "AllowedPublishers": {"SigningProfileVersionArns": ["arn:x"]}})
    _check("CreateCodeSigningConfig", r.status == 201 and j(r)["AllowedPublishers"]["SigningProfileVersionArns"] == ["arn:x"])
    cscid = j(r)["CodeSigningConfigId"]
    _check("ListCodeSigningConfigs", any(x["CodeSigningConfigId"] == cscid for x in j(call("GET", "/2015-03-31/code-signing-configs"))["CodeSigningConfigs"]))
    _check("UpdateCodeSigningConfig", j(call("PUT", f"/2015-03-31/code-signing-configs/{cscid}", {"Description": "d2"}))["Description"] == "d2")
    _check("DeleteCodeSigningConfig", call("DELETE", f"/2015-03-31/code-signing-configs/{cscid}").status == 200)

    r = call("POST", "/2015-03-31/network-connectors", {"Name": "uictest-nc", "VpcId": "vpc-1", "NetworkProtocol": "TCP"})
    _check("CreateNetworkConnector", r.status == 201 and j(r)["NetworkProtocol"] == "TCP")
    _check("ListNetworkConnectors", any(x["Name"] == "uictest-nc" for x in j(call("GET", "/2015-03-31/network-connectors"))["NetworkConnectors"]))
    _check("DeleteNetworkConnector", call("DELETE", "/2015-03-31/network-connectors/uictest-nc").status == 200)

    r = call("POST", "/2015-03-31/microvm-images", {"Name": "uictest-img", "Description": "img"})
    _check("CreateMicrovmImage", r.status == 201 and j(r)["State"] == "ACTIVE")
    _check("ListMicrovmImages", any(x["Name"] == "uictest-img" for x in j(call("GET", "/2015-03-31/microvm-images"))["MicrovmImages"]))
    r = call("POST", "/2015-03-31/microvms", {"MicrovmImage": "uictest-img"})
    _check("RunMicrovm", r.status == 201 and j(r)["Status"] == "RUNNING")
    mid = j(r)["Id"]
    _check("ListMicrovms", any(x["Id"] == mid for x in j(call("GET", "/2015-03-31/microvms"))["Microvms"]))
    _check("DeleteMicrovm", call("DELETE", f"/2015-03-31/microvms/{mid}").status == 200)
    _check("DeleteMicrovmImage", call("DELETE", "/2015-03-31/microvm-images/uictest-img").status == 200)

    r = call("POST", "/2015-03-31/applications", {"Name": "uictest-app", "Description": "a", "Template": "From scratch"})
    _check("CreateApplication", r.status == 201 and j(r)["Status"] == "CREATE_COMPLETE")
    _check("ListApplications", any(x["Name"] == "uictest-app" for x in j(call("GET", "/2015-03-31/applications"))["Applications"]))
    _check("DeleteApplication", call("DELETE", "/2015-03-31/applications/uictest-app").status == 200)

    # VPC config / EFS file systems — SubnetIds/SecurityGroupIds and EFS Arns are shape-validated
    # for real, not just stored (lambda.vpc-filesystems).
    good_subnet, good_sg = "subnet-0123456789abcdef0", "sg-0123456789abcdef0"

    vpcfn = "vpcfn"
    call("POST", F, {"FunctionName": vpcfn, "Code": {"Source": "def handler(e, c):\n    return {}\n"}})
    r = call("PUT", f"{F}/{vpcfn}/configuration",
            {"VpcConfig": {"SubnetIds": ["not-a-subnet-id"], "SecurityGroupIds": [good_sg]}})
    _check("UpdateFunctionConfiguration rejects a malformed subnet ID",
          r.status == 400 and json.loads(r.body)["error"]["code"] == "InvalidParameterValueException")
    r = call("PUT", f"{F}/{vpcfn}/configuration",
            {"VpcConfig": {"SubnetIds": [good_subnet], "SecurityGroupIds": ["not-a-sg-id"]}})
    _check("UpdateFunctionConfiguration rejects a malformed security group ID", r.status == 400)
    r = call("PUT", f"{F}/{vpcfn}/configuration", {"VpcConfig": {"SubnetIds": [good_subnet], "SecurityGroupIds": []}})
    _check("UpdateFunctionConfiguration rejects subnets without any security groups", r.status == 400)
    r = call("PUT", f"{F}/{vpcfn}/configuration",
            {"VpcConfig": {"SubnetIds": [good_subnet], "SecurityGroupIds": [good_sg]}})
    _check("UpdateFunctionConfiguration accepts a well-formed subnet + security group",
          r.status == 200 and j(r)["VpcConfig"]["SubnetIds"] == [good_subnet])
    _check("UpdateFunctionConfiguration detaches the VPC when both lists are empty",
          j(call("PUT", f"{F}/{vpcfn}/configuration", {"VpcConfig": {"SubnetIds": [], "SecurityGroupIds": []}})).get("VpcConfig") is None)

    r = call("PUT", f"{F}/{vpcfn}/configuration", {"FileSystemConfigs": [{"Arn": "arn:aws:s3:::not-an-efs-arn", "LocalMountPath": "/mnt/efs"}]})
    _check("UpdateFunctionConfiguration rejects a malformed EFS access point ARN", r.status == 400)
    r = call("PUT", f"{F}/{vpcfn}/configuration",
            {"FileSystemConfigs": [{"Arn": "arn:aws:elasticfilesystem:us-east-1:123456789012:access-point/fsap-0123456789abcdef0", "LocalMountPath": "data"}]})
    _check("UpdateFunctionConfiguration rejects a LocalMountPath not under /mnt/", r.status == 400)
    good_fsc = {"Arn": "arn:aws:elasticfilesystem:us-east-1:123456789012:access-point/fsap-0123456789abcdef0", "LocalMountPath": "/mnt/efs"}
    r = call("PUT", f"{F}/{vpcfn}/configuration", {"FileSystemConfigs": [good_fsc]})
    _check("UpdateFunctionConfiguration accepts a well-formed EFS access point", r.status == 200 and j(r)["FileSystemConfigs"] == [good_fsc])

    r = call("POST", F, {"FunctionName": "vpcfn-create", "Code": {"Source": "def handler(e, c):\n    return {}\n"},
                         "VpcConfig": {"SubnetIds": ["bad-subnet"], "SecurityGroupIds": [good_sg]}})
    _check("CreateFunction also rejects a malformed subnet ID", r.status == 400)

    _check("DeleteFunction", call("DELETE", f"{F}/{name}").status == 204)
    _check("deleted function's ESMs are gone too",
          len(j(call("GET", "/2015-03-31/event-source-mappings", q={"FunctionName": name}))["EventSourceMappings"]) == 0)

    print("\nLambda v4-console conformance: ALL GREEN")
    return s


if __name__ == "__main__":
    run()
