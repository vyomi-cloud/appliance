# v4/gcp-ref-sandbox

Owner: GCP reference-arch lane 3 - Started: 2026-11-18 - Base: origin/v4-on-main (a54fc442f) - Status: ready for review

## Purpose
A deployed Cloud Functions / Cloud Run function must reach the simulator the way a real function reaches Google: the real
`google-cloud-firestore`, `google-cloud-pubsub`, `google-cloud-storage`, `google-cloud-secret-manager` clients and plain
`requests`/`urllib`. Blocked reference components 5 (approval function writes the ledger), 7 (tools read Firestore), 12 (event function re-ingests).

## Changes
- `core/gcp_function_runtime.py` (existing offline subprocess runtime, now used by the GCP wire path): sandboxed `run_deployed()`, `function_env()`, `self_url()`, `check_requirements()`, `libraries()`, `enabled()`.
- `core/gcp_functions_core.py`: `_execute` runs Python through that runtime when a process can be spawned; the zip's other files (helper modules, json/txt) and `requirements.txt` are kept; unsatisfiable requirements fail the build with the available libraries; annotations carry env/signature/timeout/SA/files so Eventarc deliveries run the same way.
- `core/gcp_run_core.py`: `invoke_service` (Eventarc Pub/Sub and Storage deliveries, `:invoke`) runs function-deployed services through the runtime: cloudevent functions get a CloudEvent, http functions a POST.
- `core/gcp_wire_ext.py`: records where the simulator is reachable (`gcp_run.self_base`) so the sandbox can call back.
- `requirements.txt`: google-cloud-storage, google-cloud-secret-manager, requests join the pre-baked set. `wasm/core/*` mirrors regenerated (`wasm/build_cores.py`).
- `core/capabilities/gcp/functions.json`: claim `gcp.functions.sandbox.sdk-access` (nano limited, offline full). Test: `tests/conformance/test_gcp_function_sandbox_sdk.py`.

## How a function reaches the simulator
The function is a subprocess (`python -B`, own temp dir) started with a scrubbed environment (the simulator's own variables and secrets are NOT inherited) containing:
`GOOGLE_CLOUD_PROJECT`/`GCP_PROJECT`/`GCLOUD_PROJECT`, `K_SERVICE`, `K_REVISION`, `K_CONFIGURATION`, `FUNCTION_TARGET`, `FUNCTION_SIGNATURE_TYPE` (`http`|`cloudevent`), `FUNCTION_NAME`, `FUNCTION_REGION`, `PORT`, the function's own variables, plus
`VYOMI_ENDPOINT` (the simulator URL), `STORAGE_EMULATOR_HOST` (same URL: the unmodified storage client uses it), and `PUBSUB_EMULATOR_HOST`/`FIRESTORE_EMULATOR_HOST`/`VYOMI_GCP_REAL_BACKENDS` only when the host has them (lane gcp-ref-realbackend).
Application default credentials: before user code runs, a loopback metadata server starts inside the function process and sets `GCE_METADATA_HOST`; `google.auth.default()` returns Compute Engine credentials for the function's service account, project id and token (`/token`, `/identity`, `/project/project-id`, `/service-accounts/default/`). The token value is `vyomi-local-function-token`; the simulator does not verify it.
The simulator URL is `VYOMI_SELF_URL`, else the request's own base when loopback, else `http://127.0.0.1:$PORT` (9000 default).

## Libraries available
The appliance's own pre-baked wheel set, listed by `gcp_function_runtime.libraries()`: google-cloud-firestore, -pubsub, -storage, -secret-manager, -kms, -logging, -monitoring, -trace, -aiplatform, google-genai, google-auth, google-api-core, grpcio, requests, httpx, pyjwt, cryptography, protobuf, boto3, pyarrow (whatever the install has). `requirements.txt` is honoured against it with `packaging` (versions and markers); there is no internet, so nothing is pip-installed and an unmet requirement fails the deploy (`FAILED_PRECONDITION`, build error listing the available libraries).
Flask and functions_framework are the Vyomi shims (a real Flask in requirements is shadowed).

## Security model (what is and is not guaranteed)
Interpreter-level guard installed before user code: Python sockets and `getaddrinfo` only reach loopback + the simulator/emulator hosts; grpc channel creation is checked the same way; a PEP 578 audit hook confines `open`/os file calls (read: function dir, interpreter, site-packages, system CA/zoneinfo files; write: function dir only) and denies `subprocess`, `os.system/exec/spawn/fork`, and `ctypes.dlopen` from outside the interpreter. Tested: no internet (name and IP), no `/etc/passwd`, no write to `/tmp`, no subprocess, host env not visible.
Not guaranteed: native code that bypasses the interpreter (a hostile C extension, or grpc internals) is not contained. For hostile code use the Pro container runtime. This is a guard-rail, not a VM.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| Reuse `core/gcp_function_runtime` (subprocess per call, same mechanism as the AWS Lambda runner in `routes/aws_lambda_unified.py`) | new Docker/gVisor executor; keep the in-process sandbox and whitelist modules | owner rule: no new backend; the in-process sandbox cannot import compiled SDKs or open sockets by design |
| Per-function loopback metadata server inside the function process | one shared metadata endpoint on the simulator | the shared one cannot tell which function (service account) is calling; needs no router/Nano change |
| Scrubbed environment + audit hook, not an inherited environment like the Lambda runner | inherit host env | host tokens/secrets must not reach function code |
| Runtime chosen by `enabled()` (no process spawn on Nano/Pyodide; `VYOMI_GCP_FUNCTION_RUNTIME=inproc` forces it) | always subprocess | Nano cannot spawn; no new core module, so the Nano and relay CORES lists are unchanged (`test_relay_cores_parity` green) |
| Own code added: the guard + metadata server (about 150 lines inside gcp_function_runtime) | an OSS sandbox | no lightweight pure-Python OSS option covers network allow-list + metadata server + fs confinement without a container |

## Nano difference
Nano runs the function in the same Pyodide interpreter as the cores: computational stdlib and the flask/functions_framework shims only, no Google SDKs, no network. A function that imports `google.cloud` fails with `ImportError: module ... is not available in the function sandbox` (asserted by the test). The reference app's functions need offline/Mesh (or a Nano tunnel to a local appliance).

## Open issues
- [ ] Default-transport `firestore.Client()` and `PublisherClient()` are gRPC: they work only when the real emulators are the data plane (lane gcp-ref-realbackend) and `FIRESTORE_EMULATOR_HOST`/`PUBSUB_EMULATOR_HOST` are inherited; on the REST data plane the function uses gapic clients with `transport="rest"` and `api_endpoint=$VYOMI_ENDPOINT` (proven). Secret Manager has no emulator env var: pass `api_endpoint` as well.
- [ ] The in-process test harness (`facilities/server.py` `start_in_process`) does not set `REQUEST_PROVIDER` to `gcp` as `core/middleware.py` does, so Eventarc Cloud Storage triggers created by a function deploy report the bucket missing; the lane-1 harness should set it per request (the test here does).
- [ ] Function stdout is returned to the caller / delivery record but is not yet written to Cloud Logging per line.
- [ ] Per-call process start (about 0.3 s); no warm instances or concurrency.
- [ ] `tests/conformance/test_capabilities.py` environments need google-cloud-functions, google-cloud-secret-manager, google-cloud-storage, requests (see CAPABILITY-CHECK-ENV.md).
