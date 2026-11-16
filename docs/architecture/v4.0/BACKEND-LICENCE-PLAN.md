# Backend licence plan: S3 object store and the other copyleft or non-open components

Date: 2026-11-17. Branch: `v4/post-beta-licplan` (base `origin/v4-on-main` 4141d0577). Docs only, no product code changed.

**This is an engineering plan, not legal advice.** Every item marked **COUNSEL** needs a lawyer before the owner charges for hosted Mesh. Licence facts below were read from the primary LICENSE or COPYING file in each upstream repo through the GitHub API on 2026-11-17 (URL given per row). Owner rule applied: do not build our own backends; swap to a lightweight open-source equivalent.

## 1. Key finding: MinIO is a byte mirror, not the S3 implementation

Reading `core/minio_backed_store.py`, `core/minio_mirror.py` and `core/wire_ingress.py` (lines 899-926):

- All S3 and GCS API semantics (versioning, multipart, presign, lifecycle, notifications, object lock, SSE, tagging, ACL, policy) are implemented by our own cores (`core/s3_object_core.py`, `s3_ext_core.py`, `object_store.py`). SDK and conformance traffic hits the Vyomi wire ingress, never MinIO.
- MinIO only receives a write-through copy of object bytes through four seam hooks: `create_bucket`, `mirror_put`, `mirror_delete`, `fetch_bytes`, plus `list_buckets` and `list_objects_v2` for a one-time pre-C0 migration and `list_buckets` for the reachability probe. Buckets are namespaced (`aws-s3-`, `gcp-gcs-`).
- Metadata is durable in a SQLite sidecar (v4 C0), and the store already falls back to SQLite-only (`PersistentObjectStore`) when MinIO is down. Tests `tests/test_offline_core_durability.py` and `tests/netsim/test_docker_offline_e2e.py` run with MinIO pointed at a dead port (`127.0.0.1:1`).
- The only user-visible reason to keep a real S3 server is "external S3 tools can see the bytes" at host port 9100.

Consequence: the backend needs only 6 S3 calls (CreateBucket, PutObject with Content-Type and user metadata, GetObject, DeleteObject, ListBuckets, ListObjectsV2) over SigV4 path-style. S3 API coverage of the candidate is almost irrelevant to conformance; licence, footprint, multi-arch and maintenance dominate. The cheapest option of all is to drop the server (section 3, option F).

S3 operations our suites exercise through the Vyomi ingress (grep of `tests/`, count of call sites): put_object 136, get_object 58, list_objects_v2 28, delete_object 16, head_object 12, put_bucket_notification_configuration 4, copy_object 4, put_bucket_versioning 2, list_object_versions 2; Java and Go SDK suites live in `tests/conformance/aws-sdk-java` and `aws-sdk-go`. All are served by our core, not by the backend.

## 2. Candidate comparison (primary-source checks, 2026-11-17)

| Option | Licence (file read) | Maintenance | Multi-arch image | Footprint | Fit |
|---|---|---|---|---|---|
| Baseline: MinIO (our `vyomi/minio` from source, tag `RELEASE.2025-09-07T16-13-09Z`) | AGPL-3.0. https://github.com/minio/minio/blob/master/LICENSE (AGPL text). README: "THIS REPOSITORY IS NO LONGER MAINTAINED"; repo archived, last push 2026-04-24; last release `RELEASE.2025-10-15T17-29-55Z` (source only, no images). | Dead: no security fixes. | Only because we build it ourselves (we own the multi-arch pipeline and the registry cost). | Go binary, roughly 100-200 MB RAM idle (from knowledge, not measured here). | Works today. |
| A. SeaweedFS | Apache-2.0. https://github.com/seaweedfs/seaweedfs/blob/master/LICENSE (Apache License 2.0). | Very active: release 4.54 on 2026-11-16, 36k stars, repo pushed same day. | Docker Hub `chrislusf/seaweedfs:latest` 259 MB compressed: amd64, arm64, arm, 386, ppc64le, s390x; `latest_large_disk` 90 MB. Official, 42.8M pulls. | **Measured here (Mac arm64, Docker 29.4.3, 7.75 GiB VM): `weed server -s3` single container 80 MiB RSS right after start, 89 MiB after the 8 calls below. Image is 1.03 GB uncompressed on disk, `weed` binary 206 MB.** | Best fit. Single process runs master+volume+filer+S3. README advertises versioning, object lock, lifecycle, SSE-S3/KMS/C, presign, notifications. |
| B. RustFS | Apache-2.0. https://github.com/rustfs/rustfs/blob/main/LICENSE | Active but young: 1.0.6 on 2026-11-15, 36k stars. | `rustfs/rustfs:1.0.6` 129 MB, amd64 + arm64. | Not measured (the pull stalled on this machine and was cancelled). README minimum spec says 4 GB memory for a normal deployment. | Viable second choice. Younger codebase, "MinIO on-disk compatibility" is only preview; its S3 compatibility matrix is its own doc. |
| C. Garage | **AGPL-3.0**. https://github.com/deuxfleurs-org/garage/blob/main-v2/LICENSE (GNU AFFERO text). | Active. | amd64, arm64 (25 MB). | Tiny. | **Rejected: same AGPL problem as MinIO.** Also no versioning or object lock (from knowledge, not re-checked). |
| D. Ceph RGW | LGPL-2.1 or LGPL-3 for the tree (https://github.com/ceph/ceph/blob/main/COPYING, `Files: *`), with GPL3 only for one dev script and CC-BY-SA docs. | Very active. | Official images exist. | Needs mon+mgr+osd+rgw; GBs of RAM. | **Rejected: far too heavy** for a Codespace (8 GB shared with other services). |
| E. Zenko CloudServer (Scality) | Apache-2.0. https://github.com/scality/cloudserver/blob/development/9.6/LICENSE | Active: 9.4.16 on 2026-11-16. | Docker Hub tags seen are amd64 only. | Node.js, moderate. | Weak: amd64-only fails the Apple-silicon and Codespaces-arm requirement. Not recommended. |
| Others: s3proxy (Apache-2.0, https://github.com/gaul/s3proxy/blob/master/LICENSE; 4.1.1 on 2026-09-10), versitygw (Apache-2.0, https://github.com/versity/versitygw/blob/main/LICENSE; v1.11.0 on 2026-11-06) | Apache-2.0 | Active | Not checked | Both expose a POSIX directory as S3; light. | Credible lightweight fallbacks if SeaweedFS is judged too big. Not tested. |
| moto server / LocalStack | moto Apache-2.0 (https://github.com/getmoto/moto/blob/master/LICENSE; 5.2.5 on 2026-10-27). LocalStack community repo is **archived** (2026-03-23), consolidated into a single image under an End-User Licence Agreement per its README. | moto active | Python image | moto S3 is in-memory unless configured | moto is already in our stack, but it is a second S3 emulator with no value as byte store. LocalStack: **do not adopt** (EULA). |
| F. Drop the server (SQLite only) | n/a | n/a | n/a | zero | Already the tested fallback. Loses only "external tools see bytes on :9100". |

Measured SeaweedFS check (Mac arm64, 2026-11-17, boto3 1.x path-style SigV4, `weed server -s3 -dir=/data`, anonymous default identity): create_bucket, put_object (Content-Type + user metadata), get_object (metadata and content-type round-trip), list_buckets, list_objects_v2 with prefix, delete_object, put of a key under the `__entries__/` sidecar prefix, and put_bucket_versioning all returned ok. Not tested: durability across container restart, SigV4 with a configured identity (needs an `s3.json` for `cloudlearn` credentials), Linux amd64, and RustFS. Mark those as Phase 0 checks below.

How each fits the substrates:
- Nano (browser): unchanged. Nano uses our own in-browser core and never runs MinIO or any of these (the seam is "never vendored to WASM"). No work.
- Mesh (Codespace) and offline appliance: replace the `vyomi-minio` service in `docker-compose.appliance.yml`, `codespace/.devcontainer/docker-compose.sandbox.yml`, `core/backend_provisioner.py` (recipe `minio`), `core/appliance_readiness.py` and `core/wire_ingress.py`.

## 3. Recommendation

**Primary: option F now, SeaweedFS as the optional external-tools bytes service.**

1. Make the S3 byte mirror optional and default it to off. The SQLite-only store is already the tested fallback, so removing `vyomi-minio` from default Mesh and appliance profiles removes the AGPL redistribution immediately with near-zero code.
2. Keep an opt-in `vyomi-s3` service (profile `object-store`) running `chrislusf/seaweedfs` (Apache-2.0, official multi-arch image we do not rebuild) for users who want to browse bytes with external S3 tools at :9100. SeaweedFS also removes our own multi-arch MinIO build pipeline and the "image gone from Docker Hub" risk.
3. Fallback if SeaweedFS misbehaves in step 0: RustFS 1.0.6 (Apache-2.0, 129 MB, amd64+arm64) or versitygw.

Baseline kept as a documented fallback only: "keep MinIO and comply with AGPL" means a source offer for tag `RELEASE.2025-09-07T16-13-09Z` plus our Dockerfile with every image, notices (already in `THIRD-PARTY-NOTICES.md`), and no patching. It is cheap (about 1 day) but leaves an unmaintained, unpatched network service in a paid product. **COUNSEL**: whether redistributing the image unmodified as a separate container triggers the AGPL source-offer duty as engineering reads it, and section 13 if we ever patch it.

### Migration steps

0. Phase 0 checks (0.5 day): run SeaweedFS with an `s3.json` identity for access key `cloudlearn`; boto3 smoke on Linux amd64 (CI runner) and Mac; restart durability; confirm `x-amz-meta-*` and Content-Type round-trip; measure RSS under a 50 MB put. Repeat for RustFS if SeaweedFS fails.
1. Add `VYOMI_S3_BACKEND` selector (none | seaweedfs) with env alias `VYOMI_MINIO_IMAGE` kept for one release; update the `minio` Recipe in `core/backend_provisioner.py` (image, env, health URL: SeaweedFS S3 answers on its port, no `/minio/health/ready`), `core/appliance_readiness.py` row, both compose files and `cmd/vyomi/docker.go`.
2. `minio_backed_store.py`: no logic change (only boto3 put/get/delete/list_buckets/list_objects_v2); rename later. Keep the pre-C0 `__entries__/` migration path working.
3. Readiness ribbon and Service status: show "Object store (optional)" instead of a red tile when the service is intentionally off (owner feedback: ribbon is backend services only, real status).
4. Data migration: existing volumes `vyomi-minio` hold MinIO's own on-disk format, which SeaweedFS cannot read. Because bytes are also in the SQLite sidecar, no migration is needed; on first start the mirror repopulates (write a one-shot `resync_mirror()` that replays sidecar objects through `mirror_put`, about 0.5 day).
5. Update `tools/notices/notices.json` (drop MinIO row or mark "removed in vX", add SeaweedFS Apache-2.0 row), regenerate `THIRD-PARTY-NOTICES.md` and `sbom.cdx.json` with `python3 tools/notices/gen_notices.py`, update the in-product Notices page text (the "MinIO is used under AGPL v3" sentence).
6. Release note and upgrade note; retire the `vyomi/minio` build job and registry repo after one release.

### Risks

- SeaweedFS needs an `s3.json` identity file or it runs open with default access; wire credentials the same way as today (`CLOUDLEARN_MINIO_ACCESS_KEY` aliases).
- Bucket name namespace (`aws-s3-`, `gcp-gcs-`, `v24-`) must pass SeaweedFS bucket-name rules; verify with the Phase 0 smoke.
- Image is 259 MB compressed (1.03 GB on disk), larger than MinIO. Mitigate with the 90 MB `latest_large_disk` tag or keep it opt-in (the recommended default).
- Single-maintainer-style upstream risk exists for every option; SeaweedFS has 40M+ pulls and daily releases.
- Mesh readiness gates and the Playwright/console runners that assert MinIO tile text must be updated (grep `MinIO` in `wasm/clouds.html`, `wasm/readiness-strip.js`, `wasm/console_next_manifest.py`, `core/capabilities/backends/aws.json`).

### Tests that must stay green

- `tests/conformance/test_minio_backed_store.py`, `tests/conformance/test_minio_sidecar_store.py` (rename the fixtures, keep assertions).
- `tests/test_c0_unified_engine.py`, `tests/test_c0e_unified_engine.py`, `tests/test_offline_core_durability.py`, `tests/netsim/test_docker_offline_e2e.py`, `tests/netsim/test_legacy_vpc_upgrade.py` (offline fallback with the object store off).
- AWS S3 and GCS native-SDK suites: `tests/conformance/aws-sdk-java`, `aws-sdk-go`, `gcp-sdk-java`, `gcp-sdk-go` and the S3 console actions in `tests/conformance/console_actions`; the post-create probes; the CI workflow `ci.yml` (lines 75-125 reference MinIO on :9100).
- New: one test that with `VYOMI_S3_BACKEND=seaweedfs` an object put through the Vyomi S3 API is visible via a plain boto3 client at :9100, and that with the backend off S3 still works and the ribbon says "optional".

### Effort (days, honest)

| Item | Days |
|---|---|
| Phase 0 checks (SeaweedFS, plus RustFS if needed) | 0.5 |
| Compose, provisioner, readiness, selector, CLI | 1 |
| Resync tool and durability tests | 1 |
| Console/runner string updates and CI | 0.5 |
| Notices, SBOM, docs, release note | 0.5 |
| Buffer for SeaweedFS identity and naming surprises | 1 |
| **Total** | **about 4.5 (range 3-6)** |
| Compliance-only baseline (source offer, no swap) | about 1 |

## 4. Audit table: every copyleft or non-open component we ship or pull

Actions: pin, replace, drop, or comply. "Verified" means the LICENSE file was read on 2026-11-17.

| Component (where) | Licence and source | Risk | Exact action | Owner / counsel |
|---|---|---|---|---|
| MinIO `vyomi/minio` (appliance + sandbox compose, `backend_provisioner.py`) | AGPL-3.0, archived, unmaintained. Verified https://github.com/minio/minio (LICENSE, README) | High | **Drop from default, replace with optional SeaweedFS** (section 3). Until shipped: **comply** with a source offer. | Engineering; **COUNSEL** on AGPL source-offer posture |
| FRRouting (planned hybrid edge, `V4-WAVES-5-8-PLAN`) | COPYING says parts have various licences, composite binary "thought to always be distributable under GPLv2 or later" and that it is not legal advice. Verified https://github.com/FRRouting/frr/blob/master/COPYING | Medium if shipped | **Comply**: run unmodified in its own container pulled from the upstream `quay.io/frrouting/frr` image (do not rebuild or bundle it in our images), ship the licence text and a source offer link in Notices, never link it into our code. Not in compose yet, so nothing to do until the wave lands. | **COUNSEL** on whether pulling upstream image keeps us from redistributing |
| HashiCorp Vault `hashicorp/vault:1.15` (appliance compose) | **BUSL-1.1, not MPL.** The LICENSE in tags v1.15.0 and v1.15.6 is the Business Source License; "Licensed Work: Vault Version 1.15.0 or later" and the Additional Use Grant forbids offering it to third parties on a hosted or embedded basis to compete with HashiCorp's paid versions. The 2026-11-16 audit and `tools/notices/notices.json` (row 120) say MPL-2.0 for 1.15: **that is wrong and must be corrected.** Latest is v2.2.2. Verified https://github.com/hashicorp/vault/blob/v1.15.6/LICENSE | **High** (Vyomi offers KMS / Secrets Manager / Key Vault, which overlap Vault Transit/KV, in a paid hosted product) | **Replace with OpenBao** (MPL-2.0, verified https://github.com/openbao/openbao/blob/main/LICENSE; v2.7.2 released 2026-10-26; Vault-API compatible fork). Alternative: pin to the last MPL line 1.14.x (v1.14.10, Feb 2024) but that is EOL and unpatched. Needs a test that `core/vault_client.py` KV v2 and Transit calls pass on OpenBao. About 2 days. | **COUNSEL** on BUSL "competitive offering" reading, and until swapped; engineering to fix notices row |
| `amazon/dynamodb-local:latest` (appliance compose `vyomi-dynamodb`) | Not an open-source licence; Amazon's own terms. The DynamoDBLocal doc page fetched on 2026-11-17 states no licence text. | Needs review | **Drop**: since v4 C0 tables live in our shared DynamoDB core and DynamoDB Local is only the source for the one-time upgrade copy (`core/ddb_local_migration.py`, `tests/test_ddb_local_migration.py`). Remove from default compose; keep as a documented opt-in only for legacy upgrades. | **COUNSEL** only if we keep it |
| Google emulators `gcr.io/google.com/cloudsdktool/google-cloud-cli:emulators` (Pub/Sub, Firestore) | Cloud SDK source is Apache-2.0 (from knowledge); the image bundles Google components under Google Cloud terms; not re-read here | Medium | **Pin** an exact image digest, **comply** (notices) and plan **replace/drop** where our own cores already cover the API (the P1 notes say the simulator delegates only some handlers to them). No OSS drop-in exists for Firestore; for Pub/Sub, evaluate whether our core suffices. | **COUNSEL** on redistributing or running Google SDK images in a paid product |
| MySQL `mysql:8.0` | GPL-2.0 with Oracle FOSS exception (Licensing Information User Manual in the repo; not re-read in full) | Low-medium | **Comply**: unmodified upstream image, separate container, user pulls it; notices entry. Consider swapping to MariaDB or Percona if counsel objects. | **COUNSEL** (low) |
| psycopg2-binary (Python dep) | LGPL-3.0 with OpenSSL exception (from knowledge) | Low | **Comply**: dynamic use, keep licence notice, allow replacement; or move to `psycopg` v3 (also LGPL-3.0) or `pg8000` (BSD) if wanted. | Engineering |
| Qwen2.5-3B (model) | Qwen Research License, non-commercial. Already resolved by the Qwen3-4B-Instruct-2507 swap (branch `v4/ai-qwen3swap`). | Resolved | **Comply**: keep refused on paid tiers and the catalog test. | Done; **COUNSEL** item 1 of the AI audit remains |
| Llama 3.1 / 3.2, Gemma 2 (models) | Community licences with attribution and use policies (see AI-LICENCE-AUDIT section 2) | Medium | **Comply** (notices, Built with Llama, AUP flow-down) or **drop** Gemma if flow-down is too heavy. | **COUNSEL** items 2-4 |
| LocalStack (if ever adopted) | Community repo archived 2026-03-23; single image under an EULA | n/a | **Do not adopt.** | Engineering |
| Garage (candidate) | AGPL-3.0 | n/a | **Do not adopt.** | Engineering |
| Permissive pieces: Azurite (MIT), fake-gcs-server (BSD-2), elasticmq (Apache-2.0), NATS, Caddy, Valkey (BSD-3), VictoriaMetrics, registry, moto, llama.cpp, WebLLM, wllama | Verified for Azurite, fake-gcs-server, elasticmq, Valkey, moto via repo licence metadata on 2026-11-17 (others from knowledge) | Low | **Comply**: notices only. Pin `azurite:latest`, `fake-gcs-server:latest`, `elasticmq-native:latest` and `caddy:2-alpine` to explicit tags or digests so a licence change cannot slip in. | Engineering |
| Vyomi's own `LICENSE` (source-available with a hosted-offering restriction) | n/a | n/a | Confirm it is compatible with redistributing AGPL, GPL and LGPL third-party parts in the same image set. | **COUNSEL** |

## 5. Order of work

1. Fix `tools/notices/notices.json` row 120 (Vault 1.15 is BUSL-1.1) and the AI audit table line, regenerate notices (0.25 day, can ship alone).
2. Vault to OpenBao swap (2 days, highest legal exposure).
3. S3 backend: option F default plus optional SeaweedFS (about 4.5 days).
4. Drop DynamoDB Local from default compose (0.5 day).
5. Pin floating tags (0.5 day).
6. FRR: apply the "comply" recipe when the hybrid-edge wave lands.

Sources read 2026-11-17: GitHub API contents/metadata for minio/minio, seaweedfs/seaweedfs, rustfs/rustfs, deuxfleurs-org/garage, ceph/ceph, scality/cloudserver, gaul/s3proxy, versity/versitygw, getmoto/moto, localstack/localstack, FRRouting/frr, hashicorp/vault (tags v1.14.10, v1.15.0, v1.15.6), openbao/openbao; Docker Hub tag APIs for `chrislusf/seaweedfs`, `rustfs/rustfs`, `scality/cloudserver`, `dxflrs/garage`.
