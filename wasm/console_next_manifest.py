"""VENDORED (slice 1) from routes/console_next.py — the PURE manifest-building
code, extracted verbatim so it runs in Pyodide (Nano) with NO FastAPI import.

Source of truth: routes/console_next.py (lines 33..939, the constants + service
descriptor blocks + _aws/_gcp/_azure_services + _lens_services/_lens_summary +
_resolve_substrate + _capabilities). Keep in sync with that file — this copy must
produce byte-identical manifests to the appliance FastAPI route (§15 commonality).

The ONLY substrate-relevant behaviour lives inside _capabilities(substrate="nano")
already (connect.mode=relay, compute/serverless degrade) — no fork needed here.

DO NOT import FastAPI. The FastAPI route wiring (register()) is NOT vendored;
wasm/providers/console_next_adapter.py calls _capabilities() directly.
"""
from __future__ import annotations

import os


# The set of cloud lenses this vertical can serve. Each lens has a rich data-plane;
# the manifest carries a per-lens `services` catalog so widgets stay cloud-agnostic
# (§15.2): differences between clouds live HERE as data, never as widget branching.
CLOUD_LENSES = ["aws", "gcp", "azure"]


# ── S3 object-browser endpoint contract (the `api` block a cloud-agnostic
#    object-browser reads). Path templates use {bucket}/{key} placeholders the
#    widget substitutes + URL-encodes. These are the AWS-lens defaults; the GCS
#    lens supplies the SAME shape pointed at the GCS console-facade (§15.2). ──
_S3_OBJECT_BROWSER_API = {
    "listBuckets": "/api/s3/buckets",
    "createBucket": "/api/s3/buckets/{bucket}",
    "listObjects": "/api/s3/buckets/{bucket}/objects",
    "uploadObject": "/api/s3/buckets/{bucket}/objects",
    "objectMeta": "/api/s3/buckets/{bucket}/objects/{key}/meta",
    "objectDownload": "/api/s3/buckets/{bucket}/objects/{key}/download",
}

_GCS_OBJECT_BROWSER_API = {
    "listBuckets": "/api/console/gcs/buckets",
    "createBucket": "/api/console/gcs/buckets/{bucket}",
    "listObjects": "/api/console/gcs/buckets/{bucket}/objects",
    "uploadObject": "/api/console/gcs/buckets/{bucket}/objects",
    "objectMeta": "/api/console/gcs/buckets/{bucket}/objects/{key}/meta",
    "objectDownload": "/api/console/gcs/buckets/{bucket}/objects/{key}/download",
}

# The Azure Blob lens supplies the SAME object-browser shape pointed at the Azure
# Blob console-facade (§15.2). A "bucket" is a CONTAINER and an "object" a BLOB.
_AZURE_BLOB_OBJECT_BROWSER_API = {
    "listBuckets": "/api/console/azure-blob/containers",
    "createBucket": "/api/console/azure-blob/containers/{bucket}",
    "listObjects": "/api/console/azure-blob/containers/{bucket}/blobs",
    "uploadObject": "/api/console/azure-blob/containers/{bucket}/blobs",
    "objectMeta": "/api/console/azure-blob/containers/{bucket}/blobs/{key}/meta",
    "objectDownload": "/api/console/azure-blob/containers/{bucket}/blobs/{key}/download",
}

# The Azure Blob lens's connect snippet/CLI (§15.2) — the SAME object-browser widget
# renders these; only this descriptor data differs (no widget branching).
_AZURE_BLOB_CONNECT = {
    "snippet": (
        "from azure.storage.blob import BlobServiceClient\n"
        "# point the native client at the console endpoint\n"
        'svc = BlobServiceClient(account_url="{ep}",\n'
        '    credential="devstoreaccount1")\n'
        'container = svc.get_container_client("{bucket}")\n'
        'container.upload_blob(name="{key}", data=b"hello")\n'
        'container.download_blob("{key}").readall()'
    ),
    "cli": (
        "az storage blob list --container-name {bucket} \\\n"
        "  --account-name vyomistorage"
    ),
}


# ── sql-console endpoint contract (the `api` block the cloud-agnostic sql-console
#    reads). Path templates use a {db} placeholder the widget substitutes +
#    URL-encodes. These are the AWS-lens (RDS Data API) defaults; the Cloud SQL lens
#    supplies the SAME shape pointed at the Cloud SQL console-facade (§15.2). ──
_RDS_SQL_CONSOLE_API = {
    "databases": "/api/console/rds/databases",
    "execute": "/api/console/rds/execute",
    "schema": "/api/console/rds/databases/{db}/schema",
}

_CLOUDSQL_SQL_CONSOLE_API = {
    "databases": "/api/console/cloudsql/databases",
    "execute": "/api/console/cloudsql/execute",
    "schema": "/api/console/cloudsql/databases/{db}/schema",
}

_AZURE_SQL_CONSOLE_API = {
    "databases": "/api/console/azure-sql/databases",
    "execute": "/api/console/azure-sql/execute",
    "schema": "/api/console/azure-sql/databases/{db}/schema",
}

# The Azure SQL Database lens's connect snippet/CLI/hint (§15.2) — the SAME
# sql-console widget renders these; only this descriptor data differs (no widget
# branching). Azure SQL runs via the same relay-safe SQL engine as RDS/Cloud SQL.
_AZURE_SQL_CONNECT = {
    "snippet": (
        "import pyodbc\n"
        "# Azure SQL Database via the ODBC driver\n"
        'conn = pyodbc.connect(\n'
        '    "Driver={{ODBC Driver 18 for SQL Server}};"\n'
        '    "Server={ep};Database={db};Uid=sqladmin;Pwd=***")\n'
        'cur = conn.cursor()\n'
        'cur.execute("SELECT * FROM orders WHERE qty > 10")'
    ),
    "cli": (
        "az sql db show --name {db} \\\n"
        "  --server vyomi-sqlsrv --resource-group vyomi-rg"
    ),
    "hint": "⌘/Ctrl+Enter · runs against Azure SQL (Postgres engine)",
}

# The GCP Cloud SQL lens's connect snippet/CLI/hint (§15.2) — the SAME sql-console
# widget renders these; only this descriptor data differs (no widget branching). Cloud
# SQL is Postgres-backed; the console runs SQL via the same relay-safe SQL engine.
_CLOUDSQL_CONNECT = {
    "snippet": (
        "import sqlalchemy\n"
        "# Cloud SQL (Postgres) via the Cloud SQL Python Connector\n"
        "engine = sqlalchemy.create_engine(\n"
        '    "postgresql+pg8000://admin@/{db}?host={ep}")\n'
        'with engine.connect() as c:\n'
        '    c.execute(sqlalchemy.text("SELECT * FROM orders WHERE qty > 10"))'
    ),
    "cli": (
        "gcloud sql connect {db} --user=admin \\\n"
        '  --database={db}   # then: SELECT * FROM orders;'
    ),
    "hint": "⌘/Ctrl+Enter · runs against Cloud SQL (Postgres engine)",
}


# ── nosql-item-viewer endpoint contract (the `api` block the cloud-agnostic
#    nosql-item-viewer reads). Path templates use a {table} placeholder the widget
#    substitutes + URL-encodes. These are the AWS-lens (DynamoDB REST) defaults; the
#    Firestore lens supplies the SAME shape pointed at the Firestore console-facade
#    (§15.2 — no if(cloud) branching in the widget). ──
_DYNAMODB_NOSQL_API = {
    "listTables": "/api/dynamodb/tables",
    "createTable": "/api/dynamodb/tables",
    "getTable": "/api/dynamodb/tables/{table}",
    "listItems": "/api/dynamodb/tables/{table}/items",
    "putItem": "/api/dynamodb/tables/{table}/items",
    "deleteItem": "/api/dynamodb/tables/{table}/items",
    "queryItems": "/api/dynamodb/tables/{table}/query",
}

_FIRESTORE_NOSQL_API = {
    "listTables": "/api/console/firestore/collections",
    "createTable": "/api/console/firestore/collections",
    "getTable": "/api/console/firestore/collections/{table}",
    "listItems": "/api/console/firestore/collections/{table}/documents",
    "putItem": "/api/console/firestore/collections/{table}/documents",
    "deleteItem": "/api/console/firestore/collections/{table}/documents",
    "queryItems": "/api/console/firestore/collections/{table}/query",
}

_AZURE_COSMOS_NOSQL_API = {
    "listTables": "/api/console/azure-cosmos/containers",
    "createTable": "/api/console/azure-cosmos/containers",
    "getTable": "/api/console/azure-cosmos/containers/{table}",
    "listItems": "/api/console/azure-cosmos/containers/{table}/items",
    "putItem": "/api/console/azure-cosmos/containers/{table}/items",
    "deleteItem": "/api/console/azure-cosmos/containers/{table}/items",
    "queryItems": "/api/console/azure-cosmos/containers/{table}/query",
}

# The Azure Cosmos DB lens's connect snippet/CLI (§15.2) — the SAME nosql-item-viewer
# widget renders these; only this descriptor data differs (no widget branching).
# Cosmos (Core/SQL API) is a document DB; a "table" is a CONTAINER and the required
# document `id` plays the role of the partition key.
_AZURE_COSMOS_CONNECT = {
    "snippet": (
        "from azure.cosmos import CosmosClient\n"
        "# point the native client at the console endpoint\n"
        'client = CosmosClient("{ep}", credential="devkey")\n'
        'db = client.create_database_if_not_exists("vyomi-cosmos")\n'
        'cont = db.create_container_if_not_exists("{table}",\n'
        '    partition_key={"paths": ["/id"]})\n'
        'cont.upsert_item({"id": "item-1", "note": "hello"})\n'
        'cont.read_item("item-1", partition_key="item-1")'
    ),
    "cli": (
        "az cosmosdb sql container show \\\n"
        "  --account-name vyomi-cosmos --database-name vyomi-cosmos --name {table}"
    ),
}

# The GCP Firestore lens's connect snippet/CLI (§15.2) — the SAME nosql-item-viewer
# widget renders these; only this descriptor data differs (no widget branching).
# Firestore is a document DB; a "table" is a COLLECTION and the document id plays the
# role of the partition key.
_FIRESTORE_CONNECT = {
    "snippet": (
        "from google.cloud import firestore\n"
        "# point the native client at the console endpoint\n"
        'db = firestore.Client(project="cloudlearn",\n'
        '    client_options={"api_endpoint": "{ep}"})\n'
        'db.collection("{table}").document("item-1").set({"note": "hello"})\n'
        'db.collection("{table}").document("item-1").get().to_dict()'
    ),
    "cli": 'gcloud firestore documents list "{table}"',
}


# ── queue-topic-viewer endpoint contract (the `api` block the cloud-agnostic
#    queue-topic-viewer reads). Path templates use {queue}/{topic_arn} placeholders
#    the widget substitutes + URL-encodes (the SNS ARN travels in the query string,
#    so listSubscriptions has NO {topic_arn} — the widget appends ?topic_arn=). These
#    are the AWS-lens (SQS+SNS messaging) defaults; the GCP Pub/Sub lens supplies the
#    SAME shape pointed at the Pub/Sub console-facade (§15.2 — no if(cloud) branching
#    in the widget). ──
_SQS_MESSAGING_API = {
    "listQueues": "/api/console/messaging/queues",
    "createQueue": "/api/console/messaging/queues",
    "sendMessage": "/api/console/messaging/queues/{queue}/send",
    "receive": "/api/console/messaging/queues/{queue}/receive",
    "peek": "/api/console/messaging/queues/{queue}/peek",
    "purge": "/api/console/messaging/queues/{queue}/purge",
    "listTopics": "/api/console/messaging/topics",
    "createTopic": "/api/console/messaging/topics",
    "listSubscriptions": "/api/console/messaging/topics/subscriptions",
    "subscribe": "/api/console/messaging/topics/subscribe",
    "publish": "/api/console/messaging/topics/publish",
}

_PUBSUB_MESSAGING_API = {
    "listQueues": "/api/console/gcp-pubsub/subscriptions",
    "createQueue": "/api/console/gcp-pubsub/subscriptions",
    "sendMessage": "/api/console/gcp-pubsub/subscriptions/{queue}/send",
    "receive": "/api/console/gcp-pubsub/subscriptions/{queue}/receive",
    "peek": "/api/console/gcp-pubsub/subscriptions/{queue}/peek",
    "purge": "/api/console/gcp-pubsub/subscriptions/{queue}/purge",
    "listTopics": "/api/console/gcp-pubsub/topics",
    "createTopic": "/api/console/gcp-pubsub/topics",
    "listSubscriptions": "/api/console/gcp-pubsub/topics/subscriptions",
    "subscribe": "/api/console/gcp-pubsub/topics/subscribe",
    "publish": "/api/console/gcp-pubsub/topics/publish",
}

# The GCP Pub/Sub lens's connect snippet/CLI (§15.2) — the SAME queue-topic-viewer
# widget renders these; only this descriptor data differs (no widget branching). A
# Pub/Sub "topic" fans out to "subscriptions" you pull from — the widget's queue
# column IS the subscription list, the topic column the topics.
_PUBSUB_CONNECT = {
    "snippet": (
        "from google.cloud import pubsub_v1\n"
        "# point the native clients at the console endpoint\n"
        'opts = {"api_endpoint": "{ep}"}\n'
        "pub = pubsub_v1.PublisherClient(client_options=opts)\n"
        "sub = pubsub_v1.SubscriberClient(client_options=opts)\n"
        'topic = pub.topic_path("cloudlearn", "events")\n'
        "pub.create_topic(name=topic)\n"
        'subp = sub.subscription_path("cloudlearn", "{queue}")\n'
        "sub.create_subscription(name=subp, topic=topic)\n"
        'pub.publish(topic, b"hello")           # fans out to {queue}\n'
        "sub.pull(subscription=subp, max_messages=10)"
    ),
    "cli": ("gcloud pubsub topics list\ngcloud pubsub subscriptions list"),
}

# Rail-panel parentheticals for the Pub/Sub lens (the widget reads service.labels;
# AWS keeps the SQS/SNS defaults). A subscription is the pull-target ("queue"), the
# topic fans out, and wiring a subscription to a topic is the "pull" attach step.
_PUBSUB_LABELS = {"queues": "subscriptions", "topics": "Pub/Sub", "subscribe": "pull"}

# The Azure Service Bus lens's queue-topic-viewer endpoint contract — the SAME widget
# renders these; only this descriptor data differs (no widget branching). A Service Bus
# "queue" is a pull-target backlog; a "topic" fans out to attached subscriptions (an
# existing queue is attached as the subscription). Points at the Azure console-facade
# (§15.2) instead of /api/console/messaging/*.
_AZURE_SERVICEBUS_MESSAGING_API = {
    "listQueues": "/api/console/azure-servicebus/queues",
    "createQueue": "/api/console/azure-servicebus/queues",
    "sendMessage": "/api/console/azure-servicebus/queues/{queue}/send",
    "receive": "/api/console/azure-servicebus/queues/{queue}/receive",
    "peek": "/api/console/azure-servicebus/queues/{queue}/peek",
    "purge": "/api/console/azure-servicebus/queues/{queue}/purge",
    "listTopics": "/api/console/azure-servicebus/topics",
    "createTopic": "/api/console/azure-servicebus/topics",
    "listSubscriptions": "/api/console/azure-servicebus/topics/subscriptions",
    "subscribe": "/api/console/azure-servicebus/topics/subscribe",
    "publish": "/api/console/azure-servicebus/topics/publish",
}

# The Azure Service Bus lens's connect snippet/CLI (§15.2) — the SAME queue-topic-viewer
# widget renders these; only this descriptor data differs (no widget branching). A
# Service Bus topic fans out to subscriptions you receive from — the widget's queue
# column IS the queue/subscription list, the topic column the topics.
_AZURE_SERVICEBUS_CONNECT = {
    "snippet": (
        "from azure.servicebus import ServiceBusClient, ServiceBusMessage\n"
        "# point the native client at the console endpoint\n"
        'client = ServiceBusClient.from_connection_string(\n'
        '    "Endpoint={ep};SharedAccessKeyName=dev;SharedAccessKey=***")\n'
        'with client.get_topic_sender("events") as sender:\n'
        '    sender.send_messages(ServiceBusMessage(b"hello"))  # fans out to {queue}\n'
        'with client.get_queue_receiver("{queue}") as receiver:\n'
        "    for msg in receiver.receive_messages(max_message_count=10):\n"
        "        print(str(msg))"
    ),
    "cli": (
        "az servicebus queue list --namespace-name vyomi-sb \\\n"
        "  --resource-group vyomi-rg"
    ),
}

# Rail-panel parentheticals for the Service Bus lens (the widget reads service.labels).
# A subscription is an attached queue you receive from, the topic fans out, and wiring
# a queue to a topic is the "subscription" attach step.
_AZURE_SERVICEBUS_LABELS = {
    "queues": "queues / subscriptions", "topics": "Service Bus", "subscribe": "subscription"}


# ── kv-secret-viewer endpoint contract (the `api` block the cloud-agnostic
#    kv-secret-viewer reads). Path templates use a {name} placeholder the widget
#    substitutes + URL-encodes. These are the AWS-lens (Secrets Manager) defaults;
#    the GCP Secret Manager lens supplies the SAME shape pointed at the Secret
#    Manager console-facade (§15.2 — no if(cloud) branching in the widget). ──
_SECRETS_API = {
    "listSecrets": "/api/console/secrets",
    "createSecret": "/api/console/secrets",
    "describeSecret": "/api/console/secrets/{name}",
    "deleteSecret": "/api/console/secrets/{name}",
    "getValue": "/api/console/secrets/{name}/value",
    "putValue": "/api/console/secrets/{name}/value",
}

_GCP_SECRETS_API = {
    "listSecrets": "/api/console/gcp-secrets/secrets",
    "createSecret": "/api/console/gcp-secrets/secrets",
    "describeSecret": "/api/console/gcp-secrets/secrets/{name}",
    "deleteSecret": "/api/console/gcp-secrets/secrets/{name}",
    "getValue": "/api/console/gcp-secrets/secrets/{name}/value",
    "putValue": "/api/console/gcp-secrets/secrets/{name}/value",
}

# The GCP Secret Manager lens's connect snippet/CLI (§15.2) — the SAME
# kv-secret-viewer widget renders these; only this descriptor data differs (no widget
# branching). GCP secrets carry versions too; the value stays masked by default.
_GCP_SECRETS_CONNECT = {
    "snippet": (
        "from google.cloud import secretmanager\n"
        "# point the native client at the console endpoint\n"
        'opts = {"api_endpoint": "{ep}"}\n'
        "client = secretmanager.SecretManagerServiceClient(client_options=opts)\n"
        'parent = "projects/cloudlearn"\n'
        'client.create_secret(parent=parent, secret_id="{name}",\n'
        '    secret={"replication": {"automatic": {}}})\n'
        'client.add_secret_version(parent=f"{parent}/secrets/{name}",\n'
        '    payload={"data": b"s3cr3t"})\n'
        'client.access_secret_version(\n'
        '    name=f"{parent}/secrets/{name}/versions/latest").payload.data'
    ),
    "cli": 'gcloud secrets versions access latest --secret={name}',
}

_AZURE_KV_SECRETS_API = {
    "listSecrets": "/api/console/azure-kv-secrets/secrets",
    "createSecret": "/api/console/azure-kv-secrets/secrets",
    "describeSecret": "/api/console/azure-kv-secrets/secrets/{name}",
    "deleteSecret": "/api/console/azure-kv-secrets/secrets/{name}",
    "getValue": "/api/console/azure-kv-secrets/secrets/{name}/value",
    "putValue": "/api/console/azure-kv-secrets/secrets/{name}/value",
}

# The Azure Key Vault (secrets) lens's connect snippet/CLI (§15.2) — the SAME
# kv-secret-viewer widget renders these; only this descriptor data differs (no widget
# branching). Key Vault secrets carry versions too; the value stays masked by default.
_AZURE_KV_SECRETS_CONNECT = {
    "snippet": (
        "from azure.keyvault.secrets import SecretClient\n"
        "from azure.identity import DefaultAzureCredential\n"
        "# point the native client at the console endpoint\n"
        'client = SecretClient(vault_url="{ep}",\n'
        "    credential=DefaultAzureCredential())\n"
        'client.set_secret("{name}", "s3cr3t")\n'
        'client.get_secret("{name}").value'
    ),
    "cli": "az keyvault secret show --vault-name vyomi-kv --name {name}",
}


# ── kms-crypto-view endpoint contract (the `api` block the cloud-agnostic
#    kms-crypto-view reads). The describe path uses a {key_id} placeholder the widget
#    substitutes + URL-encodes. These are the AWS-lens (KMS) defaults; the GCP Cloud
#    KMS lens supplies the SAME shape pointed at the Cloud KMS console-facade (§15.2 —
#    no if(cloud) branching in the widget). ──
_KMS_API = {
    "listKeys": "/api/console/kms/keys",
    "createKey": "/api/console/kms/keys",
    "describeKey": "/api/console/kms/keys/{key_id}",
    "encrypt": "/api/console/kms/encrypt",
    "decrypt": "/api/console/kms/decrypt",
    "dataKey": "/api/console/kms/data-key",
}

_GCP_KMS_API = {
    "listKeys": "/api/console/gcp-kms/keys",
    "createKey": "/api/console/gcp-kms/keys",
    "describeKey": "/api/console/gcp-kms/keys/{key_id}",
    "encrypt": "/api/console/gcp-kms/encrypt",
    "decrypt": "/api/console/gcp-kms/decrypt",
    "dataKey": "/api/console/gcp-kms/data-key",
}

# The GCP Cloud KMS lens's connect snippet/CLI (§15.2) — the SAME kms-crypto-view
# widget renders these; only this descriptor data differs (no widget branching).
_GCP_KMS_CONNECT = {
    "snippet": (
        "from google.cloud import kms\n"
        "# point the native client at the console endpoint\n"
        'opts = {"api_endpoint": "{ep}"}\n'
        "client = kms.KeyManagementServiceClient(client_options=opts)\n"
        'key_name = "{key_id}"\n'
        'ct = client.encrypt(request={"name": key_name, "plaintext": b"hello"}).ciphertext\n'
        'client.decrypt(request={"name": key_name, "ciphertext": ct}).plaintext'
    ),
    "cli": (
        "gcloud kms encrypt --key {key_id} --plaintext-file - --ciphertext-file - "
        "<<< hello"
    ),
}

_AZURE_KV_KEYS_API = {
    "listKeys": "/api/console/azure-kv-keys/keys",
    "createKey": "/api/console/azure-kv-keys/keys",
    "describeKey": "/api/console/azure-kv-keys/keys/{key_id}",
    "encrypt": "/api/console/azure-kv-keys/encrypt",
    "decrypt": "/api/console/azure-kv-keys/decrypt",
    "dataKey": "/api/console/azure-kv-keys/data-key",
}

# The Azure Key Vault (keys) lens's connect snippet/CLI (§15.2) — the SAME
# kms-crypto-view widget renders these; only this descriptor data differs (no widget
# branching). Crypto is REAL (shared kms_core) over an independent key store.
_AZURE_KV_KEYS_CONNECT = {
    "snippet": (
        "from azure.keyvault.keys.crypto import CryptographyClient, EncryptionAlgorithm\n"
        "from azure.identity import DefaultAzureCredential\n"
        "# point the native client at the console endpoint\n"
        'crypto = CryptographyClient("{ep}/keys/{key_id}",\n'
        "    credential=DefaultAzureCredential())\n"
        'ct = crypto.encrypt(EncryptionAlgorithm.a256_gcm, b"hello").ciphertext\n'
        "crypto.decrypt(EncryptionAlgorithm.a256_gcm, ct).plaintext"
    ),
    "cli": (
        "az keyvault key encrypt --vault-name vyomi-kv --name {key_id} \\\n"
        "  --algorithm A256GCM --value hello"
    ),
}


# ── compute-terminal endpoint contract (the `api` block the cloud-agnostic
#    compute-terminal reads). The connect-info / key / exec paths use an
#    {instance_id} placeholder the widget substitutes + URL-encodes. These are the
#    AWS-lens (EC2) defaults — the SAME paths the widget already used — so the AWS
#    lens is byte-for-byte unchanged; the GCP Compute Engine lens supplies the SAME
#    shape pointed at the GCE console-facade (§15.2 — no if(cloud) branching). ──
_EC2_API = {
    "listInstances": "/api/ec2/instances",
    "connectInfo": "/api/aws/ec2/instances/{instance_id}/connect-info",
    "keyDownload": "/api/aws/ec2/instances/{instance_id}/private-key.pem",
    "exec": "/api/ec2/instances/{instance_id}/console/exec",
    # RunInstances (EC2 create) — the AWS lens carries a `launch` capability; the
    # cloud-agnostic compute-terminal reveals its "Launch instance" control ONLY
    # when the selected descriptor's `api` block has this key (§15.2 — capability-
    # driven, no if(cloud) in the widget). GCE / Azure VM console facades expose no
    # create endpoint, so they omit `launch` and the button self-hides for them.
    "launch": "/api/ec2/instances",
}

_GCE_API = {
    "listInstances": "/api/console/gce/instances",
    "connectInfo": "/api/gcp/compute/instances/{instance_id}/connect-info",
    "keyDownload": "/api/gcp/compute/instances/{instance_id}/private-key.pem",
    "exec": "/api/console/gce/instances/{instance_id}/exec",
}

# ── serverless-invoke endpoint contract (the `api` block the cloud-agnostic
#    serverless-invoke widget reads). The getFunction / invoke paths use a {name}
#    placeholder the widget substitutes + URL-encodes. These are the AWS-lens (Lambda)
#    defaults — the SAME paths the widget already used — so the AWS lens is
#    byte-for-byte unchanged; the GCP Cloud Functions lens supplies the SAME shape
#    pointed at the GCF console-facade (§15.2 — no if(cloud) branching). ──
_LAMBDA_API = {
    "listFunctions": "/api/lambda/functions",
    "getFunction": "/api/lambda/functions/{name}",
    "invoke": "/api/lambda/functions/{name}/invoke",
    "createFunction": "/api/lambda/functions",
}

_GCF_API = {
    "listFunctions": "/api/console/gcf/functions",
    "getFunction": "/api/console/gcf/functions/{name}",
    "invoke": "/api/console/gcf/functions/{name}/invoke",
    "createFunction": "/api/console/gcf/functions",
}

# The GCP Cloud Functions lens's connect snippet/CLI (§15.2) — the SAME
# serverless-invoke widget renders these; only this descriptor data differs (no
# widget branching). Cloud Functions are invoked via the Functions Framework HTTP
# trigger; the console facade runs the SAME sandboxed handler runtime as Lambda.
_GCF_CONNECT = {
    "snippet": (
        "import requests\n"
        "# call the deployed function's HTTP trigger (via the console endpoint)\n"
        'resp = requests.post("{ep}/api/console/gcf/functions/{name}/invoke",\n'
        '    json={"payload": {"hello": "world"}})\n'
        'print(resp.json()["payload"])'
    ),
    "cli": (
        "gcloud functions call {name} \\\n"
        "    --data '{\"hello\":\"world\"}'"
    ),
}

# The Azure Functions lens's serverless-invoke contract (P4) — the SAME
# serverless-invoke widget renders Azure Functions under lens=azure; only the
# manifest `api` block differs (§15.2 — no if(cloud) branching), pointing at the
# Azure Functions console-facade instead of /api/lambda/*.
_AZURE_FUNCTIONS_API = {
    "listFunctions": "/api/console/azure-functions/functions",
    "getFunction": "/api/console/azure-functions/functions/{name}",
    "invoke": "/api/console/azure-functions/functions/{name}/invoke",
    "createFunction": "/api/console/azure-functions/functions",
}

# The Azure Functions lens's connect snippet/CLI (§15.2) — the SAME serverless-invoke
# widget renders these; only this descriptor data differs (no widget branching). The
# console facade runs the SAME sandboxed handler runtime as Lambda / Cloud Functions.
_AZURE_FUNCTIONS_CONNECT = {
    "snippet": (
        "import requests\n"
        "# invoke the deployed function (via the console endpoint)\n"
        'resp = requests.post("{ep}/api/console/azure-functions/functions/{name}/invoke",\n'
        '    json={"payload": {"hello": "world"}})\n'
        'print(resp.json()["payload"])'
    ),
    "cli": (
        "az functionapp function invoke --name {name} \\\n"
        "  --resource-group cloudlearn-rg --function-name main"
    ),
}


# The GCP Compute Engine lens's connect snippet/CLI (§15.2) — the SAME compute-terminal
# widget renders these; only this descriptor data differs (no widget branching).
_GCE_CONNECT = {
    "snippet": (
        "from google.cloud import compute_v1\n"
        "# point the native client at the console endpoint\n"
        'client = compute_v1.InstancesClient(\n'
        '    client_options={"api_endpoint": "{ep}"})\n'
        'for vm in client.list(project="cloudlearn", zone="us-central1-a"):\n'
        "    print(vm.name, vm.status)"
    ),
    "cli": (
        "gcloud compute instances list --zones=us-central1-a "
        "--filter=\"name={instance_id}\""
    ),
}


# The Azure Virtual Machines lens's compute-terminal contract (P4) — the SAME
# compute-terminal widget renders Azure VMs under lens=azure; only the manifest
# `api` block differs (§15.2 — no if(cloud) branching). list + exec point at the
# Azure VM console-facade; connect-info / .pem reuse the existing NATIVE Azure VM
# endpoints (/api/azure/vm/{id}/*), exactly as the GCE lens reuses the native GCE
# connect-info / .pem.
_AZURE_VM_API = {
    "listInstances": "/api/console/azurevm/instances",
    "connectInfo": "/api/azure/vm/{instance_id}/connect-info",
    "keyDownload": "/api/azure/vm/{instance_id}/private-key.pem",
    "exec": "/api/console/azurevm/instances/{instance_id}/exec",
}

# The Azure Virtual Machines lens's connect snippet/CLI (§15.2) — the SAME
# compute-terminal widget renders these; only this descriptor data differs (no
# widget branching).
_AZURE_VM_CONNECT = {
    "snippet": (
        "from azure.mgmt.compute import ComputeManagementClient\n"
        "from azure.identity import DefaultAzureCredential\n"
        "# point the native client at the console endpoint\n"
        'client = ComputeManagementClient(\n'
        "    DefaultAzureCredential(), subscription_id='cloudlearn',\n"
        '    base_url="{ep}")\n'
        'for vm in client.virtual_machines.list("cloudlearn-rg"):\n'
        "    print(vm.name)"
    ),
    "cli": (
        "az vm list --resource-group cloudlearn-rg "
        "--query \"[?name=='{instance_id}']\""
    ),
}


def _aws_services(conf) -> list:
    """The AWS-lens service catalog (unchanged from P0/P2 — the rich vertical)."""
    return [
        {"id": "s3", "label": "S3", "icon": "▤", "widget": "object-browser",
         "terminology": "bucket", "backed_by": "MinIO",
         "api": dict(_S3_OBJECT_BROWSER_API),
         "conformance": conf.service_signal("s3")},
        {"id": "dynamodb", "label": "DynamoDB", "icon": "⊞", "widget": "nosql-item-viewer",
         "terminology": "table", "backed_by": "DynamoDB-Local",
         "api": dict(_DYNAMODB_NOSQL_API),
         "conformance": conf.service_signal("dynamodb")},
        {"id": "rds", "label": "RDS", "icon": "◫", "widget": "sql-console",
         "terminology": "db instance", "backed_by": "PostgreSQL/sqlite",
         "api": dict(_RDS_SQL_CONSOLE_API),
         "conformance": conf.service_signal("rds")},
        {"id": "sqs", "label": "SQS + SNS", "icon": "⇄", "widget": "queue-topic-viewer",
         "terminology": "queue / topic", "backed_by": "in-proc messaging",
         "api": dict(_SQS_MESSAGING_API),
         "conformance": conf.service_signal("sqs")},
        {"id": "secretsmanager", "label": "Secrets Manager", "icon": "⚿",
         "widget": "kv-secret-viewer", "terminology": "secret",
         "backed_by": "in-proc KvStore",
         "api": dict(_SECRETS_API),
         "conformance": conf.service_signal("secretsmanager")},
        {"id": "kms", "label": "KMS", "icon": "🔑", "widget": "kms-crypto-view",
         "terminology": "key", "backed_by": "in-proc KmsEngine",
         "api": dict(_KMS_API),
         "conformance": conf.service_signal("kms")},
        {"id": "ec2", "label": "EC2", "icon": "🖥", "widget": "compute-terminal",
         "terminology": "instance", "backed_by": "Docker/LXD",
         "api": dict(_EC2_API),
         "conformance": conf.service_signal("ec2")},
        {"id": "lambda", "label": "Lambda", "icon": "ƒ", "widget": "serverless-invoke",
         "terminology": "function", "backed_by": "in-proc runtime",
         "api": dict(_LAMBDA_API),
         "conformance": conf.service_signal("lambda")},
        {"id": "iam", "label": "IAM", "icon": "◆", "widget": "generic-control-plane",
         "terminology": "policy", "backed_by": "in-proc",
         "conformance": conf.service_signal("iam")},
    ]


def _gcp_services(conf) -> list:
    """The GCP-lens service catalog (P3 — the SECOND cloud). `storage` reuses the
    SAME object-browser widget: the ONLY difference is the `api` block (§15.2)."""
    return [
        {"id": "storage", "label": "Cloud Storage", "icon": "▤", "widget": "object-browser",
         "terminology": "bucket", "backed_by": "gcp_storage",
         "api": dict(_GCS_OBJECT_BROWSER_API),
         "conformance": conf.service_signal("gcp.storage")},
        {"id": "cloudsql", "label": "Cloud SQL", "icon": "◫", "widget": "sql-console",
         "terminology": "instance", "backed_by": "PostgreSQL",
         "api": dict(_CLOUDSQL_SQL_CONSOLE_API),
         "connect": dict(_CLOUDSQL_CONNECT),
         "conformance": conf.service_signal("gcp.cloudsql")},
        {"id": "firestore", "label": "Firestore", "icon": "⊞", "widget": "nosql-item-viewer",
         "terminology": "collection", "backed_by": "in-proc doc store",
         "api": dict(_FIRESTORE_NOSQL_API),
         "connect": dict(_FIRESTORE_CONNECT),
         "conformance": conf.service_signal("gcp.firestore")},
        {"id": "pubsub", "label": "Pub/Sub", "icon": "⇄", "widget": "queue-topic-viewer",
         "terminology": "topic / subscription", "backed_by": "in-proc pub/sub",
         "api": dict(_PUBSUB_MESSAGING_API),
         "connect": dict(_PUBSUB_CONNECT),
         "labels": dict(_PUBSUB_LABELS),
         "conformance": conf.service_signal("gcp.pubsub")},
        {"id": "secretmanager", "label": "Secret Manager", "icon": "⚿",
         "widget": "kv-secret-viewer", "terminology": "secret",
         "backed_by": "in-proc secret store",
         "api": dict(_GCP_SECRETS_API),
         "connect": dict(_GCP_SECRETS_CONNECT),
         "conformance": conf.service_signal("gcp.secretmanager")},
        {"id": "kms", "label": "Cloud KMS", "icon": "🔑",
         "widget": "kms-crypto-view", "terminology": "key",
         "backed_by": "in-proc KmsEngine",
         "api": dict(_GCP_KMS_API),
         "connect": dict(_GCP_KMS_CONNECT),
         "conformance": conf.service_signal("gcp.kms")},
        {"id": "compute", "label": "Compute Engine", "icon": "🖥",
         "widget": "compute-terminal", "terminology": "instance",
         "backed_by": "Docker/LXD",
         "api": dict(_GCE_API),
         "connect": dict(_GCE_CONNECT),
         "conformance": conf.service_signal("gcp.compute")},
        {"id": "functions", "label": "Cloud Functions", "icon": "ƒ",
         "widget": "serverless-invoke", "terminology": "function",
         "backed_by": "in-proc runtime",
         "api": dict(_GCF_API),
         "connect": dict(_GCF_CONNECT),
         "conformance": conf.service_signal("gcp.functions")},
        {"id": "iam", "label": "IAM", "icon": "◆", "widget": "generic-control-plane",
         "terminology": "policy", "backed_by": "in-proc",
         "conformance": conf.service_signal("gcp.iam")},
    ]


def _azure_services(conf) -> list:
    """The Azure-lens service catalog (P4 — the THIRD cloud). Each service reuses the
    SAME cloud-agnostic widget as its AWS/GCP peer; the ONLY difference is the `api`
    block (and optional `connect`) pointing at the Azure console-facade (§15.2)."""
    return [
        {"id": "blob", "label": "Blob Storage", "icon": "▤", "widget": "object-browser",
         "terminology": "container", "backed_by": "in-proc blob store",
         "api": dict(_AZURE_BLOB_OBJECT_BROWSER_API),
         "connect": dict(_AZURE_BLOB_CONNECT),
         "conformance": conf.service_signal("azure.blob")},
        {"id": "sql", "label": "SQL Database", "icon": "◫", "widget": "sql-console",
         "terminology": "database", "backed_by": "PostgreSQL/sqlite",
         "api": dict(_AZURE_SQL_CONSOLE_API),
         "connect": dict(_AZURE_SQL_CONNECT),
         "conformance": conf.service_signal("azure.sql")},
        {"id": "cosmos", "label": "Cosmos DB", "icon": "⊞", "widget": "nosql-item-viewer",
         "terminology": "container", "backed_by": "in-proc doc store",
         "api": dict(_AZURE_COSMOS_NOSQL_API),
         "connect": dict(_AZURE_COSMOS_CONNECT),
         "conformance": conf.service_signal("azure.cosmos")},
        {"id": "servicebus", "label": "Service Bus", "icon": "⇄",
         "widget": "queue-topic-viewer", "terminology": "queue / topic",
         "backed_by": "in-proc messaging",
         "api": dict(_AZURE_SERVICEBUS_MESSAGING_API),
         "connect": dict(_AZURE_SERVICEBUS_CONNECT),
         "labels": dict(_AZURE_SERVICEBUS_LABELS),
         "conformance": conf.service_signal("azure.servicebus")},
        {"id": "keyvault", "label": "Key Vault Secrets", "icon": "⚿",
         "widget": "kv-secret-viewer", "terminology": "secret",
         "backed_by": "in-proc secret store",
         "api": dict(_AZURE_KV_SECRETS_API),
         "connect": dict(_AZURE_KV_SECRETS_CONNECT),
         "conformance": conf.service_signal("azure.keyvault_secrets")},
        {"id": "keyvault-keys", "label": "Key Vault Keys", "icon": "🔑",
         "widget": "kms-crypto-view", "terminology": "key",
         "backed_by": "in-proc KmsEngine",
         "api": dict(_AZURE_KV_KEYS_API),
         "connect": dict(_AZURE_KV_KEYS_CONNECT),
         "conformance": conf.service_signal("azure.keyvault_keys")},
        {"id": "vm", "label": "Virtual Machines", "icon": "🖥",
         "widget": "compute-terminal", "terminology": "instance",
         "backed_by": "LXD/multipass",
         "api": dict(_AZURE_VM_API),
         "connect": dict(_AZURE_VM_CONNECT),
         "conformance": conf.service_signal("azure.vm")},
        {"id": "functions", "label": "Functions", "icon": "ƒ",
         "widget": "serverless-invoke", "terminology": "function",
         "backed_by": "in-proc runtime",
         "api": dict(_AZURE_FUNCTIONS_API),
         "connect": dict(_AZURE_FUNCTIONS_CONNECT),
         "conformance": conf.service_signal("azure.functions")},
        {"id": "rbac", "label": "RBAC / Entra", "icon": "◆",
         "widget": "generic-control-plane", "terminology": "role assignment",
         "backed_by": "in-proc",
         "conformance": conf.service_signal("azure.rbac")},
    ]


def _lens_services(lens: str, conf) -> list:
    if lens == "gcp":
        return _gcp_services(conf)
    if lens == "azure":
        return _azure_services(conf)
    return _aws_services(conf)


def _lens_summary(services: list) -> dict:
    """Workspace conformance summary scoped to the SELECTED lens's services (§4).
    Same flat shape as console_conformance.summary(); computed over just this lens
    so the status-bar pill is honest per cloud (the AWS pill is unaffected — the
    AWS catalog is unchanged). status = worst across the lens's services."""
    rank = {"conformant": 0, "partial": 1, "unknown": 2}
    worst = "conformant"
    services_full = passed = total = 0
    for svc in services:
        sig = svc.get("conformance") or {}
        if sig.get("mode") == "full":
            services_full += 1
        st = sig.get("status", "unknown")
        if rank.get(st, 2) > rank.get(worst, 2):
            worst = st
        c = sig.get("checks", {})
        passed += int(c.get("passed", 0))
        total += int(c.get("total", 0))
    return {
        "services_total": len(services),
        "services_full": services_full,
        "checks_passed": passed,
        "checks_total": total,
        "status": worst if services else "unknown",
    }


def _resolve_substrate(substrate: str | None = None) -> str:
    """Pick the substrate for this manifest (local | codespaces | nano).

    Precedence: explicit `?substrate=` query arg → env `VYOMI_CONSOLE_SUBSTRATE`
    → legacy env `VYOMI_SUBSTRATE` → default "local". Unknown values fall back to
    "local" so a bad query param can never fork the UI into an undefined state.
    """
    val = (substrate
           or os.environ.get("VYOMI_CONSOLE_SUBSTRATE")
           or os.environ.get("VYOMI_SUBSTRATE")
           or "local")
    val = str(val).strip().lower()
    return val if val in ("local", "codespaces", "nano") else "local"


def _capabilities(lens: str = "aws", substrate: str | None = None) -> dict:
    """Return the runtime capability manifest for THIS substrate + cloud lens (§15.1).

    `lens` selects which cloud's `services` catalog is returned (aws|gcp|azure). The
    lens switcher in the status-bar re-fetches this manifest for the chosen lens;
    widgets are cloud-agnostic and read their endpoints from each service's `api`
    block, so there is NO if(cloud===...) branching in component code (§15.2).

    `substrate` selects the serving substrate (local|codespaces|nano). Differences
    between substrates live HERE as capability *data* (§15.1 guarantee #3), never as
    forked UI: on **nano** the API is served by the SW→Pyodide cores over the same
    /api/* contract, so all data-plane widgets stay "full" (their WASM equivalents
    exist — object/sql[PGlite]/nosql/queue/kv/kms/generic per §14.9), while the two
    widgets with no in-browser real compute degrade: compute-terminal → "degraded"
    (no LXD/Docker/SSH in a tab) and serverless-invoke → "partial" (Pyodide invoke
    works, no container deploy). Those carry a `degrade_note` the SAME widget renders
    from the flag — it never checks the substrate name. On nano connect.mode="relay"
    and features.ssh=false (§14.8, §14.10).

    On the local FastAPI substrate S3 is backed by real MinIO, so object-browser is
    "full"; there is a real endpoint (not a relay); SSH exists on real compute. The
    other widgets are declared per their conformance/backing status. The UI degrades
    purely from these flags — it never checks the substrate name.
    """
    from core import console_conformance as conf

    lens = (lens or "aws").lower()
    if lens not in CLOUD_LENSES:
        lens = "aws"

    substrate = _resolve_substrate(substrate)
    # connect.mode is substrate-driven: nano reaches its SW-served API via the relay
    # (§14.8) — external SDK/CLI clients hit the relay endpoint, not host:port/SSH.
    # local/codespaces keep the env-configured mode (endpoint | ssh).
    if substrate == "nano":
        connect_mode = "relay"
    else:
        connect_mode = os.environ.get("VYOMI_CONNECT_MODE", "endpoint")  # endpoint | ssh | relay

    services = _lens_services(lens, conf)

    # ── Conformance-driven widget modes (§14.5) ──
    # The rich widget for a service renders ONLY when its widget mode is "full";
    # otherwise the center-canvas falls back to generic-control-plane. The per-service
    # mode comes from the conformance signal (core/console_conformance.py) so the gate
    # is honest and there is no substrate branching — the UI reads these flags. Built
    # from the SELECTED lens's catalog so each cloud's widgets gate honestly.
    widgets = {
        "object-browser": "generic", "sql-console": "generic",
        "compute-terminal": "generic", "serverless-invoke": "generic",
        "nosql-item-viewer": "generic", "kv-secret-viewer": "generic",
        "kms-crypto-view": "generic", "queue-topic-viewer": "generic",
        "generic-control-plane": "full",
    }
    for svc in services:
        wid = svc.get("widget")
        mode = ((svc.get("conformance") or {}).get("mode")) or "generic"
        # generic-control-plane is always "full" (it IS the fallback view).
        if wid and wid != "generic-control-plane":
            widgets[wid] = mode

    # ── Nano substrate capability degrade (§14.9, §14.10) ──
    # Nano has no real compute in a browser tab. The SAME widgets render a degraded
    # state driven purely by these flags (no if(substrate) in the widget). Only the
    # two compute-shaped widgets are affected; every data-plane widget keeps whatever
    # conformance mode the lens gave it (its WASM equivalent exists). A `degrade_note`
    # (map keyed by widget) tells the widget what CTA to show — it reads the note, it
    # never reads the substrate name.
    degrade_notes: dict = {}
    if substrate == "nano":
        # compute-terminal: metadata only, no SSH → "open a Codespace to SSH".
        widgets["compute-terminal"] = "degraded"
        degrade_notes["compute-terminal"] = (
            "No VM/SSH in a browser tab — open a Codespace to SSH into real compute."
        )
        # serverless-invoke: invoke works (Pyodide), but no container deploy.
        widgets["serverless-invoke"] = "partial"
        degrade_notes["serverless-invoke"] = (
            "Invoke runs in-browser (Pyodide); container deploy needs a Codespace."
        )

    return {
        "substrate": substrate,
        "lens": lens,
        "cloud_lenses": list(CLOUD_LENSES),  # lenses this vertical can switch between
        "widgets": widgets,
        # Per-widget degrade CTA copy (substrate-driven, §14.9). Empty on local/
        # codespaces. The widget reads widgets[name] + degrade_notes[name] — never
        # the substrate name (§15.2 anti-fork).
        "degrade_notes": degrade_notes,
        "features": {
            "glassbox": True,      # Calls tab is live in P0
            "snapshot": False,     # P2
            "fork": False,         # P2
            "replay": False,       # P2
            "relay": substrate == "nano",
            "ssh": substrate == "local" and connect_mode == "ssh",
        },
        "connect": {"mode": connect_mode},
        # The service rail is generated from this catalog — the shell renders only
        # these services, each mapped to a widget the manifest above gates. Each
        # carries its per-service conformance signal so the rail + widgets show the
        # honest state (§14.5).
        "services": services,
        # Workspace-level conformance summary for the status-bar pill (§4): flat
        # {services_total, services_full, checks_passed, checks_total, status}.
        # Scoped to the SELECTED lens so each cloud's pill is honest.
        "conformance": _lens_summary(services),
        "workspace": {
            "name": os.environ.get("VYOMI_WORKSPACE_NAME", "vyomi-dev-01"),
            "endpoint": os.environ.get("VYOMI_S3_ENDPOINT", ""),
        },
        "glassbox": {
            "event_schema_version": 1,
            "ring_max": int(os.environ.get("VYOMI_GLASSBOX_RING", "500") or "500"),
        },
    }

