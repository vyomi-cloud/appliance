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
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "core")
OUT = os.path.join(HERE, "core")

CORES = [
    "object_store.py", "s3_object_core.py",        # S3
    "nosql_store.py", "dynamodb_core.py",           # DynamoDB
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
    "vpc_core.py",                                 # v2.8.0 AWS: VPC network-simulation data plane (reachability analyzer)
    "persistent_store.py",                          # v2.4.0: file-backed (sqlite) substrate — the anti-drift gate
    "aws_wire_router.py",                            # native-wire front door (relay/bridge)
    "azure_arm_data.py", "azure_arm_core.py",       # Azure ARM control plane (native /subscriptions/* wire)
]

HEADER = ("# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.\n"
          "# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py\n")


# Relay loaders whose CORES list is fetched into the Pyodide FS. Every top-level
# `from core.X import` in a listed module MUST also be listed, or the browser boot
# raises ImportError (this guard exists because relay-shared-worker.js once lagged
# aws_wire_router's new GCP/Azure imports and broke Start-tunnel in production).
_RELAY_LOADERS = ["relay/relay-shared-worker.js", "relay/nano-endpoint.html"]
_TOPLEVEL_IMPORT = re.compile(r"^from core\.(\w+) import", re.M)
_TOPLEVEL_FROM = re.compile(r"^from core import (.+)$", re.M)


def _cores_in(js_text):
    """Extract the .py filenames from a loader's `const CORES = [ ... ]` block."""
    m = re.search(r"const CORES\s*=\s*\[(.*?)\]", js_text, re.S)
    return set(re.findall(r'"([a-z0-9_]+\.py)"', m.group(1))) if m else set()


def _deps_of(module_py):
    """Top-level core deps of core/<module_py> (as X.py). Lazy/indented imports
    are excluded — they load on demand, not at module import."""
    src = open(os.path.join(SRC, module_py)).read()
    deps = {f"{x}.py" for x in _TOPLEVEL_IMPORT.findall(src)}
    for grp in _TOPLEVEL_FROM.findall(src):
        for part in grp.split(","):
            name = part.strip().split(" as ")[0].strip()
            if name:
                deps.add(f"{name}.py")
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


def main():
    os.makedirs(OUT, exist_ok=True)
    # Make wasm/core an importable package mirror of the repo `core` package, so
    # the vendored modules' `from core.object_store import ...` resolve in Pyodide.
    with open(os.path.join(OUT, "__init__.py"), "w") as f:
        f.write(HEADER)
    for name in CORES:
        with open(os.path.join(SRC, name)) as f:
            src = f.read()
        with open(os.path.join(OUT, name), "w") as f:
            f.write(HEADER + src)
        print(f"core/{name:22} -> wasm/core/{name} ({len(src)} bytes)")
    check_relay_cores()   # fail loudly if a relay loader lags the cores


if __name__ == "__main__":
    main()
