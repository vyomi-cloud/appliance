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
from core import gcp_storage_core as gcs   # GCP: GCS JSON API, path-routed (not SigV4)
from core import gcp_firestore_core as gcp_fs
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
from core import gcp_artifactregistry_core as gcp_ar
from core import gcp_logging_core as gcp_logging
from core import gcp_compute_core as gcp_compute
from core import gcp_compute_instances_core as gcp_compute_vm
from core import gcp_resourcemanager_core as gcp_rm
from core import gcp_pam_core as gcp_pam
from core import gcp_run_core as gcp_run

# Cloud Scheduler httpTarget that names a Cloud Run job's own Admin API v2 `:run` endpoint
# (the job-trigger binding the Cloud Run console's Triggers tab shows and creates).
_SCHED_RUN_JOB_RE = re.compile(r"/v2/projects/([^/]+)/locations/([^/]+)/jobs/([^/:]+):run")


def _gcp_service(path):
    """Route a GCP request by URL path (GCP carries no SigV4; each google-cloud-*
    client is pointed at the relay and the path is the service discriminator)."""
    if re.match(r"^/v2/projects/[^/]+/locations/[^/]+/(services|jobs|workerPools|operations)([/:]|$)", path) \
            or path.lstrip("/").startswith(("apis/serving.knative.dev/", "apis/domains.cloudrun.com/")):
        # Cloud Run Admin API v2 (+ its Knative v1 facades for `gcloud run` and
        # `gcloud run domain-mappings`) — gated on its specific kinds (services/jobs/
        # workerPools/operations) because Cloud Logging also lives under /v2/projects/,
        # and Cloud Scheduler's /v1/.../locations/.../jobs shares the shape one version down.
        return "gcp-run"
    if path.startswith(("/storage/v1", "/upload/storage/v1", "/download/storage/v1")):
        return "gcp-gcs"
    if path.startswith("/v2/entries"):   # Cloud Logging: entries:write / entries:list
        return "gcp-logging"
    if re.match(r"^/v2/projects/[^/]+/(sinks|metrics|logs)([/:]|$)", path):
        return "gcp-logging"
    if re.match(r"^/v2/projects/[^/]+/locations/[^/]+/buckets", path):
        return "gcp-logging"
    if path.startswith(("/compute/v1", "/compute/beta")):
        # VPC resources → the networking core; everything else (instances, disks, images,
        # templates, groups, health checks…) → the VM core.
        if re.search(r"/(networks|subnetworks|firewalls|routes|addresses|routers)(/|$|\?|:)", path):
            return "gcp-compute"
        return "gcp-compute-vm"
    if path.startswith(("/sql/v1beta4", "/sql/v1")):
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
    if path.startswith("/v3/tagKeys"):
        return "gcp-resourcemanager"
    # Deny policies (IAM Deny API): /v2/policies/{attachmentPoint}/denypolicies[/…]
    if re.match(r"^/v2/policies/[^/]+/denypolicies(/.*)?$", path):
        return "gcp-iam"
    # Predefined roles catalog (no project scope): /v1/roles
    if path.startswith("/v1/roles"):
        return "gcp-iam"
    if re.match(r"^/v1/projects/[^/]+/locations/global/connectivityTests([/:?]|$)", path):
        return "gcp-compute"   # Network Intelligence Center Connectivity Tests → netsim via the VPC core
    if re.search(r"^/v1/projects/[^/]+/(dashboards|snoozes)([/:]|$)", path):   # Dashboards / Snoozes APIs (v1)
        return "gcp-monitoring"
    # The /v1/projects/* family — gate on /projects/ so Azure's root /secrets,
    # /keys, /topics never collide (GCP always scopes these under a project).
    if "/projects/" in path:
        if re.search(r"^/v1/projects/[^/]+/locations/[^/]+/instances([/:]|$)", path):
            return "gcp-redis"
        if re.search(r"/locations/[^/]+/entitlements([/?]|$)", path):
            return "gcp-pam"
        if "workloadIdentityPools" in path:
            return "gcp-iam"
        if re.search(r"^/v1(beta1)?/projects/[^/]+/(locations|zones)/[^/]+/(clusters|operations|serverConfig|backupPlans)([/:]|$)", path):
            return "gcp-container"
        if re.search(r"/locations/[^/]+/jobs([/:]|$)", path) or re.search(r"^/v1(beta1)?/projects/[^/]+/locations/?$", path):
            return "gcp-cloudscheduler"
        if re.search(r"^/v1(beta1)?/projects/[^/]+/locations/[^/]+/backups([/:]|$)", path):
            return "gcp-firestore"
        if "/locations/" in path and ("/repositories" in path or "/operations/" in path):
            return "gcp-artifactregistry"
        if re.search(r"^/v1/projects/[^/]+/projectSettings$", path):
            return "gcp-artifactregistry"
        if re.search(r"^/v1(beta1)?/projects/[^/]+/databases($|[/:])", path):
            return "gcp-firestore"
        if "/keyRings" in path:
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
        if re.search(r"^/v2/projects/[^/]+/policies(/|$)", path):
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
from core.azure_arm_core import AzureArm, keyvault_network_denied, acr_network_denied, acr_retention_days
from core import azure_servicebus_core as az_sb
from core import eventbridge_core as events
from core import scheduler_core as sched
from core import logs_core as logs
from core import lambda_core as lam
from core import apigateway_core as apigw
from core import apigatewayv2_core as apigw2
from core import ssm_core as ssm
from core import stepfunctions_core as sfn
from core import vpc_core as vpc
from core import autoscaling_core as asg
from core import ram_core as ram
from core import dlm_core as dlm
from core import kinesis_core as kinesis
from core import cloudwatch_core as cw
from core import azure_sql_core as az_sql
from core import azure_iam_core as az_iam
from core import azure_acr_core as az_acr
from core.azure_acr_core import AcrRegistryStore
from core import azure_graph_core as az_graph
import types as _types


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
        if s0 == "keys":
            return "az-kv-keys"
        if s0 == "secrets":
            return "az-kv-secrets"
        if s0 == "certificates":
            return "az-kv-certs"
        if s0 in ("kv", "labels", "locks", "revisions", "snapshots", "operations"):
            return "az-appconfig"
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
    "sqs": "sqs", "sns": "sns", "iam": "iam", "rds": "rds", "s3": "s3",
    "rds-data": "rds-data",   # the Aurora HTTP SQL surface (async path)
    "events": "events", "lambda": "lambda", "ec2": "vpc", "kinesis": "kinesis", "monitoring": "cloudwatch", "logs": "logs", "states": "stepfunctions",
    "autoscaling": "asg",
    "dlm": "dlm",
    "elasticloadbalancing": "elbv2",
    "cloudformation": "cloudformation",
    "ssm": "ssm", "scheduler": "scheduler", "pipes": "pipes", "ram": "ram",
    "apigateway": "apigateway",   # v1 REST control plane paths with no "/restapis" segment (apikeys, usageplans, clientcertificates, account)
}

# X-Amz-Target prefix → our core key (the JSON-wire services).
_TARGET_PREFIX = {
    "DynamoDB_": "dynamodb", "AmazonDAXV3": "dax", "TrentService": "kms",
    "secretsmanager": "secretsmanager", "AmazonSQS": "sqs", "AWSEvents": "events",
    "Kinesis_20131202": "kinesis",
    "Logs_20140328": "logs",
    "AmazonSSM": "ssm",
    "AWSStepFunctions": "stepfunctions",
    "AWSRAMFrontendService": "ram",
}

# Native JSON content-types the real SDK expects back per service.
_JSON_CT = {
    "dynamodb": "application/x-amz-json-1.0", "dax": "application/x-amz-json-1.1", "kms": "application/x-amz-json-1.1",
    "secretsmanager": "application/x-amz-json-1.1", "sqs": "application/x-amz-json-1.0",
    "events": "application/x-amz-json-1.1", "logs": "application/x-amz-json-1.1",
    "ssm": "application/x-amz-json-1.1",
    "stepfunctions": "application/x-amz-json-1.0",
    "ram": "application/x-amz-json-1.1",
}

# Query-protocol Action → service, for UNSIGNED query requests (signed ones route
# by credential scope). Small but covers the common verbs of each service.
_QUERY_ACTION = {
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


def _lower_headers(headers):
    return {str(k).lower(): v for k, v in (headers or {}).items()}


class AwsWireRouter:
    """Holds one in-tab store per service (the single source of truth for the
    relay endpoint) and routes native AWS-wire requests to the proven cores."""

    def __init__(self, sql_store=None, stores=None):
        # Stores are INJECTABLE (v2.4.0): Nano/relay pass nothing → in-WASM
        # defaults; Pro/Max passes a `stores` map of real backed stores (MinIO,
        # Postgres, Vault, NATS) behind the identical seam. `sql_store` kept for
        # back-compat (the browser PGlite path).
        s = stores or {}
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
        self.gcp_iam = s.get("gcp_iam") or InMemoryIamStore()
        self.gcp_sql = s.get("gcp_sql") or InMemorySqlStore()
        self.gcp_sched = s.get("gcp_sched") or gcp_sched.CloudSchedulerStore()   # Cloud Scheduler jobs
        self.gcp_gke = s.get("gcp_gke") or gcp_gke.ContainerStore()   # Kubernetes Engine clusters
        self.gcp_redis = s.get("gcp_redis") or gcp_redis.RedisStore()   # Memorystore for Redis instances
        self.gcp_iamc = s.get("gcp_iamc") or gcp_iamc.IamCredentialsStore()   # IAM Service Account Credentials issue log
        self.gcp_mon = s.get("gcp_mon") or gcp_mon.MonitoringStore()   # Cloud Monitoring (policies, channels, metrics, series)
        self.gcp_ar = s.get("gcp_ar") or gcp_ar.ArtifactRegistryStore()
        self.gcp_logging = s.get("gcp_logging") or gcp_logging.LoggingStore()   # Cloud Logging
        self.gcp_logging.mon_store = self.gcp_mon   # Logs Storage "Create usage alert" mirrors live byte/entry counts into Monitoring
        self.gcp_compute = s.get("gcp_compute") or gcp_compute.ComputeStore()   # VPC: networks, subnets, firewalls, routes, addresses
        self.gcp_compute_vm = s.get("gcp_compute_vm") or gcp_compute_vm.ComputeStore()   # Compute Engine VMs, disks, images, templates
        self.gcp_rm = s.get("gcp_rm") or gcp_rm.ResourceManagerStore()   # Resource Manager (project, tags, contacts, org policies)
        self.gcp_pam = s.get("gcp_pam") or gcp_pam.PamStore()   # Privileged Access Manager entitlements
        self.gcp_run = s.get("gcp_run") or gcp_run.RunStore()   # Cloud Run (backs /functions, which the real console folds into it)
        # Azure data-plane services.
        self.az_blob = s.get("az_blob") or AzureBlobStore()
        self.az_cosmos = s.get("az_cosmos") or CosmosStore()
        self.az_kvsec = s.get("az_kvsec") or InMemoryKvStore()
        self.az_kvkeys = s.get("az_kvkeys") or InMemoryKeyStore()
        self.az_kvcerts = s.get("az_kvcerts") or InMemoryKvStore()
        self.az_queue = s.get("az_queue") or AzureQueueStore()
        self.az_table = s.get("az_table") or AzureTableStore()
        self.az_arm = s.get("az_arm") or AzureArm()   # ARM control plane — read by the blob core for CORS/lifecycle/static-website enforcement
        self.az_arm.kv_secrets_store = self.az_kvsec   # APIM named values: Key Vault-type listValue resolves against this SAME space's KV secrets
        if getattr(self.az_arm, "sql_store", None) is None:   # Azure SQL export/import: this router's SQL data plane + Blob store
            self.az_arm.sql_store = self.rds
        if getattr(self.az_arm, "blob_store", None) is None:
            self.az_arm.blob_store = self.az_blob
        self.az_sb = s.get("az_sb") or InMemoryMessagingStore()   # Service Bus topics (fan-out)
        self.az_acr = s.get("az_acr") or AcrRegistryStore()   # Container Registry repositories/tags/manifests
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
        self.cw = s.get("cw") or cw.CloudWatchStore()          # CloudWatch metrics / alarms / dashboards
        self.cw.msg_store, self.cw.lam_store = self.msg, self.lam   # real SNS / Lambda alarm actions
        self.vpc = s.get("vpc") or s.get("vpc_net") or _types.SimpleNamespace()   # EC2/VPC network model
        self.vpc.cw_store = self.cw   # real StatusCheckFailed metrics (ec2.instances.monitoring / .alarms-metrics)
        self.cw.vpc_store = self.vpc  # real EC2 alarm actions (aws.cloudwatch.alarms.actions.ec2)
        self.asg = s.get("asg") or asg.AutoScalingStore()   # EC2 Auto Scaling groups + scaling policies
        self.asg.vpc_store = self.vpc   # scaling really launches/terminates real EC2 instances
        self.cw.asg_store = self.asg    # real Auto Scaling alarm actions (aws.cloudwatch.alarms.actions.compute)
        self.rds.cw_store = self.cw   # real DatabaseConnections/ReadIOPS/WriteIOPS metrics (rds.monitoring)
        self.ddb.cw_store = self.cw            # real per-op CloudWatch metrics (aws.dynamodb.monitor)
        self.ddb.kinesis_store = self.kinesis  # real Kinesis Data Streams destination (aws.dynamodb.kinesis)
        self.s3.cw_store = self.cw    # real AWS/S3 request metrics (s3.bucket.metrics), derived from actual activity
        self.ram = s.get("ram") or _types.SimpleNamespace()   # Resource Access Manager (subnet/SG sharing)
        self.vpc.ram_store = self.ram   # DeleteSubnet/DeleteSecurityGroup refuse while actively shared
        self.ram.vpc_store = self.vpc   # AssociateResourceShare validates the subnet/SG exists
        self.dax.cw_store = self.cw            # real AWS/DAX ItemCache/QueryCache hit/miss metrics
        self.dlm = s.get("dlm") or dlm.DlmStore()   # Data Lifecycle Manager (ec2.lifecycle-manager)
        self.dlm.vpc_store = self.vpc   # policies really create/prune real snapshots + AMIs
        self.logs = s.get("logs") or logs.LogsStore()         # CloudWatch Logs
        self.logs.lam_store, self.logs.kinesis_store = self.lam, self.kinesis   # real subscription-filter delivery
        self.cw.logs_store = self.logs            # real log-based Contributor Insights rules
        self.msg.logs_store = self.logs           # real SNS delivery-status logging (SQSSuccessFeedbackRoleArn/…)
        self.elbv2 = s.get("elbv2") or elbv2.Elbv2Store()
        self.elbv2.vpc_store = self.vpc    # target health reacts to real instance state
        self.elbv2.cw_store = self.cw      # real AWS/ApplicationELB + AWS/NetworkELB metrics
        self.elbv2.s3_store = self.s3      # trust-store CA bundles are read from Vyomi's own S3
        self.sfn = s.get("sfn") or sfn.StepFunctionsStore()   # Step Functions (state machines + executions)
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
                gcp_run.run_job(self.gcp_run, project, location, jid, {})
            except gcp_run._E as e:
                return e.message
            return True
        if kind != "pubsub":
            return True
        topic = d["topicName"]
        msg = {"messages": [{"data": d.get("data", ""), "attributes": d.get("attributes") or {}}]}
        r = gcp_ps.dispatch(self.gcp_msg, "POST", "/v1/%s:publish" % topic, {}, {}, json.dumps(msg).encode())
        return True if r.status < 300 else "Topic %s not found." % topic

    def _secrets_notify(self, topic, event_type, secret_name):
        """Secret Manager version lifecycle event -> a real Pub/Sub publish on the
        configured topic (the SAME gcp_ps.dispatch seam Cloud Scheduler targets use)."""
        msg = {"messages": [{
            "data": base64.b64encode(json.dumps({"secretId": secret_name, "eventType": event_type}).encode()).decode(),
            "attributes": {"eventType": event_type, "secretId": secret_name},
        }]}
        gcp_ps.dispatch(self.gcp_msg, "POST", "/v1/%s:publish" % topic, {}, {}, json.dumps(msg).encode())

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
    def service_of(self, method, path, lheaders, body, query=None):
        # Static website hosting: real S3 serves this over its OWN unsigned HTTP(S) origin
        # (bucket.s3-website-<region>.amazonaws.com), never the signed control+data API —
        # route it first, unambiguously, by the distinct path prefix the relay/dev_server
        # exposes that origin under.
        if path.startswith("/__s3_website__/"):
            return "s3-website"
        # GCP services are unambiguous by path (REST) and carry no SigV4 — route
        # them first so they never fall through to the S3 default.
        gcp = _gcp_service(path)
        if gcp:
            return gcp
        az = _azure_service(path, lheaders, query)   # Azure data plane (x-ms-* / api-version)
        if az:
            return az
        if self._servicebus_service(method, path, lheaders):
            return "az-servicebus"
        if any(path.startswith(p) for p in (  # Lambda REST (native boto3 lambda wire + sub-resources,
                "/2015-03-31/functions", "/2015-03-31/layers", "/2015-03-31/event-source-mappings",
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
        if "microsoft.authorization" in path.lower():   # Azure RBAC checkAccess
            return "azure-sql-iam-rbac"
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
        iam.record_activity(self.iam, key["user_name"], svc, self._action_name(svc, lheaders, query, body))

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
        return self.handle(method, path, query, headers, body)

    def handle(self, method, path, query, headers, body):
        """Route ONE native-wire request. Returns {status, headers, body(bytes)}.
        SYNC services only — the RDS Data API goes through ahandle()."""
        lheaders = _lower_headers(headers)
        body = body if isinstance(body, (bytes, bytearray)) else (body or b"")
        if isinstance(body, str):
            body = body.encode("utf-8")
        svc = self.service_of(method, path, lheaders, body, query)
        self._track_activity(svc, lheaders, query, body)

        if svc == "rds-data":  # async-only — guard the sync path
            return {"status": 400, "headers": {"x-amzn-errortype": "BadRequestException"},
                    "body": b'{"message":"RDS Data API requires the async dispatch path"}'}

        if svc == "s3":
            r = s3.dispatch(self.s3, method, path, query or {}, headers or {}, bytes(body))
            return {"status": r.status, "headers": dict(r.headers or {}),
                    "body": r.body or b""}

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
            r = lam.dispatch(self.lam, method, path, query or {}, headers or {}, bytes(body),
                              msg_store=self.msg, lam_store=self.lam)
            hdrs = dict(r.headers or {})
            if r.media_type and not any(k.lower() == "content-type" for k in hdrs):
                hdrs["content-type"] = r.media_type
            return {"status": r.status, "headers": hdrs, "body": r.body or b""}

        if svc == "apigatewayv2":   # native API Gateway V2 control plane (/v2/apis, …)
            r = apigw2.dispatch(self.apigwv2, method, path, query or {}, headers or {}, bytes(body))
            hdrs = dict(r.headers or {})
            if r.media_type and r.body and not any(k.lower() == "content-type" for k in hdrs):
                hdrs["content-type"] = r.media_type
            return {"status": r.status, "headers": hdrs, "body": r.body or b""}

        if svc == "dlm":   # native Data Lifecycle Manager REST (/policies, /policies/{id})
            r = dlm.dispatch(self.dlm, method, path, query or {}, headers or {}, bytes(body))
            hdrs = dict(r.headers or {})
            hdrs.setdefault("content-type", r.media_type)
            return {"status": r.status, "headers": hdrs, "body": r.body or b""}

        if svc == "apigateway":   # native API Gateway v1 control plane (/restapis)
            r = apigw.dispatch(self.apigw, method, path, query or {}, headers or {}, bytes(body))
            hdrs = dict(r.headers or {})
            if r.media_type and not any(k.lower() == "content-type" for k in hdrs):
                hdrs["content-type"] = r.media_type
            return {"status": r.status, "headers": hdrs, "body": r.body or b""}

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

        if svc and svc.startswith("gcp-"):   # GCP services — native google-cloud-* REST wire
            _gcp_core = {
                "gcp-gcs": (gcs, self.gcs), "gcp-firestore": (gcp_fs, self.gcp_fs),
                "gcp-kms": (gcp_kms, self.gcp_kms), "gcp-secretmanager": (gcp_sec, self.gcp_sec),
                "gcp-pubsub": (gcp_ps, self.gcp_msg), "gcp-iam": (gcp_iam, self.gcp_iam),
                "gcp-cloudsql": (gcp_sql, self.gcp_sql), "gcp-cloudscheduler": (gcp_sched, self.gcp_sched),
                "gcp-container": (gcp_gke, self.gcp_gke), "gcp-iamcredentials": (gcp_iamc, self.gcp_iamc),
                "gcp-monitoring": (gcp_mon, self.gcp_mon),
                "gcp-redis": (gcp_redis, self.gcp_redis),
                "gcp-artifactregistry": (gcp_ar, self.gcp_ar),
                "gcp-logging": (gcp_logging, self.gcp_logging),
                "gcp-compute": (gcp_compute, self.gcp_compute),
                "gcp-compute-vm": (gcp_compute_vm, self.gcp_compute_vm),
                "gcp-resourcemanager": (gcp_rm, self.gcp_rm),
                "gcp-pam": (gcp_pam, self.gcp_pam),
                "gcp-run": (gcp_run, self.gcp_run),
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
            elif svc == "gcp-compute":   # Connectivity Tests evaluate against the VMs too
                r = mod.dispatch(store, method, path, query or {}, headers or {}, bytes(body), vm_store=self.gcp_compute_vm)
            elif svc == "gcp-pam":   # grant activation/expiry is a real project IAM policy change
                r = mod.dispatch(store, method, path, query or {}, headers or {}, bytes(body),
                                  grant_fn=self._pam_grant, revoke_fn=self._pam_revoke)
            elif svc == "gcp-iam":   # org policy enforcement + Data Access audit log emission
                r = mod.dispatch(store, method, path, query or {}, headers or {}, bytes(body),
                                  rm_store=self.gcp_rm, logger=self._iam_audit_log)
            else:
                r = mod.dispatch(store, method, path, query or {}, headers or {}, bytes(body))
            hdrs = dict(r.headers or {})
            if r.media_type and not any(k.lower() == "content-type" for k in hdrs):
                hdrs["content-type"] = r.media_type
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
                r = mod.dispatch(store, method, path, query or {}, headers or {}, bytes(body))
            elif svc == "az-blob":   # CORS preflight, lifecycle tiering/expiry and static-website
                # serving read the storage account's ARM-stored config (blobServices/default,
                # managementPolicies/default) — the single source of truth the Configuration/
                # CORS/Lifecycle/Static website panels already write through ARM.
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
            if svc == "dynamodb":
                r = ddb.dispatch(self.ddb, target, payload, s3_store=self.s3)
            elif svc == "dax":
                r = dax.dispatch(self.dax, target, payload)
            elif svc == "kms":
                r = kms.dispatch(self.kms, target, payload)
            elif svc == "secretsmanager":   # a customer KmsKeyId is really encrypted/decrypted through the KMS core
                r = secrets.dispatch(self.sec, target, payload, kms_store=self.kms)
            elif svc == "events":
                r = events.dispatch(self.events, target, payload, lam_store=self.lam, kinesis_store=self.kinesis, sfn_store=self.sfn)
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
            else:  # sqs
                r = sqs.dispatch(self.msg, target, payload, lam_store=self.lam)
            hdrs = dict(r.headers or {})
            hdrs.setdefault("content-type", _JSON_CT[svc])
            return {"status": r.status, "headers": hdrs,
                    "body": json.dumps(r.body).encode()}

        # Query-protocol / XML services
        params = self._query_params(query, body)
        if svc == "iam":
            r = iam.dispatch(self.iam, params, s3_store=self.s3)
        elif svc == "rds":
            r = rds.dispatch(self.rds, params, msg_store=self.msg, s3_store=self.s3)
        elif svc == "vpc":
            r = vpc.dispatch(self.vpc, params)
        elif svc == "asg":
            r = asg.dispatch(self.asg, params)
        elif svc == "elbv2":
            r = elbv2.dispatch(self.elbv2, params)
        elif svc == "cloudformation":
            r = cfn.dispatch(self.cfn, params, s3_store=self.s3, ddb_store=self.ddb,
                              iam_store=self.iam, msg_store=self.msg, logs_store=self.logs)
        else:  # sns
            r = sns.dispatch(self.msg, params)
        hdrs = dict(r.headers or {})
        hdrs.setdefault("content-type", "text/xml")
        body_txt = r.body if isinstance(r.body, str) else json.dumps(r.body)
        return {"status": r.status, "headers": hdrs, "body": body_txt.encode()}
