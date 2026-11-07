# Booster local validation (Docker, Codespace-constrained)

Date 2026-11-07, branch `v4/ngboost` (from `v4-on-main`). Everything ran locally; **no GitHub, Codespace, portal or relay was involved**, so this
validates the appliance in the booster role, not the Codespace/relay/App plumbing (see "Still needs a real Codespace").

## Setup (what was actually run)
- Image `vyomi-boost-appliance:local` built from this checkout's `Dockerfile` (VERSION file says 3.0.45; there is no 4.0.0 tag yet).
- Container started like `codespace/.devcontainer/booster/docker-compose.booster.yml` (`VYOMI_ROLE=booster`, `VYOMI_COMPUTE_BACKEND=docker`, docker.sock
  mounted, user 0:0), plus `--cpus 2 --memory 8g` and one published loopback port (the real compose publishes none; the relay link is outbound only).
  The `link` service was not started (no relay).
- Session token minted with `core.booster_session.mint('local-max','max', now+8h, key=<random local key>)`; key and token passed as
  `VYOMI_BOOSTER_SESSION_KEY` / `VYOMI_BOOSTER_SESSION_TOKEN`. Pro (primary aws) and a 45 s Max token were minted the same way for section 4.
- Caveat: the Docker VM on this Mac is 8 GB **shared with ~90 stale `vyomi-i-*` containers from other sessions** (MemAvailable ~450 MB), so this is
  harsher than a clean Codespace for anything that needs real RAM.

## 1. Readiness
| Item | Result |
|---|---|
| `/healthz` | `{"status":"ok","tier":"max"}` (after the fix below; before it said `free`) |
| `/booster/status` | `booster:true, headless:true, tier:max, health ok` |
| Budget (8 GB host, 70% cap) | cap 5555 MB; split compute 2777 MB / AI 2777 MB; CPU cap 5.6 of 8 (the Mac VM has 8 CPUs, `--cpus 2` is a cgroup quota the budget does not read, see below) |
| Idle footprint | simulator ~210-230 MiB RSS, ~3% CPU (`docker stats`) |
| AI pack | `state: starting` the whole time. The simulator admitted Qwen2.5-3B Q4_K_M (2500 MB) + bge-small (250 MB) = 2750 of 2777 MB. I started the llama.cpp containers by hand (same flags as compose): the **3B download (~2.1 GB) took ~5 min on this link**, then `llm-chat` was **OOM-killed on load** because the shared Docker VM had ~450 MB free. `llm-embed` (bge-small) came up healthy. So the real 3B was NOT exercised; no fake model was substituted (the fake-server tests `test_booster_ai.py` cover that path and were not re-run against this container). Model files stay in volume `vyomi-boost-ai-models`. The local `ghcr.io/ggml-org/llama.cpp:server` image is **arm64**; Codespaces are amd64 and that manifest is unverified. |

## 2. Live-server conformance on the booster
Runner: every `target:offline` suite of kind api / sdk-python / sdk / core from `tests/conformance/hourly/suites.json` (74 suites, includes all six
named files and the other `VYOMI_BASE_URL` tests), host venv with boto3 / azure-core / google libs, pointed at the booster port.

- **Before the fix** (appliance tier `free` on the booster): DynamoDB and EventBridge returned `403 tier_service_locked` (`active_tier: free`) even with a Max
  session token. After the fix: **48 / 74 pass**.
- The 26 failures were then re-run on a **non-booster baseline** of the same image (`VYOMI_BOOSTER=0`, `CLOUDLEARN_TIER_ENFORCE=0`): **24 of the 26 fail identically there**,
  i.e. they are pre-existing or host-environment issues, not booster regressions:
  `aws-kms-kem`, `aws-ops4`, `sdk-python-aws`, `cost-savings`, `request-metrics` (needs `static/aws-console.html`, not in the image), `aws-detail-tabs` (9-11 asserts),
  `gcp-pubsub-tabs-project`, `gcp-vault-console-secrets`, `aws-console-savings`, `gcp-sql-patch-monitoring`, `sdk-gcp-kms-python`, `aws/azure event-delivery`,
  `gcp-gce-ssh` (400), `aws-rds-db-connect` (`runtime_backend=simulated`), `gcp-cloudsql-db-connect`, `sweepA-aws/azure`, `gcp-memorystore-reachable` (container IP
  not routable from a Mac), `gcp-artifactregistry-reachable`, `azure-keyvault-uri`, `azure-servicebus-endpoint`, `azure-sql-fqdn`, `azure-openai` (503: the AI model server was not up).
- The 2 booster-only differences were `post-create-aws-ec2-ssh` and `post-create-azure-vm-ssh`. Cause: **capacity**. Earlier suites leave 1 GB VMs behind and the
  compute bucket only fits two; the next RunInstances gets `InsufficientInstanceCapacity`. After terminating the leftovers both probes **pass** on the booster
  (create, running, connect-info, ssh with the shown command, file write/read, delete removes the container).
- `aws-detail-tabs` timed out (124) on the booster re-run when capacity was exhausted; it ran 122 pass / 11 fail the first time (baseline 150 / 9).

### Broad native-API smoke (create -> list -> delete), booster Max
Scripts: boto3 for AWS; raw native REST (what google-cloud-* / azure-mgmt-* send) for GCP and Azure. One representative resource per registered service.

AWS (boto3): **22 / 22** after the fix: s3, dynamodb, sqs, sns, kms, secretsmanager, iam, lambda (create+invoke), events, logs, cloudwatch, ssm, kinesis, ecr,
cloudformation, apigateway, stepfunctions, ec2 (vpc+sg), rds, redshift, bedrock (list models), cost-explorer.
Registry files with no smoke row: `malware-protection`, `securityhub`, `panels` (console-only).

GCP (REST): **20 / 21**: storage, pubsub, secret-manager, kms (keyring), compute (network), networking (firewall), firestore, iam-admin (service account),
cloudsql, run, cloudscheduler, memorystore, artifacts, kubernetes, monitoring (alert policy), logs (sink), resource-manager, eventarc/cloudbuild/vertex-ai (list only) PASS.
**FAIL: functions** - `POST /v2/projects/*/locations/*/functions` is not routed natively (405 from the S3 fallback); only the v1 path and the console path
`/api/gcp/cloudfunctions/v2/...` exist, so `google-cloud-functions` (v2 client) pointed at the endpoint would fail. Registry files with no smoke row: `backupdr`, `clouddeploy`, `hub`, `securitycenter`.
Note: deleting an `autoCreateSubnetworks:true` network returns `RESOURCE_IN_USE_BY` its auto subnet (real GCP deletes it); custom-mode networks delete fine.

Azure (ARM REST): **25 / 25**: resourcegroups, storage, keyvaults, vnets, nsgs, servicebus, cosmos, sql, acr, aks, appservices, functionapp, containerapps, dns,
loganalytics, eventgrid, appconfiguration, apim, cognitiveservices, managedidentity, streamanalytics, monitor (action group), subscriptions, entra (list), plus RG cleanup.
Registry files with no smoke row: `cost`, `defender`, `defender-storage` (VMs are in section 3).

## 3. VM flow on the booster (Docker compute backend)
| Cloud | Create | Becomes a container | SSH |
|---|---|---|---|
| AWS RunInstances t3.micro (`vyomi-i-i-<id>`) | OK, `running`, public IP 203.0.113.x | yes, `vyomi/instance:ubuntu-24.04`, sshd published on a random host port | **CreateKeyPair material is a fake string** (64 hex chars in RSA PEM headers): unusable. The shared instance key from `/api/aws/ec2/instances/<id>/private-key.pem` works (login user `ubuntu`) |
| GCE instances.insert e2-micro (`vyomi-i-gce-...`) | OK, `RUNNING` | yes | key supplied in `metadata ssh-keys` is **not injected** (auth fails); shared key via `/api/gcp/compute/instances/<name>/private-key.pem` works as `ubuntu` |
| Azure VM PUT B1s (`vyomi-i-az-...`) | OK, `Succeeded` | yes | `osProfile...publicKeys` is **not injected**; shared key works as `ubuntu` but **not** as the requested `adminUsername` (`azureuser`) |

Terminate / delete removed every container and returned the compute ledger to 0 (verified with `docker ps` on the booster's own network and `/booster/status`).
Capacity honesty: the compute bucket is 2777 MB, so **only two 1 GB VMs fit at once** (3 x t3.micro = 3072 MB is rejected with `InsufficientInstanceCapacity`; a third cloud's VM got
GCP `503 ZONE_RESOURCE_POOL_EXHAUSTED` / Azure `409 AllocationFailed` with two others running). `m5.xlarge` is rejected on capacity, `r5.2xlarge` by the Max size cap (`tier_size_limit`).

### Is a Docker VM on the booster reachable from Nano web-SSH?  No, and what is missing
- Nano's VM path (`wasm/vm/nano-vm-host.js` + `vm-worker.js` + the local relay's "In-browser VM TCP bridge", ports 22000-22999) is for **in-browser v86 VMs**: a SharedWorker
  runs the VM and the relay bridges a host TCP port to it over a WebSocket. It has nothing to do with Docker containers.
- `wasm/booster-link.js` only reroutes *HTTP* compute/AI calls (`isComputeCall`: SigV4 scope, `/compute/v1/`, `Microsoft.Compute`, Vertex/OpenAI paths). `wasm/relay/booster-dial.mjs`
  speaks one frame type: `{id, method, ...}` request -> response, i.e. plain request/response. There is **no WebSocket upgrade and no raw TCP stream** across the hub/dial pair.
- The appliance's own terminal is a WebSocket (`/ws/ec2/instances/{id}/console`, `/ws/runtime-console/{id}`) and sshd is only on the Codespace's docker network/loopback (the compose
  publishes no port). So from a Nano tab nothing can reach a booster VM's sshd or terminal today. `connect-info` hands out `ssh -J <jump>` / key-download instructions meant for a laptop CLI via a Codespace port-forward, which needs GitHub port visibility the booster design avoids.
- To make web-SSH work: (1) add stream frames to the booster hub/dial protocol (`open/data/close` carrying a WebSocket or TCP stream, with the session-token and tier checks applied per stream), (2) have the Nano
  terminal (xterm) open the console WebSocket through that tunnel (or run ssh client-side over it), (3) make `connect-info` report the tunnel endpoint instead of a bastion command, and (4) honour user-supplied keys / adminUsername so the "real SDK key" path works.

## 4. Tier enforcement / capacity / TTL (live)
| Check | Result |
|---|---|
| Pro (primary=aws) -> AWS / GCP / Azure | 200 / 403 `tier_provider_locked` / 403 `tier_provider_locked` |
| Max -> all three | 200 / 200 / 200 |
| Forged `X-Vyomi-Session-Token` on a Pro booster | 401 `BoosterSessionBadSignature` |
| Over-budget compute (3 x 1 GB vs 2777 MB; m5.xlarge) | rejected with the cloud's native capacity error; reservations released, ledger back to 0 |
| TTL (Max token with 45 s left) | `/healthz` 200 before; **410 `BoosterSessionExpired` after ~6 s of polling past the end**, on ec2 and `/booster/status` too (latched on the monotonic clock) |
Unit suites in the image: `test_booster_session` 31/31, `test_booster_one_cloud` 13/13, `test_booster` 59/59, `test_booster_capacity` 42/44 (the 2 failures, "within budget not rejected" for GCP/Azure, fail identically on the unmodified code in this container).

## Bugs found
1. **FIXED - the booster ran as Free tier.** `VYOMI_LICENSE_JWT` is passed by the compose file but read by nothing, and `boot-booster.sh` never supplies a licence, so on a real booster
   `tier_policy` treated every request as Free: Max-only services (DynamoDB, EventBridge, ...) 403'd with a valid Max session, `/healthz` said `free`, and with `VYOMI_BOOSTER` unset
   booster mode (headless guard, capacity ledger) stayed off. Fix: `core/booster_session.py` mirrors the verified session tier into the licence state on every authorised request
   (`_apply_tier`) and exposes `effective_tier()`; `core/app_context.active_tier()` and `/healthz` use it. Test: `tests/conformance/test_booster_session_tier.py` (6/6); `test_booster_session` adjusted for the now-real Pro state.
2. **OPEN, small** - user-supplied SSH keys are ignored by the Docker backend on all three clouds (see section 3); CreateKeyPair returns a non-key.
3. **OPEN, medium** - GCP Cloud Functions v2 native path (`/v2/projects/*/locations/*/functions`) is unrouted.
4. **OPEN, medium** - the compute ledger is in-memory only: after a simulator restart it reads 0 while instance containers keep running, so the cap can be exceeded. Also saw a
   1024 MB phantom reservation with no instance/container after the conformance suites (cleared by a restart); not root-caused, suspect a create path that errors after `rebind`.
5. **OPEN, note** - `resource_budget()` ignores the `--cpus 2` quota (reads host CPU count) and `docker-compose.booster.yml` does not set `VYOMI_BOOSTER_CAP_MB` / `VYOMI_BOOSTER_CPUS`; on a real
   8 GB Codespace the 70% rule gives compute 2.7 GB (two 1 GB VMs), which is a product-level limit to confirm.

## Still needs a real Codespace
Real `basicLinux32gb` boot via the GitHub App and `boot-booster.sh` fetching a portal token; the outbound `link` service and a wss relay; Nano `booster-link.js` routing against real console traffic;
the 3B model on 2 amd64 cores (load RSS, tok/s, 5-minute download in-region) with nothing else on the VM; idle-stop / 8 h TTL via the portal worker; llama.cpp amd64 manifest; real-network SSH
(port-forward / `ssh -J`) to the Docker VMs.
