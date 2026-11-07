# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""AwsWireRouter — the native-AWS-wire front door for the Nano relay / bridge.

An EXTERNAL app (unmodified boto3 / aws-cli / your service) points its
`--endpoint-url` at the relay; the relay forwards the raw HTTP request to the
in-browser Nano tab, which hands it to this router. The router inspects the
request the way a real cloud front-end does — SigV4 credential scope, then the
`X-Amz-Target` header, then the Query-protocol `Action` — picks the owning
service, and dispatches to that service's PROVEN conformance core in its NATIVE
wire (S3: method+path; DynamoDB/KMS/Secrets/SQS: X-Amz-Target JSON; IAM/RDS/SNS:
Query+XML). So an external SDK call is served by the SAME logic the conformance
suite asserts on host CPython AND Pyodide — not a stub, and not a re-implementation.

This is the relay analogue of the console's `aws_core_adapter` (which translates
the friendly console REST). Here there is NO translation: the wire IS the native
cloud wire, because the caller is a real SDK.

Design notes:
  * Substrate-free — stdlib (json/base64/urllib/re) + the cores only. No
    fastapi / socket / boto3 at module top, so it loads under Pyodide and is
    provable on both substrates like every core.
  * Routing reads SigV4 but NEVER verifies it (handlers don't enforce SigV4 so
    an unmodified SDK works); the credential scope is just the cleanest service
    signal a real SDK always sends, even through `--endpoint-url`.
  * SNS and SQS SHARE one MessagingStore so `Publish` fans out into a subscribed
    SQS queue — the canonical SNS→SQS pattern, exactly as the messaging
    conformance suite proves.

Output is uniform: {"status": int, "headers": {str:str}, "body": bytes}.
"""
from __future__ import annotations

import base64
import json
import re
from urllib.parse import parse_qsl
from xml.sax.saxutils import escape as _xml_escape

from core.object_store import InMemoryObjectStore
from core import s3_object_core as s3
from core.nosql_store import InMemoryNoSqlStore
from core import dynamodb_core as ddb
from core import dax_core as dax
from core.kms_keystore import InMemoryKeyStore
from core import kms_core as kms
from core.kv_store import InMemoryKvStore
from core import secrets_core as secrets
from core.sql_store import InMemorySqlStore
from core import rds_core as rds
from core.iam_store import InMemoryIamStore
from core import iam_core as iam
from core.messaging_store import InMemoryMessagingStore
from core import sqs_core as sqs
from core import sns_core as sns
from core import elbv2_core as elbv2
from core import cloudformation_core as cfn
from core import rds_data_core as rds_data
from core import gcp_project as gcp_proj   # GCP: the one project (ID + number) + Resource Manager
from core import gcp_storage_core as gcs   # GCP: GCS JSON API, path-routed (not SigV4)
from core import gcp_firestore_core as gcp_fs
from core import gcp_datastore_core as gcp_ds
from core import gcp_eventarc_core as gcp_eventarc
from core import gcp_hub_core as gcp_hub
from core import gcp_audit_core as gcp_audit
from core.gcp_firestore_core import FirestoreStore
from core import gcp_kms_core as gcp_kms
from core import gcp_secretmanager_core as gcp_sec
from core import gcp_pubsub_core as gcp_ps
from core import gcp_iam_core as gcp_iam
from core import gcp_cloudsql_core as gcp_sql
from core import gcp_cloudscheduler_core as gcp_sched
from core import gcp_container_core as gcp_gke
from core import gcp_iamcredentials_core as gcp_iamc
from core import gcp_monitoring_core as gcp_mon
from core import gcp_redis_core as gcp_redis
from core import gcp_vertex_core as gcp_vertex
from core import gcp_artifactregistry_core as gcp_ar
from core import nano_triggers
from core import gcp_logging_core as gcp_logging
from core import gcp_compute_core as gcp_compute
from core import gcp_compute_instances_core as gcp_compute_vm
from core import gcp_resourcemanager_core as gcp_rm
from core import gcp_pam_core as gcp_pam
from core import gcp_run_core as gcp_run
from core import gcp_binauthz_core as gcp_binauthz
from core import gcp_bigquery_core as gcp_bigquery
from core import gcp_trace_core as gcp_trace
from core import gcp_osconfig_core as gcp_osconfig
from core import gcp_commit_core as gcp_commit
from core import gcp_apphub_core as gcp_apphub
from core import gcp_clouddeploy_core as gcp_clouddeploy
from core import gcp_backupdr_core as gcp_backupdr
from core import gcp_cloudbuild_core as gcp_cloudbuild
from core import gcp_posture_core as gcp_posture
from core import gcp_wire_ext   # GCP wire gap-filler: Functions v1/v2, Cloud DNS, SCC v1 + schema-driven store for the rest

# Cloud Scheduler httpTarget that names a Cloud Run job's own Admin API v2 `:run` endpoint
# (the job-trigger binding the Cloud Run console's Triggers tab shows and creates).
_SCHED_RUN_JOB_RE = re.compile(r"/v2/projects/([^/]+)/locations/([^/]+)/jobs/([^/:]+):run")


def _gcp_service(path):
    """Route a GCP request by URL path (GCP carries no SigV4; each google-cloud-*
    client is pointed at the relay and the path is the service discriminator)."""
    if gcp_vertex.handles(path):
        return "gcp-vertex"   # Vertex AI control plane (endpoints/models/datasets/jobs/indexes/feature store/metadata) + Workbench + Model Garden (core/gcp_vertex_core)
    if re.match(r"^/v2/(projects|organizations|folders)/[^/]+/(locations/[^/]+/)?(sources|findings|muteConfigs|notificationConfigs)([/:?]|$)", path):
        return "gcp-scc"   # Security Command Center API v2 (core/gcp_scc_core over the posture/threat/vulnerability engines)
    if re.match(r"^/v1/projects/[^/]+/locations/[^/]+/sources([/:]|$)", path) \
            or re.match(r"^/v1/projects/[^/]+/locations/[^/]+/operations/operation-[0-9a-f]{16}$", path):
        return "gcp-commit"   # Migrate to Virtual Machines (vmmigration v1) over the Compute store (core/gcp_commit_core)
    if re.match(r"^/v2/projects/[^/]+/locations/[^/]+/(nodes|acceleratorTypes|runtimeVersions)([/:]|$)", path) \
            or re.match(r"^/v2/projects/[^/]+/locations/[a-z]+-[a-z]+[0-9]+-[a-z]/operations/operation-[0-9a-f]{16}$", path):
        return "gcp-commit"   # Cloud TPU v2 nodes (record-level; core/gcp_commit_core)
    if re.match(r"^/v2/projects/[^/]+/locations/[^/]+/(services|jobs|workerPools|operations)([/:]|$)", path) \
            or path.lstrip("/").startswith(("apis/serving.knative.dev/", "apis/domains.cloudrun.com/")):
        # Cloud Run Admin API v2 (+ its Knative v1 facades for `gcloud run` and
        # `gcloud run domain-mappings`) — gated on its specific kinds (services/jobs/
        # workerPools/operations) because Cloud Logging also lives under /v2/projects/,
        # and Cloud Scheduler's /v1/.../locations/.../jobs shares the shape one version down.
        return "gcp-run"
    if re.match(r"^/v1(beta1)?/projects/[^/]+/locations/[^/]+/publishers/[^/]+/models/[^/:]+:[A-Za-z]+$", path):
        return "gcp-aiplatform"   # Vertex AI publisher models (Gemini generateContent/countTokens/embed) -> core/ai_models_core over the local-LLM seam
    if path.startswith(("/storage/v1", "/upload/storage/v1", "/download/storage/v1", "/storage/website/")):
        return "gcp-gcs"
    if re.match(r"^/v[12]/projects/[^/]+/traces([/:]|$)", path) or re.match(r"^/v2/projects/[^/]+/traces/", path) \
            or re.match(r"^/v1/projects/[^/]+/locations/global/traceScopes([/:]|$)", path) \
            or re.match(r"^/v2/projects/[^/]+/locations/global/logScopes([/:]|$)", path):
        return "gcp-trace"   # Cloud Trace v1/v2 + Trace scopes + Log scopes (core/gcp_trace_core, state on the Monitoring store)
    if re.match(r"^/v1/projects/[^/]+/(locations/[^/]+/)?builds([/:?]|$)", path) or re.match(r"^/v1/projects/[^/]+/triggers([/:?]|$)", path):
        return "gcp-cloudbuild"   # Cloud Build builds + triggers on the shared CI seam (core/gcp_cloudbuild_core; images pushed into Artifact Registry)
    if re.match(r"^/v1/projects/[^/]+/locations/[^/]+/(deliveryPipelines|targets)([/:?]|$)", path):
        return "gcp-clouddeploy"   # Cloud Deploy: pipelines/targets/releases/rollouts state machine deploying to the simulator's Cloud Run + GKE (core/gcp_clouddeploy_core)
    if gcp_bigquery.handles(path):
        return "gcp-bigquery"   # BigQuery v2: datasets/tables/rows + SQL (SQLite engine); Storage Insights datasets are populated here (core/gcp_bigquery_core)
    if gcp_binauthz.handles(path):
        return "gcp-binauthz"   # Binary Authorization policy/attestors + attestation occurrences, enforced at Cloud Run deploy (core/gcp_binauthz_core)
    if re.match(r"^/v1/projects/[^/]+/locations/[^/]+/(backupVaults|backupPlans|backupPlanAssociations)([/:?]|$)", path):
        return "gcp-backupdr"   # Backup and DR: vaults/plans/associations; backups are real Compute snapshots (core/gcp_backupdr_core, state on the Compute store)
    if re.match(r"^/v1/projects/[^/]+/locations/[^/]+/(applications|discoveredServices|discoveredWorkloads)([/:?]|$)", path):
        return "gcp-apphub"   # App Hub applications + registered services/workloads (core/gcp_apphub_core, state on the Monitoring store)
    if re.match(r"^/v1/projects/[^/]+/(patchJobs|patchDeployments|patchReport)([/:]|$)", path) \
            or re.match(r"^/v1/projects/[^/]+/locations/[^/]+/instances/[^/]+/inventor(y|ies)$", path) \
            or re.match(r"^/v1/projects/[^/]+/locations/[^/]+/osPolicyAssignments([/:]|$)", path):
        return "gcp-osconfig"   # VM Manager: OS Config patch jobs/deployments + OS policy assignments (core/gcp_osconfig_core, state on the VM store)
    if re.match(r"^/v1/projects/[^/]+/(securityPosture/(compute|storage|threats|vulnerabilities|all))$", path):
        return "gcp-posture"   # rule-based posture findings over real VM / firewall / bucket state (core/gcp_posture_core)
    if path.startswith("/v2/entries"):   # Cloud Logging: entries:write / entries:list
        return "gcp-logging"
    if re.match(r"^/v2/projects/[^/]+/(sinks|metrics|logs)([/:]|$)", path):
        return "gcp-logging"
    if re.match(r"^/v2/projects/[^/]+/locations/[^/]+/buckets", path):
        return "gcp-logging"
    if re.match(r"^/v1/projects/[^/]+/locations/[^/]+/recommenders([/:]|$)", path):
        return "gcp-compute-vm"   # Recommender API v1 — recommendations computed from live Compute state (core/gcp_compute_ext_core)
    if path.startswith(("/compute/v1", "/compute/beta")):
        # VPC resources → the networking core; everything else (instances, disks, images,
        # templates, groups, health checks…) → the VM core.
        if re.search(r"/(networks|subnetworks|firewalls|routes|addresses|routers|firewallPolicies|packetMirrorings|usableSubnetworks)(/|$|\?|:)", path):
            return "gcp-compute"
        # Shared VPC (XPN) project-level custom methods: /compute/v1/projects/{p}/enableXpnHost etc.
        if re.search(r"/projects/[^/]+/(enableXpnHost|disableXpnHost|enableXpnResource|disableXpnResource|listXpnHosts|getXpnResources)$", path):
            return "gcp-compute"
        return "gcp-compute-vm"
    # Private Service Connection (servicenetworking.googleapis.com): no /projects/ segment —
    # the project is resolved from the `network` link in the body/query.
    if path.startswith("/v1/services/servicenetworking.googleapis.com/connections"):
        return "gcp-compute"
    if path.startswith(("/sql/v1beta4", "/sql/v1")):
        return "gcp-cloudsql"
    # Cloud SQL Admin v1 on its own host (sqladmin.googleapis.com/v1/projects/{p}/instances …): the Python/Java/JS
    # clients built from the v1 discovery document send no /sql prefix, so claim the unambiguous roots
    # (instances, tiers) — nothing else simulated lives at /v1/projects/{p}/instances or /tiers.
    if re.match(r"^/(v1|v1beta4)/projects/[^/]+/(instances|tiers)([/:?]|$)", path):
        return "gcp-cloudsql"
    if path == "/v3/uptimeCheckIps":   # Cloud Monitoring API v3 (global, no project)
        return "gcp-monitoring"
    # Resource Manager's projects.create / projects.search (no project id in the path yet).
    if path == "/v3/projects" or path.startswith("/v3/projects:search"):
        return "gcp-resourcemanager"
    m = re.match(r"^/v3/projects/[^/]+(/.*)?$", path)
    if m:
        # Bare "/v3/projects/{id}" is Resource Manager's GetProject/UpdateProject;
        # anything with a sub-resource after the project id is Cloud Monitoring
        # (alertPolicies, metricDescriptors, timeSeries, …).
        return "gcp-monitoring" if m.group(1) else "gcp-resourcemanager"
    if path.startswith(("/v3/tagKeys", "/v3/tagValues", "/v3/tagBindings", "/v3/folders")):
        return "gcp-resourcemanager"
    # Deny policies (IAM Deny API): /v2/policies/{attachmentPoint}/denypolicies[/…]
    if re.match(r"^/v2/policies/[^/]+/denypolicies(/.*)?$", path):
        return "gcp-iam"
    # STS (sts.googleapis.com): federated token exchange + introspection
    if path in ("/v1/token", "/v1/introspect"):
        return "gcp-iam"
    # Predefined roles catalog (no project scope): /v1/roles
    if path.startswith("/v1/roles"):
        return "gcp-iam"
    # Asset Inventory search, Security Insights and Identity-Aware Proxy resources —
    # all project-scoped IAM & Admin sub-features that don't fit the generic
    # "/serviceAccounts" / "/roles" checks below.
    if re.match(r"^/v1/projects/[^/]+:searchAllResources$", path):
        return "gcp-iam"
    if re.match(r"^/v1/projects/[^/]+/locations/global/insights$", path):
        return "gcp-iam"
    if re.match(r"^/v1/projects/[^/]+/iap_web(/|:|$)", path):
        return "gcp-iam"
    # Organizations, Cloud Identity Groups, Workforce Identity Federation pools and
    # Principal Access Boundary policies/bindings — org-scoped resources Resource
    # Manager backs (every project has an implicit backing organization; see
    # gcp_resourcemanager_core.get_or_create_default_org).
    if path.startswith("/v3/organizations"):
        return "gcp-resourcemanager"
    if path.startswith("/v1/groups"):
        return "gcp-resourcemanager"
    if path.startswith("/v1/locations/global/workforcePools"):
        return "gcp-resourcemanager"
    if re.match(r"^/v1/projects/[^/]+/locations/[^/]+/(reportConfigs|reportDetails)([/:?]|$)", path):
        return "gcp-gcs"   # storageinsights.googleapis.com inventory reports (core/gcp_storageinsights_core via gcp_storage_core)
    if re.match(r"^/v1/projects/[^/]+/locations/global/connectivityTests([/:?]|$)", path):
        return "gcp-compute"   # Network Intelligence Center Connectivity Tests → netsim via the VPC core
    if re.search(r"^/v1/projects/[^/]+/locations/[^/]+/internalRanges([/:?]|$)", path):
        return "gcp-compute"   # networkconnectivity.googleapis.com Internal Range Allocator
    if re.search(r"^/v1/projects/[^/]+/locations/[^/]+/connectors([/:?]|$)", path):
        return "gcp-compute"   # vpcaccess.googleapis.com Serverless VPC Access connectors
    if re.search(r"^/v1/projects/[^/]+/(dashboards|snoozes)([/:]|$)", path):   # Dashboards / Snoozes APIs (v1)
        return "gcp-monitoring"
    # The /v1/projects/* family — gate on /projects/ so Azure's root /secrets,
    # /keys, /topics never collide (GCP always scopes these under a project).
    if gcp_hub.is_hub_path(path):
        return "gcp-hub"
    if "/projects/" in path:
        if re.search(r"^/v1/projects/[^/]+/locations/[^/]+/instances([/:]|$)", path):
            return "gcp-redis"
        if re.search(r"/locations/[^/]+/(entitlements|settings|notifications)([/?]|$)", path) and "/workloadIdentityPools" not in path:
            return "gcp-pam"
        if "workloadIdentityPools" in path:
            return "gcp-iam"
        if re.search(r"^/v1(beta1)?/projects/[^/]+/(locations|zones)/[^/]+/(clusters|operations|serverConfig|backupPlans|memberships)([/:]|$)", path):
            return "gcp-container"
        if re.search(r"/locations/[^/]+/jobs([/:]|$)", path) or re.search(r"^/v1(beta1)?/projects/[^/]+/locations/?$", path):
            return "gcp-cloudscheduler"
        if gcp_ds.is_datastore_path(path):
            return "gcp-datastore"
        if gcp_eventarc.is_eventarc_path(path):
            return "gcp-eventarc"
        if re.search(r"^/v1(beta1)?/projects/[^/]+/locations/[^/]+/backups([/:]|$)", path):
            return "gcp-firestore"
        if "/locations/" in path and ("/repositories" in path or "/operations/" in path):
            return "gcp-artifactregistry"
        if re.search(r"^/v1/projects/[^/]+/projectSettings$", path):
            return "gcp-artifactregistry"
        if re.search(r"^/v1(beta1)?/projects/[^/]+/databases($|[/:])", path) \
                or re.search(r"^/v1/projects/[^/]+(/(rulesets|releases)([/?]|$)|:test$)", path.split("?", 1)[0]):
            return "gcp-firestore"
        if "/keyRings" in path or "/keyHandles" in path or "autokeyConfig" in path:
            return "gcp-kms"
        if "/secrets" in path:
            return "gcp-secretmanager"
        if "/topics" in path or "/subscriptions" in path or "/snapshots" in path or "/schemas" in path:
            return "gcp-pubsub"
        if re.search(r"^/v1/projects/[^/]+/serviceAccounts/[^/:]+:(generateAccessToken|generateIdToken|signBlob|signJwt)$", path):
            return "gcp-iamcredentials"
        if "/serviceAccounts" in path or path.endswith(
                (":getIamPolicy", ":setIamPolicy", ":testIamPermissions")):
            return "gcp-iam"
        if re.search(r"^/v2/projects/[^/]+/(policies(:simulate)?|simulations)(/|$)", path):
            return "gcp-resourcemanager"
        if re.search(r"^/v1/projects/[^/]+/roles(/|$)", path):
            return "gcp-iam"
        if re.search(r"^/v1/projects/[^/]+/contacts(/|$)", path):
            return "gcp-resourcemanager"
        if re.search(r"^/v1/projects/[^/]+/policyActivity$", path):
            return "gcp-iam"
    return None


from core import azure_blob_core as az_blob
from core.azure_blob_core import AzureBlobStore
from core import azure_cosmos_core as az_cosmos
from core.azure_cosmos_core import CosmosStore
from core import azure_keyvault_secrets_core as az_kvsec
from core import azure_keyvault_keys_core as az_kvkeys
from core import azure_keyvault_certificates_core as az_kvcerts
from core import azure_appconfiguration_core as az_appconfig
from core import azure_queue_core as az_queue
from core.azure_queue_core import AzureQueueStore
from core import azure_table_core as az_table
from core.azure_table_core import AzureTableStore
from core.azure_arm_core import (AzureArm, keyvault_network_denied, keyvault_access_denied,
                                  classify_keyvault_operation, CALLER_PRINCIPAL_ID,
                                  acr_network_denied, acr_retention_days)
from core import azure_servicebus_core as az_sb
from core import eventbridge_core as events
from core import scheduler_core as sched
from core import logs_core as logs
from core import lambda_core as lam
from core import apigateway_core as apigw
from core import apigatewayv2_core as apigw2
from core import apigatewayv2_gateway as apigw2_gw
from core import ssm_core as ssm
from core import stepfunctions_core as sfn
from core import vpc_core as vpc
from core import autoscaling_core as asg
from core import ram_core as ram
from core import netfw_core as netfw
from core import dnsfw_core as dnsfw
from core import organizations_core as orgs
from core import dlm_core as dlm
from core import kinesis_core as kinesis
from core import cloudwatch_core as cw
from core import azure_sql_core as az_sql
from core import azure_iam_core as az_iam
from core import azure_appconfiguration_core as az_appcfg
from core import azure_dns_core as az_dns
from core import azure_acr_core as az_acr
from core import ecr_core
from core import gcp_scc_core
from core.azure_acr_core import AcrRegistryStore
from core import azure_graph_core as az_graph
import types as _types


# The offline appliance serves Azure Storage per account at /azure-data/{blob|queue}/{account}
# (core/azure_dataplane.py); Nano has one Azurite-style account. Accept the offline form too,
# so one connection string works on both.
_AZ_DATA_ALIAS = re.compile(r"^/azure-data/(?:blob|queue)/[^/?]+")


def _azure_data_alias(path):
    m = _AZ_DATA_ALIAS.match(path or "")
    return "/devstoreaccount1" + path[m.end():] if m else path


def _azure_service(path, lheaders, query):
    """Route an Azure data-plane request. Azure carries no SigV4; we read the
    x-ms-* headers, the ?api-version / ?restype / ?comp query, and the path
    shape. Known limits: over a single relay we can't see the .blob/.queue host,
    so root `?comp=list` (list-containers vs list-queues) defaults to blob."""
    query = query or {}
    # Microsoft Graph (Entra ID): unambiguous `/v1.0/...` or `/beta/...` prefix, checked
    # first so it never falls through to a data-plane guess below. The oauth2/v2.0/token
    # endpoint (real Azure AD hostname is login.microsoftonline.com, not graph.microsoft.com,
    # but this relay has no per-host routing) is claimed the same way, by its unambiguous
    # path shape, so Entra's client-credentials sign-in reaches az_graph.dispatch() too.
    if path.startswith("/v1.0/") or path.startswith("/beta/"):
        return "az-graph"
    p0 = path.split("?", 1)[0]
    if re.match(r"^/openai/(deployments/[^/]+/)?(chat/completions|completions|embeddings)$|^/openai/v1/", p0):
        return "az-openai"   # Azure OpenAI data plane -> core/ai_models_core (deployment must exist in the ARM state)
    if re.search(r"/oauth2(/v2\.0)?/token$", p0):
        return "az-graph"
    p = path
    if p.startswith("/devstoreaccount1/"):     # Azurite account prefix
        p = p[len("/devstoreaccount1"):]
    elif p == "/devstoreaccount1":
        p = "/"
    # Container Registry data plane: the OCI/Docker Registry v2 push+pull wire (`docker push`,
    # `az acr`, oras/crane) and the ACR REST repository-metadata extension — both live on the
    # registry's own host (no SigV4, no api-version). "/v2/projects/..." and "/v2/entries" are
    # GCP (already routed away by _gcp_service above); "/v2/apis", "/v2/domainnames", … are the
    # AWS API Gateway V2 control plane (routed later in service_of) — so only the specific OCI
    # Distribution shapes are claimed here, not every "/v2/..." path.
    if p.startswith("/acr/v1/") or p == "/acr/v1":
        return "az-acr"
    if p == "/v2" or p == "/v2/" or p == "/v2/_catalog":
        return "az-acr"
    v2segs = [s for s in p.split("/") if s]
    if len(v2segs) >= 3 and v2segs[0] == "v2" and (
            v2segs[-2] == "manifests" or (v2segs[-2] == "tags" and v2segs[-1] == "list")
            or v2segs[-2] == "blobs" or (len(v2segs) >= 4 and v2segs[-3] == "blobs" and v2segs[-2] == "uploads")):
        return "az-acr"
    apiv = ("api-version" in query) or ("api-version=" in path)
    # Key Vault (data plane): root /keys or /secrets WITH api-version (GCP secrets
    # live under /v1/projects/…; a plain S3 bucket named "keys" has no api-version).
    # App Configuration (data plane) shares the bare root "/keys" with Key Vault (its
    # GET /keys lists distinct key NAMES used across key-values, vs Key Vault's full
    # keys CRUD) — disambiguated by api-version shape: Key Vault sends "7.x"
    # (azure_keyvault_keys_core.API_VERSION), App Configuration sends a dated version
    # ("2023-11-01", azure_appconfiguration_core.DATA_API_VERSION) or the legacy "1.0".
    if apiv and "/projects/" not in p:
        s0 = p.lstrip("/").split("/", 1)[0]
        m = re.search(r"api-version=([^&]+)", path)
        av = query.get("api-version") or (m.group(1) if m else "")
        if s0 == "keys" and not re.match(r"^\d+\.\d+$", str(av)):
            return "az-appconfig"
        if s0 in ("keys", "deletedkeys"):
            return "az-kv-keys"
        if s0 in ("secrets", "deletedsecrets"):
            return "az-kv-secrets"
        if s0 == "certificates":
            return "az-kv-certs"
        if s0 in ("kv", "labels", "locks", "revisions", "snapshots", "operations"):
            return "az-appconfig"
    # Front Door / CDN edge (core/azure_cdn_edge_core via the blob core) and the Cosmos Data Migration extension.
    if p.startswith("/_edge/"):
        return "az-blob"
    if p.startswith("/vyomi/migrations"):
        return "az-cosmos"
    # Cosmos DB: /dbs path or the documentdb headers.
    if p.startswith("/dbs") or any(k.startswith("x-ms-documentdb") for k in lheaders):
        return "az-cosmos"
    # Table storage: azure-data-tables always sends `Accept: application/json;odata=...`
    # (Blob/Queue speak XML) and the wire shape — the "Tables" collection name and the
    # parenthesised PartitionKey/RowKey entity key — is distinctive; no blob container or
    # queue name (lowercase-only) can look like it.
    accept = lheaders["accept"] if "accept" in lheaders else ""
    tsegs = [s for s in p.split("/") if s]
    if "odata" in accept.lower() or (tsegs and (tsegs[0] == "Tables" or tsegs[0].startswith("Tables(") or "(" in tsegs[0])):
        return "az-table"
    # Blob / Queue: identified by the x-ms-* storage headers.
    if "x-ms-version" in lheaders or "x-ms-blob-type" in lheaders:
        if "/messages" in p:
            return "az-queue"
        if "x-ms-blob-type" in lheaders or query.get("restype") == "container":
            return "az-blob"
        segs = [s for s in p.split("/") if s]
        if len(segs) >= 2:          # /{container}/{blob}
            return "az-blob"
        if len(segs) == 1:          # /{queue} create/delete/metadata (blob container ops carry restype)
            # …unless it is a path-style account root `/{account}?comp=list` whose
            # SharedKey authorization names that account (list containers).
            m = re.match(r"^\s*SharedKey(?:Lite)?\s+([^:\s]+):", lheaders.get("authorization", "") or "", re.I)
            if m and m.group(1) == segs[0] and query.get("comp") == "list":
                return "az-blob"
            return "az-queue"
        return "az-blob"            # root ?comp=list → default to containers
    return None

# SigV4 credential scope: "Credential=AKID/20230626/us-east-1/<service>/aws4_request"
_CRED_RE = re.compile(r"Credential=[^/]+/[^/]+/[^/]+/([^/,]+)/aws4_request")
# The AKID itself — sent in clear in the Credential scope regardless of signature
# verification (Vyomi doesn't verify SigV4). A real aws-cli/SDK caller configured with
# an IAM user's OWN access key (CreateAccessKey) is attributable this way; the console's
# fixed operator credential ("VYOMICONSOLE") and unsigned/placeholder test credentials are
# not, since they don't match any store.iam.access_keys entry (see iam_core.record_activity).
_AKID_RE = re.compile(r"Credential=([^/]+)/")

# AWS signing-name → our core key. (S3 falls through as the default.)
_SIGNING = {
    "dynamodb": "dynamodb", "dax": "dax", "kms": "kms", "secretsmanager": "secretsmanager",
    "sqs": "sqs", "sns": "sns", "iam": "iam", "rds": "rds", "redshift": "redshift", "s3": "s3",
    "rds-data": "rds-data",   # the Aurora HTTP SQL surface (async path)
    "events": "events", "lambda": "lambda", "ec2": "vpc", "kinesis": "kinesis", "monitoring": "cloudwatch", "logs": "logs", "states": "stepfunctions",
    "autoscaling": "asg",
    "dlm": "dlm",
    "cloudtrail": "cloudtrail",   # minimal CloudTrail (trails + S3 data-event selectors) -> core/s3_ext_core via the S3 store
    "vpc-lattice": "vpc-lattice",   # VPC Lattice control plane (rest-json /servicenetworks, /services, /targetgroups, ...) -> core/vpc_lattice_core over the EC2 model
    "mgn": "mgn",   # Application Migration Service (rest-json POST /<Operation>) -> core/mgn_core over the shared EC2 model
    "xray": "xray",   # AWS X-Ray (rest-json /TraceSegments, /Traces, /TraceSummaries, /ServiceGraph) -> core/xray_core over the Step Functions store's trace bag
    "rbin": "rbin",   # EC2 Recycle Bin (rest-json /rules...) -> core/ec2_ops_core.rbin_dispatch over the shared EC2 model
    "securityhub": "securityhub", "guardduty": "guardduty",   # Security Hub + GuardDuty (rest-json) -> core/secscan_core over the S3 store's persisted account bag
    "codeconnections": "codeconnections", "codestar-connections": "codeconnections",   # CodeConnections-lite + CloudFormation Git sync (JSON 1.0) -> core/aws_codeconn_core over the S3 store's account bag + the CFN core
    "schemas": "schemas",   # EventBridge Schemas (rest-json /v1/registries, /v1/discoverers) -> core/eventbridge_schemas_core via the EventBridge store
    "aws-marketplace": "marketplace",   # AWS Marketplace (Vyomi SaaS spaces + AMI products; rest-json) -> core/marketplace_core over the S3 + EC2 models
    "s3files": "s3files", "fsx": "fsx",   # S3 Files (rest-json) + FSx for OpenZFS with S3 access points (JSON 1.1) -> core/s3files_core over the S3 + EC2 models
    "ec2-instance-connect": "eic",   # EC2 Instance Connect SendSSHPublicKey (JSON 1.1) -> core/ec2_instance_connect_core over the EC2 model
    "application-autoscaling": "appas",   # Application Auto Scaling (DynamoDB) -> core/appautoscaling_core over the DynamoDB store
    "cloudfront": "cloudfront",   # CloudFront public keys + key groups (rest-xml /2020-05-31/...) -> core/cloudfront_keys_core via the S3 store
    "savingsplans": "savingsplans",   # Savings Plans (rest-json POST /<Operation>) + EC2 coverage/capacity views -> core/savingsplans_core over the EC2 model
    "bedrock-agentcore": "agentcore",   # Bedrock AgentCore control plane + gateway MCP endpoint -> core/bedrock_agents_core (S3 + Lambda stores)
    "glue": "glue", "redshift-data": "redshift-data",
    "dms": "dms", "bedrock": "bedrock",   # Bedrock runtime + foundation-model catalogue -> core/ai_models_core over the local-LLM seam (core/llm_core)
    "ecr": "ecr", "inspector2": "inspector2",   # Amazon ECR control plane + Inspector2 findings -> core/ecr_core over the S3 store (images/layers live in the simulator S3)
    "backup": "backup",   # AWS Backup subset (region settings + DynamoDB copy jobs) -> core/backup_core over the DynamoDB + S3 stores
    "vyomi-reservations": "vyomi-reservations",   # Vyomi-only: DynamoDB reserved capacity + RDS capacity reservations (rest-json POST /<Operation>) -> core/reservations_core over the DDB + RDS stores
    "networkmanager": "networkmanager",   # AWS Network Manager (rest-json /global-networks...) -> core/networkmanager_core over the S3 account bag + the EC2 model (transit gateways)
    "imagebuilder": "imagebuilder",   # EC2 Image Builder (rest-json PUT/POST/GET /<Operation>) -> core/imagebuilder_core over the S3 account bag + the EC2 model (AMIs)
    "s3vectors": "s3vectors",   # Amazon S3 Vectors (rest-json POST /<Operation>) -> core/s3_vectors_core via the S3 store
    "s3tables": "s3tables",   # Amazon S3 Tables (rest-json /buckets, /namespaces, /tables, /tag) -> core/s3_tables_core via the S3 store
    "elasticloadbalancing": "elbv2",
    "sts": "sts",
    "cloudformation": "cloudformation",
    "ssm": "ssm", "scheduler": "scheduler", "pipes": "pipes", "ram": "ram", "organizations": "organizations", "ce": "ce",
    "route53resolver": "dnsfw",   # Route 53 Resolver DNS Firewall control plane (core/dnsfw_core)
    "network-firewall": "netfw",   # AWS Network Firewall control plane (core/netfw_core, state in the VPC model)
    "apigateway": "apigateway",   # v1 REST control plane paths with no "/restapis" segment (apikeys, usageplans, clientcertificates, account)
}

# X-Amz-Target prefix → our core key (the JSON-wire services).
_TARGET_PREFIX = {
    "DynamoDB_": "dynamodb", "AmazonDAXV3": "dax", "TrentService": "kms",
    "secretsmanager": "secretsmanager", "AmazonSQS": "sqs", "AWSEvents": "events",
    "Kinesis_20131202": "kinesis",
    "Logs_20140328": "logs",
    "AmazonSSM": "ssm",
    "AWSGlue": "glue", "RedshiftData": "redshift-data",   # Glue zero-ETL integrations + Redshift Data API over the Redshift-lite warehouse -> core/zeroetl_core
    "AmazonDMSv20160101": "dms",   # Database Migration Service between simulator RDS instances -> core/dms_core
    "AWSStepFunctions": "stepfunctions",
    "AWSRAMFrontendService": "ram",
    "NetworkFirewall_20201112": "netfw",
    "Route53Resolver": "dnsfw",
    "com.amazonaws.cloudtrail.v20131101.CloudTrail_20131101": "cloudtrail",
    "AWSOrganizationsV20161128": "organizations",
    "AmazonEC2ContainerRegistry_V20150921": "ecr",   # Amazon ECR
    "AWSInsightsIndexService": "ce",   # Cost Explorer
    "AWSEC2InstanceConnectService": "eic",
    "AnyScaleFrontendService": "appas",   # Application Auto Scaling
    "com.amazonaws.codeconnections.CodeConnections_20231201": "codeconnections",
    "com.amazonaws.codestar.connections.CodeStar_connections_20191201": "codeconnections",
}

# Native JSON content-types the real SDK expects back per service.
_JSON_CT = {
    "dynamodb": "application/x-amz-json-1.0", "dax": "application/x-amz-json-1.1", "kms": "application/x-amz-json-1.1",
    "secretsmanager": "application/x-amz-json-1.1", "sqs": "application/x-amz-json-1.0",
    "events": "application/x-amz-json-1.1", "logs": "application/x-amz-json-1.1",
    "ssm": "application/x-amz-json-1.1", "dms": "application/x-amz-json-1.1",
    "glue": "application/x-amz-json-1.1", "redshift-data": "application/x-amz-json-1.1",
    "stepfunctions": "application/x-amz-json-1.0",
    "ram": "application/x-amz-json-1.1",
    "organizations": "application/x-amz-json-1.1", "ce": "application/x-amz-json-1.1",
    "appas": "application/x-amz-json-1.1", "eic": "application/x-amz-json-1.1",
    "netfw": "application/x-amz-json-1.0", "dnsfw": "application/x-amz-json-1.1",
}

# Query-protocol Action → service, for UNSIGNED query requests (signed ones route
# by credential scope). Small but covers the common verbs of each service.
_QUERY_ACTION = {
    # STS
    "GetCallerIdentity": "sts",
    # SNS
    "CreateTopic": "sns", "DeleteTopic": "sns", "ListTopics": "sns",
    "Subscribe": "sns", "Unsubscribe": "sns", "ListSubscriptions": "sns",
    "ListSubscriptionsByTopic": "sns", "Publish": "sns", "GetTopicAttributes": "sns",
    "SetSubscriptionAttributes": "sns", "GetSubscriptionAttributes": "sns",
    # RDS
    "CreateDBInstance": "rds", "DescribeDBInstances": "rds", "DeleteDBInstance": "rds",
    "ModifyDBInstance": "rds", "StartDBInstance": "rds", "StopDBInstance": "rds",
    "RebootDBInstance": "rds", "CreateDBSnapshot": "rds", "DescribeDBSnapshots": "rds",
    # IAM
    "CreateUser": "iam", "DeleteUser": "iam", "ListUsers": "iam", "GetUser": "iam",
    "CreateRole": "iam", "DeleteRole": "iam", "ListRoles": "iam",
    "CreatePolicy": "iam", "DeletePolicy": "iam", "ListPolicies": "iam",
    "AttachUserPolicy": "iam", "DetachUserPolicy": "iam",
    "SimulatePrincipalPolicy": "iam", "CreateGroup": "iam", "ListGroups": "iam",
    # EC2 / VPC (one Query-protocol service; boto3's "ec2" client signs ALL of this)
    "CreateVpc": "vpc", "CreateSubnet": "vpc", "CreateSecurityGroup": "vpc",
    "DescribeSecurityGroups": "vpc",
    "DeleteVpc": "vpc", "DeleteSubnet": "vpc", "DeleteSecurityGroup": "vpc",
    "DetachInternetGateway": "vpc", "DeleteInternetGateway": "vpc",
    "DeleteRouteTable": "vpc", "DeleteNetworkAcl": "vpc",
    "AuthorizeSecurityGroupIngress": "vpc", "AuthorizeSecurityGroupEgress": "vpc",
    "RevokeSecurityGroupIngress": "vpc", "RevokeSecurityGroupEgress": "vpc",
    "DescribeSecurityGroups": "vpc", "DeleteSecurityGroup": "vpc",
    "CreateInternetGateway": "vpc", "DescribeInternetGateways": "vpc", "AttachInternetGateway": "vpc",
    "DetachInternetGateway": "vpc", "DeleteInternetGateway": "vpc",
    "CreateRoute": "vpc", "DeleteRoute": "vpc",
    "DescribeVpcs": "vpc", "DeleteVpc": "vpc", "ModifyVpcAttribute": "vpc", "DescribeVpcAttribute": "vpc",
    "DescribeSubnets": "vpc", "DeleteSubnet": "vpc",
    "CreateSubnetCidrReservation": "vpc", "GetSubnetCidrReservations": "vpc", "DeleteSubnetCidrReservation": "vpc",
    "CreateRouteTable": "vpc", "DescribeRouteTables": "vpc", "DeleteRouteTable": "vpc",
    "AssociateRouteTable": "vpc", "DisassociateRouteTable": "vpc", "ReplaceRouteTableAssociation": "vpc",
    "CreateNetworkAcl": "vpc", "DescribeNetworkAcls": "vpc", "DeleteNetworkAcl": "vpc",
    "CreateNetworkAclEntry": "vpc", "DeleteNetworkAclEntry": "vpc",
    "AssociateNetworkAcl": "vpc", "ReplaceNetworkAclAssociation": "vpc", "AnalyzeReachability": "vpc",
    "ModifySubnetAttribute": "vpc", "ModifyNetworkInterfaceAttribute": "vpc",
    "CreateNetworkInsightsPath": "vpc", "DescribeNetworkInsightsPaths": "vpc", "DeleteNetworkInsightsPath": "vpc",
    "StartNetworkInsightsAnalysis": "vpc", "DescribeNetworkInsightsAnalyses": "vpc", "DeleteNetworkInsightsAnalysis": "vpc",
    "CreateNatGateway": "vpc", "DescribeNatGateways": "vpc", "DeleteNatGateway": "vpc",
    "CreateEgressOnlyInternetGateway": "vpc", "DescribeEgressOnlyInternetGateways": "vpc",
    "DeleteEgressOnlyInternetGateway": "vpc",
    "CreateDhcpOptions": "vpc", "DescribeDhcpOptions": "vpc", "DeleteDhcpOptions": "vpc", "AssociateDhcpOptions": "vpc",
    "DescribeVpcDnsResolution": "vpc",
    "CreateManagedPrefixList": "vpc", "DescribeManagedPrefixLists": "vpc", "DeleteManagedPrefixList": "vpc",
    "CreateVpcPeeringConnection": "vpc", "DescribeVpcPeeringConnections": "vpc",
    "AcceptVpcPeeringConnection": "vpc", "DeleteVpcPeeringConnection": "vpc",
    "CreateRouteServer": "vpc", "DescribeRouteServers": "vpc", "DeleteRouteServer": "vpc",
    "CreateTransitGateway": "vpc", "DescribeTransitGateways": "vpc", "ModifyTransitGateway": "vpc",
    "DeleteTransitGateway": "vpc", "CreateTransitGatewayVpcAttachment": "vpc", "DescribeTransitGatewayVpcAttachments": "vpc",
    "DescribeTransitGatewayAttachments": "vpc", "DeleteTransitGatewayVpcAttachment": "vpc", "ModifyTransitGatewayVpcAttachment": "vpc",
    "CreateTransitGatewayRouteTable": "vpc", "DescribeTransitGatewayRouteTables": "vpc", "DeleteTransitGatewayRouteTable": "vpc",
    "CreateTransitGatewayRoute": "vpc", "DeleteTransitGatewayRoute": "vpc", "SearchTransitGatewayRoutes": "vpc",
    "AssociateTransitGatewayRouteTable": "vpc", "DisassociateTransitGatewayRouteTable": "vpc", "EnableTransitGatewayRouteTablePropagation": "vpc",
    "DisableTransitGatewayRouteTablePropagation": "vpc", "GetTransitGatewayRouteTableAssociations": "vpc", "GetTransitGatewayRouteTablePropagations": "vpc",
    "CreateCustomerGateway": "vpc", "DescribeCustomerGateways": "vpc", "DeleteCustomerGateway": "vpc", "CreateVpnGateway": "vpc", "DescribeVpnGateways": "vpc", "AttachVpnGateway": "vpc", "DetachVpnGateway": "vpc", "DeleteVpnGateway": "vpc", "CreateVpnConnection": "vpc", "DescribeVpnConnections": "vpc", "DeleteVpnConnection": "vpc", "CreateVpnConnectionRoute": "vpc", "DeleteVpnConnectionRoute": "vpc", "ModifyVpnTunnelOptions": "vpc", "ModifyVpnConnectionOptions": "vpc", "EnableVgwRoutePropagation": "vpc", "DisableVgwRoutePropagation": "vpc",
    "CreateClientVpnEndpoint": "vpc", "DescribeClientVpnEndpoints": "vpc", "ModifyClientVpnEndpoint": "vpc", "DeleteClientVpnEndpoint": "vpc", "AssociateClientVpnTargetNetwork": "vpc", "DisassociateClientVpnTargetNetwork": "vpc", "DescribeClientVpnTargetNetworks": "vpc", "AuthorizeClientVpnIngress": "vpc", "RevokeClientVpnIngress": "vpc", "DescribeClientVpnAuthorizationRules": "vpc", "CreateClientVpnRoute": "vpc", "DeleteClientVpnRoute": "vpc", "DescribeClientVpnRoutes": "vpc", "DescribeClientVpnConnections": "vpc", "TerminateClientVpnConnections": "vpc", "CreateVpnConcentrator": "vpc", "DescribeVpnConcentrators": "vpc", "DeleteVpnConcentrator": "vpc",
    "AssociateVpcCidrBlock": "vpc", "DisassociateVpcCidrBlock": "vpc",
    "CreateTrafficMirrorTarget": "vpc", "DescribeTrafficMirrorTargets": "vpc", "DeleteTrafficMirrorTarget": "vpc", "CreateTrafficMirrorFilter": "vpc", "DescribeTrafficMirrorFilters": "vpc", "DeleteTrafficMirrorFilter": "vpc", "ModifyTrafficMirrorFilterNetworkServices": "vpc", "CreateTrafficMirrorFilterRule": "vpc", "DescribeTrafficMirrorFilterRules": "vpc", "ModifyTrafficMirrorFilterRule": "vpc", "DeleteTrafficMirrorFilterRule": "vpc", "CreateTrafficMirrorSession": "vpc", "DescribeTrafficMirrorSessions": "vpc", "ModifyTrafficMirrorSession": "vpc", "DeleteTrafficMirrorSession": "vpc",
    "CreateTransitGatewayPolicyTable": "vpc", "DescribeTransitGatewayPolicyTables": "vpc", "DeleteTransitGatewayPolicyTable": "vpc", "AssociateTransitGatewayPolicyTable": "vpc", "DisassociateTransitGatewayPolicyTable": "vpc", "GetTransitGatewayPolicyTableAssociations": "vpc", "GetTransitGatewayPolicyTableEntries": "vpc", "CreateTransitGatewayMulticastDomain": "vpc", "DescribeTransitGatewayMulticastDomains": "vpc", "DeleteTransitGatewayMulticastDomain": "vpc", "AssociateTransitGatewayMulticastDomain": "vpc", "DisassociateTransitGatewayMulticastDomain": "vpc", "GetTransitGatewayMulticastDomainAssociations": "vpc", "SearchTransitGatewayMulticastGroups": "vpc", "RegisterTransitGatewayMulticastGroupMembers": "vpc", "RegisterTransitGatewayMulticastGroupSources": "vpc", "DeregisterTransitGatewayMulticastGroupMembers": "vpc", "DeregisterTransitGatewayMulticastGroupSources": "vpc", "CreateTransitGatewayMeteringPolicy": "vpc", "DescribeTransitGatewayMeteringPolicies": "vpc", "DeleteTransitGatewayMeteringPolicy": "vpc", "ModifyTransitGatewayMeteringPolicy": "vpc", "CreateTransitGatewayMeteringPolicyEntry": "vpc", "DeleteTransitGatewayMeteringPolicyEntry": "vpc", "GetTransitGatewayMeteringPolicyEntries": "vpc",
    "CreateFlowLogs": "vpc", "DescribeFlowLogs": "vpc", "DeleteFlowLogs": "vpc",
    "RunInstances": "vpc", "DescribeInstances": "vpc", "StartInstances": "vpc",
    "StopInstances": "vpc", "TerminateInstances": "vpc", "RebootInstances": "vpc",
    "ModifyInstanceAttribute": "vpc", "MonitorInstances": "vpc", "UnmonitorInstances": "vpc",
    "DescribeInstanceTypes": "vpc", "DescribeAvailabilityZones": "vpc",
    "CreateImage": "vpc", "DescribeImages": "vpc", "DeregisterImage": "vpc",
    "CopyImage": "vpc", "ModifyImageAttribute": "vpc",
    "CreateVolume": "vpc", "DescribeVolumes": "vpc", "AttachVolume": "vpc",
    "DetachVolume": "vpc", "DeleteVolume": "vpc", "ModifyVolume": "vpc",
    "CreateSnapshot": "vpc", "DescribeSnapshots": "vpc", "DeleteSnapshot": "vpc", "CopySnapshot": "vpc",
    "CreateKeyPair": "vpc", "ImportKeyPair": "vpc", "DescribeKeyPairs": "vpc", "DeleteKeyPair": "vpc",
    "AllocateAddress": "vpc", "DescribeAddresses": "vpc", "AssociateAddress": "vpc",
    "DisassociateAddress": "vpc", "ReleaseAddress": "vpc",
    "CreateNetworkInterface": "vpc", "DescribeNetworkInterfaces": "vpc",
    "DeleteNetworkInterface": "vpc", "AttachNetworkInterface": "vpc", "DetachNetworkInterface": "vpc",
    "CreatePlacementGroup": "vpc", "DescribePlacementGroups": "vpc", "DeletePlacementGroup": "vpc",
    "CreateLaunchTemplate": "vpc", "DescribeLaunchTemplates": "vpc", "DeleteLaunchTemplate": "vpc",
    "CreateTags": "vpc", "DeleteTags": "vpc", "DescribeTags": "vpc",
    "GetEbsEncryptionByDefault": "vpc", "EnableEbsEncryptionByDefault": "vpc",
    "DisableEbsEncryptionByDefault": "vpc", "GetEbsDefaultKmsKeyId": "vpc",
    "ModifyEbsDefaultKmsKeyId": "vpc", "ResetEbsDefaultKmsKeyId": "vpc",
    # PrivateLink
    "CreateVpcEndpoint": "vpc", "DescribeVpcEndpoints": "vpc", "DeleteVpcEndpoints": "vpc",
    "CreateVpcEndpointServiceConfiguration": "vpc", "DescribeVpcEndpointServiceConfigurations": "vpc",
    "DeleteVpcEndpointServiceConfigurations": "vpc", "ModifyVpcEndpointServicePermissions": "vpc",
    "DescribeVpcEndpointConnections": "vpc", "AcceptVpcEndpointConnections": "vpc",
    "RejectVpcEndpointConnections": "vpc",
    # Network Access Analyzer
    "CreateNetworkInsightsAccessScope": "vpc", "DescribeNetworkInsightsAccessScopes": "vpc",
    "DeleteNetworkInsightsAccessScope": "vpc", "StartNetworkInsightsAccessScopeAnalysis": "vpc",
    "DescribeNetworkInsightsAccessScopeAnalyses": "vpc", "DescribeNetworkInsightsAccessScopeAnalysisFindings": "vpc",
    # AWS Verified Access
    "CreateVerifiedAccessInstance": "vpc", "DescribeVerifiedAccessInstances": "vpc", "DeleteVerifiedAccessInstance": "vpc",
    "CreateVerifiedAccessTrustProvider": "vpc", "DescribeVerifiedAccessTrustProviders": "vpc",
    "DeleteVerifiedAccessTrustProvider": "vpc", "AttachVerifiedAccessTrustProvider": "vpc",
    "DetachVerifiedAccessTrustProvider": "vpc", "CreateVerifiedAccessGroup": "vpc", "DescribeVerifiedAccessGroups": "vpc",
    "DeleteVerifiedAccessGroup": "vpc", "CreateVerifiedAccessEndpoint": "vpc", "DescribeVerifiedAccessEndpoints": "vpc",
    "DeleteVerifiedAccessEndpoint": "vpc", "VerifyAccessEndpointPolicy": "vpc",
    # VPC console settings
    "GetVpcBlockPublicAccessOptions": "vpc", "ModifyVpcBlockPublicAccessOptions": "vpc",
    "CreateVpcBlockPublicAccessExclusion": "vpc", "DescribeVpcBlockPublicAccessExclusions": "vpc",
    "DeleteVpcBlockPublicAccessExclusion": "vpc",
    # CloudFormation
    "CreateStack": "cloudformation", "UpdateStack": "cloudformation", "DeleteStack": "cloudformation",
    "DescribeStacks": "cloudformation", "ListStacks": "cloudformation",
    "ContinueUpdateRollback": "cloudformation", "UpdateTerminationProtection": "cloudformation",
    "GetTemplate": "cloudformation", "DescribeStackEvents": "cloudformation",
    "DescribeStackResources": "cloudformation", "DescribeStackResource": "cloudformation",
    "ListStackResources": "cloudformation", "ListExports": "cloudformation",
    "ValidateTemplate": "cloudformation",
    "CreateChangeSet": "cloudformation", "DescribeChangeSet": "cloudformation",
    "ExecuteChangeSet": "cloudformation", "DeleteChangeSet": "cloudformation",
    "ListChangeSets": "cloudformation",
    "DetectStackDrift": "cloudformation", "DescribeStackDriftDetectionStatus": "cloudformation",
    "DescribeStackResourceDrifts": "cloudformation",
    "CreateStackSet": "cloudformation", "DescribeStackSet": "cloudformation",
    "ListStackSets": "cloudformation", "DeleteStackSet": "cloudformation",
    "ListStackInstances": "cloudformation", "ListStackRefactors": "cloudformation",
}


# Auto Scaling (Query protocol; signs as `autoscaling`).
for _a in asg.OPERATIONS:
    _QUERY_ACTION.setdefault(_a, "asg")


# SQS legacy Query protocol (unsigned `Action=…` requests; signed ones route by scope).
for _a in ("CreateQueue", "DeleteQueue", "ListQueues", "GetQueueUrl", "GetQueueAttributes",
           "SetQueueAttributes", "SendMessage", "SendMessageBatch", "ReceiveMessage", "DeleteMessage",
           "DeleteMessageBatch", "ChangeMessageVisibility", "ChangeMessageVisibilityBatch", "PurgeQueue",
           "ListQueueTags", "TagQueue", "UntagQueue", "ListDeadLetterSourceQueues"):
    _QUERY_ACTION.setdefault(_a, "sqs")


# ELBv2 (Query protocol; signs as `elasticloadbalancing`). Tag / limit verbs are
# shared with other services, so unsigned requests only route here for the rest.
_AMBIGUOUS_ELB = {"AddTags", "RemoveTags", "DescribeTags", "DescribeAccountLimits"}
for _a in elbv2.OPERATIONS:
    if _a not in _AMBIGUOUS_ELB:
        _QUERY_ACTION.setdefault(_a, "elbv2")
# CloudWatch actions whose names other Query services also use — routed by SigV4 scope only.
_GENERIC_ACTIONS = {"TagResource", "UntagResource", "ListTagsForResource"}


# Azure RBAC role assignments / definitions / checkAccess stay on the IAM store
# (shared with Azure SQL enforcement); every other ARM path goes to AzureArm.
_AUTHZ_IAM = re.compile(r"/providers/microsoft\.authorization/(roleassignments|roledefinitions|checkaccess)", re.I)


class ResourceCollections:
    """Same public shape as wasm/backends/store.ResourceStore ({provider/account/service: {name:
    record}}), so nano_persist snapshots move it between the console and the tunnel."""

    def __init__(self) -> None:
        self.collections: dict = {}


def _execute_api_id(path, lheaders):
    """The HTTP API an invoke-URL request is for: host `{id}.execute-api.<anything>` (as the CLI
    prints it) or the path-style fallback `/apigw/{id}/…` (same as the offline gateway's)."""
    host = (lheaders.get("host", "") or "").split(":", 1)[0].lower()
    if ".execute-api." in host:
        return host.split(".", 1)[0]
    if path.startswith("/apigw/"):
        return path[len("/apigw/"):].split("/", 1)[0].split("?", 1)[0]
    return ""


# A Microsoft.Sql database resource (GET/PUT answer carries its connectionInfo, like offline).
_SQL_DB = re.compile(r"/providers/microsoft\.sql/servers/[^/]+/databases/[^/]+$", re.I)


def _is_arm_path(path):
    """Azure Resource Manager: the subscription list, anything under a
    subscription, the tenant list, and the LRO poll URLs AzureArm hands out.
    Checked before the S3 default so ARM never answers with S3 XML (#176)."""
    p = path.split("?", 1)[0]
    return p in ("/subscriptions", "/tenants") or p.startswith(("/subscriptions/", "/api/azure/operations/"))


def _lower_headers(headers):
    return {str(k).lower(): v for k, v in (headers or {}).items()}


class AwsWireRouter:
    """Holds one in-tab store per service (the single source of truth for the
    relay endpoint) and routes native AWS-wire requests to the proven cores."""
    STRICT_GCP_PROJECT = True   # one project per GCP space; engine conformance scripts set False to use ad-hoc project ids

    def __init__(self, sql_store=None, stores=None):
        # Stores are INJECTABLE (v2.4.0): Nano/relay pass nothing → in-WASM
        # defaults; Pro/Max passes a `stores` map of real backed stores (MinIO,
        # Postgres, Vault, NATS) behind the identical seam. `sql_store` kept for
        # back-compat (the browser PGlite path).
        s = stores or {}
        # The console's generic catalog store (EC2 instances, …) — wasm/backends/store.ResourceStore,
        # registered in the shared registry as "resources". The tunnel never builds one, so give the
        # registry a plain holder of the same shape: nano_persist then restores the console's
        # resources into it, and DescribeInstances reads them. Looked up per request, because the
        # console swaps in its full ResourceStore (adopting this one's contents) when it boots.
        if isinstance(stores, dict):
            stores.setdefault("resources", ResourceCollections())
        self._stores = s
        self.s3 = s.get("s3") or InMemoryObjectStore()
        self.ddb = s.get("ddb") or InMemoryNoSqlStore()
        self.dax = s.get("dax") or dax.DaxStore()
        self.dax.ddb_store = self.ddb   # real read-through/write-through into the fronted table
        self.kms = s.get("kms") or InMemoryKeyStore()
        self.sec = s.get("sec") or InMemoryKvStore()
        self.rds = s.get("rds") or sql_store or InMemorySqlStore()
        self.iam = s.get("iam") or InMemoryIamStore()
        self.msg = s.get("msg") or InMemoryMessagingStore()   # SHARED by sqs + sns (fan-out)
        # GCP services — each its own store instance (namespaced from AWS).
        self.gcs = s.get("gcs") or InMemoryObjectStore()
        self.gcp_fs = s.get("gcp_fs") or FirestoreStore()
        self.gcp_kms = s.get("gcp_kms") or InMemoryKeyStore()
        self.gcp_sec = s.get("gcp_sec") or InMemoryKvStore()
        self.gcp_msg = s.get("gcp_msg") or InMemoryMessagingStore()
        self.gcp_msg.gcs_store = self.gcs   # topic ingestion / Cloud Storage subscription delivery read/write real GCS objects

        self.gcp_iam = s.get("gcp_iam") or InMemoryIamStore()
        self.gcp_sql = s.get("gcp_sql") or InMemorySqlStore()
        self.gcp_sched = s.get("gcp_sched") or gcp_sched.CloudSchedulerStore()   # Cloud Scheduler jobs
        self.gcp_gke = s.get("gcp_gke") or gcp_gke.ContainerStore()   # Kubernetes Engine clusters
        self.gcp_vertex = s.get("gcp_vertex") or gcp_vertex.VertexStore()   # Vertex AI resources
        self.gcp_redis = s.get("gcp_redis") or gcp_redis.RedisStore()   # Memorystore for Redis instances
        self.gcp_iamc = s.get("gcp_iamc") or gcp_iamc.IamCredentialsStore()   # IAM Service Account Credentials issue log
        self.gcp_mon = s.get("gcp_mon") or gcp_mon.MonitoringStore()   # Cloud Monitoring (policies, channels, metrics, series)
        self.gcp_ar = s.get("gcp_ar") or gcp_ar.ArtifactRegistryStore()
        # The GCP project every GCP request is normalized to (a dict, or a callable
        # returning one): Nano's fixed project unless the host injects its own.
        self.gcp_project = s.get("gcp_project") or dict(gcp_proj.NANO_PROJECT)
        self.gcp_logging = s.get("gcp_logging") or gcp_logging.LoggingStore()   # Cloud Logging
        self.gcp_logging.mon_store = self.gcp_mon   # Logs Storage "Create usage alert" mirrors live byte/entry counts into Monitoring
        self.gcp_msg.mon_store = self.gcp_mon   # Pub/Sub topic/subscription Metrics tabs mirror live publish/backlog counts into Monitoring
        self.gcs.mon_store = self.gcp_mon   # Cloud Storage request-count metering (storage.googleapis.com/api/request_count)
        self.gcp_compute = s.get("gcp_compute") or gcp_compute.ComputeStore()   # VPC: networks, subnets, firewalls, routes, addresses
        self.gcp_compute_vm = s.get("gcp_compute_vm") or gcp_compute_vm.ComputeStore()   # Compute Engine VMs, disks, images, templates
        self.gcp_mon.redis_store = self.gcp_redis   # Memorystore Monitoring metrics derive from real instance state
        self.gcp_mon.compute_vm_store = self.gcp_compute_vm   # Overview "VMs with Ops Agent" + uptime checks targeting a GCE instance read real Compute Engine state
        self.gcp_mon.gcs_store = self.gcs   # Cost Explorer's Cloud Storage line item prices real bucket bytes stored
        self.gcp_rm = s.get("gcp_rm") or gcp_rm.ResourceManagerStore()   # Resource Manager (project, tags, contacts, org policies)
        self.gcp_rm.inputs = self._rm_inputs   # org-policy simulation reads the project's real service accounts / keys / buckets
        self.gcp_pam = s.get("gcp_pam") or gcp_pam.PamStore()   # Privileged Access Manager entitlements
        self.gcp_run = s.get("gcp_run") or gcp_run.RunStore()   # Cloud Run (backs /functions, which the real console folds into it)
        self.gcp_run.ar_push = self._run_ar_push   # source deploys push the built image into the simulated Artifact Registry
        self.gcp_run.pubsub_store = self.gcp_msg    # Eventarc Pub/Sub-sourced triggers validate/create a real subscription
        self.gcp_run.logging_store = self.gcp_logging   # Observability "Logs" — real Cloud Logging entries per invocation
        self.gcp_mon.gke_store = self.gcp_gke   # Cloud Deploy deploys into GKE data planes
        self.gcp_mon.run_store, self.gcp_mon.vm_store = self.gcp_run, self.gcp_compute_vm   # App Hub discovers Cloud Run services + managed instance groups
        self.gcp_run.mon_store = self.gcp_mon       # Observability "Metrics" — real Cloud Monitoring points per invocation
        if getattr(self.gcp_fs, "on_doc_event", None) is None:
            self.gcp_fs.on_doc_event = self._firestore_event   # Eventarc Firestore document triggers fire on real writes
        if getattr(self.gcs, "refs", None) is None:
            self.gcs.refs = self._run_refs   # bucket CMEK keys are checked against real Cloud KMS keys
        if getattr(self.gcs, "on_object_event", None) is None:
            self.gcs.on_object_event = self._gcs_object_event   # Eventarc Cloud Storage triggers fire on real object finalize/delete
        if getattr(self.gcp_sql, "refs", None) is None:
            self.gcp_sql.refs = self._run_refs          # Cloud SQL CMEK keys are checked against real Cloud KMS keys
        if getattr(self.gcp_run, "refs", None) is None:   # a store already wired by its host (offline routes) keeps its own
            self.gcp_run.refs = self._run_refs          # Cloud SQL / KMS / GCS references in a revision template are checked for real
        # Azure data-plane services.
        self.az_blob = s.get("az_blob") or AzureBlobStore()
        self.az_cosmos = s.get("az_cosmos") or CosmosStore()
        self.az_kvsec = s.get("az_kvsec") or InMemoryKvStore()
        self.az_kvkeys = s.get("az_kvkeys") or InMemoryKeyStore()
        self.az_kvcerts = s.get("az_kvcerts") or InMemoryKvStore()
        self.az_queue = s.get("az_queue") or AzureQueueStore()
        self.az_table = s.get("az_table") or AzureTableStore()
        self.az_arm = s.get("az_arm") or AzureArm()   # ARM control plane — read by the blob core for CORS/lifecycle/static-website enforcement
        self.az_arm.acr_store = None   # set below once the ACR store exists (Defender for Containers image scanning)
        self.az_arm.kv_secrets_store = self.az_kvsec   # APIM named values: Key Vault-type listValue resolves against this SAME space's KV secrets
        if getattr(self.az_arm, "sql_store", None) is None:   # Azure SQL export/import: this router's SQL data plane + Blob store
            self.az_arm.sql_store = self.rds
        if getattr(self.az_arm, "blob_store", None) is None:
            self.az_arm.blob_store = self.az_blob
        self.az_sb = s.get("az_sb") or InMemoryMessagingStore()   # Service Bus topics (fan-out)
        self.az_arm = s.get("az_arm") or AzureArm()   # Azure Resource Manager — the console's ARM store
        self.az_acr = s.get("az_acr") or AcrRegistryStore()   # Container Registry repositories/tags/manifests
        self.az_arm.acr_store = self.az_acr
        self.az_graph = s.get("az_graph") or az_graph.GraphStore()   # Microsoft Graph (Entra ID)
        # EventBridge shares the messaging store (rules + SQS delivery); Lambda gets
        # its own lightweight function registry (a namespace the core attaches to).
        # EventBridge shares the messaging store (rule targets deliver into the real SQS/SNS).
        # Not "events": in Nano's registry that key is the cloudsim activity log (nano_events).
        self.events = s.get("eventbridge") or self.msg
        self.sched = s.get("sched") or sched.SchedulerStore()   # EventBridge Scheduler (schedules + groups)
        self.ssm = s.get("ssm") or ssm.SsmStore()   # Systems Manager (Parameter Store, documents, Run Command, …)
        # Nano's registry names these "compute" / "vpc_net" (persisted via their private
        # _lambda_functions / _apigateway_apis / _vpc_model attrs) — use them, else state is lost.
        self.lam = s.get("lam") or s.get("compute") or _types.SimpleNamespace()
        # API Gateway shares the Lambda store so an AWS_PROXY integration can reach
        # the registered functions (the API-GW → Lambda synergy).
        self.apigw = s.get("apigw") or self.lam
        # S3 event notifications: deliver for real into the SAME SQS/SNS/Lambda stores
        # every other native-wire call reaches (the Nano/dev-server counterpart of the
        # offline appliance's own delivery path, which wires its own AppStateObjectStore
        # and never consults these — see object_store.ObjectStore.emit_event).
        self.s3.msg_store, self.s3.lam_store = self.msg, self.lam
        self.kinesis = s.get("kinesis") or kinesis.KinesisStore()   # Kinesis Data Streams
        self.apigwv2 = s.get("apigwv2") or apigw2.ApiGwV2Store()   # API Gateway V2 (HTTP/WebSocket APIs)
        from core import observability_core as _obsc0
        self.obs = s.get("obs") or _obsc0.ObsStore()           # shared request-telemetry recorder + OTLP trace/metric store
        from core import azure_monitor_core as _azmon0
        _azmon0.request_telemetry = lambda acct, _o=self.obs: _obsc0.azure_storage_request_metrics(_o, acct)   # storage Availability/latency from measured requests
        _azmon0.resource_metric_defs = _obsc0.azure_metric_defs
        _azmon0.resource_series = lambda *a, _o=self.obs: _obsc0.azure_series(_o, *a)   # per-resource request/latency/error metrics
        self.cw = s.get("cw") or cw.CloudWatchStore()          # CloudWatch metrics / alarms / dashboards
        self.cw.msg_store, self.cw.lam_store = self.msg, self.lam   # real SNS / Lambda alarm actions
        self.vpc = s.get("vpc") or s.get("vpc_net") or _types.SimpleNamespace()   # EC2/VPC network model
        self.vpc.cw_store = self.cw   # real StatusCheckFailed metrics (ec2.instances.monitoring / .alarms-metrics)
        self.cw.vpc_store = self.vpc  # real EC2 alarm actions (aws.cloudwatch.alarms.actions.ec2)
        self.asg = s.get("asg") or asg.AutoScalingStore()   # EC2 Auto Scaling groups + scaling policies
        self.asg.vpc_store = self.vpc   # scaling really launches/terminates real EC2 instances
        self.cw.asg_store = self.asg    # real Auto Scaling alarm actions (aws.cloudwatch.alarms.actions.compute)
        self.kinesis.cw_store = self.cw   # real AWS/Kinesis metrics (kinesis.stream.monitoring-metrics)
        self.rds.cw_store = self.cw   # real DatabaseConnections/ReadIOPS/WriteIOPS metrics (rds.monitoring)
        self.ddb.cw_store = self.cw            # real per-op CloudWatch metrics (aws.dynamodb.monitor)
        self.ddb.lam_store = self.lam          # DynamoDB Streams -> Lambda event-source mappings (dynamodb.lambda-triggers)
        self.ddb.kinesis_store = self.kinesis  # real Kinesis Data Streams destination (aws.dynamodb.kinesis)
        self.s3.events_store = self.events   # S3 -> EventBridge notifications (default bus)
        self.s3.cw_store = self.cw    # real AWS/S3 request metrics (s3.bucket.metrics), derived from actual activity
        self.ram = s.get("ram") or _types.SimpleNamespace()   # Resource Access Manager (subnet/SG sharing)
        self.vpc.ram_store = self.ram   # DeleteSubnet/DeleteSecurityGroup refuse while actively shared
        self.ram.vpc_store = self.vpc   # AssociateResourceShare validates the subnet/SG exists
        self.ram.org_store = self.iam   # principals (org / OU ARNs, member accounts) are checked against AWS Organizations (state in the IAM store)
        self.dax.cw_store = self.cw            # real AWS/DAX ItemCache/QueryCache hit/miss metrics
        self.dlm = s.get("dlm") or dlm.DlmStore()   # Data Lifecycle Manager (ec2.lifecycle-manager)
        self.dlm.vpc_store = self.vpc   # policies really create/prune real snapshots + AMIs
        self.logs = s.get("logs") or logs.LogsStore()         # CloudWatch Logs
        # Lambda invocations land in CloudWatch Logs (/aws/lambda/<fn>) like real Lambda.
        if getattr(self.lam, "_log_sink", None) is None:
            def _lambda_log_sink(group, stream, lines, _logs=self.logs):
                import time as _tm
                hdr = "Logs_20140328."
                logs.dispatch(_logs, hdr + "CreateLogGroup", {"logGroupName": group})
                logs.dispatch(_logs, hdr + "CreateLogStream", {"logGroupName": group, "logStreamName": stream})
                now = int(_tm.time() * 1000)
                logs.dispatch(_logs, hdr + "PutLogEvents", {"logGroupName": group, "logStreamName": stream,
                              "logEvents": [{"timestamp": now + i, "message": ln + "\n"} for i, ln in enumerate(lines)]})
            try:
                self.lam._log_sink = _lambda_log_sink
            except Exception:
                pass
        self.logs.lam_store, self.logs.kinesis_store = self.lam, self.kinesis   # real subscription-filter delivery
        self.cw.logs_store = self.logs            # real log-based Contributor Insights rules
        self.msg.cw_store = self.cw               # real AWS/SNS SMS delivery metrics (sns.sms.delivery-statistics)
        self.msg.logs_store = self.logs           # real SNS delivery-status logging (SQSSuccessFeedbackRoleArn/…)
        self.rds.managed_secret_hook = self._rds_managed_secret   # RDS ManageMasterUserPassword -> a Secrets Manager secret OWNED by RDS
        self.sec.owner_hooks = {"rds": self._rds_secret_rotated, "redshift": self._redshift_secret_rotated}
        self.rds.iam_store = self.iam             # RDS IAM role association validates the role + its trust policy
        self.iam.role_usage_probe = self._role_usage_refs   # IAM Role manager: Lambda execution roles + EC2 instance profiles
        self.lam.role_use_hook = lambda role, svc, act: iam.record_role_use(self.iam, role, svc, act)   # Lambda invoke -> role last-used
        self.sec.lam_store = self.lam             # Secrets Manager rotation really invokes the Lambda rotation function
        self.msg.kms_store = self.kms             # EventBridge bus/archive KMS encryption (real Encrypt/Decrypt)
        self.elbv2 = s.get("elbv2") or elbv2.Elbv2Store()
        self.elbv2.vpc_store = self.vpc    # target health reacts to real instance state
        self.vpc.elbv2_store = self.elbv2  # VPC encryption-control audit reads the load balancers
        self.elbv2.cw_store = self.cw      # real AWS/ApplicationELB + AWS/NetworkELB metrics
        self.elbv2.s3_store = self.s3      # trust-store CA bundles are read from Vyomi's own S3
        self.sfn = s.get("sfn") or sfn.StepFunctionsStore()   # Step Functions (state machines + executions)
        self.sfn.logs_store = self.logs           # Step Functions loggingConfiguration -> CloudWatch Logs
        self.cfn = s.get("cfn") or cfn.CloudFormationStore()   # CloudFormation (stacks, change sets, stack sets)

    def _iamc_resolve(self, ident):
        """IAM Credentials: service-account email / uniqueId -> email, or None if unknown
        (IAM core store, then the appliance's console-side IAM state when present)."""
        for email, sa in (getattr(self.gcp_iam, "gcp_service_accounts", None) or {}).items():
            if ident in (email, sa.get("uniqueId")):
                return email
        try:
            from providers.gcp_iam import gcp_iam_state
            for accts in gcp_iam_state.get("service_accounts", {}).values():
                for rec in accts.values():
                    if ident in (rec.get("email"), rec.get("uniqueId")):
                        return rec["email"]
        except Exception:
            pass
        return None

    def _sched_invoke(self, kind, d):
        """Cloud Scheduler firing a job: deliver a pubsub target via the Pub/Sub core, or —
        for an httpTarget that names a Cloud Run job's own `:run` endpoint — actually run that
        job (the one HTTP destination this appliance can call without a network); any other
        httpTarget is recorded as attempted only. Returns True, or an error string recorded on
        the job's status."""
        if kind == "http":
            m = _SCHED_RUN_JOB_RE.search(d.get("uri") or "")
            if not m:
                return True
            project, location, jid = m.groups()
            try:
                op = gcp_run.run_job(self.gcp_run, project, location, jid, {})
                eid = op["response"]["name"].rsplit("/", 1)[-1]
                self._run_log("job", project, location, jid,
                              "Execution %s started (%d task(s))" % (eid, op["response"]["taskCount"]))
            except gcp_run._E as e:
                return e.message
            return True
        if kind != "pubsub":
            return True
        topic = d["topicName"]
        msg = {"messages": [{"data": d.get("data", ""), "attributes": d.get("attributes") or {}}]}
        r = gcp_ps.dispatch(self.gcp_msg, "POST", "/v1/%s:publish" % topic, {}, {}, json.dumps(msg).encode(),
                            on_publish=self._eventarc_deliver)
        return True if r.status < 300 else "Topic %s not found." % topic

    def _secrets_notify(self, topic, event_type, secret_name):
        """Secret Manager version lifecycle event -> a real Pub/Sub publish on the
        configured topic (the SAME gcp_ps.dispatch seam Cloud Scheduler targets use)."""
        msg = {"messages": [{
            "data": base64.b64encode(json.dumps({"secretId": secret_name, "eventType": event_type}).encode()).decode(),
            "attributes": {"eventType": event_type, "secretId": secret_name},
        }]}
        gcp_ps.dispatch(self.gcp_msg, "POST", "/v1/%s:publish" % topic, {}, {}, json.dumps(msg).encode(),
                        on_publish=self._eventarc_deliver)

    def _secrets_log(self, secret_name, event_type, message):
        """Secret Manager lifecycle event -> a real Cloud Logging entry (the Logs tab
        reads these back via entries:list, the same way the real console's audit logs do)."""
        m = re.match(r"^projects/([^/]+)/secrets/([^/]+)$", secret_name)
        if not m:
            return
        project, secret_id = m.groups()
        entry = {
            "logName": f"projects/{project}/logs/secretmanager.googleapis.com%2Factivity",
            "resource": {"type": "secretmanager.googleapis.com/Secret",
                        "labels": {"resource_container": f"projects/{project}", "secret_id": secret_id}},
            "severity": "NOTICE",
            "textPayload": message,
            "labels": {"eventType": event_type},
        }
        gcp_logging.write_entries(self.gcp_logging, None, {"entries": [entry]})

    def _iam_audit_log(self, project, log_type, message):
        """IAM Data Access audit config (Audit logs page) taking effect: a read gated
        by an enabled ADMIN_READ toggle for iam.googleapis.com -> a real Cloud Logging
        entry (the same entries:list the gcp-logs console page and Cloud Logging API
        read back)."""
        entry = {
            "logName": f"projects/{project}/logs/iam.googleapis.com%2Fdata_access",
            "resource": {"type": "project", "labels": {"project_id": project}},
            "severity": "NOTICE",
            "textPayload": message,
            "labels": {"logType": log_type},
        }
        gcp_logging.write_entries(self.gcp_logging, None, {"entries": [entry]})

    def _run_log(self, kind, project, location, rid, message, severity="INFO"):
        """A real Cloud Run mutation (or Eventarc delivery) -> a real Cloud Logging entry,
        the same seam _secrets_log/_iam_audit_log use (the Observability tab's Logs section
        reads these back via entries:list)."""
        restype = "cloud_run_revision" if kind == "service" else "cloud_run_job"
        label_key = "service_name" if kind == "service" else "job_name"
        entry = {
            "logName": "projects/%s/logs/run.googleapis.com%%2F%s" % (project, "requests" if kind == "service" else "executions"),
            "resource": {"type": restype, "labels": {"project_id": project, "location": location, label_key: rid}},
            "severity": severity,
            "textPayload": message,
        }
        gcp_logging.write_entries(self.gcp_logging, None, {"entries": [entry]})

    def hub_inputs(self, project):
        """Live facts for Cloud Hub + Privacy & Security (read from the real stores / Cloud Logging)."""
        def n(x):
            try:
                return len(x)
            except Exception:
                return 0
        pre = "projects/%s/" % project
        res = {}
        def put(k, v):
            if v:
                res[k] = v
        put("Cloud Storage buckets", n(getattr(self.gcs, "buckets", {}) or {}))
        vm = self.gcp_compute_vm
        put("Compute Engine VM instances", sum(1 for k in (getattr(vm, "instances", {}) or {}) if k.startswith(pre)))
        put("Compute Engine disks", sum(1 for k in (getattr(vm, "disks", {}) or {}) if k.startswith(pre)))
        put("Compute Engine snapshots", sum(1 for k in (getattr(vm, "snapshots", {}) or {}) if k.startswith(pre)))
        put("GKE clusters", sum(1 for k in (getattr(self.gcp_gke, "clusters", {}) or {}) if k.startswith(pre)))
        put("Cloud Run services", sum(1 for k in (getattr(self.gcp_run, "services", {}) or {}) if k.startswith(pre)))
        put("Cloud Run jobs", sum(1 for k in (getattr(self.gcp_run, "jobs", {}) or {}) if k.startswith(pre)))
        put("Firestore databases", n(getattr(self.gcp_fs, "databases", {}) or {}))
        put("Pub/Sub topics", sum(1 for k in (getattr(self.gcp_msg, "topics", {}) or {}) if str(k).startswith(pre)))
        keys = [k for k in self.gcp_kms.key_ids() if k.startswith(pre)] if hasattr(self.gcp_kms, "key_ids") else []
        put("Cloud KMS keys", len(keys))
        trg = [t for k, t in (self.gcp_mon.ext or {}).get("eventarc_triggers", {}).items() if k.startswith(pre)] if getattr(self.gcp_mon, "ext", None) else []
        put("Eventarc triggers", len(trg))
        audit = []
        for e in reversed(getattr(self.gcp_logging, "entries", []) or []):
            pp = e.get("protoPayload") or {}
            if e.get("logName", "").startswith("projects/%s/logs/cloudaudit.googleapis.com" % project) and pp.get("methodName"):
                audit.append({"time": e.get("timestamp"), "principal": (pp.get("authenticationInfo") or {}).get("principalEmail", ""),
                              "service": pp.get("serviceName"), "method": pp.get("methodName"), "resource": pp.get("resourceName"),
                              "logType": e["logName"].rsplit("%2F", 1)[-1]})
            if len(audit) >= 500:
                break
        incidents = []
        for k, inc in (getattr(self.gcp_mon, "incidents", {}) or {}).items():
            if k.startswith(pre) and str(inc.get("state", "OPEN")).upper() == "OPEN":
                incidents.append({"name": k, "summary": inc.get("summary") or inc.get("policyName") or k.rsplit("/", 1)[-1], "startTime": inc.get("startTime")})
        uptime = [{"name": k.rsplit("/", 1)[-1], "displayName": (u or {}).get("displayName", "")} for k, u in (getattr(self.gcp_mon, "uptime_checks", {}) or {}).items() if k.startswith(pre)]
        rm = getattr(self.gcp_rm, "org_policies", {}) or {}
        loc = None
        for name, pol in rm.items():
            if name.endswith("constraints/gcp.resourceLocations"):
                vals = []
                for rule in (pol.get("spec") or {}).get("rules", []):
                    vals += ((rule.get("values") or {}).get("allowedValues") or [])
                loc = {"constraint": "constraints/gcp.resourceLocations", "state": "ENFORCED", "allowedValues": vals}
        return {"resources": res, "incidents": incidents, "uptime": uptime, "audit": audit, "eventarc": len(trg),
                "kms_keys": len(keys), "locations": loc, "audit_config": {"dataAccessEnabledServices": []}}

    def _firestore_event(self, db, rel, old, new):
        """A real Firestore document write -> Eventarc Firestore triggers."""
        name = (self.gcp_fs.databases.get(db) or {}).get("name", "projects/-/databases/%s" % db)
        gcp_eventarc.on_firestore_write(self.gcp_mon, self.gcp_run, name.split("/")[1], db, rel, old, new, log_fn=self._run_log)

    def gcp_audit(self, method, path, query, headers, body, status):
        """Describe a served GCP mutation as an Admin Activity audit log entry (core/gcp_audit_core.py) in Cloud
        Logging, then fire Eventarc Cloud Audit Logs triggers on it. Best effort, never raises."""
        try:
            import time as _t
            key = (method.upper(), path.split("?", 1)[0], hash(body), tuple(sorted((str(k), str(v)) for k, v in (query or {}).items())))
            now = _t.monotonic()
            seen = self.__dict__.setdefault("_audit_seen", {})
            if now - seen.get(key, -9) < 1.5:
                return
            seen[key] = now
            if len(seen) > 500:
                seen.clear()
            try:
                bj = json.loads(body.decode()) if body else None
            except Exception:
                bj = None
            entry = gcp_audit.build_entry(method, path, status, query, headers, bj if isinstance(bj, dict) else None)
            if entry is None:
                return
            gcp_logging.write_entries(self.gcp_logging, None, {"entries": [entry]})
            gcp_eventarc.on_audit_entry(self.gcp_mon, self.gcp_run, entry, log_fn=self._run_log)
        except Exception:
            pass

    def _eventarc_deliver(self, topic_full, messages):
        """A real Pub/Sub publish -> deliver to every Cloud Run Eventarc-style trigger
        bound to that topic (see core/gcp_run_core.deliver_event)."""
        gcp_run.deliver_event(self.gcp_run, topic_full, messages, log_fn=self._run_log)
        gcp_eventarc.on_pubsub_publish(self.gcp_mon, self.gcp_run, topic_full, messages, log_fn=self._run_log)

    def _rm_inputs(self):
        """Existing GCP resources an org-policy simulation evaluates (read as a GCP request)."""
        try:
            from core import app_context as _ctx
            tok = _ctx.REQUEST_PROVIDER.set("gcp")
        except Exception:   # Nano: no app_context, the stores are plain
            _ctx, tok = None, None
        try:
            return {"sa_keys": dict(getattr(self.gcp_iam, "gcp_sa_keys", None) or {}),
                    "service_accounts": dict(getattr(self.gcp_iam, "gcp_service_accounts", None) or {}),
                    "buckets": dict(self.gcs.buckets)}
        finally:
            if tok is not None:
                _ctx.REQUEST_PROVIDER.reset(tok)

    def _gcs_object_event(self, bucket, name, event, obj):
        gcp_run.deliver_storage_event(self.gcp_run, bucket, name, event, obj, log_fn=self._run_log)
        gcp_eventarc.on_storage_event(self.gcp_mon, self.gcp_run, bucket, name, event, obj, log_fn=self._run_log)

    def _run_refs(self, kind, *args):
        """Existence of a resource a Cloud Run template references (True/False; None = unknown)."""
        if kind == "sql":
            return gcp_sql._get_instance(self.gcp_sql, args[0], args[1]) is not None
        if kind == "kms":
            try:
                from core import app_context as _ctx
                tok = _ctx.REQUEST_PROVIDER.set("gcp")   # offline GCP stores are provider-scoped
            except Exception:   # Nano: plain stores
                _ctx, tok = None, None
            key = args[0]
            _m = re.match(r"projects/([^/]+)/(.*)$", key)
            if _m:   # the project part may be the number or (Nano) the `vyomi-project` alias of the one project
                _proj = self.gcp_project() if callable(self.gcp_project) else self.gcp_project
                _pid = gcp_proj.resolve(_m.group(1), _proj)
                if _pid:
                    key = f"projects/{_pid}/{_m.group(2)}"
            try:
                return gcp_kms.dispatch(self.gcp_kms, "GET", "/v1/" + key, {}, {}, b"").status == 200
            finally:
                if tok is not None:
                    _ctx.REQUEST_PROVIDER.reset(tok)
        if kind == "image_digest":   # Binary Authorization: image ref -> digest via the simulated Artifact Registry
            return gcp_ar.resolve_image_digest(self.gcp_ar, args[0])
        if kind == "bucket":
            return bool(self.gcs.bucket_exists(args[0]))
        if kind == "vpcconn":   # Serverless VPC Access connector: (project, region, name)
            return "%s/%s/%s" % args in (getattr(self.gcp_compute, "vpc_connectors", None) or {})
        if kind == "subnet":    # VPC subnetwork: (project, region, name)
            return "%s/%s/%s" % args in (getattr(self.gcp_compute, "subnetworks", None) or {})
        return None

    def _run_topic_exists(self, topic_full):
        return bool(self.gcp_msg.get_topic(topic_full))

    def _pam_grant(self, resource, role, member):
        """Privileged Access Manager activating a grant: add `member` to `role` on the
        project's real IAM policy (the same store the console's Allow tab reads)."""
        gcp_iam.grant_member(self.gcp_iam, resource, role, member)

    def _pam_revoke(self, resource, role, member):
        """PAM grant ending (revoked/denied/expired): undo _pam_grant."""
        gcp_iam.revoke_member(self.gcp_iam, resource, role, member)

    def _servicebus_service(self, method, path, lheaders):
        """Azure Service Bus (topics) — the pub/sub-fan-out peer of SNS/Pub-Sub.
        Distinct from Azure Storage (carries NO x-ms-* storage headers) and from
        the ARM control plane (`subscriptions` is segment[1], not segment[0]).
        Identified by: a subscription-scoped path, a Service Bus runtime marker
        (BrokerProperties / atom+xml management), or a first segment that already
        names a known topic (so send/receive on an existing topic routes cleanly)."""
        if "x-ms-version" in lheaders or "x-ms-blob-type" in lheaders:
            return False   # Azure Storage (Blob/Queue), not Service Bus
        segs = [s for s in path.split("?", 1)[0].split("/") if s]
        if len(segs) >= 3 and segs[1] == "subscriptions":
            return True    # /{topic}/subscriptions/{sub}[...] — unambiguous
        if "brokerproperties" in lheaders:
            return True    # a Service Bus send/receive runtime request
        ct = (lheaders.get("content-type") or "")
        if "atom+xml" in ct:
            return True    # Service Bus entity-management (create topic/subscription)
        if segs and segs[0] in getattr(self.az_sb, "topics", {}):
            return True    # send/get/delete on an already-created topic
        return False

    # ── service detection ──────────────────────────────────────────────
    _SCHED_EVERY_S = 20.0

    def _sched_pulse(self):
        """Lazy scheduler pulse (core/schedule_core): backup plans/policies, DLM, Cloud SQL backup windows and ECR lifecycle run on
        their schedules whenever the router is serving traffic (Nano: only while the page is open); the offline appliance also
        ticks from a background loop. Throttled; never affects the request."""
        import time as _t
        now = _t.time()
        if now - getattr(self, "_sched_last", 0.0) < self._SCHED_EVERY_S:
            return
        self._sched_last = now
        try:
            from core import schedule_core
            schedule_core.tick(self, now)
        except Exception:
            pass

    def ecr_registry(self, method, path, query, headers, body):
        r = ecr_core.registry_dispatch(self.s3, method, path, query, headers, bytes(body))
        return {"status": r.status, "headers": dict(r.headers or {}), "body": r.body or b""}

    def service_of(self, method, path, lheaders, body, query=None):
        # Static website hosting: real S3 serves this over its OWN unsigned HTTP(S) origin
        # (bucket.s3-website-<region>.amazonaws.com), never the signed control+data API —
        # route it first, unambiguously, by the distinct path prefix the relay/dev_server
        # exposes that origin under.
        if path.startswith("/__s3_website__/"):
            return "s3-website"
        # GCP services are unambiguous by path (REST) and carry no SigV4 — route
        # them first so they never fall through to the S3 default.
        if path.startswith("/v2") and ecr_core.is_registry_request(lheaders, path):
            return "ecr-registry"   # docker push/pull against <acct>.dkr.ecr.<region>.<host> (AWS:<token> basic auth)
        gcp = _gcp_service(path)
        if gcp:
            return gcp
        az = _azure_service(path, lheaders, query)   # Azure data plane (x-ms-* / api-version)
        if az:
            return az
        if self._servicebus_service(method, path, lheaders):
            return "az-servicebus"
        if _execute_api_id(path, lheaders):   # HTTP API invoke URL ({id}.execute-api.* or /apigw/{id}/…)
            return "apigw-invoke"
        if any(path.startswith(p) for p in (  # Lambda REST (native boto3 lambda wire + sub-resources,
                "/lambda-url/", "/2015-03-31/functions", "/2015-03-31/layers", "/2015-03-31/event-source-mappings",
                # plus Vyomi-exclusive console surfaces — see core/lambda_core.py module note)
                "/2015-03-31/capacity-providers", "/2015-03-31/code-signing-configs",
                "/2015-03-31/network-connectors", "/2015-03-31/microvm-images",
                "/2015-03-31/microvms", "/2015-03-31/applications", "/2015-03-31/replicas",
                # the other API-date prefixes boto3 / the CLI use for newer operations
                "/2014-11-13/functions", "/2016-08-19/account-settings", "/2017-03-31/tags",
                "/2017-10-31/functions", "/2018-10-31/layers", "/2019-09-25/functions",
                "/2019-09-30/functions", "/2020-04-22/code-signing-configs", "/2020-06-30/functions",
                "/2021-07-20/functions", "/2021-10-31/functions", "/2021-11-15/functions",
                "/2024-08-31/functions", "/2025-11-30/functions", "/2025-11-30/capacity-providers",
                "/2025-12-01/functions")):
            return "lambda"
        if path.startswith("/v2/") and path[4:].split("/", 1)[0] in (   # API Gateway V2 control plane
                "apis", "domainnames", "vpclinks", "tags", "portals", "portalproducts", "domainnameaccessassociations"):
            return "apigatewayv2"
        if "/restapis" in path:               # API Gateway v1 control plane
            return "apigateway"
        if _AUTHZ_IAM.search(path):   # Azure RBAC role assignments/definitions + checkAccess
            return "azure-sql-iam-rbac"
        if _is_arm_path(path):        # Azure Resource Manager (az, azure-mgmt-* SDKs)
            return "azure-arm"
        if path.startswith("/azure-data/appconfig/"):   # App Configuration data plane (store endpoint)
            return "azure-appconfig"
        if path.startswith("/azure-data/site/"):   # App Service front door + app host (/azure-data/site/{app}/...)
            return "azure-site"
        if path.startswith("/azure-data/apim/"):   # API Management gateway data plane (/azure-data/apim/{service}/{api path}/...)
            return "azure-apim-gw"
        if path.split("?", 1)[0] == "/azure-data/dns/query":   # Azure DNS resolution ("dig" over HTTP)
            return "azure-dns-query"
        if path.startswith("/azure-sql/") or path == "/azure-sql":  # Azure SQL data plane
            return "azure-sql"
        if path.startswith("/service/" + cw.TARGET_PREFIX + "/") or lheaders.get("smithy-protocol") == "rpc-v2-cbor":
            return "cloudwatch"            # CloudWatch rpc-v2-cbor (the default protocol of current SDKs)
        target = lheaders.get("x-amz-target", "") or ""
        if target.startswith(cw.TARGET_PREFIX + "."):
            return "cloudwatch"            # CloudWatch JSON 1.0
        if target:
            for prefix, svc in _TARGET_PREFIX.items():
                if target.startswith(prefix):
                    return svc
        auth = lheaders.get("authorization", "") or ""
        m = _CRED_RE.search(auth)
        if m:
            svc = _SIGNING.get(m.group(1))
            if svc:
                return svc
        # Unsigned Query-protocol request: route by Action.
        ct = (lheaders.get("content-type", "") or "").lower()
        if "x-www-form-urlencoded" in ct or "Action=" in (self._text(body) or ""):
            action = self._query_params(None, body).get("Action", "")
            svc = _QUERY_ACTION.get(action)
            if svc:
                return svc
            if action in cw.OPERATIONS and action not in _GENERIC_ACTIONS:
                return "cloudwatch"
        if rds_data.is_data_api_path(path):  # unsigned Data API (rest-json path)
            return "rds-data"
        return "s3"  # default: bucket/key path-style

    def _azure_sql_conn(self, base):
        """What a Microsoft.Sql database is backed by here: the tunnel's /azure-sql data plane on
        the shared SqlStore — real Postgres when PGlite is loaded, SQLite otherwise. Nano has no TCP
        database to connect to, so unlike offline there is no host/port, only the HTTP data plane."""
        pg = type(self.rds).__name__ == "PGliteSqlStore"
        return {"engine": "PostgreSQL (PGlite, in-browser)" if pg else "SQLite (in-browser)",
                "dataPlane": f"{base}/azure-sql"}

    _EC2_NS = "http://ec2.amazonaws.com/doc/2016-11-15/"
    _EC2_STATE_CODES = {"pending": 0, "running": 16, "shutting-down": 32, "terminated": 48,
                        "stopping": 64, "stopped": 80}

    def _ec2_describe_instances(self, params):
        """EC2 DescribeInstances over the instances the Nano console launched (the shared
        "resources" store) — `aws ec2 describe-instances` sees what the console shows. Filters:
        InstanceId.N and instance-state-name / tag:Name (the common ones)."""
        res = self._stores.get("resources") if isinstance(self._stores, dict) else None
        cols = getattr(res, "collections", {}) or {}
        ids = {v for k, v in params.items() if k.startswith("InstanceId.")}
        filters = {}
        for k, v in params.items():
            m = re.match(r"Filter\.(\d+)\.Name$", k)
            if m:
                filters[v] = {params[x] for x in params if x.startswith(f"Filter.{m.group(1)}.Value.")}
        acct = self.iam.account_id
        items = []
        for ns, recs in cols.items():
            parts = ns.split("/")
            if len(parts) != 3 or parts[0] != "aws" or parts[2] != "ec2":
                continue
            for name, r in (recs or {}).items():
                iid = str(r.get("instance_id") or "")
                state = str(r.get("state") or r.get("status") or "running").lower()
                if not iid or (ids and iid not in ids):
                    continue
                if "instance-state-name" in filters and state not in filters["instance-state-name"]:
                    continue
                if "tag:Name" in filters and name not in filters["tag:Name"]:
                    continue
                x = _xml_escape
                items.append(
                    f"<item><reservationId>r-{iid[2:]}</reservationId><ownerId>{acct}</ownerId><groupSet/>"
                    f"<instancesSet><item><instanceId>{x(iid)}</instanceId>"
                    f"<imageId>{x(str(r.get('image_id') or ''))}</imageId>"
                    f"<instanceState><code>{self._EC2_STATE_CODES.get(state, 16)}</code><name>{x(state)}</name></instanceState>"
                    f"<privateDnsName>ip-{x(str(r.get('private_ip') or '').replace('.', '-'))}.ec2.internal</privateDnsName>"
                    f"<dnsName>{x(str(r.get('public_dns') or ''))}</dnsName>"
                    f"<instanceType>{x(str(r.get('instance_type') or 't3.micro'))}</instanceType>"
                    f"<launchTime>{x(str(r.get('launch_time') or ''))}</launchTime>"
                    f"<placement><availabilityZone>{x(str(r.get('availability_zone') or 'us-east-1a'))}</availabilityZone></placement>"
                    f"<privateIpAddress>{x(str(r.get('private_ip') or ''))}</privateIpAddress>"
                    f"<ipAddress>{x(str(r.get('public_ip') or ''))}</ipAddress>"
                    f"<tagSet><item><key>Name</key><value>{x(name)}</value></item></tagSet>"
                    f"</item></instancesSet></item>")
        body = (f'<?xml version="1.0" encoding="UTF-8"?><DescribeInstancesResponse xmlns="{self._EC2_NS}">'
                f"<requestId>{iam._req_id()}</requestId><reservationSet>{''.join(items)}</reservationSet>"
                "</DescribeInstancesResponse>")
        return {"status": 200, "headers": {"content-type": "text/xml"}, "body": body.encode()}

    _STS_NS = "https://sts.amazonaws.com/doc/2011-06-15/"

    def _sts(self, params):
        """STS GetCallerIdentity — `aws sts get-caller-identity`, the account the
        CLI and SDKs use. The account is the IAM store's, so it matches the ARNs."""
        rid = iam._req_id()   # IAM's request ids (STS sits beside IAM)
        action = params.get("Action", "")
        if action == "GetCallerIdentity":
            acct = self.iam.account_id
            body = ('<?xml version="1.0" encoding="UTF-8"?>'
                    f'<GetCallerIdentityResponse xmlns="{self._STS_NS}"><GetCallerIdentityResult>'
                    f"<Arn>arn:aws:iam::{acct}:root</Arn><UserId>{acct}</UserId><Account>{acct}</Account>"
                    f"</GetCallerIdentityResult><ResponseMetadata><RequestId>{rid}</RequestId></ResponseMetadata>"
                    "</GetCallerIdentityResponse>")
            return {"status": 200, "headers": {"content-type": "text/xml"}, "body": body.encode()}
        if action in ("AssumeRole", "GetSessionToken", "GetAccessKeyInfo"):
            import uuid as _uuid, datetime as _dt
            acct = self.iam.account_id
            x = _xml_escape
            if action == "GetAccessKeyInfo":
                inner = f"<Account>{acct}</Account>"
            else:
                exp = (_dt.datetime.utcnow() + _dt.timedelta(seconds=int(params.get("DurationSeconds") or 3600))).strftime("%Y-%m-%dT%H:%M:%SZ")
                creds = (f"<Credentials><AccessKeyId>ASIA{_uuid.uuid4().hex[:16].upper()}</AccessKeyId>"
                         f"<SecretAccessKey>{_uuid.uuid4().hex}{_uuid.uuid4().hex[:8]}</SecretAccessKey>"
                         f"<SessionToken>{_uuid.uuid4().hex}{_uuid.uuid4().hex}</SessionToken><Expiration>{exp}</Expiration></Credentials>")
                inner = creds
                if action == "AssumeRole":
                    rarn = params.get("RoleArn", "")
                    sess = params.get("RoleSessionName", "session")
                    rname = rarn.rsplit("/", 1)[-1] if "/" in rarn else rarn
                    inner += (f"<AssumedRoleUser><AssumedRoleId>AROA{_uuid.uuid4().hex[:17].upper()}:{x(sess)}</AssumedRoleId>"
                              f"<Arn>arn:aws:sts::{acct}:assumed-role/{x(rname)}/{x(sess)}</Arn></AssumedRoleUser>")
            body = ('<?xml version="1.0" encoding="UTF-8"?>'
                    f'<{action}Response xmlns="{self._STS_NS}"><{action}Result>{inner}</{action}Result>'
                    f"<ResponseMetadata><RequestId>{rid}</RequestId></ResponseMetadata></{action}Response>")
            return {"status": 200, "headers": {"content-type": "text/xml"}, "body": body.encode()}
        body = ('<?xml version="1.0" encoding="UTF-8"?>'
                f'<ErrorResponse xmlns="{self._STS_NS}"><Error><Type>Sender</Type><Code>InvalidAction</Code>'
                f"<Message>Unsupported STS action '{_xml_escape(action)}'.</Message></Error>"
                f"<RequestId>{rid}</RequestId></ErrorResponse>")
        return {"status": 400, "headers": {"content-type": "text/xml"}, "body": body.encode()}

    # ── body helpers ───────────────────────────────────────────────────
    @staticmethod
    def _text(body):
        if body is None:
            return ""
        if isinstance(body, (bytes, bytearray)):
            try:
                return body.decode("utf-8")
            except Exception:
                return ""
        return str(body)

    def _json_body(self, body):
        txt = self._text(body).strip()
        if not txt:
            return {}
        try:
            d = json.loads(txt)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def _query_params(self, query, body):
        params = dict(query or {})
        txt = self._text(body)
        if txt:
            params.update(dict(parse_qsl(txt, keep_blank_values=True)))
        return params

    def _rds_managed_secret(self, action: str, db: dict, kms_key_id: str = "", owner: str = "rds"):
        rid = db.get("dbi_resource_id") or db.setdefault("dbi_resource_id", "db-" + "".join(c for c in db["db_instance_identifier"].upper() if c.isalnum())[:26].ljust(26, "X"))
        name = f"rds!{rid.lower()}" if owner == "rds" else f"{owner}!{db['db_instance_identifier']}"
        if action == "delete":
            secrets.delete_managed_secret(self.sec, name)
            return None
        if action == "rotate":
            secrets._rotate_secret(self.sec, {"SecretId": name}, self.kms)
            return None
        pw = secrets._gen_password()
        doc = {"username": db.get("master_username", "admin"), "password": pw, "engine": db.get("engine", "postgres"),
               "host": db.get("endpoint_address", ""), "port": db.get("endpoint_port", 5432), "dbname": db.get("db_name", ""),
               "dbInstanceIdentifier": db["db_instance_identifier"]}
        db["master_user_password"] = pw
        if owner == "redshift":
            doc["dbClusterIdentifier"] = db["db_instance_identifier"]
            doc.pop("dbInstanceIdentifier", None)
        out = secrets.create_managed_secret(self.sec, name, owner, doc, self.kms, kms_key_id or None,
                                            f"Secret associated with primary {owner.upper() if owner == 'rds' else 'Redshift'} resource: {db.get('db_instance_arn', '')}")
        return {"SecretArn": out["ARN"], "SecretStatus": "active", "KmsKeyId": kms_key_id or "aws/secretsmanager"}

    def _redshift_secret_rotated(self, event: str, secret: dict, doc: dict) -> None:
        try:
            from core import redshift_core
            redshift_core._get(self.rds, doc.get("dbClusterIdentifier", ""))["master_password"] = doc["password"]
        except Exception:
            pass

    def _rds_secret_rotated(self, event: str, secret: dict, doc: dict) -> None:
        """Secrets Manager rotated an RDS-owned secret: apply the new password to the instance (the owning service's job)."""
        try:
            inst = self.rds.get_instance(doc.get("dbInstanceIdentifier", ""))
            if inst is not None:
                inst["master_user_password"] = doc["password"]
        except Exception:
            pass

    def _role_usage_refs(self, role: dict) -> list:
        """Live resources that still depend on an IAM role (IAM Role manager delete checks)."""
        refs, arn, name = [], role["arn"], role["role_name"]
        try:
            fns = getattr(self.lam, "functions", None)
            from core import lambda_core as _lc
            fns = _lc._functions(self.lam)
            refs += [{"Type": "LambdaFunction", "Id": n} for n, f in sorted(fns.items()) if str(f.get("role", "")).rsplit("/", 1)[-1] == name]
        except Exception:
            pass
        try:
            from core import vpc_core as _vc
            ips = {n for n, ip in iam._ip_all(self.iam).items() if name in ip["roles"]}
            for iid, inst in _vc._model(self.vpc)["instances"].items():
                prof = str(inst.get("iam_instance_profile") or "").rsplit("/", 1)[-1]
                if prof and prof in ips and str(inst.get("state")) not in ("terminated", "shutting-down"):
                    refs.append({"Type": "Ec2Instance", "Id": iid})
        except Exception:
            pass
        return refs

    # ── activity log (Vyomi-only — see iam_core.record_activity) ───────
    # Query/JSON-protocol services carry an explicit action name (Action= param or the
    # X-Amz-Target header); REST services (S3, Lambda, API Gateway, …) don't, so only the
    # service — not the action — is attributable for them.
    _ACTION_FROM_QUERY = {"iam", "rds", "vpc", "elbv2", "cloudformation", "sns", "sqs"}

    def _action_name(self, svc, lheaders, query, body):
        target = lheaders.get("x-amz-target", "") or ""
        if target:
            return target.rsplit(".", 1)[-1]
        if svc in self._ACTION_FROM_QUERY:
            return self._query_params(query, body).get("Action") or None
        return None

    def _track_activity(self, svc, lheaders, query, body):
        akid_m = _AKID_RE.search(lheaders.get("authorization", "") or "")
        if not akid_m:
            return
        key = self.iam.access_keys.get(akid_m.group(1))
        if not key:   # not an IAM user's own access key (console operator / unsigned / unknown)
            return
        iam.record_activity(self.iam, key["user_name"], svc, self._action_name(svc, lheaders, query, body),
                            access_key_id=akid_m.group(1))

    # ── dispatch ───────────────────────────────────────────────────────
    async def ahandle(self, method, path, query, headers, body):
        """Async front door: serves the RDS Data API (which must await the SQL
        engine) and delegates every other — synchronous — service to handle(). The
        relay tab calls THIS so an external `boto3 rds-data` request reaches PGlite."""
        lheaders = _lower_headers(headers)
        b = body if isinstance(body, (bytes, bytearray)) else (body or b"")
        if isinstance(b, str):
            b = b.encode("utf-8")
        svc = self.service_of(method, path, lheaders, b, query)
        if svc == "rds-data":
            r = await rds_data.dispatch(self.rds, path, self._json_body(b))
            hdrs = dict(r.headers or {})
            hdrs.setdefault("content-type", "application/json")
            return {"status": r.status, "headers": hdrs, "body": json.dumps(r.body).encode()}
        if svc == "rds":   # snapshots read the (possibly async) engine; exports await the Parquet writer
            r = await rds.adispatch(self.rds, self._query_params(query, b), msg_store=self.msg, s3_store=self.s3)
            return {"status": r.status, "headers": {"content-type": r.media_type, **dict(r.headers or {})},
                    "body": r.body.encode() if isinstance(r.body, str) else r.body}
        if svc in ("bedrock", "gcp-aiplatform", "az-openai") or (svc == "azure-arm" and re.search(
                r"/providers/microsoft\.cognitiveservices/accounts/[^/]+/openai/", path.lower())):   # model inference: Nano's WebLLM backend is async (core/llm_core.arun)
            from core import llm_core
            return await llm_core.arun(lambda: self.handle(method, path, query, headers, body))
        return self.handle(method, path, query, headers, body)

    # ── security scanning (core/secscan_core.py): audit feed + Security Hub / GuardDuty inputs ──
    def secscan_bag(self) -> dict:
        return self.s3.account.setdefault("secscan_root", {})

    def secscan_audit(self, cloud, method, path, query, headers, body, status, svc="", actor=None):
        """Best-effort: record the served call into the control-plane audit feed (never raises)."""
        try:
            from core import secscan_core as sc
            lh = _lower_headers(headers)
            if actor is None:
                m = _AKID_RE.search(lh.get("authorization", "") or "")
                key = self.iam.access_keys.get(m.group(1)) if m else None
                actor = key["user_name"] if key else "console"
            action = self._action_name(svc, lh, query, body) if cloud == "aws" else ""
            ev = sc.classify(cloud, method, path, query, headers, body, int(status), svc=svc, action=action or "", actor=actor)
            if ev:
                sc.append(sc._state(self.secscan_bag())["audit"], ev)
        except Exception:
            pass

    def secscan_inventory(self) -> dict:
        from core import secscan_core as sc
        try:
            from core import vpc_core
            vm = vpc_core._model(self.vpc)
        except Exception:
            vm = None
        trails = 0
        try:
            trails = sum(1 for t in self.s3.account.get("s3ext", {}).get("trails", {}).values() if t.get("_logging", True) and not t.get("_stopped"))
        except Exception:
            pass
        return sc.aws_collect(s3=self.s3, vpc_model=vm, rds=self.rds, iam=self.iam, trails=trails, lam=self.lam)

    def secscan_threats(self, cloud="aws") -> list:
        from core import secscan_core as sc
        return sc.detect(cloud, sc._state(self.secscan_bag())["audit"])

    def secscan_serve(self, svc, method, path, body: bytes) -> dict:
        from core import secscan_core as _sc
        bag = self.secscan_bag()
        if svc == "guardduty" and path.split("?", 1)[0].startswith("/malware-protection-plan"):   # GuardDuty Malware Protection for S3 (core/malware_scan_core)
            from core import malware_scan_core as _mw
            r = _mw.gd_dispatch(self.s3, method, path, body)
            if method != "GET":
                try:
                    self.s3.persist()
                except Exception:
                    pass
            return {"status": r.status, "headers": {**r.headers, "content-type": "application/json"}, "body": r.body}
        if svc == "securityhub":
            rows = self.secscan_posture() if _sc._state(bag)["hub"]["enabled"] else []
            r = _sc.hub_dispatch(bag, method, path, body, rows, self.secscan_threats())
        else:
            r = _sc.gd_dispatch(bag, method, path, body, self.secscan_threats())
        if method != "GET":
            try:
                self.s3.persist()
            except Exception:
                pass
        return {"status": r.status, "headers": {**r.headers, "content-type": "application/json"}, "body": r.body}

    def _run_ar_push(self, project, location, sid, tag, bid):
        """Cloud Run source deploy: ensure the `cloud-run-source-deploy` Docker repo, push the BuildKit image, return its AR reference."""
        repo = "cloud-run-source-deploy"
        if gcp_ar._repo_name(project, location, repo) not in self.gcp_ar.repos:
            gcp_ar._create_repo(self.gcp_ar, project, location, {"repositoryId": repo}, {"format": "DOCKER", "description": "Cloud Run Source Deployments"})
        ref = "%s-docker.pkg.dev/%s/%s/%s:%s" % (location, project, repo, sid, bid)
        gcp_cloudbuild.push_to_ar(self.gcp_ar, project, ref, tag)
        return ref

    def _cb_run_deploy(self, project, region, service, opts, create):
        """Cloud Build `gcloud run deploy|services update` step -> a real create/patch on the simulated Cloud Run (so Binary
        Authorization, validation and revision cutting all apply). Raises ValueError with the API's message on failure."""
        base = "/v2/projects/%s/locations/%s/services" % (project, region)

        def call(method, path, query, body=None):
            r = gcp_run.dispatch(self.gcp_run, method, path, query, {}, json.dumps(body).encode() if body is not None else b"",
                                 log_fn=self._run_log, topic_exists=self._run_topic_exists)
            try:
                return r.status, json.loads(r.body or b"{}")
            except Exception:
                return r.status, {}
        labels = dict(kv.split("=", 1) for kv in str(opts.get("labels") or "").split(",") if "=" in kv)
        env = [dict(zip(("name", "value"), kv.split("=", 1))) for kv in str(opts.get("set-env-vars") or "").split(",") if "=" in kv]
        st, cur = call("GET", "%s/%s" % (base, service), {})
        if st == 200:
            tpl = cur.get("template") or {"containers": [{}]}
            c0 = (tpl.get("containers") or [{}])[0]
            if opts.get("image"):
                c0["image"] = opts["image"]
            if opts.get("port") and opts["port"] is not True:
                c0["ports"] = [{"containerPort": int(opts["port"])}]
            if env:
                c0["env"] = env
            tpl["containers"] = [c0] + (tpl.get("containers") or [])[1:]
            tpl.pop("revision", None)
            body = {"template": tpl, "labels": {**(cur.get("labels") or {}), **labels}}
            st, op = call("PATCH", "%s/%s" % (base, service), {"updateMask": "template,labels"}, body)
        elif create:
            c0 = {"image": opts["image"], **({"ports": [{"containerPort": int(opts["port"])}]} if opts.get("port") and opts["port"] is not True else {}), **({"env": env} if env else {})}
            st, op = call("POST", base, {"serviceId": service}, {"template": {"containers": [c0]}, "labels": labels})
        else:
            raise ValueError("Service [%s] could not be found." % service)
        if st != 200:
            raise ValueError(((op.get("error") or {}).get("message")) or "Cloud Run rejected the deploy (HTTP %d)." % st)
        resp = op.get("response") or {}
        rev = (resp.get("latestReadyRevision") or resp.get("latestCreatedRevision") or "").rsplit("/", 1)[-1]
        return "Deploying container to Cloud Run service [%s] in project [%s] region [%s]\nDone. Service [%s] revision [%s] has been deployed and is serving 100 percent of traffic." % (service, project, region, service, rev)

    def _ca_vuln_occurrences(self, project):
        """Container Analysis VULNERABILITY occurrences of the project's scanned Artifact Registry images."""
        try:
            scans = gcp_ar.scan_images(self.gcp_ar, project, self._trivy_reports())
        except Exception:
            return []
        return [gcp_posture.occurrence(project, sc, v) for sc in scans for v in sc["scan"]["findings"]]

    def _trivy_reports(self):
        """Real Trivy reports by image digest (offline appliance, when the Trivy container has scanned the image)."""
        try:
            from providers import trivy_runner
            return trivy_runner.cached_reports()
        except Exception:
            return None

    def _gcs_read_object(self, bucket, obj):
        """Bytes of a simulated GCS object (Cloud Build storageSource), or None."""
        from urllib.parse import quote
        if not self.gcs.bucket_exists(bucket):
            return None
        r = gcs.dispatch(self.gcs, "GET", "/storage/v1/b/%s/o/%s" % (bucket, quote(obj, safe="")), {"alt": "media"}, {}, b"")
        return r.body if r.status == 200 else None

    def scc_ctx(self) -> dict:
        """What core/gcp_scc_core needs from the platform: generated posture rows + Pub/Sub for notification configs."""
        def generated(project):
            try:
                scans = gcp_ar.scan_images(self.gcp_ar, project)
            except Exception:
                scans = []
            fws = list(self.gcp_compute.firewalls.values())
            return (gcp_posture.compute_findings(project, self.gcp_compute_vm.instances, fws) + gcp_posture.storage_findings(project, self.gcs.buckets)
                    + gcp_posture.threat_findings(project, self.secscan_threats("gcp")) + gcp_posture.vulnerability_findings(project, scans))

        def topic_exists(topic):
            return gcp_ps.dispatch(self.gcp_msg, "GET", "/v1/" + topic, {}, {}, b"").status == 200

        def publish(topic, data_b64, attrs):
            r = gcp_ps.dispatch(self.gcp_msg, "POST", "/v1/" + topic + ":publish", {}, {},
                                json.dumps({"messages": [{"data": data_b64, "attributes": attrs}]}).encode())
            return r.status == 200
        return {"generated": generated, "topic_exists": topic_exists, "publish": publish, "default_project": gcp_scc_core.DEFAULT_PROJECT}

    def secscan_posture(self) -> list:
        from core import secscan_core as sc
        return sc.aws_posture_findings(self.secscan_inventory(), [])

    @staticmethod
    def _apim_fetch():
        """Outbound HTTP for the APIM gateway (offline appliance only; Nano has no sockets and passes None)."""
        try:
            import urllib.request
            import socket  # noqa: F401
        except Exception:
            return None

        def fetch(method, url, headers, data):
            import urllib.error
            req = urllib.request.Request(url, data=data or None, method=method, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return r.status, dict(r.headers), r.read()
            except urllib.error.HTTPError as e:
                return e.code, dict(e.headers), e.read()
        return fetch

    def handle(self, method, path, query, headers, body):
        """Telemetry-recording front door: measures each request (resource, op, status, latency) into the shared
        observability recorder, serves the /_obs OTLP / Jaeger / Prometheus surface, and refreshes the cloud metric
        stores from the measured series before a read of them."""
        import time as _t
        from core import observability_core as _obsc
        self._sched_pulse()
        p0 = path.split("?", 1)[0]
        if p0.startswith(_obsc.BASE + "/") or p0 == _obsc.BASE:
            r = _obsc.dispatch(self.obs, method, p0, query or {}, headers or {}, body if isinstance(body, (bytes, bytearray)) else (body or "").encode(), cw_store=self.cw, mon_store=self.gcp_mon)
            return {"status": r.status, "headers": dict(r.headers), "body": r.body}
        lh = _lower_headers(headers)
        bb = body if isinstance(body, (bytes, bytearray)) else (body or b"")
        svc = self.service_of(method, path, lh, bb if isinstance(bb, bytes) else bytes(bb), query)
        try:
            if svc == "cloudwatch":
                _obsc.publish_cloudwatch(self.obs, self.cw)
            elif svc == "gcp-monitoring":
                _obsc.publish_gcp(self.obs, self.gcp_mon, _obsc.gcp_project_of(path))
            elif svc == "gcp-trace":
                _obsc.sync_gcp_traces(self.obs, self.gcp_mon, _obsc.gcp_project_of(path))
        except Exception:
            pass
        t0 = _t.time()
        res = self._handle_inner(method, path, query, headers, body)
        try:
            if svc and svc != "gcp-trace":   # the tracer does not trace its own reads/writes
                cloud = "gcp" if svc.startswith("gcp-") else ("azure" if svc.startswith("az-") else "aws")
                r_, op_ = _obsc.extract_resource(cloud, svc, method, path, lh, bytes(bb))
                _obsc.record(self.obs, cloud, svc, r_, op_, int(res.get("status", 0)), (_t.time() - t0) * 1000.0,
                             traceparent=lh.get("traceparent", ""), nbytes_in=len(bb), nbytes_out=len(res.get("body") or b""))
        except Exception:
            pass
        return res

    def _handle_inner(self, method, path, query, headers, body):
        """Route ONE native-wire request, then record it in the security audit feed."""
        r = self._handle_raw(method, path, query, headers, body)
        if r.get("status", 200) >= 400 and gcp_wire_ext.looks_unwired(r):   # a Google API method no dedicated core answers: the schema-driven store
            try:
                _fb = gcp_wire_ext.fallback(self, method, path, query, headers, bytes(body) if isinstance(body, (bytes, bytearray)) else (body or "").encode(), r)
            except Exception:   # never let the gap-filler turn an honest "unknown route" into a 500
                _fb = None
            if _fb is not None:
                r = _fb
        try:
            lh = _lower_headers(headers)
            svc = self.service_of(method, path, lh, body if isinstance(body, (bytes, bytearray)) else (body or b""), query)
            if svc and not svc.startswith(("gcp-", "az-", "azure")):
                self.secscan_audit("aws", method, path, query, headers, body, r.get("status", 200), svc=svc)
            elif svc and svc.startswith("gcp-"):
                self.secscan_audit("gcp", method, path, query, headers, body, r.get("status", 200), svc=svc)
        except Exception:
            pass
        return r

    def _handle_raw(self, method, path, query, headers, body):
        """Route ONE native-wire request. Returns {status, headers, body(bytes)}.
        SYNC services only — the RDS Data API goes through ahandle()."""
        # /azure-data/queue/{acct} says "queue storage" outright — the one thing a shared
        # endpoint can't otherwise tell (a root ?comp=list is containers or queues).
        queue_alias = (path or "").startswith("/azure-data/queue/")
        path = _azure_data_alias(path)
        lheaders = _lower_headers(headers)
        body = body if isinstance(body, (bytes, bytearray)) else (body or b"")
        if isinstance(body, str):
            body = body.encode("utf-8")
        _gx = gcp_wire_ext.pre(self, method, path, query, lheaders, bytes(body))   # Functions v1/v2, Cloud DNS, SCC v1, /gcf HTTPS URL
        if _gx is not None:
            return _gx
        _tr = nano_triggers.route(self, method, path, query, lheaders, bytes(body))   # /gcf, Event Grid publish, function apps
        if _tr is not None:
            return _tr
        svc = self.service_of(method, path, lheaders, body, query)
        if queue_alias and svc == "az-blob":
            svc = "az-queue"
        self._track_activity(svc, lheaders, query, body)

        if svc == "rds-data":  # async-only — guard the sync path
            return {"status": 400, "headers": {"x-amzn-errortype": "BadRequestException"},
                    "body": b'{"message":"RDS Data API requires the async dispatch path"}'}

        if svc == "s3":
            r = s3.dispatch(self.s3, method, path, query or {}, headers or {}, bytes(body))
            return {"status": r.status, "headers": dict(r.headers or {}),
                    "body": r.body or b""}

        if svc == "cloudtrail":
            r = s3.dispatch(self.s3, "POST", "/__cloudtrail__", {}, {"x-amz-target": lheaders.get("x-amz-target", "")}, bytes(body))
            return {"status": r.status, "headers": {**dict(r.headers or {}), "content-type": "application/x-amz-json-1.1"}, "body": r.body or b""}

        if svc == "vpc-lattice":
            from core import vpc_lattice_core
            return vpc_lattice_core.dispatch(self.vpc, method, path, query or {}, headers or {}, bytes(body))

        if svc == "mgn":
            from core import mgn_core
            return mgn_core.dispatch(self.vpc, method, path, query or {}, headers or {}, bytes(body))
        if svc == "xray":
            from core import xray_core
            return xray_core.dispatch(self.sfn, method, path, query or {}, headers or {}, bytes(body))
        if svc == "rbin":
            from core import ec2_ops_core
            r = ec2_ops_core.rbin_dispatch(self.vpc, method, path, query or {}, headers or {}, bytes(body))
            return r
        if svc in ("securityhub", "guardduty"):
            return self.secscan_serve(svc, method, path, bytes(body))
        if svc == "codeconnections":
            from core import aws_codeconn_core as _cc
            def _cfn_call(params):
                return cfn.dispatch(self.cfn, params, s3_store=self.s3, ddb_store=self.ddb, iam_store=self.iam, msg_store=self.msg,
                                    logs_store=self.logs, cw_store=self.cw)
            status, doc = _cc.dispatch_json(self.s3.account, lheaders.get("x-amz-target", ""), bytes(body), _cfn_call, self.cfn)
            try:
                self.s3.persist()
            except Exception:
                pass
            hdrs = {"content-type": "application/x-amz-json-1.0"}
            if status >= 400:
                hdrs["x-amzn-errortype"] = doc.get("__type", "")
            return {"status": status, "headers": hdrs, "body": json.dumps(doc).encode()}
        if svc == "schemas":
            from core import eventbridge_schemas_core as _schemas
            r = _schemas.dispatch(self.msg, method, path, query or {}, headers or {}, bytes(body))
            return {"status": r.status, "headers": {**dict(r.headers or {}), "content-type": "application/json"}, "body": r.body or b""}

        if svc == "marketplace":
            from core import marketplace_core
            r = marketplace_core.dispatch(self.s3, self.vpc, method, path, query or {}, bytes(body))
            hdrs = dict(r.headers or {})
            hdrs.setdefault("content-type", "application/json")
            return {"status": r.status, "headers": hdrs, "body": r.body or b""}

        if svc == "s3files":
            from core import s3files_core
            r = s3files_core.dispatch(self.s3, self.vpc, method, path, query or {}, bytes(body))
            hdrs = dict(r.headers or {})
            hdrs.setdefault("content-type", "application/json")
            return {"status": r.status, "headers": hdrs, "body": r.body or b""}

        if svc == "fsx":
            from core import s3files_core
            r = s3files_core.fsx_dispatch(self.s3, self.vpc, lheaders.get("x-amz-target", ""), bytes(body))
            return {"status": r.status, "headers": dict(r.headers or {}), "body": r.body or b""}

        if svc == "bedrock":
            from core import ai_models_core
            from core import bedrock_agents_core
            if bedrock_agents_core.handles(path.split("?", 1)[0]):   # Bedrock Agents / Knowledge Bases / agent-runtime share signing name `bedrock`
                return bedrock_agents_core.dispatch(self.s3, method, path.split("?", 1)[0], query or {}, lheaders, bytes(body))
            return ai_models_core.bedrock_dispatch(method, path, query or {}, lheaders, bytes(body))

        if svc == "agentcore":
            from core import bedrock_agents_core
            return bedrock_agents_core.agentcore_dispatch(self.s3, self.lam, method, path.split("?", 1)[0], query or {}, lheaders, bytes(body))

        if svc == "gcp-aiplatform":
            from core import ai_models_core
            return ai_models_core.vertex_dispatch(method, path.split("?", 1)[0], query or {}, lheaders, bytes(body))

        if svc == "az-openai":
            from core import ai_models_core
            return ai_models_core.azure_openai_dispatch(self.az_arm.state, method, path.split("?", 1)[0], query or {}, lheaders, bytes(body))

        if svc == "backup":
            from core import backup_core
            r = backup_core.dispatch(self.ddb, self.s3, method, path, query or {}, bytes(body), rds_store=self.rds, vpc_store=self.vpc)
            hdrs = dict(r.headers or {})
            hdrs.setdefault("content-type", "application/json")
            return {"status": r.status, "headers": hdrs, "body": r.body or b""}

        if svc == "savingsplans":
            from core import savingsplans_core
            return savingsplans_core.dispatch(self.vpc, method, path, bytes(body))

        if svc == "cloudfront":
            from core import cloudfront_keys_core
            return cloudfront_keys_core.dispatch(self.s3, method, path, query or {}, headers or {}, bytes(body))

        if svc == "vyomi-reservations":
            from core import reservations_core
            return reservations_core.dispatch(self.s3, self.ddb, self.rds, method, path, bytes(body))

        if svc == "networkmanager":
            from core import networkmanager_core
            return networkmanager_core.dispatch(self.s3, self.vpc, method, path, query or {}, bytes(body))

        if svc == "imagebuilder":
            from core import imagebuilder_core
            return imagebuilder_core.dispatch(self.s3, self.vpc, method, path, query or {}, bytes(body))

        if svc == "s3vectors":
            r = s3.dispatch(self.s3, method, "/__s3vectors__" + path, query or {}, headers or {}, bytes(body))
            hdrs = dict(r.headers or {})
            hdrs.setdefault("content-type", "application/json")
            return {"status": r.status, "headers": hdrs, "body": r.body or b""}

        if svc == "s3tables":
            r = s3.dispatch(self.s3, method, "/__s3tables__" + path, query or {}, headers or {}, bytes(body))
            hdrs = dict(r.headers or {})
            if r.media_type and r.body and not any(k.lower() == "content-type" for k in hdrs):
                hdrs["content-type"] = r.media_type
            return {"status": r.status, "headers": hdrs, "body": r.body or b""}

        if svc == "s3-website":
            rest = path[len("/__s3_website__/"):]
            bucket, _, key = rest.partition("/")
            r = s3.website_dispatch(self.s3, method, bucket, key, headers or {})
            hdrs = dict(r.headers or {})
            if r.media_type:
                hdrs.setdefault("content-type", r.media_type)
            return {"status": r.status, "headers": hdrs, "body": r.body or b""}

        if svc == "cloudwatch":   # CloudWatch: rpc-v2-cbor / JSON 1.0 / Query on one engine
            return cw.wire(self.cw, method, path, headers or {}, bytes(body), query or {})

        if svc == "lambda":   # native Lambda REST (function mgmt + sandboxed invoke)
            if path.startswith("/lambda-url/"):
                _id, _, _rest = path[len("/lambda-url/"):].partition("/")
                r = lam.url_invoke(self.lam, _id, method, _rest.split("?", 1)[0], query or {}, headers or {}, bytes(body))
            else:
                r = lam.dispatch(self.lam, method, path, query or {}, headers or {}, bytes(body),
                                  msg_store=self.msg, lam_store=self.lam)
            hdrs = dict(r.headers or {})
            if r.media_type and not any(k.lower() == "content-type" for k in hdrs):
                hdrs["content-type"] = r.media_type
            return {"status": r.status, "headers": hdrs, "body": r.body or b""}

        if svc == "apigw-invoke":   # an HTTP API's invoke URL → the shared gateway engine
            api_id = _execute_api_id(path, lheaders)
            rest = path.split("?", 1)[0]
            if rest.startswith(f"/apigw/{api_id}"):           # path-style: /apigw/{id}[/{stage}]/…
                rest = rest[len(f"/apigw/{api_id}"):]
            api = self.apigwv2.apis.get(api_id) or {}
            first = rest.strip("/").split("/", 1)[0]
            stage = first if first and first != "$default" and first in (api.get("stages") or {}) else "$default"
            if stage != "$default":
                rest = rest.strip("/")[len(stage):]
            fstore = self.lam

            def invoker(fn, event):   # the Lambda store this router serves (shared with the console)
                fn = str(fn).split(":function:", 1)[-1].split(":", 1)[0]
                out = lam.dispatch(fstore, "POST", f"/2015-03-31/functions/{fn}/invocations", {}, {},
                                        json.dumps(event).encode())
                if out.status >= 300 or (out.headers or {}).get("X-Amz-Function-Error"):
                    return {"_error": True}
                try:
                    return json.loads((out.body or b"null").decode("utf-8"))
                except Exception:
                    return None
            r = apigw2_gw.handle(self.apigwv2, api_id, stage, method, rest.lstrip("/"), headers or {},
                                 query or {}, bytes(body), invoker=invoker)
            return {"status": r.status, "headers": dict(r.headers or {}), "body": r.body or b""}

        if svc == "apigatewayv2":   # native API Gateway V2 control plane (/v2/apis, …)
            r = apigw2.dispatch(self.apigwv2, method, path, query or {}, headers or {}, bytes(body))
            hdrs = dict(r.headers or {})
            if r.media_type and r.body and not any(k.lower() == "content-type" for k in hdrs):
                hdrs["content-type"] = r.media_type
            out = r.body or b""
            if lheaders.get("host") and b".execute-api.localhost:" in out:
                # The shown ApiEndpoint must work from where the client is: the simulator origin's
                # path-style invoke form (<origin>/apigw/<id>), not a host-style name on the gateway port.
                _o = f"{lheaders.get('x-forwarded-proto', 'http')}://{lheaders['host']}"
                out = re.sub(rb"https://([a-z0-9]+)\.execute-api\.localhost:\d+", lambda m: (_o + "/apigw/").encode() + m.group(1), out)
            return {"status": r.status, "headers": hdrs, "body": out}

        if svc == "dlm":   # native Data Lifecycle Manager REST (/policies, /policies/{id})
            r = dlm.dispatch(self.dlm, method, path, query or {}, headers or {}, bytes(body))
            hdrs = dict(r.headers or {})
            hdrs.setdefault("content-type", r.media_type)
            return {"status": r.status, "headers": hdrs, "body": r.body or b""}

        if svc == "apigateway":   # native API Gateway v1 control plane (/restapis) + the local invoke URL
            _m = re.match(r"^/restapis/([^/]+)/([^/]+)/_user_request_(/[^?]*)?", path)
            if _m:   # http://<host>/restapis/<id>/<stage>/_user_request_/<path>  (the standard local invoke form)
                r = apigw.invoke(self.apigw, _m.group(1), _m.group(2), method, _m.group(3) or "/", lheaders,
                                 {k: (v[0] if isinstance(v, list) else v) for k, v in (query or {}).items()},
                                 bytes(body), lambda_store=self.lam)
                hdrs = dict(r.headers or {})
                if r.media_type and not any(k.lower() == "content-type" for k in hdrs):
                    hdrs["content-type"] = r.media_type
                return {"status": r.status, "headers": hdrs, "body": r.body or b""}
            r = apigw.dispatch(self.apigw, method, path, query or {}, headers or {}, bytes(body))
            hdrs = dict(r.headers or {})
            if r.media_type and not any(k.lower() == "content-type" for k in hdrs):
                hdrs["content-type"] = r.media_type
            return {"status": r.status, "headers": hdrs, "body": r.body or b""}

        if svc == "azure-arm":   # Azure Resource Manager → the same AzureArm the Nano console uses
            host = lheaders.get("host", "")
            # LRO poll URLs must be absolute for az / azure-mgmt pollers.
            self.az_arm._base = f"{lheaders.get('x-forwarded-proto', 'http')}://{host}" if host else ""
            r = self.az_arm.handle(method, path, query or {}, self._json_body(body) if body else None)
            out = r.get("body")
            if _SQL_DB.search(path.split("?", 1)[0]) and r["status"] < 300 and isinstance(out, dict):
                out.setdefault("properties", {})["connectionInfo"] = self._azure_sql_conn(self.az_arm._base)
            hdrs = dict(r.get("headers") or {})
            if out is not None:
                hdrs.setdefault("content-type", "application/json")
            return {"status": r["status"], "headers": hdrs, "body": json.dumps(out).encode() if out is not None else b""}

        if svc == "azure-apim-gw":   # core/azure_apim_gateway_core.py: real routing + policies + subscription keys over the ARM state
            from core import azure_apim_gateway_core as apim_gw
            name, _, rest = path.split("?", 1)[0][len("/azure-data/apim/"):].partition("/")
            svc_rec = apim_gw.find_service(self.az_arm.state, name, lheaders.get("x-vyomi-rg"))
            if svc_rec is None:
                return {"status": 404, "headers": {"content-type": "application/json"},
                        "body": json.dumps({"statusCode": 404, "message": f"API Management service '{name}' not found."}).encode()}
            from core import azure_webhost_core as _wh
            r = apim_gw.handle(self.az_arm.state, svc_rec, method, "/" + rest, query or {}, lheaders, bytes(body or b""),
                               fetch=_wh.make_fetch(self.az_arm.state, self._apim_fetch()),
                               ip=lheaders.get("x-forwarded-for", "127.0.0.1").split(",")[0].strip(),
                               gateway=lheaders.get("x-vyomi-apim-gateway") or None)
            return {"status": r["status"], "headers": r["headers"], "body": r["body"]}

        if svc == "azure-site":   # /azure-data/site/{app}/... : the App Service front door + app host (core/azure_webhost_core.py)
            from core import azure_webhost_core as _wh
            from core import azure_autoscale_core as _asc
            name, _, rest = path.split("?", 1)[0][len("/azure-data/site/"):].partition("/")
            site = next((r for r in self.az_arm.state.values() if isinstance(r, dict) and str(r.get("type", "")).lower() == "microsoft.web/sites"
                         and str(r.get("name", "")).lower() == name.lower()), None)
            if site is None:
                return {"status": 404, "headers": {"content-type": "text/html"},
                        "body": f"<html><body><h2>404 Web Site not found: {name}</h2></body></html>".encode()}
            _asc.evaluate(self.az_arm.state)
            r = _wh.serve(self.az_arm.state, site, method, "/" + rest, {k: (v[0] if isinstance(v, list) else v) for k, v in (query or {}).items()},
                          lheaders, bytes(body or b""))
            _asc.evaluate(self.az_arm.state)
            return {"status": r["status"], "headers": r["headers"], "body": r["body"]}

        if svc == "azure-appconfig":   # /azure-data/appconfig/{store}/... over the ARM state's stores
            host = lheaders.get("host", "")
            store, _, rest = path[len("/azure-data/appconfig/"):].partition("/")
            base = f"{lheaders.get('x-forwarded-proto', 'http')}://{host}/azure-data/appconfig/{store}" if host else ""
            r = az_appcfg.data_dispatch(self.az_arm.state, store, method, "/" + rest, query or {},
                                        headers or {}, bytes(body) if method in ("PUT", "PATCH") else b"", base=base)
            hdrs = dict(r.get("headers") or {})
            hdrs.setdefault("Sync-Token", "zAJw6V16=Njo4NDk6;sn=849")
            if r.get("body") is None:
                return {"status": r["status"], "headers": hdrs, "body": b""}
            hdrs.setdefault("content-type", r.get("media") or "application/json")
            return {"status": r["status"], "headers": hdrs, "body": json.dumps(r["body"]).encode()}

        if svc == "azure-dns-query":   # DNS-over-HTTP JSON answers from the ARM state's zones
            r = az_dns.data_dispatch(self.az_arm.state, method, query or {})
            return {"status": r["status"], "headers": {"content-type": "application/json"},
                    "body": json.dumps(r["body"]).encode()}

        if svc == "scheduler":   # native EventBridge Scheduler REST (/schedules, /schedule-groups)
            r = sched.dispatch(self.sched, method, path, query or {}, headers or {}, bytes(body),
                                msg_store=self.msg, lam_store=self.lam, kinesis_store=self.kinesis, sfn_store=self.sfn)
            hdrs = dict(r.headers or {})
            if r.media_type and not any(k.lower() == "content-type" for k in hdrs):
                hdrs["content-type"] = r.media_type
            return {"status": r.status, "headers": hdrs, "body": r.body or b""}

        if svc == "pipes":   # native EventBridge Pipes REST (/v1/pipes) — SQS source -> target delivery
            r = events.dispatch_pipes(self.events, method, path, query or {}, headers or {}, bytes(body))
            hdrs = dict(r.headers or {})
            if r.media_type and not any(k.lower() == "content-type" for k in hdrs):
                hdrs["content-type"] = r.media_type
            return {"status": r.status, "headers": hdrs, "body": r.body or b""}

        if svc == "azure-sql-iam-rbac":   # Azure RBAC checkAccess (shares the IAM store)
            r = az_iam.dispatch(self.iam, method, path, query or {}, headers or {}, bytes(body))
            hdrs = dict(r.headers or {})
            if r.media_type and not any(k.lower() == "content-type" for k in hdrs):
                hdrs["content-type"] = r.media_type
            return {"status": r.status, "headers": hdrs, "body": r.body or b""}

        if svc == "azure-sql":   # Azure SQL data plane (shares the SqlStore, `/azure-sql` prefix)
            sql_path = path[len("/azure-sql"):] or "/"
            r = az_sql.dispatch(self.rds, method, sql_path, query or {}, headers or {}, bytes(body),
                                arm_state=self.az_arm.state, kv_store=self.az_kvkeys)
            hdrs = dict(r.headers or {})
            if r.media_type and not any(k.lower() == "content-type" for k in hdrs):
                hdrs["content-type"] = r.media_type
            return {"status": r.status, "headers": hdrs, "body": r.body or b""}

        if svc == "gcp-scc":
            r = gcp_scc_core.dispatch(self.s3.account.setdefault("gcp_scc", {}), method, path, query or {}, bytes(body), self.scc_ctx())
            try:
                self.s3.persist()
            except Exception:
                pass
            return {"status": r.status, "headers": {"content-type": "application/json"}, "body": r.body}

        if svc == "gcp-posture":
            proj = path.split("/")[3] if path.count("/") >= 3 else ""
            try:
                scans = gcp_ar.scan_images(self.gcp_ar, proj)
            except Exception:
                scans = []
            r = gcp_posture.dispatch(self.gcp_compute_vm, self.gcp_compute, self.gcs, method, path, threats=self.secscan_threats("gcp"), scans=scans)
            return {"status": r.status, "headers": {"content-type": r.media_type}, "body": r.body}

        if svc and svc.startswith("gcp-"):   # GCP services — native google-cloud-* REST wire
            # One project, by ID or number (core/gcp_project): normalize before the core sees it.
            proj = self.gcp_project() if callable(self.gcp_project) else self.gcp_project
            if self.STRICT_GCP_PROJECT:
                path, query, err = gcp_proj.normalize_request(path, dict(query or {}), method, proj)
            else:   # lax (engine unit tests only): any project id addresses its own data
                err = None
            _crm = svc == "gcp-resourcemanager" and self.STRICT_GCP_PROJECT and gcp_proj.CRM_PATH_RE.match(path)   # the project's own describe/list; folders, org policy, asset search stay v4's
            if err is not None or _crm:
                st, obj = err if err is not None else gcp_proj.crm_dispatch(method, path, query, proj)
                if st == 200 and path.startswith("/v3/projects") and isinstance(obj, dict):
                    # v3 Projects carry their real backing organization (Resource Manager store) as `parent`
                    for _pj in ([obj] if obj.get("projectId") else obj.get("projects") or []):
                        if isinstance(_pj, dict) and _pj.get("projectId") and "parent" not in _pj:
                            try:
                                par = gcp_rm._get_or_create_project(self.gcp_rm, _pj["projectId"]).get("parent")
                                if isinstance(par, dict) and par.get("id"):
                                    _pj["parent"] = dict(par)   # same shape the Resource Manager core serves
                            except Exception:
                                pass
                return {"status": st, "headers": {"content-type": "application/json"},
                        "body": json.dumps(obj).encode()}
            if svc == "gcp-backupdr":
                # Backup and DR (backupdr.googleapis.com) and Backup for GKE (gkebackup.googleapis.com) both serve
                # .../locations/{l}/backupPlans: tell them apart by what the call names (same hosts differ on real GCP)
                mb = re.match(r"^/v1/projects/([^/]+)/locations/([^/]+)/backupPlans(?:/([^/:?]+))?(/backups.*)?$", path)
                if mb:
                    _bd = {}
                    try:
                        _bd = json.loads(body) if body[:1] == b"{" else {}
                    except Exception:
                        _bd = {}
                    if mb.group(3):
                        _full = "projects/%s/locations/%s/backupPlans/%s" % (mb.group(1), mb.group(2), mb.group(3))
                        _gke = bool(mb.group(4)) or _full in self.gcp_gke.backup_plans
                    elif method == "POST":
                        _gke = "cluster" in _bd or "backupConfig" in _bd or "resourceType" not in _bd
                    else:
                        _h = {str(k).lower(): v for k, v in (headers or {}).items()}
                        _gke = mb.group(2) != "-" or "gkebackup" in str(_h.get("x-vyomi-service", "")).lower()   # "-" lists belong to Backup and DR unless the caller says gkebackup
                    if _gke:
                        svc = "gcp-container"
            if self.STRICT_GCP_PROJECT and svc != "gcp-gcs" and body[:1] in (b"{", b"["):   # object bytes are never rewritten
                body = gcp_proj.rewrite_body(bytes(body), proj)
            _gcp_core = {
                "gcp-gcs": (gcs, self.gcs), "gcp-firestore": (gcp_fs, self.gcp_fs), "gcp-datastore": (gcp_ds, self.gcp_fs), "gcp-eventarc": (gcp_eventarc, self.gcp_mon), "gcp-hub": (gcp_hub, self.gcp_mon),
                "gcp-kms": (gcp_kms, self.gcp_kms), "gcp-secretmanager": (gcp_sec, self.gcp_sec),
                "gcp-pubsub": (gcp_ps, self.gcp_msg), "gcp-iam": (gcp_iam, self.gcp_iam),
                "gcp-cloudsql": (gcp_sql, self.gcp_sql), "gcp-cloudscheduler": (gcp_sched, self.gcp_sched),
                "gcp-container": (gcp_gke, self.gcp_gke), "gcp-iamcredentials": (gcp_iamc, self.gcp_iamc),
                "gcp-monitoring": (gcp_mon, self.gcp_mon),
                "gcp-trace": (gcp_trace, self.gcp_mon),
                "gcp-osconfig": (gcp_osconfig, self.gcp_compute_vm),
                "gcp-commit": (gcp_commit, self.gcp_compute_vm),
                "gcp-apphub": (gcp_apphub, self.gcp_mon),
                "gcp-clouddeploy": (gcp_clouddeploy, self.gcp_mon),
                "gcp-cloudbuild": (gcp_cloudbuild, self.gcp_mon),
                "gcp-backupdr": (gcp_backupdr, self.gcp_compute_vm),
                "gcp-redis": (gcp_redis, self.gcp_redis),
                "gcp-vertex": (gcp_vertex, self.gcp_vertex),
                "gcp-artifactregistry": (gcp_ar, self.gcp_ar),
                "gcp-logging": (gcp_logging, self.gcp_logging),
                "gcp-compute": (gcp_compute, self.gcp_compute),
                "gcp-compute-vm": (gcp_compute_vm, self.gcp_compute_vm),
                "gcp-resourcemanager": (gcp_rm, self.gcp_rm),
                "gcp-pam": (gcp_pam, self.gcp_pam),
                "gcp-run": (gcp_run, self.gcp_run),
                "gcp-binauthz": (gcp_binauthz, self.gcp_run),
                "gcp-bigquery": (gcp_bigquery, self.gcs),
            }[svc]
            mod, store = _gcp_core
            if svc == "gcp-iamcredentials":   # service accounts live in the IAM core's store
                r = mod.dispatch(store, method, path, query or {}, headers or {}, bytes(body), resolver=self._iamc_resolve)
            elif svc == "gcp-cloudscheduler":   # a pubsub target publishes into the Pub/Sub core
                r = mod.dispatch(store, method, path, query or {}, headers or {}, bytes(body), invoker=self._sched_invoke)
            elif svc == "gcp-secretmanager":   # version lifecycle -> real Pub/Sub publish + Cloud Logging entry
                r = mod.dispatch(store, method, path, query or {}, headers or {}, bytes(body),
                                  notifier=self._secrets_notify, logger=self._secrets_log)
            elif svc == "gcp-container" and re.search(r"/operations([/:]|$)", path):   # operations are shared with Memorystore
                r = gcp_redis.dispatch_shared_operations(
                    self.gcp_redis, lambda *a: gcp_gke.dispatch(self.gcp_gke, *a), method, path, query or {}, headers or {}, bytes(body))
            elif svc == "gcp-cloudsql":   # instances.export/import read/write the simulator's GCS objects
                r = mod.dispatch(store, method, path, query or {}, headers or {}, bytes(body), gcs_store=self.gcs)
            elif svc == "gcp-firestore":   # exportDocuments/importDocuments read/write real GCS objects
                r = mod.dispatch(store, method, path, query or {}, headers or {}, bytes(body), gcs_store=self.gcs)
            elif svc == "gcp-compute-vm":   # image import (rawDisk) / export read+write the simulator's GCS objects
                r = mod.dispatch(store, method, path, query or {}, headers or {}, bytes(body), gcs_store=self.gcs, vpc_store=self.gcp_compute)
            elif svc == "gcp-compute":   # Connectivity Tests evaluate against the VMs too
                r = mod.dispatch(store, method, path, query or {}, headers or {}, bytes(body), vm_store=self.gcp_compute_vm)
            elif svc == "gcp-pam":   # grant activation/expiry is a real project IAM policy change
                r = mod.dispatch(store, method, path, query or {}, headers or {}, bytes(body),
                                  grant_fn=self._pam_grant, revoke_fn=self._pam_revoke)
            elif svc == "gcp-iam":   # org policy enforcement + Data Access audit log emission + SA metrics
                r = mod.dispatch(store, method, path, query or {}, headers or {}, bytes(body),
                                  rm_store=self.gcp_rm, logger=self._iam_audit_log, iamc_store=self.gcp_iamc)
            elif svc == "gcp-artifactregistry":   # a repository's CMEK key is checked/used through the real KMS core
                r = mod.dispatch(store, method, path, query or {}, headers or {}, bytes(body), kms_store=self.gcp_kms)
            elif svc == "gcp-cloudbuild":   # docker build/push steps run on the CI seam and push into the simulated Artifact Registry
                r = mod.dispatch(store, method, path, query or {}, headers or {}, bytes(body), ar_store=self.gcp_ar, gcs_read=self._gcs_read_object, run_deploy=self._cb_run_deploy)
            elif svc == "gcp-hub":   # Marketplace / Cloud Hub / Privacy & Security — derived from live state
                r = mod.dispatch(store, method, path, query or {}, headers or {}, bytes(body), inputs=self.hub_inputs)
            elif svc == "gcp-eventarc":   # triggers validate their Cloud Run destination / bucket / topic for real
                r = mod.dispatch(store, method, path, query or {}, headers or {}, bytes(body), run_store=self.gcp_run,
                                  pubsub_store=self.gcp_msg, gcs_store=self.gcs, log_fn=self._run_log)
            elif svc == "gcp-pubsub":   # a message delivered to an Eventarc-style Cloud Run trigger
                r = mod.dispatch(store, method, path, query or {}, headers or {}, bytes(body), on_publish=self._eventarc_deliver)
            elif svc == "gcp-binauthz":   # tags resolve to digests through the simulated Artifact Registry
                r = mod.dispatch(store, method, path, query or {}, headers or {}, bytes(body),
                                  resolver=lambda ref: gcp_ar.resolve_image_digest(self.gcp_ar, ref),
                                  vuln=self._ca_vuln_occurrences)
            elif svc == "gcp-run":   # real mutations + Eventarc deliveries -> real Cloud Logging entries
                r = mod.dispatch(store, method, path, query or {}, headers or {}, bytes(body),
                                  log_fn=self._run_log, topic_exists=self._run_topic_exists)
            else:
                r = mod.dispatch(store, method, path, query or {}, headers or {}, bytes(body))
            nano_triggers.after_gcp(self, svc, method, path, query, bytes(body), r)   # uploads / publishes fire Eventarc triggers
            hdrs = dict(r.headers or {})
            if r.media_type and not any(k.lower() == "content-type" for k in hdrs):
                hdrs["content-type"] = r.media_type
            if method.upper() != "GET":
                self.gcp_audit(method, path, query or {}, headers or {}, bytes(body), r.status)
            return {"status": r.status, "headers": hdrs, "body": r.body or b""}

        if svc == "az-appconfig":   # App Configuration data plane ({store}.azconfig.io: /kv /keys /labels /locks /revisions /snapshots /operations)
            # Key-values live INSIDE the store's ARM record (core/azure_appconfiguration_core.py),
            # so the "store" is just an ARM state lookup, not a separate InMemory* store — same
            # seam the ARM control plane (az_arm.state) and the console's own ARM calls already
            # share. Real App Configuration routes by the store's own {store}.azconfig.io
            # hostname; this one-relay-for-every-store simulation has no per-store host, so the
            # console sends the store it's showing as `x-vyomi-store` (azure/services/
            # appconfiguration/api.js setActiveStore), the same pattern Key Vault uses for
            # `x-vyomi-vault`.
            store = lheaders.get("x-vyomi-store", "")
            r = az_appconfig.data_dispatch(self.az_arm.state, store, method, path, query or {}, headers or {}, bytes(body))
            hdrs = dict(r.get("headers") or {})
            media = r.get("media")
            if media and not any(k.lower() == "content-type" for k in hdrs):
                hdrs["content-type"] = media
            out_body = r.get("body")
            return {"status": r["status"], "headers": hdrs, "body": b"" if out_body is None else json.dumps(out_body).encode()}

        if svc and svc.startswith("az-"):   # Azure data plane — native azure-* SDK wire
            _az_core = {
                "az-blob": (az_blob, self.az_blob), "az-cosmos": (az_cosmos, self.az_cosmos),
                "az-kv-secrets": (az_kvsec, self.az_kvsec), "az-kv-keys": (az_kvkeys, self.az_kvkeys),
                "az-kv-certs": (az_kvcerts, self.az_kvcerts),
                "az-queue": (az_queue, self.az_queue), "az-table": (az_table, self.az_table),
                "az-servicebus": (az_sb, self.az_sb),
                "az-acr": (az_acr, self.az_acr),
                "az-graph": (az_graph, self.az_graph),
            }[svc]
            mod, store = _az_core
            if svc in ("az-kv-secrets", "az-kv-keys", "az-kv-certs"):
                # Key Vault's own wire carries no vault identity (real Key Vault routes by the
                # vault's hostname, which this one-relay-for-every-vault simulation doesn't have);
                # the console sends the vault it's showing as `x-vyomi-vault` (azure/services/
                # keyvaults/api.js setActiveVault) so the Networking blade's publicNetworkAccess /
                # networkAcls can actually be enforced (azure.keyvaults.networking).
                vault = lheaders.get("x-vyomi-vault", "")
                if vault and keyvault_network_denied(self.az_arm.state, vault):
                    body_json = json.dumps({"error": {"code": "Forbidden",
                        "message": f"Client address is not authorized and caller is not a trusted "
                                   f"service. Client address not allowed to access vault '{vault}'."}}).encode()
                    return {"status": 403, "headers": {"content-type": "application/json"}, "body": body_json}
                # azure.keyvaults.access_configuration / azure.keyvaults.access_policies:
                # the vault's RBAC-vs-access-policy permission model, ENFORCED against the
                # single simulated signed-in principal (core/azure_arm_core.py
                # CALLER_PRINCIPAL_ID) every Keys/Secrets/Certificates call carries the vault
                # for (same x-vyomi-vault signal the networking check above reads).
                op = vault and classify_keyvault_operation(method, path)
                if op and keyvault_access_denied(self.az_arm.state, vault, op[0], op[1]):
                    body_json = json.dumps({"error": {"code": "Forbidden",
                        "message": f"The user, group or application 'oid={CALLER_PRINCIPAL_ID}' does not have "
                                   f"{op[0]} {op[1]} permission on key vault '{vault}'."}}).encode()
                    return {"status": 403, "headers": {"content-type": "application/json"}, "body": body_json}
                r = mod.dispatch(store, method, path, query or {}, headers or {}, bytes(body))
            elif svc == "az-blob":   # CORS preflight, lifecycle tiering/expiry and static-website
                # serving read the storage account's ARM-stored config (blobServices/default,
                # managementPolicies/default) — the single source of truth the Configuration/
                # CORS/Lifecycle/Static website panels already write through ARM.
                r = mod.dispatch(store, method, path, query or {}, headers or {}, bytes(body), arm_state=self.az_arm.state)
            elif svc == "az-cosmos":   # account network rules + provisioned/autoscale RU/s (429), from the ARM state
                r = mod.dispatch(store, method, path, query or {}, headers or {}, bytes(body), arm_state=self.az_arm.state)
            elif svc == "az-acr":
                # Same registry-scoped networking/retention enforcement as the offline substrate
                # (core/wire_ingress.py) — see azure.acr.networking / azure.acr.retention. The
                # console sends `x-vyomi-registry` (azure/services/acr/api.js setActiveRegistry);
                # the registry's own data-plane wire has no other way to say which registry's
                # publicNetworkAccess/retention policy applies.
                registry = lheaders.get("x-vyomi-registry", "")
                if registry and acr_network_denied(self.az_arm.state, registry):
                    body_json = json.dumps({"errors": [{"code": "Denied",
                        "message": f"Client is not authorized: public network access is disabled on registry '{registry}'."}]}).encode()
                    return {"status": 403, "headers": {"content-type": "application/json"}, "body": body_json}
                kwargs = {}
                if registry:
                    days = acr_retention_days(self.az_arm.state, registry)
                    if days is not None:
                        kwargs["retention_days"] = days
                r = mod.dispatch(store, method, path, query or {}, headers or {}, bytes(body), **kwargs)
            else:
                r = mod.dispatch(store, method, path, query or {}, headers or {}, bytes(body))
            hdrs = dict(r.headers or {})
            if r.media_type and not any(k.lower() == "content-type" for k in hdrs):
                hdrs["content-type"] = r.media_type
            return {"status": r.status, "headers": hdrs, "body": r.body or b""}

        if svc == "ecr":   # ECR JSON 1.1 control plane (region from the SigV4 credential scope)
            rm = re.search(r"Credential=[^/]+/[^/]+/([^/]+)/", lheaders.get("authorization", "") or "")
            r = ecr_core.dispatch(self.s3, lheaders.get("x-amz-target", "") or "", self._json_body(body), rm.group(1) if rm else ecr_core.DEFAULT_REGION)
            return {"status": r.status, "headers": {"content-type": "application/x-amz-json-1.1", **(r.headers or {})}, "body": json.dumps(r.body).encode()}

        if svc == "inspector2":
            rm = re.search(r"Credential=[^/]+/[^/]+/([^/]+)/", lheaders.get("authorization", "") or "")
            r = ecr_core.inspector_dispatch(self.s3, method, path, bytes(body), rm.group(1) if rm else ecr_core.DEFAULT_REGION)
            return {"status": r.status, "headers": {"content-type": "application/json"}, "body": json.dumps(r.body).encode()}

        if svc == "ecr-registry":   # OCI / Docker Registry v2 on the ECR host; layers + manifests stored in the simulator S3
            return self.ecr_registry(method, path, query or {}, headers or {}, bytes(body))

        if svc == "kinesis":   # JSON 1.1 (boto3/Go/CLI) or CBOR (Java SDK) by Content-Type
            status, hdrs, out = kinesis.handle_wire(self.kinesis, lheaders.get("x-amz-target", "") or "",
                                                    bytes(body), lheaders.get("content-type", ""))
            return {"status": status, "headers": hdrs, "body": out}

        if svc == "sqs" and not lheaders.get("x-amz-target"):   # legacy SQS Query protocol (XML)
            params = self._query_params(query, body)
            if "QueueUrl" not in params:   # POSTed to the queue URL itself (Java v1 SDK style)
                segs = [x for x in path.split("/") if x]
                if len(segs) == 2:
                    params["QueueUrl"] = segs[1]
            status, xml = sqs.dispatch_query(self.msg, params, lam_store=self.lam)
            return {"status": status, "headers": {"content-type": "text/xml"}, "body": xml.encode()}

        if svc in _JSON_CT:
            target = lheaders.get("x-amz-target", "") or ""
            payload = self._json_body(body)
            if svc == "ram" and not target:
                # boto3 / aws-cli speak RAM as rest-json (POST /createresourceshare, DELETE /deleteresourceshare?resourceShareArn=…),
                # not X-Amz-Target; map the lower-cased operation path onto the same core.
                _act = {k.lower(): k for k in ram._OPS}.get(path.split("?", 1)[0].strip("/").lower())
                if _act:
                    target = "AWSRAMFrontendService." + _act
                    if method in ("GET", "DELETE") and query:
                        payload = {**dict(query), **(payload if isinstance(payload, dict) else {})}
            if svc == "dynamodb":
                r = ddb.dispatch(self.ddb, target, payload, s3_store=self.s3)
            elif svc == "dax":
                r = dax.dispatch(self.dax, target, payload)
            elif svc == "kms":
                r = kms.dispatch(self.kms, target, payload)
            elif svc == "secretsmanager":   # a customer KmsKeyId is really encrypted/decrypted through the KMS core
                r = secrets.dispatch(self.sec, target, payload, kms_store=self.kms)
            elif svc == "events":
                r = events.dispatch(self.events, target, payload, lam_store=self.lam, kinesis_store=self.kinesis, sfn_store=self.sfn,
                                    caller_account=lheaders.get("x-amz-account-id"))
            elif svc == "kinesis":
                r = kinesis.dispatch(self.kinesis, target, payload)
            elif svc == "logs":
                r = logs.dispatch(self.logs, target, payload)
            elif svc == "ssm":   # SecureString parameters are really encrypted/decrypted through the KMS core
                r = ssm.dispatch(self.ssm, target, payload, kms_store=self.kms)
            elif svc == "stepfunctions":
                r = sfn.dispatch(self.sfn, target, payload, lambda_store=self.lam)
            elif svc == "ram":
                r = ram.dispatch(self.ram, target, payload, vpc_store=self.vpc)
            elif svc == "dms":   # DMS: endpoints resolve to simulator RDS instances; tasks copy real rows between them
                from core import dms_core
                r = dms_core.dispatch(self.rds, target, payload)
            elif svc in ("glue", "redshift-data"):   # zero-ETL integrations (DynamoDB/RDS -> Redshift-lite) + the Redshift Data API over them
                from core import zeroetl_core
                import types as _ty
                _fn = zeroetl_core.dispatch_glue if svc == "glue" else zeroetl_core.dispatch_redshift_data
                if svc == "glue":   # Data Catalog / crawlers (real S3 reads) / jobs -> core/glue_catalog_core; zero-ETL stays in zeroetl_core
                    from core import glue_catalog_core
                    _st, _doc = glue_catalog_core.dispatch(self.rds, self.s3, self.ddb, target, payload, fallback=_fn)
                else:
                    _st, _doc = _fn(self.rds, self.ddb, target, payload)
                r = _ty.SimpleNamespace(status=_st, headers={"x-amzn-errortype": _doc["__type"]} if _st >= 400 else {}, body=_doc)
            elif svc == "netfw":   # AWS Network Firewall (state lives in the VPC model so subnets/VPCs are validated for real)
                r = netfw.dispatch(self.vpc, target, payload)
            elif svc == "dnsfw":   # Route 53 Resolver DNS Firewall (state in the VPC model)
                r = dnsfw.dispatch(self.vpc, target, payload)
            elif svc == "organizations":   # AWS Organizations (state in the IAM store: extras["org"] + org_policies)
                r = orgs.dispatch(self.iam, target, payload)
            elif svc == "ce":   # Cost Explorer over the EC2/EBS (VPC model) + RDS inventory
                from core import ce_core
                r = ce_core.dispatch(self.vpc, self.rds, target, payload)
            elif svc == "eic":   # EC2 Instance Connect: pushed keys land on the EC2-model instance with a real 60 s validity window
                from core import ec2_instance_connect_core
                r = ec2_instance_connect_core.dispatch(self.vpc, target, payload)
            elif svc == "appas":   # Application Auto Scaling for DynamoDB (adjusts the table's real provisioned capacity)
                from core import appautoscaling_core
                r = appautoscaling_core.dispatch(self.ddb, target, payload)
            else:  # sqs
                r = sqs.dispatch(self.msg, target, payload, lam_store=self.lam)
            hdrs = dict(r.headers or {})
            hdrs.setdefault("content-type", _JSON_CT[svc])
            return {"status": r.status, "headers": hdrs,
                    "body": json.dumps(r.body).encode()}

        # Query-protocol / XML services
        params = self._query_params(query, body)
        if svc == "sts":
            return self._sts(params)
        if svc == "iam":
            params.pop("__caller", None)   # never trust a client-supplied caller; derive it from the signing key
            akid_m = _AKID_RE.search(lheaders.get("authorization", "") or "")
            ckey = self.iam.access_keys.get(akid_m.group(1)) if akid_m else None
            if ckey and ckey["user_name"] in self.iam.users:
                params["__caller"] = ckey["user_name"]
            r = iam.dispatch(self.iam, params, s3_store=self.s3)
        elif svc == "rds":
            r = rds.dispatch(self.rds, params, msg_store=self.msg, s3_store=self.s3)
        elif svc == "redshift":   # Redshift clusters (Query API) over the Redshift-lite SQL engine, state on the RDS store
            from core import redshift_core
            _st, _xml = redshift_core.dispatch(self.rds, params)
            return {"status": _st, "headers": {"content-type": "text/xml"}, "body": _xml.encode()}
        elif svc == "vpc":
            r = vpc.dispatch(self.vpc, params)
        elif svc == "asg":
            r = asg.dispatch(self.asg, params)
        elif svc == "elbv2":
            r = elbv2.dispatch(self.elbv2, params)
        elif svc == "cloudformation":
            r = cfn.dispatch(self.cfn, params, s3_store=self.s3, ddb_store=self.ddb,
                              iam_store=self.iam, msg_store=self.msg, logs_store=self.logs, cw_store=self.cw)
        else:  # sns
            r = sns.dispatch(self.msg, params)
        hdrs = dict(r.headers or {})
        hdrs.setdefault("content-type", "text/xml")
        body_txt = r.body if isinstance(r.body, str) else json.dumps(r.body)
        return {"status": r.status, "headers": hdrs, "body": body_txt.encode()}
