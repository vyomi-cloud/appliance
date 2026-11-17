"""vyomi-endurance PROOF layers (SDK/CLI/UI): simulator defects found by reading Terraform-created resources back through other clients.
Host + Pyodide.

    PYTHONPATH=. python3 tests/conformance/test_endurance_proof_core.py
"""
import json
import types

from core import bedrock_agents_core as ag
from core import vpc_core


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  [PASS] {name}")


def run():
    # F500: DescribeLaunchTemplateVersions accepts the symbolic versions $Latest / $Default (aws cli + SDKs use them constantly)
    store = types.SimpleNamespace()
    vpc_core.dispatch(store, {"Action": "CreateLaunchTemplate", "LaunchTemplateName": "lt-proof", "LaunchTemplateData.InstanceType": "t3.micro"})
    lt = next(iter(vpc_core._model(store)["launch_templates"].values()))
    vpc_core.dispatch(store, {"Action": "CreateLaunchTemplateVersion", "LaunchTemplateName": "lt-proof", "LaunchTemplateData.InstanceType": "t3.small"})
    for tok, want in (("$Latest", ["2"]), ("$Default", ["1"]), ("1", ["1"])):
        body = vpc_core.dispatch(store, {"Action": "DescribeLaunchTemplateVersions", "LaunchTemplateId": lt["id"],
                                         "LaunchTemplateVersion.1": tok}).body
        body = body.decode() if isinstance(body, bytes) else body
        got = [v for v in ("1", "2") if f"<versionNumber>{v}</versionNumber>" in body]
        _check(f"F500 DescribeLaunchTemplateVersions {tok} -> version {want}", got == want)

    # F501: bedrock-agent ListAgents is POST /agents/ (trailing slash, maxResults/nextToken in the JSON body), not GET
    s3 = types.SimpleNamespace(account={})
    r = ag.dispatch(s3, "PUT", "/agents/", {}, {}, json.dumps({"agentName": "a1", 
                                                                 "agentResourceRoleArn": "arn:aws:iam::123456789012:role/r"}).encode())
    _check("F501 CreateAgent ok", r["status"] in (200, 202))
    r = ag.dispatch(s3, "POST", "/agents/", {}, {}, json.dumps({"maxResults": 10}).encode())
    _check("F501 ListAgents (POST /agents/) answers 200", r["status"] in (200, 202))
    names = [a["agentName"] for a in json.loads(r["body"])["agentSummaries"]]
    _check("F501 ListAgents lists the agent", names == ["a1"])
    r = ag.dispatch(s3, "POST", "/agents/", {}, {}, json.dumps({}).encode())
    _check("F501 ListAgents with an empty body", r["status"] in (200, 202))

    # F502: the Mesh CORS preflight must allow what a native-wire console sends (x-amz-date ...) and PUT/DELETE, or every Nano->Mesh call
    # from a real browser is blocked (the Nano console showed 'Failed to load ... HTTP 503' on a mesh-homed space)
    from core import mesh
    h = dict((k.decode(), v.decode()) for k, v in mesh.cors_headers("http://127.0.0.1:1", "authorization,content-type,x-amz-date,x-amz-target,x-amz-content-sha256"))
    allowed = [x.strip() for x in h["access-control-allow-headers"].split(",")]
    _check("F502 preflight allows x-amz-date / x-amz-target / x-amz-content-sha256 plus the mesh token header",
           {"x-amz-date", "x-amz-target", "x-amz-content-sha256", "x-vyomi-mesh-token", "authorization"} <= set(allowed))
    _check("F502 preflight allows PUT/DELETE/HEAD", all(m in h["access-control-allow-methods"] for m in ("PUT", "DELETE", "HEAD")))
    _check("F502 response headers are exposed to the page", h.get("access-control-expose-headers") == "*")
    _check("F502 junk requested header names are not reflected",
           "bad header" not in dict((k.decode(), v.decode()) for k, v in mesh.cors_headers("http://x", "bad header,x-ok"))["access-control-allow-headers"])


if __name__ == "__main__":
    run()
    print("ALL PASS")
