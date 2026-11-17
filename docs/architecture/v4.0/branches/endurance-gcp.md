# endurance-gcp: GCP reference estate (Terraform) + simulator fixes

Branch `v4/endurance-gcp` (from `v4-on-main` + `v4/vyomi-endurance`). Mission: an enterprise GCP estate exported as Terraform that passes
validate -> apply -> no-diff re-plan -> destroy -> rebuild -> destroy against the real simulator server (`tests/endurance/run_estate.sh`).
Every defect found is a simulator bug; fixes are `F300-F399`, regression tests in `tests/conformance/test_endurance_gcp_core.py`.

## Working provider block (verified)
OpenTofu 1.13 in docker, `hashicorp/google ~> 5.45` (5.45.2), `hashicorp/random`. Auth is a dummy `access_token` (the simulator never validates it);
project `vyomi-project` (the simulator's default GCP identity, number 123456789012). One `*_custom_endpoint` per API, all pointing at the one server:

| provider argument | value | note |
|---|---|---|
| `compute_custom_endpoint` | `$EP/compute/v1/` | |
| `iam_custom_endpoint` | `$EP/` | hand-written IAM client appends `v1/` itself |
| `kms_custom_endpoint`, `secret_manager_custom_endpoint`, `pubsub_custom_endpoint`, `redis_custom_endpoint`, `firestore_custom_endpoint`, `cloud_scheduler_custom_endpoint`, `resource_manager_custom_endpoint` | `$EP/v1/` | |
| `storage_custom_endpoint` | `$EP/storage/v1/` | |
| `sql_custom_endpoint` | `$EP/sql/v1beta4/` | instance resource appends the prefix again (F300) |
| `monitoring_custom_endpoint` | `$EP/` | resources append `v3/` / `v1/` (dashboards) themselves |
| `logging_custom_endpoint`, `cloud_run_v2_custom_endpoint`, `cloudfunctions2_custom_endpoint` | `$EP/v2/` | |
| `artifact_registry_custom_endpoint`, `vertex_ai_custom_endpoint` | `$EP/v1/` | |
`$EP` = `http://host.docker.internal:19103` from the tofu container. Run: `tests/endurance/run_estate.sh tests/endurance/estate/gcp $EP`.

Estate rules that mirror real GCP: KMS key rings/keys are undeletable, so the ring name carries a `random_id` (a rebuild would 409 on real GCP too).

## Simulator fixes
| id | fix |
|---|---|
| F300 | Some provider clients append the API version to a custom endpoint that already ends in it (`/v1/v1/...` KMS destroy, `/sql/v1beta4/sql/v1beta4/` Cloud SQL): `core/middleware.py` collapses the duplicate prefix. |
| F301 | Router created without `bgp` no longer reports a phantom `{asn: 64512}` (permanent in-place update). |
| F302 | Cloud NAT keeps `natIps` and other client fields; `logConfig` only when set. |
| F303 | Firestore database create/update/delete are long-running operations (`name`/`done`/`response`), as on the real API; the provider polled the database resource forever. |
| F304 | Pub/Sub `schemas.get` without `view` returns the definition (provider sends no view). |
| F305 | Memorystore instance reports `displayName`/`redisConfigs` only when set. |
| F306 | Compute serves Google's public image projects (`debian-cloud`, `ubuntu-os-cloud`, `cos-cloud`, `rocky-linux-cloud`): `images.get` / `getFromFamily` (a `source_image = "debian-cloud/debian-12"` could not resolve). |
| F307 | Cloud Logging `LogMetric.name` / `LogSink.name` on the wire are the short id (provider re-uses it in the GET url); `disabled:false` omitted. Existing logging test updated. |
| F308 | Cloud Logging `buckets:createAsync` / `:updateAsync` long-running operations + `operations/bucket-<id>`. |
| F309 | Compute instance template: insert op `targetId` = template id and `GET` by numeric id works; the template keeps all sent properties (tags, serviceAccounts, scheduling...), the stub dropped them and forced replacement forever. |
| F310 | `setCommonInstanceMetadata` drops the null slots the provider sends (the provider nil-dereferenced when reading them back). |
| F311 | Artifact Registry docker repository without `dockerConfig` reports none. |
| F312 | Health checks always report `proxyHeader` (default `NONE`). |
| F313 | Cloud Run v2 wire view hides simulator-filled defaults (container `name`, `cpuIdle`, `executionEnvironment`); internal consumers still see them. |
| F314 | Cloud Functions v2 (`/v2/projects/*/locations/*/functions|runtimes`) is mounted on the offline server and runs under the GCP provider scope (it read a different Cloud Storage state before). |
| F315 | Secret Manager replication validation ignores a null counterpart (`userManaged` + `automatic: null`). |
| F316 | VPC peering reports `exportSubnetRoutesWithPublicIp` (default true) / `importSubnetRoutesWithPublicIp` (false). |
| F317 | Regional network firewall policy rules keep every sent field and `getRule`/`patchRule` exist. |
| F318 | Functions v2 `vpcConnectorEgressSettings` only reported with a connector. |
Existing suites adjusted to the real wire shapes: firestore admin/datastore (create returns an operation), pubsub schema get default view, logging metric/sink names.

## Estate (tests/endurance/estate/gcp, 70 resources, one root, 7 stage modules)
stage1 network+identity (VPC x2, subnets, firewall x2, route, router+NAT, addresses, peering x2, SAs, custom role, IAM members, KMS ring/key, secrets x2),
stage2 compute (disk, snapshot, health check, instance template, Artifact Registry repo, project metadata), stage3 data (GCS bucket+object+IAM,
Cloud SQL instance+db+user, Firestore db+document, Memorystore), stage4 messaging (Pub/Sub schema/topics/subscriptions incl. DLQ+push, Scheduler job),
stage5 serverless (Cloud Run service+IAM+job, Functions v2), stage6 AI (Vertex dataset, endpoint, tensorboard, feature online store, index, index endpoint),
stage7 observability (log metric/sink/bucket, notification channel, alert policy, uptime check, dashboard).
Gate: `ENDURANCE_LOG_DIR=... tests/endurance/run_estate.sh tests/endurance/estate/gcp http://host.docker.internal:19103` -> init/validate/apply/replan no-diff/destroy/reapply/final-destroy all PASS (apply ~18s, destroy ~9s). No compute containers are created (no GCE instances, no GKE).
Coverage: `tests/endurance/estate/coverage-map.gcp.json` (60 manifest ids, verify = tf only; SDK/CLI/UI proof not yet attached).

## Open gaps
- DCL-based provider resources (`google_compute_*network_firewall_policy*`, the regional/global policy rules) poll the operation by its absolute `selfLink` (https://compute.googleapis.com/...), i.e. the real Google API, and hang. Fix = simulator emits selfLinks on the request's public base (`_gcp_capture_public_base` exists in middleware); not done. Estate uses classic firewall rules only.
- Not in the estate yet: GCE instances (need a docker compute container), GKE, Cloud Build/Deploy, Eventarc, Spanner/Bigtable (not in the manifest), Vertex models/jobs (no google provider resource), Memorystore/SQL replicas, BigQuery-backed features.
- `tests/test_c0d_unified_engine.py::test_firestore_admin_and_documents_native_and_classic_share_state` already fails on v4-on-main (project `c0d-proj` -> 403), unrelated.
- F318's regression test is a source assertion (the functions core needs a full ctx to call).
