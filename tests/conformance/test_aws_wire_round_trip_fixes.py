"""Regression checks for two native-wire bugs the v4 AWS smoke found (2026-10-31) — host + Pyodide.

* EC2 launch templates on Nano: state is persisted as JSON, which turns the int version
  keys into strings, so CreateLaunchTemplateVersion (SourceVersion=1) answered
  InvalidLaunchTemplateId.VersionNotFound after a reload.
* Lambda's newer API-date prefixes: TagResource / ListTags (`/2017-03-31/tags/{ARN}`) and
  GetAccountSettings (`/2016-08-19/account-settings`) — boto3 / the CLI call these.
"""
import json
import re
import types

try:
    from core import lambda_core as lam
    from core import vpc_core as vpc
except ImportError:  # pragma: no cover - Pyodide flat layout
    import lambda_core as lam  # type: ignore
    import vpc_core as vpc  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run_launch_template_json_reload(store=None):
    s = store or types.SimpleNamespace()
    r = vpc.dispatch(s, {"Action": "CreateLaunchTemplate", "LaunchTemplateName": "lt-json",
                         "LaunchTemplateData.InstanceType": "t3.micro"})
    lt_id = re.search(r"<launchTemplateId>(.*?)</launchTemplateId>", r.body).group(1)
    s._vpc_model = json.loads(json.dumps(s._vpc_model))          # what Nano's persistence does
    r = vpc.dispatch(s, {"Action": "CreateLaunchTemplateVersion", "LaunchTemplateId": lt_id, "SourceVersion": "1"})
    _check("CreateLaunchTemplateVersion after a JSON reload → 200", r.status == 200)
    body = vpc.dispatch(s, {"Action": "DescribeLaunchTemplateVersions", "LaunchTemplateId": lt_id}).body
    _check("version 2 listed, source data carried over",
           "<versionNumber>2</versionNumber>" in body and body.count("t3.micro") == 2)
    return s


def run_lambda_prefixes(store=None):
    s = store or types.SimpleNamespace()

    def call(m, p, b=None, q=None):
        return lam.dispatch(s, m, p, q or {}, {}, json.dumps(b).encode() if b is not None else b"")

    call("POST", "/2015-03-31/functions", {"FunctionName": "tagged", "Runtime": "python3.12",
                                           "Code": {"Source": "def handler(e, c):\n    return 1\n"}})
    arn = lam._fn_arn("tagged")
    _check("TagResource /2017-03-31/tags/{ARN} → 200",
           call("POST", f"/2017-03-31/tags/{arn}", {"Tags": {"team": "core", "env": "dev"}}).status == 200)
    tags = json.loads(call("GET", f"/2017-03-31/tags/{arn}").body)["Tags"]
    _check("ListTags returns them", tags == {"team": "core", "env": "dev"})
    call("DELETE", f"/2017-03-31/tags/{arn}", q={"tagKeys": ["env"]})
    _check("UntagResource removes the key", json.loads(call("GET", f"/2017-03-31/tags/{arn}").body)["Tags"] == {"team": "core"})
    acct = json.loads(call("GET", "/2016-08-19/account-settings").body)
    _check("GetAccountSettings counts the account's functions", acct["AccountUsage"]["FunctionCount"] == 1)
    eic = call("PUT", "/2019-09-25/functions/tagged/event-invoke-config",
               {"DestinationConfig": {"OnSuccess": {"Destination": "arn:aws:sqs:us-east-1:123456789012:q"}}})
    _check("PutFunctionEventInvokeConfig on its own API date → 200", eic.status == 200)
    return s


def run():
    run_launch_template_json_reload()
    run_lambda_prefixes()
    print("\nAWS wire round-trip fixes: ALL GREEN")


if __name__ == "__main__":
    run()
