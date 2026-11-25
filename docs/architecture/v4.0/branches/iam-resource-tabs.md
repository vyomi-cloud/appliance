# v4/iam-resource-tabs

Per-resource permissions tabs in the v4 consoles (`consoles/src` only), built on the picker branches (`v4/iam-pickers-integ`).
Each tab reads the REAL stored policy through the service's native call and saves through the native call.

## Shared components (one per cloud)

| Cloud | Component | Config |
|---|---|---|
| AWS | `consoles/src/aws/kit/ResourcePolicyTab.jsx` (statements table + JSON, Edit -> Visual editor with Principal/Action pickers from the IAM catalog, or the IAM JSON editor with the live status bar) | `kit/resourcePolicies.js` kind -> load/save/remove |
| AWS Lambda | `services/lambda/ResourcePermissions.jsx` (GetPolicy, Add permissions = AddPermission, Delete = RemovePermission) | n/a (Lambda has no whole-document PUT) |
| GCP | `consoles/src/gcp/kit/ResourcePermissionsPanel.jsx` (Grant access = the project IAM `GrantAccessPanel`, now exported with a `resourceLabel`; View by principals/roles; Remove access) | `kit/resourceIam.js` kind -> getIamPolicy/setIamPolicy |
| Azure | existing `kit/ResourceIam.jsx`, now wired into every ARM resource blade, scoped to the resource id | `iam:` entry of each blade |

## Services done

AWS: S3 bucket policy (PutBucketPolicy / DeleteBucketPolicy), SQS access policy (SetQueueAttributes Policy), SNS access policy (SetTopicAttributes Policy), Secrets Manager resource permissions (Put/DeleteResourcePolicy), ECR repository policy (Set/DeleteRepositoryPolicy), Backup vault access policy (PutBackupVaultAccessPolicy), EventBridge bus policy (UpdateEventBus Policy; PutPermission/RemovePermission form kept), API Gateway REST resource policy (PATCH /restapis/{id} /policy), Lambda resource-based policy (AddPermission/RemovePermission).
GCP: Storage bucket, Pub/Sub topic, Pub/Sub subscription, Cloud Run service, Cloud Functions (same Run v2 wire the console uses), Compute instance (new Permissions tab), KMS key (replaced the free-text dialog), Secret Manager secret (replaced), Artifact Registry repository.
Azure: Access control (IAM) = ResourceIam on Key Vault, Service Bus namespace and queue, VM, VNet, NSG, ACR, APIM, App Service, Function App, Container Apps (app, environment, job), Cosmos DB, Event Grid topic, AI Search, SQL database, Stream Analytics job, Recovery Services vault, Resource group (plus AKS, Cognitive Services, App Configuration, DNS, Log Analytics, SQL server, Storage account, Subscription which already used it). Hand-rolled per-blade copies were deleted.

## Skipped and why

| Service | Reason |
|---|---|
| AWS KMS key policy | existing key-policy tab already has the real admin/user visual editor (PutKeyPolicy); kept. The real console has no grants UI |
| AWS DynamoDB / Kinesis resource policy | existing editors on their detail pages kept (revision-id handshake), not migrated |
| AWS Step Functions, Glue, Cognito | no resource-policy tab in the real console / service not in this console |
| GCP BigQuery, Spanner, Firestore | services not simulated in the v4 GCP console |
| GCP Compute disk | `compute-disk` kind is registered but there is no disk detail page to host the tab |
| Azure Storage container access policy / SAS stored policies | there is no blob container detail blade in this console |
| Azure Key Vault access policies vs RBAC, Service Bus SAS policies, Cosmos keys | already present as their own blades (Access policies, Access configuration, Shared access policies, Keys); not duplicated |
| Azure Entra user/app blades | not ARM resources |

## Differences from the real consoles

- AWS visual editor has no Condition builder (conditions are preserved on round trip and edited in JSON); NotAction/NotPrincipal statements are JSON-only.
- The Azure kit PUTs the role assignment under the subscription with `properties.scope` = the resource id (existing kit behaviour), and the Azure kit has extra tabs (Enforcement, Effective access, Audit).
- GCP role picker is not filtered by resource type; the Permissions panel does not show inherited (project) bindings, so Inheritance is always "Direct".
- New Azure capability registry entries (`azure.aisearch.iam`, `azure.functionapp.iam`, `azure.sql.database.iam`, `azure.streamanalytics.iam`, `azure.common.resource.iam`) were added; their tests reference `test_azure_arm_core.py` and were not re-run.
- Lambda AddPermission UI was built and compiled but is not covered by a smoke test.

## Tests (consoles/tests)

`smoke-aws-resource-policy-tabs.mjs` (S3, SQS, Secrets), `smoke-gcp-resource-permissions.mjs` (bucket, topic, Run), `smoke-azure-resource-iam-tabs.mjs` (Key Vault, Service Bus namespace + queue). Existing `smoke-aws-iam-pickers`, `smoke-gcp-iam-pickers`, `smoke-azure-iam-pickers`, `iam-pickers-unit` re-run green.
