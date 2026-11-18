# v4/gcp-ref-realbackend: real Pub/Sub + Firestore emulators as the data plane, gRPC story for Logging/Monitoring

Lane 4 of the GCP 13/13 reference-architecture build (probe: `docs/architecture/v4.0/REF-ARCH-PROBE-GCP.md`, items 2, 5, 5b, 8).
Offline / Mesh only. Nano keeps the in-browser cores; the default (flag off) behaviour is unchanged.

## Changes

| File | What |
|---|---|
| `core/gcp_real_backends.py` (new, appliance only, not in the Nano CORES lists) | `VYOMI_GCP_REAL_BACKENDS=1` + `PUBSUB_EMULATOR_HOST` / `FIRESTORE_EMULATOR_HOST` (or the `CLOUDLEARN_*` twins) replaces `gcp_pubsub_core.dispatch` and `gcp_firestore_core.dispatch` with wrappers that forward to the real emulators' REST endpoints. Installed from `server.py` and `wire_ingress.appliance_router()` (idempotent, no-op when off or on emscripten). |
| `core/gcp_grpc_front.py` (new, appliance only) | Optional gRPC front door (`VYOMI_GCP_GRPC_PORT`, optional TLS via `VYOMI_GCP_GRPC_TLS_CERT/KEY`): turns the gRPC calls of REST-less Google clients into REST calls on the simulator's own front door. Table-driven (17 RPCs: Monitoring Metric + AlertPolicy, Logging write/list/delete/list-logs). |
| `server.py`, `core/wire_ingress.py` | Four lines each to install the above. |
| `docker-compose.appliance.yml`, `docker-compose.yml`, `codespace/.devcontainer/mesh/docker-compose.mesh.yml` | Env passthrough; Mesh gets a `gcp-real` profile with the two emulators (loopback-bound 8085 / 8080) and `expose: 50051`. The offline appliance compose already ran and published the emulators. |
| `core/capabilities/backends/gcp.json` | pubsub / firestore offline notes + `differs`; logs / monitoring note the gRPC front door. |
| `tests/conformance/test_gcp_real_backends.py`, `test_gcp_grpc_front.py` | Regression tests (SDK based, see below). |

## How the mode works

One seam: every simulator feature that touches Pub/Sub or Firestore already calls `gcp_pubsub_core.dispatch(store, ...)` /
`gcp_firestore_core.dispatch(...)` (wire front door, console classic routes, Eventarc, Cloud Run triggers, Cloud Scheduler,
SCC notifications, log sinks, Secret Manager notifications, Eventarc dead-letter). The wrappers sit on those two functions, so
the cores are untouched (Nano) and nothing else needed rewiring.

* **(a) gRPC clients**: the emulator holds all state, so `PUBSUB_EMULATOR_HOST` / `FIRESTORE_EMULATOR_HOST` pointing at the
  emulator ports gives unmodified `pubsub_v1` / `firestore.Client`.
* **(b) REST / console see the same data**: topics, subscriptions, snapshots, publish/pull/ack/seek/modifyAckDeadline and every
  `(default)`-database document call (CRUD, `:commit`, `:runQuery`, `:batchGet`, `:beginTransaction`, `:listCollectionIds`) are
  proxied. A metadata-only shadow of topics/subscriptions is kept in the core's store for simulator features that read the store
  directly (Eventarc topic checks, the Eventarc-owned subscription flag); `AppStatePubsubStore.get_topic` imports a topic a gRPC
  client created on first miss. Hidden `vyomi-tap-*` subscriptions are filtered out of every list.
* **(c) simulator consumers**: callers pass their `on_publish` hook as before; the wrapper calls it after a successful emulator
  publish, so Cloud Run Eventarc triggers, the Eventarc core, Scheduler pubsubTarget, SCC and sink publishes keep working. For
  messages published by a gRPC client, a 0.5 s poller owns one hidden subscription per trigger topic and delivers them through the
  same hook, de-duplicated against REST publishes by message id. Firestore document events (Eventarc document triggers) fire for
  REST writes (old/new document read around the write).
* An unreachable emulator returns 503 UNAVAILABLE naming the emulator; there is no silent fallback to the core.

### What does NOT work in this mode (said exactly)

* Pub/Sub schemas, IAM policies stay on the simulator core (the emulator lacks them); message transforms and schema validation on
  publish do not run; the console message peek and the Pub/Sub metrics mirrored into Monitoring no longer see messages.
* Firestore: only the `(default)` database data plane is proxied. Admin plane, other databases, Datastore mode, Vyomi's
  security-rules enforcement, TTL and index enforcement are the core's and do not apply to emulator-held documents (the emulator
  accepts queries with no index).
* Eventarc Firestore triggers do **not** fire for writes a gRPC client makes directly (the emulator has no change stream).
  gRPC-published Pub/Sub messages reach triggers within about 1 s (poller), a trigger created less than 0.5 s before the publish
  may miss it.
* No persistence guarantee beyond the emulator container's (the appliance compose mounts volumes; Mesh does not).
* Tier gating is untouched: Firestore is Max-tier on a licensed appliance.

## Decision memo: Logging and Monitoring (gRPC-only Python gapic clients)

| Option | Verdict |
|---|---|
| `logging.Client(_use_grpc=False)` REST mode | Supported by the library, zero own code, works today (write + `list_entries`; list needs lane 2's timestamp-filter fix). Not the default constructor, so unmodified-default is not met. **Used for the app's Logging when the app prefers no extra port.** |
| `monitoring_v3` REST transport | **Does not exist** (checked `google-cloud-monitoring` 2.32.0: transports are `grpc`, `grpc_asyncio` only; the probe's `KeyError: 'rest'`). Not an option. |
| Small gRPC front door (grpcio server -> existing REST cores) | **Chosen.** ~190 lines, table-driven, adapter only (no data store, no engine invented), covers both libraries with their DEFAULT constructors. About 0.5 d, not the 2.5 d the probe estimated for emulator-based gRPC, because it is a protocol adapter over cores that already exist. |
| Document REST only | Fails the "unmodified clients" bar for Monitoring. Rejected. |

Why own code is justified: no open-source Cloud Logging / Cloud Monitoring emulator exists; the cores are already the
implementation, only the transport was missing. The adapter keeps one implementation (REST core) and one state.

Connecting (no emulator env var exists for these two libraries, so the endpoint is passed; TLS keeps the default constructors):
`VYOMI_GCP_GRPC_PORT=50051 VYOMI_GCP_GRPC_TLS_CERT=... VYOMI_GCP_GRPC_TLS_KEY=...` on the simulator, then on the client
`GRPC_DEFAULT_SSL_ROOTS_FILE_PATH=<cert>` and `client_options={"api_endpoint": "localhost:50051"}` plus `AnonymousCredentials()`.
Without TLS vars the port is plaintext and the client needs `transport=...GrpcTransport(channel=grpc.insecure_channel(...))`.

## Proven (observed runs, macOS arm64, Python 3.13, google-cloud-pubsub 2.44.0, firestore 2.34.1, logging 3.17.0, monitoring 2.32.0)

`tests/conformance/test_gcp_real_backends.py` (starts the local emulator image on free ports, removes only its own named containers;
SKIPs without docker / image / SDKs): ALL PASS, 22 checks: gRPC publish->pull->ack, Firestore transaction / query / batch,
simulator REST transport of both SDKs sees the gRPC-written data, a topic and a document created through the simulator are
visible to the gRPC clients, REST `runQuery`, Firestore document events on REST writes, core-seam publish reaches the emulator and
fires `on_publish`, shadow import of gRPC-created topics, Cloud Run trigger fires for REST publish and for gRPC publish (once),
tap subscription hidden, schemas still served by the core, 503 when the emulator is down, flag-off falls back to the core.

`tests/conformance/test_gcp_grpc_front.py`: Monitoring over gRPC (descriptor create/list, time series write/read, NOT_FOUND mapping,
alert policy CRUD) and default `logging.Client` over gRPC (write; read via gapic) PASS. `logging.Client.list_entries` (REST and gRPC)
is reported BLOCKED on this branch alone (the default `timestamp>=` filter: lane 2) and was run PASS on a scratch merge with
`origin/v4/gcp-ref-corefix` (all 8 checks).

## Design decisions

* Wrap the two dispatch functions rather than editing the cores: one seam, Nano untouched, other lanes do not conflict.
* Shadow metadata + `on_publish` pass-through instead of rewriting Eventarc / scheduler / SCC.
* Poller instead of modifying the emulator: the emulator has no push hooks; one hidden subscription per trigger topic.
* Pub/Sub emulator wire: REST is served on the same port as gRPC; Firestore REST likewise; both used as the proxy target.

## Open issues

* Mesh: the simulator's `expose` and the emulators' loopback ports need the ssh forward the tunnel uses for :9000; not exercised
  against a real Codespace (no Codespace was used; docker compose only syntax-checked).
* Eventarc Firestore triggers for direct gRPC writes are not possible without a change feed.
* `test_backends_registry.py` fails on azure (`aisearch`, `foundry` missing in azure.json): pre-existing, not this branch.
* Capability-registry claims (`core/capabilities/gcp/*.json`) were not extended: that harness probes the Nano in-process router,
  which by design does not run this mode.
