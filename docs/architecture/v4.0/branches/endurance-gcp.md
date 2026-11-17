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
| `sql_custom_endpoint` | `$EP/sql/v1beta4/` | |
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
