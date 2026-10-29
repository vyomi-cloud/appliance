# vyomi-libs: shared cloud engines as separately released images

**Status:** proposal for review, 2026-10-29
**Decision asked for:** split the shared cloud engines out of the appliance into `vyomi-<lib>` packages. Each one ships
as its own Docker image, the way `vyomi/cloudsim` and `vyomi/minio` already do, so separate teams can build and
release them on their own schedule.

## 1. Why

- **Real backends everywhere.** Each lib owns one capability across all three clouds (logs, metrics, workflows, IaC,
  identity, messaging…) and makes the resource really work.
- **Team ownership.** Today every engine lives in `core/` of one repo and ships only with an appliance release. A lib
  has its own owners, tests, version and release.
- **One engine, three clouds.** A lib implements the capability once and adds a thin front end per cloud API, for
  example CloudWatch Logs, Cloud Logging and Log Analytics on one log store.
- **Precedent.** `cloudsim` is built from `cloudsim-backbone/` in this repo and published as `vyomi/cloudsim`, tagged
  like the appliance. MinIO is mirrored from source as `vyomi/minio`. The libs follow the same pattern.

## 2. What a vyomi-lib is

One Python package, three ways to run it:

| Deliverable | What | Used by |
|---|---|---|
| **Core wheel** `vyomi_<lib>` | Pure Python, substrate-free: no fastapi, sockets or subprocess in the core (today's `core/` rule). Holds the engine, the per-cloud API front ends and the store seam. | Nano (loaded into Pyodide), embedded mode, the service image |
| **Service image** `vyomi/<lib>:<version>` | The core plus a thin ASGI server. Where the lib drives an open-source backend (Caddy, NATS, VictoriaMetrics…), it also contains that **controller**. Multi-arch (amd64 + arm64), pinned, healthcheck. | The appliance (Docker), Codespaces sandboxes, enterprise installs |
| **Embedded mode** | The appliance imports the core wheel in-process instead of calling the image. | Low-RAM tiers (see §7), development, CI fallback |

The same code runs in all three. A conformance test that passes against one passes against the others.

## 3. Lib catalog

| Lib | Cloud services | Real backend it drives | Nano |
|---|---|---|---|
| **vyomi-iam** | Shared IAM enforcement (#172–#175), AWS STS, GCP IAM Credentials, Azure managed-identity tokens | in-process (token signer, policy evaluators) | ✅ |
| **vyomi-identity** | Cognito user pools + identity pools, GCP Identity Platform, Entra External ID / B2C | in-process OAuth2/OIDC server; Keycloak optional (Max, SAML federation tests) | ✅ |
| **vyomi-workflow** | Step Functions, GCP Workflows, Logic Apps | in-process durable engine; Temporal on Pro+ | ✅ (in-process) |
| **vyomi-iac** | CloudFormation + Cloud Control, ARM/Bicep deployments, Deployment Manager; GCP Infrastructure Manager | in-process template engine; OpenTofu for Infrastructure Manager | ✅ (in-process) |
| **vyomi-logs** | CloudWatch Logs, Cloud Logging, Log Analytics, Application Insights | in-process DuckDB log store; Fluent Bit agent; VictoriaLogs optional | ✅ |
| **vyomi-metrics** | CloudWatch metrics + alarms, Cloud Monitoring, Azure Monitor, managed Prometheus | VictoriaMetrics + vmalert | in-process subset |
| **vyomi-messaging** | SNS, EventBridge, Cloud Tasks, Kinesis, Event Hubs, Cloud Scheduler, plus the shared dispatcher (timers, HTTP delivery) | NATS JetStream | in-process subset |
| **vyomi-gateway** | API Gateway v1/v2, ELB/ALB, GCP API Gateway, API Management, Front Door | Caddy (admin API) | control plane |
| **vyomi-containers** | Cloud Run, Container Apps, App Runner, ECS | Docker compute + vyomi-gateway; Knative optional (Max) | control plane |
| **vyomi-kubernetes** | GKE, AKS, EKS | k3s | control plane |
| **vyomi-mail** | SES (v1 receipt rules + v2), alert email | Mailpit; optional user SMTP relay and IMAP inbound | control plane |
| **vyomi-dns** | Route 53, Cloud DNS, Azure DNS | CoreDNS | control plane |
| **vyomi-cache** | ElastiCache, Memorystore, Azure Cache for Redis | Valkey per instance | control plane |
| **vyomi-registry** | ECR, Artifact Registry, ACR | CNCF Distribution (registry:2) | control plane |
| **vyomi-ai** | Bedrock, Vertex AI, Azure AI services | Ollama (decision pending) | control plane |
| *(existing)* **vyomi-cloudsim**, **vyomi-minio** | unchanged | — | — |

Services that are plain data stores with no cross-cloud twin (SSM Parameter Store, App Configuration, Secrets…) stay
in the appliance's `core/` until a team wants them.

"Control plane" in the Nano column means the browser keeps the management API but not the backend. It can't run
Caddy, NATS or k3s.

## 4. The lib contract (v1)

Every lib implements the same contract, so the appliance treats them all alike and a lib can be swapped or upgraded on
its own.

1. **Wire dispatch.** `dispatch(store, method, path, query, headers, body) -> Response` per cloud front end. This is
   exactly the shape the `core/` engines use today, so existing engines move with little change. The service image
   exposes it over HTTP. The appliance's router (`core/aws_wire_router.py`) forwards a matched request unchanged.
2. **Request context headers**, set by the appliance and trusted only on the internal network (`vyomi-net`):
   - `X-Vyomi-Space`: the space; all state is space-scoped.
   - `X-Vyomi-Principal`: the caller as authenticated and authorized by vyomi-iam at the front door.
   - `X-Vyomi-Request-Id`: for tracing.
   - `X-Vyomi-Tier`.
3. **State ownership.** Each lib owns its storage in its own volume (SQLite/DuckDB files, or its backend's data), plus
   a `export(space)` / `import(space)` pair for backup, space clone and Nano sync. No lib reads another's storage.
4. **Cross-service calls go through the front door.** When SNS delivers to Lambda, or a workflow calls an HTTP API, the
   lib calls the appliance's public wire endpoint as a real client would, signed as the resource's role. That way IAM,
   metrics and logs apply to internal calls too, and libs never import each other.
5. **Events out.** Resource created/changed/deleted events, for the console activity log, CloudSim and the cost meter,
   published to NATS subject `vyomi.events.<lib>.<cloud>.<service>`, one schema for all libs.
6. **Ops endpoints:**
   - `/healthz` and `/readyz` (the dashboard readiness strip),
   - `/metrics` (Prometheus, scraped into vyomi-metrics),
   - `/version` (lib version + contract version + backend versions).
7. **Contract version.** `contract: 1` in `/version`. The appliance refuses a lib with an incompatible contract and
   says so on the dashboard.
8. **Contract tests.** A shared suite every lib must pass (context headers, space isolation, export/import round trip,
   events schema, health endpoints), plus the lib's own per-cloud SDK/CLI conformance tests.

## 5. Repository and release

**Start in the monorepo, so a later split needs no interface change:**

```
libs/
  vyomi-logs/
    pyproject.toml          # version, deps (core must stay Pyodide-safe)
    src/vyomi_logs/core/    # engine + per-cloud front ends (no fastapi/sockets)
    src/vyomi_logs/server/  # ASGI app, controller for any OSS backend
    Dockerfile              # multi-arch, pinned base, non-root, healthcheck
    tests/                  # contract tests + SDK/CLI conformance (Java, Go, Python, CLI)
    CHANGELOG.md
    CODEOWNERS entry        # the owning team
```

**Each lib releases independently:**
- Tag `vyomi-logs/v1.4.0` → its own workflow runs its tests and publishes:
  - `vyomi/logs:1.4.0` + GHCR (multi-arch),
  - the core wheel as a GitHub Release asset.
- Semver: patch = fixes; minor = new operations or services; major = contract change.
- Each lib's own CI runs only its tests on changes under `libs/<lib>/`.

**The appliance pins lib versions** in `libs.lock.json` (lib → image version + wheel version + sha256):
- `release.yml` pins the images in the compose files, as it does today for `vyomi/appliance`.
- The Nano build vendors the pinned wheels.
- The portal Nano sync carries them.
- Bumping a lib is a one-line PR to `libs.lock.json`, which runs the full appliance conformance before merge.
- The release notes list lib versions.

**Splitting out later:** a lib moves to `vyomi-cloud/vyomi-<lib>` with its history (`git filter-repo`). Nothing
changes for the appliance: it still pins an image and a wheel.

## 6. Runtime in the appliance

- Each lib is a compose service under profile `full`, pinned, with a memory limit and healthcheck.
- **Libs start on demand** through `core/backend_provisioner.py`, when the first request for one of their services
  arrives or the first resource is created. They stop with the stack.
- The router maps each cloud service to its lib, from `services/registry.json` + `libs.lock.json`. A lib that isn't
  running yet gets started; the request waits up to a timeout, and the console shows "starting".
- **Dashboard:** replaces "all 12 services running" with:
  - **Cloud services**: each service with its lib, version and live state ("GKE: vyomi-kubernetes 1.0.2, 1 cluster
    running").
  - **Libs and backends**: each with version and health.

## 7. Footprint

A Python service container idles at roughly 40–60 MB. Fifteen always-on libs would be 600–900 MB, far over the Free
(64 MB) and Lite (128 MB) budgets. Three measures keep it in budget:

1. **On demand:** only libs whose services you use run.
2. **Shared slim base image** (python-slim + common deps), so images share layers on disk.
3. **Embedded mode on Free/Lite:** the appliance loads the same core wheels in-process. Pro and up run the images.
   Behaviour is identical, because it's the same code and the contract tests run in both modes.

The OSS backends a lib drives (k3s, VictoriaMetrics, Temporal…) keep their own tier rules in `backends.json`.

## 8. Pipeline and gate

- `backends.json` gains a `lib` per shared backend. The pipeline page shows "Lib" next to "Real backend".
- A new service lands **in its lib** (`libs/<lib>/`), not in `core/`.
- The gate runs the lib's contract tests, its SDK/CLI suites in **both modes** (image and embedded), and the existing
  real-backend checks.
- The hourly conformance run tests the appliance with the pinned libs. Each lib's own CI tests the lib at HEAD.

## 9. Migration plan

| Phase | Work | Exit criterion |
|---|---|---|
| 0 | Contract v1, `libs/` scaffold, shared base image, lib release workflow, `libs.lock.json`, router + provisioner support, dashboard lists libs | A "hello" lib released, pinned and started on demand |
| 1 | **vyomi-workflow** first: move `core/stepfunctions_core.py` (already real) into the lib unchanged, then add GCP Workflows | Step Functions suites pass in image and embedded mode; Nano unchanged |
| 2 | **vyomi-logs** (from `core/logs_core.py`) and **vyomi-messaging** (NATS delivery for SNS, EventBridge, Cloud Tasks, Scheduler; fixes #147–#149, #171) | Real delivery tests pass |
| 3 | **vyomi-iam** (#172–#175), then **vyomi-identity** | Fake key rejected; least-privilege tests pass |
| 4 | **vyomi-gateway**, **vyomi-dns**, **vyomi-cache**, **vyomi-mail**, **vyomi-registry** | The 14 released services' "Wired today" all real or explained |
| 5 | **vyomi-metrics**, **vyomi-iac**, **vyomi-containers**, **vyomi-kubernetes**, **vyomi-ai** | Depends on tier decisions |
| — | The 26 open service PRs are rebuilt into their libs as each lib lands | Gate passes with the real backend |

Until a lib passes the same conformance as the code it replaces, the appliance keeps the in-process engine as the
fallback, so no release regresses.

## 10. Open decisions

1. **Embedded mode on Free/Lite** (§7), or images on every tier with a higher Free budget.
2. **Tiers for heavy backends:** k3s (GKE/AKS/EKS, Knative), Temporal, Ollama, VictoriaLogs.
3. **Azure AI services backend:** Ollama with a small model, a mock, or bring-your-own key.
4. **Monorepo first then split** (proposed), or separate repos from day one.
5. **Lib names:** `vyomi/<lib>` image names (`vyomi/logs`) vs. `vyomi/vyomi-logs`.
