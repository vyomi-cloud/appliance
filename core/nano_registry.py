"""Single in-context store registry (Fix #2, Python half).

ONE source of truth both the console adapter (providers/aws_core_adapter) and the
native-wire relay (core/aws_wire_router via its `stores=` seam) read/write — so a
resource created in the console is seen by the SDK/relay and vice-versa *within a
Pyodide context*. Cross-CONTEXT parity (console page ↔ relay page) is added on top by
nano_persist + the IndexedDB/BroadcastChannel sync.

ALL THREE CLOUDS: the AWS console adapter, the GCP console adapter, the Azure
console adapter AND the native-wire relay (AwsWireRouter via `stores=`) all draw
from this one registry — so a resource created in ANY console (UI) is seen by the
SDK/CLI/curl (relay) and vice-versa, for every service of every cloud. Keys match
the AwsWireRouter `stores=` attrs AND nano_persist's STORE_ATTRS, so nano_persist
captures/restores the whole set for cross-context + reload persistence.
"""
from __future__ import annotations

from core.object_store import InMemoryObjectStore
from core.nosql_store import InMemoryNoSqlStore
from core.kms_keystore import InMemoryKeyStore
from core.kv_store import InMemoryKvStore
from core.sql_store import InMemorySqlStore
from core.iam_store import InMemoryIamStore
from core.messaging_store import InMemoryMessagingStore
from core.gcp_firestore_core import FirestoreStore
from core.gcp_artifactregistry_core import ArtifactRegistryStore
from core.azure_blob_core import AzureBlobStore
from core.azure_cosmos_core import CosmosStore
from core.azure_queue_core import AzureQueueStore
from core.nano_events import EventStore
from core.kinesis_core import KinesisStore
from core.apigatewayv2_core import ApiGwV2Store
from core.logs_core import LogsStore
from core.elbv2_core import Elbv2Store
from core.ssm_core import SsmStore
from core.stepfunctions_core import StepFunctionsStore
from core.gcp_cloudscheduler_core import CloudSchedulerStore
from core.gcp_iamcredentials_core import IamCredentialsStore
from core.gcp_redis_core import RedisStore
from core.gcp_container_core import ContainerStore
from core.gcp_compute_core import ComputeStore
from core.gcp_compute_instances_core import ComputeStore as ComputeVmStore
from core.gcp_resourcemanager_core import ResourceManagerStore
from core.gcp_pam_core import PamStore
from core.gcp_logging_core import LoggingStore
from core.scheduler_core import SchedulerStore
from core.gcp_run_core import RunStore
from core.azure_arm_core import AzureArm
from core.azure_graph_core import GraphStore

import types
from core.cloudwatch_core import CloudWatchStore
from core.gcp_monitoring_core import MonitoringStore

_REG: dict | None = None


def get() -> dict:
    """The shared store registry — a singleton per Pyodide context. Keys match the
    AwsWireRouter `stores=` names, nano_persist STORE_ATTRS, and the per-cloud
    console adapter store maps. One store per service, shared by UI + CLI/SDK/curl."""
    global _REG
    if _REG is None:
        _REG = {
            # ── AWS ──
            "s3":  InMemoryObjectStore(),
            "ddb": InMemoryNoSqlStore(),
            "kms": InMemoryKeyStore(),
            "sec": InMemoryKvStore(),
            "rds": InMemorySqlStore(),
            "iam": InMemoryIamStore(),
            "msg": InMemoryMessagingStore(),   # SHARED by sqs + sns (fan-out)
            "kinesis": KinesisStore(),         # Kinesis Data Streams
            "apigwv2": ApiGwV2Store(),
            # Console compute/network models: Lambda + API Gateway share ONE namespace
            # (AWS_PROXY reaches the registered functions); VPC has its own. They
            # live here (not as module singletons) so nano_persist snapshots them.
            "compute": types.SimpleNamespace(),
            "vpc_net": types.SimpleNamespace(),
            "extras": types.SimpleNamespace(items={}, cfg={}),   # console EC2/VPC/EventBridge sub-resource CRUD
            "logs": LogsStore(),               # CloudWatch Logs (core/logs_core.py)
            "elbv2": Elbv2Store(),             # ELBv2 load balancers / target groups / listeners (control plane)
            "ssm": SsmStore(),
            "sfn": StepFunctionsStore(),
            # ── GCP ── (storage/firestore/kms/secretmanager/pubsub/iam/cloudsql)
            "gcs":     InMemoryObjectStore(),
            "gcp_fs":  FirestoreStore(),
            "gcp_kms": InMemoryKeyStore(),
            "gcp_sec": InMemoryKvStore(),
            "gcp_gke": ContainerStore(),   # Kubernetes Engine clusters
            "gcp_mon": MonitoringStore(),   # Cloud Monitoring (policies, channels, metrics, series)
            "gcp_redis": RedisStore(),   # Memorystore for Redis instances
            "gcp_iamc": IamCredentialsStore(),   # IAM Credentials issue log
            "gcp_sched": CloudSchedulerStore(),   # Cloud Scheduler jobs
            "gcp_msg": InMemoryMessagingStore(),
            "gcp_iam": InMemoryIamStore(),
            "gcp_sql": InMemorySqlStore(),
            "gcp_ar":  ArtifactRegistryStore(),   # Artifact Registry repositories/packages
            "sched": SchedulerStore(),   # EventBridge Scheduler: schedules + schedule groups
            "gcp_logging": LoggingStore(),   # Cloud Logging: entries, sinks, metrics, buckets, views
            "gcp_rm": ResourceManagerStore(),   # Resource Manager: project, tags, contacts, org policies
            "gcp_pam": PamStore(),   # Privileged Access Manager entitlements
            "gcp_compute_vm": ComputeVmStore(),   # Compute Engine VMs, disks, images, templates
            "gcp_compute": ComputeStore(),   # VPC network: networks/subnets/firewalls/routes/addresses
            "gcp_run": RunStore(),   # Cloud Run (services, jobs, worker pools, domain mappings) — backs /functions
            # ── Azure ── (blob/cosmos/keyvault secrets+keys/queue/servicebus)
            "az_blob":   AzureBlobStore(),
            "az_cosmos": CosmosStore(),
            "az_kvsec":  InMemoryKvStore(),
            "az_kvkeys": InMemoryKeyStore(),
            "az_kvcerts": InMemoryKvStore(),
            "az_queue":  AzureQueueStore(),
            "az_sb":     InMemoryMessagingStore(),   # Service Bus (router-only today)
            "az_graph":  GraphStore(),               # Microsoft Graph (Entra ID: users/groups/apps)
            "az_arm":    AzureArm(),                 # ARM control plane (VMs, apps, …): public `state` map → persisted + synced
            # ── cross-cloud ── per-resource cloudsim event / activity log. DURABLE
            # + bounded: recorded on every mutating dispatch; persisted + cross-tab
            # synced via nano_persist (public dict attr `by_resource`, union-merge).
            "events": EventStore(),
            "cw": CloudWatchStore(),   # CloudWatch (metrics / alarms / dashboards)
        }
    return _REG
