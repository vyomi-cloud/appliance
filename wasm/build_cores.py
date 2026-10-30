"""Vendor the canonical conformance cores into the Nano bundle.

Nano serves the `wasm/` folder as its web root (the repo source is never
exposed), but the page-side backend (nano-boot.js) must fetch the SAME proven
core modules the conformance suite runs against. So we COPY — never fork — the
canonical files from `core/` into `wasm/core/`, where they're reachable from the
web root. The copies are generated artifacts (like `wasm/fixtures/`): re-run this
after changing any core to keep the bundle in lock-step with the proven source.

Cores vendored (each green on host CPython AND Pyodide via tests/conformance/):
  core/object_store.py     -> the S3 data-plane seam
  core/s3_object_core.py   -> the S3 handler logic (native wire)
  core/nosql_store.py      -> the DynamoDB data-plane seam
  core/dynamodb_core.py    -> the DynamoDB handler logic (native wire)

Run:  python3 wasm/build_cores.py   (part of the bundle build, with build_fixtures.py)
"""
import json
import os
import ast
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "core")
OUT = os.path.join(HERE, "core")

CORES = [
    "object_store.py", "s3_object_core.py",        # S3
    "nosql_store.py", "dynamodb_core.py",           # DynamoDB
    "dynamodb_expr.py",                             # DynamoDB expression engine (v4 C0: key/filter/condition/update/projection)
    "kms_keystore.py", "kms_core.py",               # KMS
    "kv_store.py", "secrets_core.py",               # Secrets Manager
    "sql_store.py", "rds_core.py",                  # RDS
    "iam_store.py", "iam_core.py",                  # IAM
    "messaging_store.py", "sqs_core.py", "sns_core.py",  # SQS + SNS (eventing)
    "rds_data_core.py",                             # RDS Data API (HTTP SQL over the relay)
    "gcp_storage_core.py",                          # GCP: GCS JSON API (native google-cloud-storage wire)
    "gcp_firestore_core.py",                        # GCP: Firestore REST (native google-cloud-firestore)
    "gcp_kms_core.py",                              # GCP: Cloud KMS REST (native google-cloud-kms)
    "gcp_secretmanager_core.py",                    # GCP: Secret Manager REST (native google-cloud-secret-manager)
    "gcp_pubsub_core.py",                           # GCP: Pub/Sub REST (native google-cloud-pubsub)
    "gcp_iam_core.py",                              # GCP: Cloud IAM REST (SA + policy eval)
    "gcp_cloudsql_core.py",                         # GCP: Cloud SQL Admin REST (control plane)
    "gcp_artifactregistry_core.py",                 # GCP: Artifact Registry REST v1 (repositories, packages, versions, tags, docker images)
    "azure_blob_core.py",                           # Azure: Blob REST (native azure-storage-blob)
    "azure_cosmos_core.py",                         # Azure: Cosmos DB SQL/Core API (native azure-cosmos)
    "azure_keyvault_secrets_core.py",               # Azure: Key Vault secrets (native azure-keyvault-secrets)
    "azure_keyvault_keys_core.py",                  # Azure: Key Vault keys (native azure-keyvault-keys)
    "azure_queue_core.py",                          # Azure: Storage Queue (native azure-storage-queue)
    "azure_servicebus_core.py",                     # v2.5.0 Azure: Service Bus topics (pub/sub fan-out — SNS/Pub-Sub peer)
    "azure_sql_core.py",                            # v2.6.0 Azure: SQL data plane on the SqlStore seam (RDS/Cloud SQL peer)
    "azure_iam_core.py",                            # v2.6.0 Azure: RBAC checkAccess decision core (IAM/testIamPermissions peer)
    "eventbridge_core.py",                          # v2.6.0 AWS: EventBridge event-bus data plane (rules → SQS delivery)
    "lambda_core.py",                              # v2.6.0 AWS: Lambda serverless invoke (sandboxed Python runtime)
    "apigateway_core.py",                          # v2.7.0 AWS: API Gateway data plane (routing + MOCK/Lambda-proxy integrations)
    "cost_model.py",                                # list prices -> the space cost-savings metrics (pure data)
    "kinesis_core.py",                             # AWS: Kinesis Data Streams (shards, records, iterators, consumers)
    "apigatewayv2_core.py",                        # AWS: API Gateway V2 control plane
    "apigatewayv2_gateway.py",                     # AWS: API Gateway V2 data plane (authorizers, throttling, CORS, Lambda proxy)
    "elbv2_core.py",                                # AWS: Elastic Load Balancing v2 control plane — native Query wire + console REST
    "ssm_core.py",                                 # AWS: Systems Manager (Parameter Store, documents, Run Command, windows, baselines)
    "gcp_cloudscheduler_core.py",                  # expansion GCP: Cloud Scheduler (jobs, cron, pause/resume/run)
    "gcp_iamcredentials_core.py",                  # expansion GCP: IAM Service Account Credentials (access/ID tokens, signBlob, signJwt)
    "gcp_redis_core.py",                           # expansion GCP: Memorystore for Redis (instances, failover, upgrade, import/export, operations)
    "gcp_monitoring_core.py",                      # expansion GCP: Cloud Monitoring (alert policies, channels, metrics, time series, uptime checks)
    "gcp_container_core.py",                       # expansion GCP: Kubernetes Engine (clusters, node pools, operations)
    "gcp_logging_core.py",                         # GCP: Cloud Logging REST v2 (entries, sinks, log-based metrics, log buckets/views)
    "stepfunctions_core.py",                       # AWS: Step Functions (ASL interpreter, executions, activities)
    "cloudwatch_core.py",                          # AWS CloudWatch: metrics / alarms / dashboards (rpc-v2-cbor + JSON + Query wire)
    "vpc_core.py",                                 # v2.8.0 AWS: VPC network-simulation data plane (reachability analyzer)
    "logs_core.py",                                # expansion AWS: CloudWatch Logs (log groups/streams/events/insights) — vendored VERBATIM
    "persistent_store.py",                          # v2.4.0: file-backed (sqlite) substrate — the anti-drift gate
    "aws_wire_router.py",                            # native-wire front door (relay/bridge)
    "azure_cognitiveservices_core.py",             # expansion Azure: AI services (Microsoft.CognitiveServices accounts, deployments, keys) — vendored VERBATIM
    "azure_monitor_core.py",                      # expansion Azure: Monitor (Microsoft.Insights action groups, alerts, autoscale) — vendored VERBATIM
    "azure_dns_core.py",                          # expansion Azure: DNS (Microsoft.Network/dnsZones, record sets) — vendored VERBATIM
    "azure_operationalinsights_core.py",          # expansion Azure: Log Analytics (Microsoft.OperationalInsights workspaces, saved searches, tables) — vendored VERBATIM
    "azure_appconfiguration_core.py",             # expansion Azure: App Configuration (stores, key-values, snapshots) — vendored VERBATIM
    "azure_app_core.py",                            # expansion Azure: Container Apps (Microsoft.App: environments, apps, revisions, jobs) — vendored VERBATIM
    "azure_arm_data.py", "azure_arm_core.py",       # Azure ARM control plane (native /subscriptions/* wire)
    "console_conformance.py",                       # console-next capability manifest: per-service conformance signal (pure, `os` only)
    "nano_events.py",                               # per-resource cloudsim event/activity log (recorded on every mutating dispatch; MUST precede nano_registry which imports it)
    "nano_registry.py",                             # shared in-context store registry (console adapter + relay router draw from ONE set)
    "nano_persist.py",                              # store serialize/restore + cross-context sync (persistence + console↔SDK parity)
]

# Cores vendored byte-for-byte (no GENERATED header): the service gate requires the
# Nano copy of a new service's engine to be identical to core/.
VERBATIM = {"gcp_monitoring_core.py", "cloudwatch_core.py", "apigatewayv2_core.py", "logs_core.py", "elbv2_core.py", "ssm_core.py", "stepfunctions_core.py", "gcp_cloudscheduler_core.py", "gcp_container_core.py", "gcp_iamcredentials_core.py", "gcp_redis_core.py", "gcp_artifactregistry_core.py", "azure_app_core.py", "azure_appconfiguration_core.py", "azure_cognitiveservices_core.py", "azure_dns_core.py", "azure_monitor_core.py", "azure_operationalinsights_core.py"}

HEADER = ("# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.\n"
          "# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py\n")


# Relay loaders whose CORES list is fetched into the Pyodide FS. Every top-level
# `from core.X import` in a listed module MUST also be listed, or the browser boot
# raises ImportError (this guard exists because relay-shared-worker.js once lagged
# aws_wire_router's new GCP/Azure imports and broke Start-tunnel in production).
_RELAY_LOADERS = ["relay/relay-shared-worker.js", "relay/nano-endpoint.html"]
def _load_time_imports(tree):
    """Import statements that run when the module is imported: the module body
    and the bodies of top-level try/except, if/else and with blocks, but not
    function or class bodies (those load on demand)."""
    stack = list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield node
        elif isinstance(node, (ast.Try, getattr(ast, "TryStar", ast.Try))):
            stack += node.body + node.orelse + node.finalbody + [x for h in node.handlers for x in h.body]
        elif isinstance(node, (ast.If, ast.With)):
            stack += node.body + getattr(node, "orelse", [])


def _cores_in(js_text):
    """Extract the .py filenames from a loader's `const CORES = [ ... ]` block."""
    m = re.search(r"const CORES\s*=\s*\[(.*?)\]", js_text, re.S)
    return set(re.findall(r'"([a-z0-9_]+\.py)"', m.group(1))) if m else set()


def _deps_of(module_py):
    """Core modules core/<module_py> imports at load time (as X.py), including
    the Pyodide fallbacks inside top-level `try: from core import x / except
    ImportError: import x` blocks: azure_arm_core's six such imports were
    missed by the old regex (indented = "lazy") and broke the relay in v3.0.18+."""
    tree = ast.parse(open(os.path.join(SRC, module_py)).read())
    deps = set()
    for node in _load_time_imports(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "core":
                deps |= {f"{a.name}.py" for a in node.names}
            elif node.module and node.module.startswith("core."):
                deps.add(node.module.split(".")[1] + ".py")
            elif node.module and node.level == 0:
                deps.add(node.module.split(".")[0] + ".py")      # flat fallback: from x import y
        else:
            for a in node.names:
                name = a.name.split(".")
                deps.add((name[1] if name[0] == "core" and len(name) > 1 else name[0]) + ".py")
    return deps


def check_relay_cores():
    """Fail the build if any relay CORES list is not import-closed."""
    problems = []
    for loader in _RELAY_LOADERS:
        path = os.path.join(HERE, loader)
        if not os.path.exists(path):
            continue
        listed = _cores_in(open(path).read())
        if not listed:
            continue
        for mod in list(listed):
            if not os.path.exists(os.path.join(SRC, mod)):
                continue
            missing = _deps_of(mod) - listed
            # only flag deps that are actually core modules (exist in core/)
            missing = {d for d in missing if os.path.exists(os.path.join(SRC, d))}
            for d in sorted(missing):
                problems.append(f"  {loader}: '{mod}' imports '{d}' but it's not in the CORES list")
    if problems:
        print("\nRELAY CORES DRIFT — these loaders will ImportError at browser boot:")
        print("\n".join(problems))
        print("Add the missing modules to the loader's CORES list.")
        raise SystemExit(1)
    print("relay CORES lists are import-closed ✓")


def _expansion_cores():
    """Cores of services built by the expansion agent (services/manifests/*.json).
    The service gate requires their Nano copy to be BYTE-IDENTICAL to core/, so they are
    vendored without the GENERATED header (the file is the canonical source verbatim)."""
    import glob
    import json
    out = set()
    for f in glob.glob(os.path.join(ROOT, "services", "manifests", "*.json")):
        try:
            out.add(os.path.basename(json.load(open(f)).get("core", "")))
        except Exception:
            pass
    out.discard("")
    return out


NANO_BACKENDS = os.path.join(HERE, "fixtures", "nano-backends.json")


def _category(store):
    if store.startswith("gcp_") or store == "gcs":
        return "gcp"
    if store.startswith("az_"):
        return "azure"
    return "core" if store == "events" else "aws"


def nano_backends():
    """Nano's backend services = the engine stores core/nano_registry.py builds (plain
    state namespaces aren't backends), plus the Pyodide runtime they run in. Written to
    fixtures/nano-backends.json for the Service status cards (wasm/sw.js), so the list
    is the registry's own, release after release."""
    import importlib
    import types
    sys.path.insert(0, HERE)
    for m in [m for m in sys.modules if m == "core" or m.startswith("core.")]:
        del sys.modules[m]
    reg = importlib.import_module("core.nano_registry").get()
    out = [{"name": "runtime", "label": "Pyodide runtime", "category": "core"}]
    for key, store in reg.items():
        if isinstance(store, types.SimpleNamespace):
            continue
        out.append({"name": key, "label": f"{key} · {type(store).__name__}", "category": _category(key)})
    return out


def write_nano_backends():
    with open(NANO_BACKENDS, "w") as f:
        json.dump(nano_backends(), f, indent=1)
        f.write("\n")


def check_nano_backends():
    want = nano_backends()
    try:
        have = json.load(open(NANO_BACKENDS))
    except (OSError, ValueError):
        have = None
    if have != want:
        sys.exit("wasm/fixtures/nano-backends.json is stale: run python3 wasm/build_cores.py")
    print(f"nano-backends.json lists all {len(want)} Nano backends \u2713")


def main():
    os.makedirs(OUT, exist_ok=True)
    verbatim = _expansion_cores()
    # Make wasm/core an importable package mirror of the repo `core` package, so
    # the vendored modules' `from core.object_store import ...` resolve in Pyodide.
    with open(os.path.join(OUT, "__init__.py"), "w") as f:
        f.write(HEADER)
    for name in CORES:
        with open(os.path.join(SRC, name)) as f:
            src = f.read()
        with open(os.path.join(OUT, name), "w") as f:
            f.write(src if name in verbatim else HEADER + src)
        print(f"core/{name:22} -> wasm/core/{name} ({len(src)} bytes)")
    check_relay_cores()   # fail loudly if a relay loader lags the cores
    write_nano_backends()


if __name__ == "__main__":
    if "--check" in sys.argv:          # CI: verify the relay loaders + backend list, write nothing
        check_relay_cores()
        check_nano_backends()
    else:
        main()
