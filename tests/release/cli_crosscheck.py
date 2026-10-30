#!/usr/bin/env python3
"""Release check: the real aws / gcloud / az CLIs against a running appliance.

Three parts, every release:

1. Identity — the account / project / subscription each CLI discovers the way
   a user's CLI does (`aws sts get-caller-identity`, `gcloud projects list`,
   `az account list` = GET /subscriptions) must be the one its console uses
   (the console catalog). If they differ, the CLI and the console silently
   work on different stores.
2. CLI suites — every tests/cli/*-cli-smoke.sh, each on its own, pointed at
   the console's account / project / subscription. A missing CLI is a failure
   here, not a skip.
3. Both directions — for core resource types in each cloud: created with the
   CLI → listed by the console's own API calls; created through the console
   API → listed by the CLI. The CLI side uses the identity the CLI discovered
   in part 1 (what a user's CLI would use), the console side uses the catalog.

Plus coverage: released services (services/registry.json) with no CLI suite.

    ENDPOINT=http://localhost:9000 OUT=cli-check python3 tests/release/cli_crosscheck.py

Writes OUT/summary.md ("N/M checks passed" first) and OUT/results.json; exits
1 if any check fails. CLI config goes to a temp dir, never the user's.
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
B = os.environ.get("ENDPOINT", "http://localhost:9000").rstrip("/")
OUT = os.environ.get("OUT", "cli-check")
T = str(int(time.time()))[-7:]
TMP = tempfile.mkdtemp(prefix="vyomi-cli-")
ENV = dict(os.environ,
           AWS_ACCESS_KEY_ID="test", AWS_SECRET_ACCESS_KEY="test", AWS_DEFAULT_REGION="us-east-1",
           AWS_PAGER="", AWS_CONFIG_FILE=os.path.join(TMP, "aws-config"),
           AWS_SHARED_CREDENTIALS_FILE=os.path.join(TMP, "aws-creds"),
           CLOUDSDK_CONFIG=os.path.join(TMP, "gcloud"), CLOUDSDK_CORE_DISABLE_PROMPTS="1",
           CLOUDSDK_AUTH_DISABLE_CREDENTIALS="true",
           CLOUDSDK_API_ENDPOINT_OVERRIDES_STORAGE=f"{B}/storage/v1/",
           CLOUDSDK_API_ENDPOINT_OVERRIDES_PUBSUB=f"{B}/",
           CLOUDSDK_API_ENDPOINT_OVERRIDES_SECRETMANAGER=f"{B}/",
           CLOUDSDK_API_ENDPOINT_OVERRIDES_CLOUDRESOURCEMANAGER=f"{B}/",
           STORAGE_EMULATOR_HOST=B.split("://", 1)[1],
           AZURE_CONFIG_DIR=os.path.join(TMP, "azure"), AZURE_CORE_COLLECT_TELEMETRY="false",
           AZURE_CORE_ONLY_SHOW_ERRORS="true")

results: list[dict] = []


def check(section: str, name: str, ok: bool, detail: str = "") -> bool:
    results.append({"section": section, "name": name, "ok": bool(ok), "detail": detail.strip()[-600:]})
    print(f"{'PASS' if ok else 'FAIL'} [{section}] {name}" + ("" if ok else f" :: {detail.strip()[-300:]}"), flush=True)
    return bool(ok)


def run(*cmd: str, timeout: int = 120) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, env=ENV, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr)
    except FileNotFoundError:
        return 127, f"{cmd[0]}: not installed"
    except subprocess.TimeoutExpired:
        return 124, f"{' '.join(cmd[:3])}: timed out after {timeout}s"


def http(method: str, path: str, body=None) -> tuple[int, object]:
    req = urllib.request.Request(B + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            t = r.read().decode()
            code = r.status
    except urllib.error.HTTPError as e:
        t, code = e.read().decode(errors="ignore"), e.code
    except Exception as e:  # noqa: BLE001 — connection errors are a check failure
        return 0, str(e)
    try:
        return code, json.loads(t) if t.strip() else {}
    except ValueError:
        return code, t


def jsonout(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return None


def names(obj, *keys: str) -> set[str]:
    """Every string under the given keys anywhere in a JSON value, plus the
    last path segment of each (ids and resource names come back as paths)."""
    out: set[str] = set()
    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                for s in ([v] if isinstance(v, str) else v if isinstance(v, list) else []) if k in keys else []:
                    if isinstance(s, str):
                        out.add(s)
                        out.add(s.rstrip("/").rsplit("/", 1)[-1])
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(obj)
    return out


def wait_ready(timeout_s: int = int(os.environ.get("READY_TIMEOUT_S", "900"))) -> None:
    """Wait for the appliance, then start every on-demand backend the way the
    UI does (tests/installer/startup_check.mjs), so the CLIs hit live backends."""
    t0, kicked, rd = time.time(), set(), {}
    while time.time() - t0 < timeout_s:
        code, rd = http("GET", "/api/runtime/readiness")
        if code == 200 and isinstance(rd, dict):
            for svc in rd.get("services", []):
                if svc.get("status") != "ready" and svc.get("name") != "simulator" and svc["name"] not in kicked:
                    kicked.add(svc["name"])
                    http("POST", f"/api/runtime/backends/{svc['name']}/provision")
            if rd.get("ready"):
                break
        time.sleep(5)
    rd = rd if isinstance(rd, dict) else {}
    down = [f"{x.get('name')}: {x.get('status')}" for x in rd.get("services", []) if x.get("status") != "ready"]
    check("tools", f"appliance backends ready ({rd.get('ready_count', '?')}/{rd.get('total_count', '?')})",
          bool(rd.get("ready")), "; ".join(down) or "appliance not reachable")


# ── 1. identity ────────────────────────────────────────────────────────────
def catalog(cloud: str) -> dict:
    code, d = http("GET", f"/api/{cloud}/catalog")
    return d if code == 200 and isinstance(d, dict) else {}


def identities() -> dict:
    ids: dict = {}
    con = catalog("aws").get("account", "")
    rc, out = run("aws", "--endpoint-url", B, "sts", "get-caller-identity", "--output", "json")
    cli = (jsonout(out) or {}).get("Account", "") if rc == 0 else ""
    check("identity", "AWS: `aws sts get-caller-identity` account is the console's account",
          cli and cli == con, f"CLI={cli or out[-200:]} console={con}")
    ids["aws"] = {"console": con, "cli": cli or con}

    con = catalog("gcp").get("project", "")
    rc, out = run("gcloud", "projects", "list", "--format=value(projectId)")
    listed = [l.strip() for l in out.splitlines() if l.strip() and rc == 0 and not l.startswith(("ERROR", "WARNING"))]
    check("identity", "GCP: `gcloud projects list` returns the console's project",
          con and con in listed, f"CLI={listed or out[-200:]} console={con}")
    # A user's gcloud works in the project it can see; with none it falls back
    # to the project our own CLI suite has always assumed.
    ids["gcp"] = {"console": con, "cli": listed[0] if listed else "gcp-dev"}

    cat = catalog("azure")
    con, rg = cat.get("subscription", ""), cat.get("resourceGroup", "")
    rc, out = run("az", "rest", "--method", "get", "--url", f"{B}/subscriptions?api-version=2022-12-01",
                  "--skip-authorization-header")
    subs = [s.get("subscriptionId") for s in ((jsonout(out) or {}).get("value") or [])] if rc == 0 else []
    check("identity", "Azure: `az account list` (GET /subscriptions) returns the console's subscription",
          con and con in subs, f"CLI={subs or out[-200:]} console={con}")
    ids["azure"] = {"console": con, "cli": subs[0] if subs else "sub-001", "rg": rg}
    return ids


# ── 2. both directions ─────────────────────────────────────────────────────
def roundtrip(cloud: str, kind: str, cli_create, console_list, console_create, cli_list, cleanup) -> None:
    tag = re.sub(r"[^a-z0-9]", "", kind.lower())[:4]
    a, b = f"cli{tag}{T}", f"con{tag}{T}"
    rc, out = cli_create(a)
    if check("both-ways", f"{cloud}: {kind} created with the CLI", rc == 0, out):
        seen = console_list()
        check("both-ways", f"{cloud}: {kind} created with the CLI shows in the console", a in seen,
              f"console lists {sorted(seen)[-8:]}")
    code, body = console_create(b)
    if check("both-ways", f"{cloud}: {kind} created in the console", 200 <= code < 300, str(body)[-300:]):
        seen = cli_list()
        check("both-ways", f"{cloud}: {kind} created in the console shows in the CLI", b in seen,
              f"CLI lists {sorted(seen)[-8:]}")
    for n in (a, b):
        try:
            cleanup(n)
        except Exception:  # noqa: BLE001 — cleanup is best effort
            pass


def both_ways(ids: dict) -> None:
    aws = lambda *a: run("aws", "--endpoint-url", B, *a, "--output", "json")  # noqa: E731
    con_list = lambda path, *keys: names(http("GET", path)[1], *keys)  # noqa: E731

    roundtrip("AWS", "S3 bucket",
              lambda n: aws("s3api", "create-bucket", "--bucket", n),
              lambda: con_list("/api/s3/buckets", "name", "Name"),
              lambda n: http("POST", f"/api/s3/buckets/{n}", {"name": n}),
              lambda: names(jsonout(aws("s3api", "list-buckets")[1]), "Name"),
              lambda n: (aws("s3", "rb", f"s3://{n}", "--force"), http("DELETE", f"/api/s3/buckets/{n}")))
    roundtrip("AWS", "SQS queue",
              lambda n: aws("sqs", "create-queue", "--queue-name", n),
              lambda: con_list("/api/sqs/queues", "name", "queue_name", "QueueName"),
              lambda n: http("POST", "/api/sqs/queues", {"name": n}),
              lambda: {u.rsplit("/", 1)[-1] for u in (jsonout(aws("sqs", "list-queues")[1]) or {}).get("QueueUrls", [])},
              lambda n: http("DELETE", f"/api/sqs/queues/{n}"))
    roundtrip("AWS", "DynamoDB table",
              lambda n: aws("dynamodb", "create-table", "--table-name", n, "--billing-mode", "PAY_PER_REQUEST",
                            "--attribute-definitions", "AttributeName=id,AttributeType=S",
                            "--key-schema", "AttributeName=id,KeyType=HASH"),
              lambda: con_list("/api/dynamodb/tables", "name", "table_name", "table_names", "TableName"),
              lambda n: http("POST", "/api/dynamodb/tables", {"name": n, "partition_key": "id", "billing_mode": "PAY_PER_REQUEST"}),
              lambda: set((jsonout(aws("dynamodb", "list-tables")[1]) or {}).get("TableNames", [])),
              lambda n: http("DELETE", f"/api/dynamodb/tables/{n}"))
    roundtrip("AWS", "SNS topic",
              lambda n: aws("sns", "create-topic", "--name", n),
              lambda: con_list("/api/aws/sns/topics", "name", "TopicArn", "arn"),
              lambda n: http("POST", "/api/aws/sns/topics", {"name": n, "type": "Standard"}),
              lambda: {a.rsplit(":", 1)[-1] for a in names(jsonout(aws("sns", "list-topics")[1]), "TopicArn")},
              lambda n: None)
    roundtrip("AWS", "Secrets Manager secret",
              lambda n: aws("secretsmanager", "create-secret", "--name", n, "--secret-string", "v"),
              lambda: con_list("/api/aws/secrets", "name", "Name"),
              lambda n: http("POST", "/api/aws/secrets", {"name": n, "value": "v"}),
              lambda: names(jsonout(aws("secretsmanager", "list-secrets")[1]), "Name"),
              lambda n: aws("secretsmanager", "delete-secret", "--secret-id", n, "--force-delete-without-recovery"))

    gp_cli, gp_con = ids["gcp"]["cli"], ids["gcp"]["console"]
    gc = lambda *a: run("gcloud", *a, f"--project={gp_cli}", "--format=json")  # noqa: E731
    roundtrip("GCP", "Cloud Storage bucket",
              lambda n: gc("storage", "buckets", "create", f"gs://{n}"),
              lambda: con_list(f"/api/gcp/storage/v1/b?project={gp_con}", "name", "id"),
              lambda n: http("POST", f"/api/gcp/storage/v1/b?project={gp_con}", {"name": n}),
              lambda: names(jsonout(gc("storage", "buckets", "list")[1]), "name", "id"),
              lambda n: (gc("storage", "buckets", "delete", f"gs://{n}"), http("DELETE", f"/api/gcp/storage/v1/b/{n}")))
    roundtrip("GCP", "Pub/Sub topic",
              lambda n: gc("pubsub", "topics", "create", n),
              lambda: con_list(f"/api/gcp/pubsub/v1/projects/{gp_con}/topics", "name"),
              lambda n: http("POST", f"/api/gcp/pubsub/v1/projects/{gp_con}/topics", {"name": n}),
              lambda: names(jsonout(gc("pubsub", "topics", "list")[1]), "name"),
              lambda n: (gc("pubsub", "topics", "delete", n), http("DELETE", f"/api/gcp/pubsub/v1/projects/{gp_con}/topics/{n}")))
    roundtrip("GCP", "Secret Manager secret",
              lambda n: gc("secrets", "create", n, "--replication-policy=automatic"),
              lambda: con_list(f"/api/gcp/secrets?project={gp_con}", "name", "id"),
              lambda n: http("POST", f"/api/gcp/secrets?project={gp_con}", {"name": n}),
              lambda: names(jsonout(gc("secrets", "list")[1]), "name"),
              lambda n: gc("secrets", "delete", n))

    sub_cli, sub_con, rg = ids["azure"]["cli"], ids["azure"]["console"], ids["azure"]["rg"] or "cloudlearn-rg"
    def az(method: str, path: str, body=None):
        cmd = ["az", "rest", "--method", method, "--url", B + path, "--skip-authorization-header"]
        if body is not None:
            cmd += ["--body", json.dumps(body)]
        return run(*cmd)
    arm_list = lambda path: names(jsonout(az("get", path)[1]), "name", "id")  # noqa: E731
    con_arm_list = lambda path: names(http("GET", path)[1], "name", "id")  # noqa: E731
    roundtrip("Azure", "resource group",
              lambda n: az("put", f"/subscriptions/{sub_cli}/resourceGroups/{n}?api-version=2021-04-01", {"location": "eastus"}),
              lambda: con_arm_list(f"/subscriptions/{sub_con}/resourcegroups?api-version=2021-04-01"),
              lambda n: http("PUT", f"/subscriptions/{sub_con}/resourceGroups/{n}?api-version=2021-04-01", {"location": "eastus"}),
              lambda: arm_list(f"/subscriptions/{sub_cli}/resourcegroups?api-version=2021-04-01"),
              lambda n: (az("delete", f"/subscriptions/{sub_cli}/resourceGroups/{n}?api-version=2021-04-01"),
                         http("DELETE", f"/subscriptions/{sub_con}/resourceGroups/{n}?api-version=2021-04-01")))
    for kind, prov, api, body in (
            ("storage account", "Microsoft.Storage/storageAccounts", "2023-01-01",
             {"location": "eastus", "sku": {"name": "Standard_LRS"}, "kind": "StorageV2"}),
            ("virtual network", "Microsoft.Network/virtualNetworks", "2023-09-01",
             {"location": "eastus", "properties": {"addressSpace": {"addressPrefixes": ["10.42.0.0/16"]}}})):
        # The CLI targets the resource group the console shows, in the
        # subscription the CLI discovered — what a user does after looking at the portal.
        cli_coll = f"/subscriptions/{sub_cli}/resourceGroups/{rg}/providers/{prov}"
        con_coll = f"/subscriptions/{sub_con}/resourceGroups/{rg}/providers/{prov}"
        roundtrip("Azure", kind,
                  lambda n, c=cli_coll, a=api, b=body: az("put", f"{c}/{n}?api-version={a}", b),
                  lambda c=con_coll, a=api: con_arm_list(f"{c}?api-version={a}"),
                  lambda n, c=con_coll, a=api, b=body: http("PUT", f"{c}/{n}?api-version={a}", b),
                  lambda c=cli_coll, a=api: arm_list(f"{c}?api-version={a}"),
                  lambda n, c1=cli_coll, c2=con_coll, a=api: (az("delete", f"{c1}/{n}?api-version={a}"),
                                                             http("DELETE", f"{c2}/{n}?api-version={a}")))


# ── 3. every CLI suite, individually ───────────────────────────────────────
def cli_suites(ids: dict) -> None:
    env = {"ENDPOINT": B, "PROJECT": ids["gcp"]["console"], "AZURE_SUBSCRIPTION_ID": ids["azure"]["console"],
           "AZURE_RESOURCE_GROUP": ids["azure"]["rg"]}
    for f in sorted(glob.glob(os.path.join(ROOT, "tests", "cli", "*-cli-smoke.sh"))):
        name = os.path.basename(f)[:-len("-cli-smoke.sh")]
        try:
            p = subprocess.run(["bash", f], env=dict(ENV, **env), capture_output=True, text=True, timeout=900, cwd=ROOT)
            out, rc = p.stdout + p.stderr, p.returncode
        except subprocess.TimeoutExpired:
            out, rc = "timed out after 900s", 124
        # Two output styles: "PASS name" / "FAIL name :: why" and "[PASS] name" / "[FAIL] name :: why".
        np, nf = len(re.findall(r"^\[?PASS\]? ", out, re.M)), len(re.findall(r"^\[?FAIL\]? ", out, re.M))
        skipped = re.search(r"^SKIP ", out, re.M) is not None
        fails = "; ".join(re.sub(r"^\[?FAIL\]? ", "", l).split(" :: ")[0] for l in out.splitlines()
                          if re.match(r"\[?FAIL\]? ", l))[:400]
        check("cli-suite", f"{name}: {np} passed, {nf} failed", rc == 0 and nf == 0 and not skipped and np > 0,
              ("CLI not installed (" + out.strip()[:200] + ")") if skipped else (fails or out[-400:]))


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    for tool in ("aws", "gcloud", "az"):
        rc, out = run(tool, "--version", timeout=60)
        check("tools", f"{tool} installed", rc == 0, out[-200:])
    wait_ready()
    ids = identities()
    both_ways(ids)
    cli_suites(ids)
    reg = json.load(open(os.path.join(ROOT, "services", "registry.json")))["services"]
    have = {os.path.basename(f)[:-len("-cli-smoke.sh")] for f in glob.glob(os.path.join(ROOT, "tests", "cli", "*-cli-smoke.sh"))}
    no_cli = sorted(f"{s['cloud'].upper()} {s['name']}" for s in reg
                    if s.get("status") == "released" and f"{s['cloud']}-{s['key']}" not in have)

    ok = sum(r["ok"] for r in results)
    titles = {"tools": "CLIs", "identity": "Identity: CLI and console use the same account / project / subscription",
              "both-ways": "Both directions: CLI → console and console → CLI",
              "cli-suite": "CLI suites, each on its own"}
    md = [f"**{ok}/{len(results)} checks passed** against `{B}`.", ""]
    for sec, title in titles.items():
        rs = [r for r in results if r["section"] == sec]
        if not rs:
            continue
        md += [f"### {title} ({sum(r['ok'] for r in rs)}/{len(rs)})", "", "| | Check | Detail |", "|---|---|---|"]
        md += [f"| {'✅' if r['ok'] else '❌'} | {r['name']} | {'' if r['ok'] else r['detail'][-240:].replace('|', '/').replace(chr(10), ' ')} |" for r in rs]
        md.append("")
    if no_cli:
        md += [f"### Released services with no CLI suite yet ({len(no_cli)})", "", ", ".join(no_cli), ""]
    open(os.path.join(OUT, "summary.md"), "w").write("\n".join(md) + "\n")
    json.dump({"endpoint": B, "identities": ids, "results": results, "no_cli_suite": no_cli},
              open(os.path.join(OUT, "results.json"), "w"), indent=1)
    print(f"\n{ok}/{len(results)} checks passed → {OUT}/summary.md")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
