# Capability registry check: complete environment recipe

Branch `v4/post-beta-capfix` (base `origin/v4-on-main` 4141d0577, v4.0.3). Measured on macOS arm64 (Darwin 24.3), Python 3.13.11,
Node 26.3.0. Nothing here was run on Linux.

`tests/conformance/test_capabilities.py` (nano substrate, in-process `AwsWireRouter`) proves every claim in
`core/capabilities/*/*.json`: 1472 claims. Each "tests only" claim runs its listed test files as subprocesses, so the environment
must contain everything those files import. A scratch venv with only `requirements.txt` fails 40+ claims for environment reasons
alone (Azure SDKs missing); that is not a product signal.

## Install recipe

```bash
python3.13 -m venv capvenv
capvenv/bin/pip install -r requirements.txt pytest requests pyyaml
capvenv/bin/pip install azure-core azure-identity azure-mgmt-loganalytics azure-mgmt-resource "azure-mgmt-monitor==6.0.2" \
  azure-mgmt-sql azure-mgmt-network azure-mgmt-web azure-mgmt-storage azure-mgmt-security azure-mgmt-resourcegraph \
  azure-mgmt-containerservice azure-mgmt-applicationinsights azure-mgmt-servicebus azure-mgmt-kubernetesconfiguration \
  azure-mgmt-cosmosdb azure-mgmt-cognitiveservices azure-mgmt-apimanagement azure-mgmt-eventgrid azure-servicebus \
  azure-cosmos azure-data-tables azure-appconfiguration azure-keyvault-keys azure-keyvault-secrets openai
# Google SDK tests (tests/conformance/test_gcp_ref_corefix_sdk.py): real client libraries against the in-process simulator
capvenv/bin/pip install google-cloud-logging google-cloud-trace google-cloud-kms google-cloud-storage google-cloud-pubsub \
  google-cloud-functions google-cloud-aiplatform google-genai
# Nano AMQP test (Pyodide + Node): vendored Pyodide (15 MB, untracked/ignored) and the JS deps for the relay
python3 wasm/fetch_pyodide.py && python3 wasm/build_cores.py
mkdir sbnm && (cd sbnm && npm init -y && npm i ws @azure/service-bus)      # 31 MB
export VYOMI_SB_JS_NODE_MODULES=$PWD/sbnm/node_modules
# CLI smokes need aws, az, gcloud, node on PATH; console smokes need Playwright (the harness looks for
# /Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright or $PW).
export CLOUDLEARN_STATE_FILE=$(mktemp -d)/state.sqlite3          # fresh per run
PYTHONPATH=. capvenv/bin/python tests/conformance/test_capabilities.py
```

Version pins that matter:

* `azure-mgmt-monitor==6.0.2`. 7.x removed `MonitorManagementClient.diagnostic_settings` and the subscription diagnostic-settings
  models; `test_azure_netenforce_sdk.py` and `test_azure_sdk_defender_automation_export.py` fail with AttributeError/ImportError on 7.x.
* `pyarrow` (in requirements.txt) is required by `test_azure_cosmos_export.py`. On macOS its thread pool can deadlock at interpreter
  exit after the test passed; the test now ends with `os._exit` for that reason.
* CI (`ci.yml`, `release-checks.yml`, `service-gate.yml`) installs only `requests pytest boto3 azure-storage-blob [pyyaml]`: it does
  not run this check, so it never needed the Azure management SDKs.

Disk: about 600 MB for the venv, 31 MB node deps, 15 MB Pyodide. `lambda_functions/{dbl,inc,mkkey,upper}/` appear untracked after
a sweep (test output); do not commit them.

## Harness fixes made on this branch (test_capabilities.py)

1. pytest-only test files (no `__main__` runner, 9 of 384 python files, for example `test_azure_offline_wiring.py`,
   `test_azure_servicebus_amqp_*.py`, `test_azure_sdk_webhost_autoscale_apim_prom.py`) were run with plain `python file`, which imports
   them and runs NOTHING, so the claim "passed" vacuously (or failed on a module-level skip). They now run under `pytest` and need at
   least one passing test (an all-skipped file does not count as holding).
2. Each test file now gets its own fresh `CLOUDLEARN_STATE_FILE` instead of sharing the parent sweep's persisted state. Sharing it made
   `test_bedrock_flows`, `test_bedrock_evals`, `test_model_import` and `test_training_jobs` fail inside the sweep while passing alone.

Result with this recipe on the branch: 1472/1472 claims hold on nano (macOS arm64). Before the fixes: 1426/1472 (46 failures: 41 missing Azure SDKs/pyodide/node deps or vacuous pytest runs, 4 state pollution, 1 timing flake; the 4 Service Bus AMQP-on-Nano claims were a REAL regression: nano-endpoint.html CORES lagged relay-shared-worker.js, fixed in this commit).
