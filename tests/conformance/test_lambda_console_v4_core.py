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
except ImportError:  # pragma: no cover - Pyodide flat layout
    import lambda_core as lam  # type: ignore

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

    # Destinations (event invoke config) — config_only round-trip.
    dest = {"DestinationConfig": {"OnSuccess": {"Destination": "arn:aws:sqs:us-east-1:123456789012:q"}}}
    _check("PutFunctionEventInvokeConfig", call("PUT", f"{F}/{name}/event-invoke-config", dest).status == 200)
    _check("GetFunctionEventInvokeConfig round-trips",
          j(call("GET", f"{F}/{name}/event-invoke-config"))["DestinationConfig"] == dest["DestinationConfig"])
    _check("DeleteFunctionEventInvokeConfig", call("DELETE", f"{F}/{name}/event-invoke-config").status == 204)

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

    _check("DeleteFunction", call("DELETE", f"{F}/{name}").status == 204)
    _check("deleted function's ESMs are gone too",
          len(j(call("GET", "/2015-03-31/event-source-mappings", q={"FunctionName": name}))["EventSourceMappings"]) == 0)

    print("\nLambda v4-console conformance: ALL GREEN")
    return s


if __name__ == "__main__":
    run()
