# Vyomi — Complete Cross-Cloud Parity Gaps

A full, grounded audit of what Vyomi supports across **AWS · GCP · Azure**, along five
dimensions: (1) service coverage, (2) conformance depth, (3) operation-level gaps,
(4) **backing-tech ("cheap tech") integration**, (5) substrate parity (Nano/Pro/Max).

Generated 2026-07-13 from the catalogs, cores (`core/*_core.py`), conformance tests,
`aws_wire_router`, `wire_ingress`, and the running backend containers.

---

## 1. Service equivalence map — 3-cloud coverage

| Capability | AWS | GCP | Azure | Symmetric? |
|---|---|---|---|---|
| Object storage | S3 ✅ | Cloud Storage ✅ | Blob ✅ | ✅ all three |
| Relational SQL | RDS ✅ | Cloud SQL ◑ (control only) | SQL ⚠️ (ARM control only) | ⚠️ data plane uneven |
| NoSQL / document | DynamoDB ✅ | Firestore ✅ | Cosmos DB ✅ | ✅ all three |
| Key management | KMS ✅ | Cloud KMS ✅ | Key Vault keys ✅ | ✅ all three |
| Secrets | Secrets Manager ✅ | Secret Manager ✅ | Key Vault secrets ✅ | ✅ all three |
| Queue | SQS ✅ | Pub/Sub ✅ | Storage Queue ✅ | ✅ all three |
| Pub/sub topics | SNS ✅ | Pub/Sub ✅ (shared) | ❌ (Service Bus/Event Grid catalog-only) | ⚠️ Azure gap |
| Event bus | EventBridge ❌ | Eventarc ❌ | Event Grid ❌ | ❌ none (catalog-only) |
| Identity / policy | IAM ✅ | Cloud IAM ✅ | RBAC / role_definition ⚠️ (ARM only) | ⚠️ Azure = ARM generic |
| Compute | EC2 ◑ (Docker) | Compute ◑ (Docker) | VM ⚠️ (ARM metadata, no runtime) | ⚠️ Azure has no compute runtime |
| Serverless | Lambda ❌ | Functions ❌ | Function App ❌ | ❌ none (no runtime) |
| API gateway | API Gateway ❌ | API Gateway ❌ | APIM ❌ | ❌ none (catalog-only) |
| Networking | VPC ❌ | VPC ❌ | VNet / NSG ❌ | ❌ none (catalog-only) |

Legend: ✅ real conformance core · ◑ partial (control-plane / one-plane only) ·
⚠️ generic/metadata-only · ❌ catalog entry with no data plane.

**Cross-cloud symmetry gaps:**
- **Azure has no first-class pub/sub topic core** (SNS/Pub-Sub equivalents) — Service Bus / Event Grid are catalog-only.
- **Azure identity is ARM-generic** (`role_definition`/`rbac` via the generic ARM handler), not a dedicated policy-decision core like AWS IAM / GCP IAM.
- **Relational data plane is uneven:** RDS + Cloud SQL run real SQL (Postgres/PGlite); **Azure SQL has no data plane** (TDS is non-HTTP, only ARM control plane exists).
- **Compute is AWS/GCP-only** (Docker/LXD); Azure VM is ARM metadata with no runtime.
- **Serverless, API gateway, networking, event bus** have **no data plane on any cloud** — catalog/ARM resources only.

---

## 2. Conformance depth tiers

| Tier | Meaning |
|---|---|
| **T1** | **Native vendor SDK proven** end-to-end (unmodified boto3 / google-cloud-* / azure-* round-trips). |
| **T2** | **Conformance core** (substrate-free, host + Pyodide green) but native SDK **not** proven, or SDK-transport-limited (gRPC/local-crypto). |
| **T3** | **Control-plane / ARM / catalog only** — create/list/delete a resource; no data-plane SDK conformance. |
| **T4** | **Catalog stub** — appears in the console list, no real behavior. |

### Depth by service (with conformance-test check counts)

| Service | AWS | GCP | Azure |
|---|---|---|---|
| Object storage | **T1** S3 (34) | **T1** GCS (30) | **T1** Blob (37) |
| NoSQL | **T2** DynamoDB (46) | **T2** Firestore (34, gRPC-ltd) | **T1** Cosmos (44) |
| KMS/keys | **T1** KMS (37) | **T1** Cloud KMS (27) | **T2** KV keys (30, local-crypto) |
| Secrets | **T2** Secrets Mgr (33) | **T1** Secret Mgr (24) | **T1** KV secrets (31) |
| Queue | **T1** SQS (32*) | **T1** Pub/Sub (29) | **T1** Queue (41) |
| Pub/sub topics | **T1** SNS (32*) | (Pub/Sub) | ❌ |
| Identity | **T1** IAM (29) | **T1** Cloud IAM (30) | **T3** ARM RBAC (35*) |
| Relational | **T1** RDS (30) + Data API (14) | **T3** Cloud SQL control (29) | **T3** SQL (ARM only) |
| Compute / serverless / apigw / net / eventbus | **T3/T4** | **T3/T4** | **T3/T4** |

\* SQS+SNS share `test_messaging_core.py` (32); Azure ARM is `test_azure_arm_core.py` (35).
T1 sources: AWS relay E2E (boto3/CLI unchanged); GCS/GCP-KMS/SecretMgr/IAM/CloudSQL and
Azure Blob/Queue/Cosmos/KV-secrets proven against their real SDKs this cycle.
**T2 reasons:** Firestore + Pub/Sub Python clients are **gRPC** (can't cross the HTTP relay;
REST wire is conformant); Azure **KV keys** — `CryptographyClient` does RSA locally, so the
service-side path isn't exercised by the SDK; DynamoDB/Secrets(AWS)/SNS proven vs boto3 in
the relay E2E but not re-swept this cycle → conservatively T2.

---

## 3. Operation-level gaps (the "go deeper")

### AWS
- **S3** — has: Put/Get(+Range)/Head/Delete/ListV2, bucket CRUD. **Missing:** CopyObject,
  **multipart upload**, object tagging, ACL, versioned-object tagging. *(marked "v1 slice")*
- **DynamoDB** — has: table CRUD, Put/Get/Delete/Update(SET), Query(=,begins_with,BETWEEN),
  Scan, Batch{Get,Write}, tags. **Missing:** Streams, **TransactWrite/Get**, GSI/LSI mutations
  (UpdateTable), FilterExpression, ProjectionExpression. *(regex-based KeyCondition parsing)*
- **KMS** — has: CreateKey/Describe/List/Encrypt/Decrypt/GenerateDataKey(+WithoutPlaintext)/
  GenerateRandom/Enable/Disable/ScheduleKeyDeletion/aliases. **Missing:** grants, key policy,
  **key rotation**, TagResource, CancelKeyDeletion, alias update/delete.
- **Secrets Manager** — has: Create/Get/Put/Update/Describe/List/ListVersionIds/Delete/Restore.
  **Missing:** **RotateSecret**, replication, resource policy, tags, BatchGetSecretValue.
- **SQS** — has: queue CRUD, attrs, Send/Receive/Delete, ChangeVisibility, Purge. **Missing:**
  **batch ops**, tags, **FIFO**, **dead-letter** config.
- **SNS** — has: topic CRUD, Subscribe/Unsubscribe, Publish (real SQS fan-out). **Missing:**
  topic attributes, **filter policies**, HTTP/email/Lambda delivery, PublishBatch, raw delivery.
- **IAM** — has: users/roles/policies/groups CRUD, attach/detach, inline policy, access keys,
  **SimulatePrincipalPolicy** (real eval). **Missing:** Update{User,Role}, group membership
  removal, role inline-policy read, login profiles, account summary.
- **RDS** — has: instance lifecycle + snapshots (Query/XML). **Missing:** **clusters/Aurora**,
  restore-from-snapshot, read replicas, parameter/subnet groups, tags.
- **RDS Data API** — has: Execute/BatchExecute/Begin/Commit/Rollback. **Missing:** **real
  transaction isolation** (all statements autocommit — documented boundary).

### GCP
- **Cloud Storage** — has: bucket CRUD, object media+multipart upload, get/download/list/delete.
  **Missing:** **resumable upload**, object PATCH, compose, ACL/IAM, signed URLs, lifecycle.
- **Firestore** — has: doc create(+auto-id)/get/patch(merge)/delete/list, runQuery (single
  **EQUAL** filter). **Missing:** **transactions**, batch, complex filters (>,<,IN,
  array-contains), orderBy/limit, composite indexes, listener streams.
- **Cloud KMS** — has: keyRings/cryptoKeys/versions, encrypt/decrypt. **Missing:** IAM, **rotation
  schedule**, **asymmetric keys**, version-state lifecycle, update ops.
- **Secret Manager** — has: create/addVersion/access(latest)/list/versions/delete/destroy/
  disable/enable. **Missing:** IAM, replication config, **rotation**, updateSecret, labels.
- **Pub/Sub** — has: topics/subs CRUD, publish (fan-out), pull, acknowledge. **Missing:**
  **push subscriptions**, modifyAckDeadline/redelivery, seek, ordering keys, dead-letter,
  filters, schemas, snapshots.
- **Cloud IAM** — has: service accounts CRUD, get/set IamPolicy, **testIamPermissions** (real
  binding eval). **Missing:** SA **keys**, enable/disable/undelete SA, **custom roles**,
  conditions, org/folder hierarchy.
- **Cloud SQL** — has: instances + databases (control plane). **Missing:** **users**, **backups**,
  data plane in-core (runs via shared SqlStore), flags, replication, failover, PITR, export/import.

### Azure
- **Blob** — has: container CRUD, block-blob put/get/HEAD/delete, list(+prefix), **range GET**,
  metadata. **Missing:** **append/page blobs**, **block staging/blocklist**, SAS, copy, snapshot,
  lease.
- **Cosmos DB** — has: db/collection/document CRUD, upsert, query (=,!=,>,<,>=,<=), account
  discovery. **Missing:** stored procs/triggers/UDFs, **ORDER BY / aggregates / DISTINCT**,
  continuation tokens, RU/throughput, change feed, TTL, cross-partition.
- **Key Vault secrets** — has: set/get(+version)/list/versions/soft-delete, auth challenge,
  tags. **Missing:** recover/purge, backup/restore, **rotation**, HSM, RBAC.
- **Key Vault keys** — has: create(RSA)/get/list/encrypt/decrypt, soft-delete, base64url.
  **Missing:** **EC/AES keys**, **sign/verify**, **wrap/unwrap**, import, rotate. *(RSA public
  numbers cosmetic; crypto via envelope engine — see T2 note)*
- **Storage Queue** — has: queue CRUD, put/get/peek/delete msg, visibility, pop-receipt, clear,
  approx-count. **Missing:** **update message**, queue metadata set, lease, SAS.
- **ARM control plane** — has: RG CRUD, **generic resource CRUD** for any `Microsoft.X/{type}`,
  LRO polling, action verbs (start/stop/listKeys/…), PATCH tags. **Missing:** template deploy,
  policy/RBAC assignment, managed identities, locks, metrics, **real provisioning lifecycle**
  (LRO always Succeeded), quota, schema validation.

---

## 4. Backing-tech ("cheap tech") integration — the real gaps

Running backends: **MinIO · fake-gcs-server · Azurite · Postgres · Vault · NATS-JetStream**.

| Service group | Ideal cheap backend | Wired in **unified** (v2.4.0)? | In **drifted** default path? | Gap |
|---|---|---|---|---|
| S3 / GCS object | MinIO (or fake-gcs) | ✅ MinIO | ✅ MinIO | — |
| RDS / Cloud SQL data | Postgres / PGlite | ✅ Postgres | ✅ Postgres/PGlite | — |
| KMS / Cloud KMS / KV keys | Vault Transit | ✅ Vault | (Vault) | — |
| SQS / SNS / Pub/Sub | NATS JetStream | ✅ NATS | (NATS) | — |
| **Secrets (all 3)** | **Vault KV** | ❌ **in-memory KvStore** | (partial) | **Vault KV not wired for secrets — only KMS keys got Vault** |
| **DynamoDB** | **DynamoDB-Local** | ❌ **in-memory** | ❌ in-memory | **no real NoSQL backend wired** (nosql_store references DynamoDB-Local but isn't backed) |
| **Firestore** | **Firestore emulator** | ❌ **in-memory** | ✅ **firestore_emulator** | **unified path REGRESSED** — the real emulator only runs in the drifted path |
| **Azure Cosmos** | (no light emulator; Postgres-compat?) | ❌ **in-memory** | ❌ in-memory | **no real backend** (heavy emulator rejected; azure_cosmos_core stays in-memory) |
| **Azure Blob (unified)** | **Azurite** | ❌ **in-memory** | ✅ **Azurite** | **unified path REGRESSED** — bespoke `AzureBlobStore` seam can't ride the backed store (seam-unification gap) |
| **Azure Queue (unified)** | **Azurite queue / NATS** | ❌ **in-memory** | (Azurite) | same seam issue as Blob |
| **Azure SQL data plane** | Postgres (compat) | ❌ | ❌ | **TDS non-HTTP** — only ARM control plane exists |
| IAM / Cloud IAM | (in-proc, no ext backend) | in-proc + persist-gate | in-proc | durable backend not wired (only the sqlite anti-drift gate proves persistence) |
| Compute (EC2/GCE) | Docker / LXD | Docker | Docker | Azure VM has **no** runtime backend |
| Serverless / API-gw / VPC / event-bus | (none) | ❌ | ❌ | **no data-plane backing on any cloud** |

### The two headline backing-tech findings
1. **Secrets + NoSQL have no real backend wired** in the unified path — Vault KV isn't used for
   Secrets Manager / GCP Secret Manager / Azure KV secrets (only KMS keys got Vault Transit),
   and DynamoDB/Firestore/Cosmos run in-memory (DynamoDB-Local / emulators not integrated).
2. **The unified v2.4.0 path regressed three services vs. the current default (drifted) path:**
   **Firestore** (was `firestore_emulator` → now in-memory), **Pub/Sub** (was `pubsub_emulator` →
   now NATS-KV state), and **Azure Blob/Queue** (were **Azurite** → now in-memory, blocked by the
   bespoke `AzureBlobStore` seam). Azurite is **running but unwired** in the unified path; the
   Firestore/Pub-Sub emulators exist only behind the old handlers.

---

## 5. Substrate parity (Nano vs Pro/Max)

| | **Nano** (browser/WASM) | **Pro/Max** (real backends) |
|---|---|---|
| Object / NoSQL / KMS / Secrets / Queue / IAM cores | ✅ in-WASM (in-memory / PGlite / stdlib crypto) | ✅ same cores, real backends behind the seam (opt-in ingress) |
| Firestore / Pub-Sub **gRPC SDK** | ❌ (gRPC can't cross HTTP relay; REST-only) | ✅ real Google emulators (drifted path) |
| Azure KV keys **real crypto** | ❌ (envelope engine) | ✅ Vault Transit |
| Relational data plane | PGlite (real Postgres-in-WASM) | Postgres |
| Compute / serverless | ❌ (no in-browser runtime) | Docker/LXD (compute); serverless ❌ |

---

## 6. Prioritized gap backlog

**P0 — unified-path regressions (close before promoting the switchover):**
1. ✅ **[CLOSED v2.5.0]** Azure Blob/Queue durable — `PersistentAzureBlobStore` +
   `PersistentAzureQueueStore` (file-backed substrate) wired in `wire_ingress`; durable across a
   fresh router. (Chose the persist-hook path over the full seam refactor — MinIO/Azurite
   byte-backing is a further fidelity step.)
2. ✅ **[CLOSED v2.5.0]** Secrets (×3) on **Vault KV v2** — `VaultBackedKvStore` wired for
   `sec`/`gcp_sec`/`az_kvsec`.
3. ✅ **[CLOSED v2.5.0]** Firestore + Pub/Sub — took the documented "accept the backing and prove
   the SDK" branch: Firestore durable via `PersistentFirestoreStore`, Pub/Sub on
   `NatsBackedMessagingStore`; **both proven durable in the anti-drift substrate matrix** and green
   on their native-SDK conformance suites. (The emulators remain available behind the drifted
   handlers; the unified path uses the proven persistent/NATS backing.)

**P1 — backing-tech completeness:**
4. ✅ **[CLOSED v2.5.0]** DynamoDB durable via `PersistentNoSqlStore` (file-backed substrate).
5. ✅ **[CLOSED v2.5.0]** Azure Cosmos durable via `PersistentCosmosStore` (file-backed substrate).
6. ✅ **[ROOT-CAUSED v2.6.0]** DynamoDB + Azure-Blob live switchover — live sweep vs the running
   unified ingress shows **S3 + SQS green on real backends**; the DynamoDB "403" is the **tier gate**
   (nosql → Max tier, working as designed) and the Azure-Blob "404" is the running container on
   **pre-v2.5.0 code** (current code returns 201/200, verified). Neither is an ingress defect;
   remaining action is a coordinated container redeploy, not a code change.

**P2 — operation-level depth (high-value missing ops):**  ✅ **ALL CLOSED (v2.5.0 + v2.6.0)**
7. ✅ **[CLOSED]** S3 **CopyObject** (v2.5.0) + S3 **multipart upload** + GCS **resumable upload** (v2.6.0).
8. ✅ **[CLOSED]** Cosmos **richer queries** + DynamoDB **transactions** (v2.5.0); DynamoDB **GSI** +
   Firestore **richer structuredQuery** (v2.6.0).
9. ✅ **[CLOSED v2.6.0]** KMS + Secrets **rotation**; SQS **FIFO + DLQ**; SNS **filter policies**.
10. ✅ **[CLOSED v2.6.0]** Azure KV keys **wrap/unwrap + sign/verify**.

**P3 — cross-cloud symmetry:**  ✅ **ALL CLOSED (v2.5.0 + v2.6.0)**
11. ✅ **[CLOSED v2.5.0]** Azure **pub/sub topic core** — `azure_servicebus_core` (Service Bus REST
    wire: topics + subscriptions + **real fan-out** + peek-lock/complete/abandon), the SNS/Pub-Sub peer.
12. ✅ **[CLOSED v2.6.0]** Azure **RBAC decision core** — `azure_iam_core` checkAccess (wildcard +
    notActions + scope inheritance + explicit-deny), the SimulatePrincipalPolicy/testIamPermissions peer.
13. ✅ **[CLOSED v2.6.0]** Azure **SQL data plane** — `azure_sql_core` (real SQL on the SqlStore seam),
    the RDS/Cloud SQL peer.

**P4 — new capability (no data plane anywhere):**
14. ✅ **[CLOSED v2.6.0]** Serverless runtime — `lambda_core` (function lifecycle + sandboxed
    Python-runtime synchronous Invoke).
15. ◑ **[PARTIAL v2.6.0]** Event bus — `eventbridge_core` (rules + patterns → SQS delivery) DONE;
    **API gateway + VPC data planes remain open** (each a dedicated-release-sized subsystem; deferred
    deliberately rather than shipped as shallow stubs — see v2.6.0 Phase F note).

---

## 7. Honest summary

- **~10–11 services per cloud reach a real conformance core**; **11 are native-SDK-proven**
  across the three clouds. The **data/identity/secrets/messaging/relational** core is solid and
  largely symmetric.
- The **biggest real gaps** are: (a) **backing-tech** — Secrets + NoSQL run in-memory, and the
  unified path regressed Firestore/Pub-Sub/Azure-Blob vs the emulator/Azurite-backed default;
  (b) **cross-cloud asymmetry** — Azure lacks a pub/sub topic core, a dedicated IAM decision
  core, and a SQL data plane; (c) **whole categories with no data plane anywhere** — serverless,
  API gateway, networking, event bus (catalog/ARM only).
- Everything here is tracked; the P0/P1 items are the ones that gate a clean, real-backend
  cutover of the v2.4.0 unified ingress.
