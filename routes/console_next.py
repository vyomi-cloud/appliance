"""console-next (P0) — the fidelity-first console redesign vertical.

Additive routes for the new Lit-based console engine. Coexists with the existing
static/*-console.html consoles; touches none of them.

Endpoints added here:
  GET  /api/console/capabilities        — the capability manifest (§15.1). The UI
                                           reads it and gates on it — NO substrate/
                                           cloud branching in components (§15.2).
  GET  /api/console/calls               — one-shot ring-buffer snapshot (newest-first)
  GET  /api/console/calls/stream        — SSE stream of captured calls (§12.3)
  POST /api/console/calls/clear         — clear the ring buffer (dev convenience)
  GET  /console-next[/...]              — the SPA shell (index.html)

Static assets for the SPA are served from the /console-next-assets mount so that
asset refs are base-path-relative and the same bundle can be served under a subpath
(Nano's /nano/ scope) — §15.1 guarantee #6.
"""

from __future__ import annotations

import os

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

_HERE = os.path.dirname(__file__)
_ASSETS_DIR = os.path.join(_HERE, "..", "static", "console-next")
_INDEX = os.path.join(_ASSETS_DIR, "index.html")


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
    "deleteBucket": "/api/s3/buckets/{bucket}",
    "listObjects": "/api/s3/buckets/{bucket}/objects",
    "uploadObject": "/api/s3/buckets/{bucket}/objects",
    "objectMeta": "/api/s3/buckets/{bucket}/objects/{key}/meta",
    "objectDownload": "/api/s3/buckets/{bucket}/objects/{key}/download",
    "deleteObject": "/api/s3/buckets/{bucket}/objects/{key}",
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
#
# Launch (create db instance): each `api` block also carries a `create` path +
# a `createForm` hint pointing at the REAL NATIVE provisioning endpoint (the one
# the classic console / native SDK uses) — NOT the /api/console/* SQL facade. The
# sql-console widget's "Create database instance" control is capability-driven: it
# shows ONLY when `api.create` is present, and it builds the per-cloud request
# BODY from `createForm` (method + field labels/defaults + a body template with
# {id}/{engine} placeholders) so the widget stays generic (no if(cloud) branching).
_RDS_SQL_CONSOLE_API = {
    "databases": "/api/console/rds/databases",
    "execute": "/api/console/rds/execute",
    "schema": "/api/console/rds/databases/{db}/schema",
    # Native RDS CreateDBInstance (providers/aws_routes.py → api_rds_create_database,
    # RDSDatabaseRequest). Real provisioning — spins the Docker/LXD runtime bundle.
    "create": "/api/rds/databases",
    "createForm": {
        "method": "POST",
        "title": "Create DB instance",
        "idLabel": "db instance identifier",
        "idPlaceholder": "vy-rds-01",
        "engineLabel": "engine",
        "engineDefault": "postgres",
        "engineOptions": ["postgres", "mysql", "mariadb"],
        # Body mirrors RDSDatabaseRequest (accepts db_instance_identifier / engine /
        # db_instance_class). {id}/{engine} substituted from the form.
        "body": {
            "db_instance_identifier": "{id}",
            "engine": "{engine}",
            "db_instance_class": "db.t3.micro",
        },
    },
}

_CLOUDSQL_SQL_CONSOLE_API = {
    "databases": "/api/console/cloudsql/databases",
    "execute": "/api/console/cloudsql/execute",
    "schema": "/api/console/cloudsql/databases/{db}/schema",
    # Native Cloud SQL Admin insert (server.py → api_gcp_sql_create_instance).
    # Real provisioning — spins the gcp_sql runtime bundle. Project defaults to
    # cloudlearn (the appliance's fixed project) so the console needn't thread it.
    "create": "/api/gcp/sql/v1beta4/projects/cloudlearn/instances",
    "createForm": {
        "method": "POST",
        "title": "Create instance",
        "idLabel": "instance name",
        "idPlaceholder": "vy-sql-01",
        "engineLabel": "database version",
        "engineDefault": "POSTGRES_15",
        "engineOptions": ["POSTGRES_15", "POSTGRES_14", "MYSQL_8_0"],
        # Cloud SQL Admin instances#insert shape: name + databaseVersion + region +
        # settings.tier (_gcp_sql_instance_record reads these).
        "body": {
            "name": "{id}",
            "databaseVersion": "{engine}",
            "region": "us-central1",
            "settings": {"tier": "db-f1-micro"},
        },
    },
}

_AZURE_SQL_CONSOLE_API = {
    "databases": "/api/console/azure-sql/databases",
    "execute": "/api/console/azure-sql/execute",
    "schema": "/api/console/azure-sql/databases/{db}/schema",
    # Native ARM create (PUT) of a Microsoft.Sql/servers resource — the generic ARM
    # dispatcher (providers/azure_services.py handle_arm) upserts the record. The
    # {id} (server name) travels in the PATH (ARM is name-in-URL), so the widget
    # substitutes it into `create` before sending; api-version is on the query.
    "create": ("/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/"
               "cloudlearn-rg/providers/Microsoft.Sql/servers/{id}"
               "?api-version=2023-05-01-preview"),
    "createForm": {
        "method": "PUT",
        "title": "Create SQL server",
        "idLabel": "server name",
        "idPlaceholder": "vy-sqlsrv-01",
        "idInPath": True,             # {id} goes in the ARM URL, not the body
        "engineLabel": "version",
        "engineDefault": "12.0",
        "engineOptions": ["12.0"],
        # ARM Microsoft.Sql/servers PUT shape: location + properties.
        "body": {
            "location": "eastus",
            "properties": {
                "administratorLogin": "sqladmin",
                "administratorLoginPassword": "Password123!",
                "version": "{engine}",
            },
        },
    },
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


def _sandbox_ssh_info() -> dict:
    """One-time SSH bastion setup for a Codespaces-hosted sandbox.

    When the appliance runs inside a Codespace, a remote dev reaches EVERY instance
    through the Codespace as a jump host — set up ONCE per laptop, then `ssh -J` to
    each instance at the private IP shown in the console. No per-instance forwarding.
    Returns {} off-Codespace so the shell renders no setup banner. Keyed off the
    GitHub-set CODESPACE_NAME (reliable regardless of the substrate string)."""
    cs = (os.environ.get("CODESPACE_NAME") or "").strip()
    if not cs:
        return {}
    jump = f"cs.{cs}"
    return {
        "codespace_name": cs,
        "jump_host": jump,
        "ssh_setup_command": f"gh codespace ssh --config -c {cs} >> ~/.ssh/config",
        "note": (
            f"Run once on your laptop. Installs SSH alias '{jump}' — a secure tunnel "
            f"into this sandbox over your gh auth. Afterwards every instance's SSH "
            f"command works (ssh -J {jump} …) and reaches it at the private IP shown "
            f"in the console. One setup covers all instances and all clouds — no "
            f"per-instance forwarding. If your alias differs, use the Host name the "
            f"command printed. Databases reuse this same jump — each DB view shows a "
            f"ready-to-run tunnel + psql/mysql command."
        ),
        # Databases reuse the jump via a local port-forward — ONE tunnel per engine
        # covers every database on it. The exact per-DB command (with creds) rides on
        # each DB's view (connect_help); these are the generic patterns for the banner.
        "db": {
            "note": ("Databases (RDS / Cloud SQL / Azure DB): one tunnel per engine "
                     "covers every database. Each DB view shows the exact command."),
            "postgres_tunnel": f"ssh -fN -L 15432:localhost:5432 {jump}",
            "mysql_tunnel": f"ssh -fN -L 13306:localhost:3306 {jump}",
        },
    }


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
        # One-time SSH bastion setup, present only when hosted in a Codespace (§ SSH).
        # The shell renders a single dismissible banner from this — the setup is
        # laptop-wide (covers every instance/cloud), so it lives here, not per-instance.
        "sandbox": _sandbox_ssh_info(),
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


def register(app: FastAPI) -> None:
    # ── Static assets for the SPA ──
    if os.path.isdir(_ASSETS_DIR):
        app.mount("/console-next-assets",
                  StaticFiles(directory=_ASSETS_DIR),
                  name="console-next-assets")

    # ── Capability manifest (§15.1) ── lens-aware: ?lens=aws|gcp (default aws).
    #    The status-bar cloud-lens switcher re-fetches this per lens; widgets read
    #    their endpoints from each service's `api` block so there is no cloud
    #    branching in component code (§15.2).
    #    ?substrate=local|codespaces|nano lets the same bundle declare its serving
    #    substrate (default from env VYOMI_CONSOLE_SUBSTRATE / VYOMI_SUBSTRATE); on
    #    nano this flips connect.mode→relay and degrades compute-terminal/serverless
    #    per §14.9 — as capability DATA, never forked UI.
    @app.get("/api/console/capabilities", include_in_schema=False)
    def api_console_capabilities(lens: str = Query(default="aws"),
                                 substrate: str = Query(default=None)):
        return JSONResponse(_capabilities(lens, substrate))

    # ── Glass-box: one-shot buffer snapshot ──
    @app.get("/api/console/calls", include_in_schema=False)
    def api_console_calls(limit: int = Query(default=200, ge=1, le=2000)):
        from core.glassbox import RING
        return JSONResponse({"calls": RING.snapshot(limit=limit)})

    # ── Glass-box: SSE stream (§12.3) ──
    @app.get("/api/console/calls/stream", include_in_schema=False)
    async def api_console_calls_stream(replay: int = Query(default=50, ge=0, le=500)):
        from core.glassbox import sse_stream
        return StreamingResponse(
            sse_stream(replay=replay),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.post("/api/console/calls/clear", include_in_schema=False)
    def api_console_calls_clear():
        from core.glassbox import RING
        RING.clear()
        return {"ok": True}

    # ── Glass-box REPLAY (§12): re-issue a captured call against CURRENT state and
    #    report old→new status. The recorded method/path/body/query come straight
    #    from the ring-buffer event (core/glassbox.py). Re-dispatched IN-PROCESS
    #    against this same ASGI app (no network hop) so it exercises the real
    #    handlers and current backend state. Additive; touches no existing route.
    #
    #    HONEST LIMITS (surfaced to the UI):
    #    - The captured request body is the glass-box SUMMARY (capped, redacted
    #      headers). Replay reuses that summary as the body when it wasn't truncated;
    #      truncated/binary bodies can't be replayed faithfully and are refused.
    #    - Only console-facade JSON endpoints (/api/console/*) are replayable here —
    #      the native SigV4-signed wire paths can't be re-signed from a redacted
    #      capture. This keeps replay safe + deterministic. ──
    @app.post("/api/console/calls/{call_id}/replay", include_in_schema=False)
    async def api_console_calls_replay(call_id: str):
        from core.glassbox import find_event
        ev = find_event(call_id)
        if ev is None:
            raise HTTPException(404, detail=f"NotFound call {call_id!r} is not in the buffer")

        http = ev.get("http") or {}
        method = (http.get("method") or "GET").upper()
        path = http.get("path") or "/"
        old_status = int(http.get("status") or 0)

        if not path.startswith("/api/console/"):
            raise HTTPException(
                400,
                detail="ValidationError only /api/console/* facade calls are replayable "
                       "(native signed-wire calls can't be re-signed from a redacted capture)")

        req = ev.get("request") or {}
        # Re-encode the captured query (parse_qs shape: {name: [values]}).
        from urllib.parse import urlencode
        pairs = []
        for k, vals in (req.get("query") or {}).items():
            for v in (vals if isinstance(vals, list) else [vals]):
                pairs.append((k, v))
        query_string = urlencode(pairs).encode("latin-1")

        # Reconstruct the body from the (uncapped) summary. Refuse truncated/binary.
        summary = req.get("body_summary") or ""
        if summary.startswith("‹binary") or "…(+" in summary:
            raise HTTPException(
                422,
                detail="Unprocessable this call's body was truncated/binary in the "
                       "capture and can't be replayed faithfully")
        body = summary.encode("utf-8")
        req_headers = []
        if body and method in ("POST", "PUT", "PATCH", "DELETE"):
            req_headers.append((b"content-type", b"application/json"))
        req_headers.append((b"accept", b"application/json"))

        # ── minimal in-process ASGI round-trip against THIS app ──
        scope = {
            "type": "http", "http_version": "1.1", "method": method,
            "path": path, "raw_path": path.encode("latin-1"),
            "query_string": query_string, "headers": req_headers,
            "scheme": "http", "server": ("127.0.0.1", 80), "client": ("127.0.0.1", 0),
        }
        sent = {"status": 0, "body": b""}
        _delivered = {"done": False}

        async def _receive():
            if _delivered["done"]:
                return {"type": "http.disconnect"}
            _delivered["done"] = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def _send(message):
            mt = message.get("type")
            if mt == "http.response.start":
                sent["status"] = message.get("status", 0)
            elif mt == "http.response.body":
                sent["body"] += message.get("body", b"") or b""

        try:
            await app(scope, _receive, _send)
        except Exception as e:  # a handler that raises → report it, don't 500 the replay
            return {
                "call_id": call_id, "method": method, "path": path,
                "old_status": old_status, "new_status": 500,
                "changed": old_status != 500,
                "error": f"{type(e).__name__}: {e}",
            }

        new_status = int(sent["status"] or 0)
        body_text = sent["body"][:2048].decode("utf-8", errors="replace")
        return {
            "call_id": call_id, "method": method, "path": path,
            "old_status": old_status, "new_status": new_status,
            "changed": old_status != new_status,
            "response_summary": body_text,
        }

    # ── Conformance signal (F5 seam) — per-service + workspace rollup. The pill
    #    reads the rollup; the widgets/rail read per-service. Stubbed source today
    #    (core/console_conformance.py), live-runner-ready shape. ──
    @app.get("/api/console/conformance", include_in_schema=False)
    def api_console_conformance():
        from core import console_conformance as conf
        return {"rollup": conf.rollup(), "services": conf.all_signals()}

    # ── RDS sql-console (§13.4): relay-safe SQL via the RDS Data API core ──
    @app.get("/api/console/rds/databases", include_in_schema=False)
    def api_console_rds_databases():
        from core import console_sql
        return console_sql.list_databases()

    @app.post("/api/console/rds/execute", include_in_schema=False)
    async def api_console_rds_execute(payload: dict = Body(default=None)):
        from core import console_sql
        payload = payload or {}
        sql = (payload.get("sql") or "").strip()
        if not sql:
            raise HTTPException(400, detail="ValidationError sql is required")
        return await console_sql.execute(payload.get("db") or "",
                                         sql, payload.get("parameters"))

    @app.get("/api/console/rds/databases/{db_id}/schema", include_in_schema=False)
    async def api_console_rds_schema(db_id: str):
        from core import console_sql
        return await console_sql.schema(db_id)

    # ── Cloud SQL sql-console (P3 — the GCP lens's SQL data plane) ── the SAME
    #    sql-console widget renders Cloud SQL under lens=gcp; the ONLY difference is
    #    the manifest `api` block pointing here (§15.2). Cloud SQL is Postgres-backed,
    #    so this facade reuses the SAME relay-safe SQL engine as RDS
    #    (core/console_cloudsql mirrors console_sql with its own store), returning the
    #    SAME response shape. Purely additive; touches no existing Cloud SQL handler.
    @app.get("/api/console/cloudsql/databases", include_in_schema=False)
    def api_console_cloudsql_databases():
        from core import console_cloudsql
        return console_cloudsql.list_databases()

    @app.post("/api/console/cloudsql/execute", include_in_schema=False)
    async def api_console_cloudsql_execute(payload: dict = Body(default=None)):
        from core import console_cloudsql
        payload = payload or {}
        sql = (payload.get("sql") or "").strip()
        if not sql:
            raise HTTPException(400, detail="ValidationError sql is required")
        return await console_cloudsql.execute(payload.get("db") or "",
                                              sql, payload.get("parameters"))

    @app.get("/api/console/cloudsql/databases/{db_id}/schema", include_in_schema=False)
    async def api_console_cloudsql_schema(db_id: str):
        from core import console_cloudsql
        return await console_cloudsql.schema(db_id)

    # ── Azure SQL Database sql-console (P4 — the Azure lens's SQL data plane) ── the
    #    SAME sql-console widget renders Azure SQL under lens=azure; the ONLY
    #    difference is the manifest `api` block pointing here (§15.2). Azure SQL reuses
    #    the SAME relay-safe SQL engine as RDS/Cloud SQL (core/console_azure_sql mirrors
    #    console_sql with its own store), returning the SAME response shape. Purely
    #    additive; touches no existing Azure SQL handler.
    @app.get("/api/console/azure-sql/databases", include_in_schema=False)
    def api_console_azure_sql_databases():
        from core import console_azure_sql
        return console_azure_sql.list_databases()

    @app.post("/api/console/azure-sql/execute", include_in_schema=False)
    async def api_console_azure_sql_execute(payload: dict = Body(default=None)):
        from core import console_azure_sql
        payload = payload or {}
        sql = (payload.get("sql") or "").strip()
        if not sql:
            raise HTTPException(400, detail="ValidationError sql is required")
        return await console_azure_sql.execute(payload.get("db") or "",
                                               sql, payload.get("parameters"))

    @app.get("/api/console/azure-sql/databases/{db_id}/schema", include_in_schema=False)
    async def api_console_azure_sql_schema(db_id: str):
        from core import console_azure_sql
        return await console_azure_sql.schema(db_id)

    # ── Azure Cosmos DB nosql-item-viewer (P4 — the Azure lens's NoSQL data plane) ──
    #    the SAME nosql-item-viewer widget renders Cosmos under lens=azure; the ONLY
    #    difference is the manifest `api` block pointing here (§15.2). This facade
    #    returns the SAME JSON response shapes as the DynamoDB/Firestore console REST
    #    APIs so the widget is cloud-agnostic. A "table" is a Cosmos CONTAINER and an
    #    "item" a DOCUMENT (the required `id` field is surfaced as the partition key).
    #    Independent in-memory store (core/console_azure_cosmos) so Azure NoSQL state
    #    is isolated from the AWS/GCP facades; purely additive.
    def _cos():
        from core import console_azure_cosmos as c
        return c

    def _cosguard(fn):
        from core.console_azure_cosmos import CosmosError
        try:
            return fn()
        except CosmosError as e:
            raise HTTPException(e.status, detail=e.message)

    @app.get("/api/console/azure-cosmos/containers", include_in_schema=False)
    def api_console_cos_list():
        return _cosguard(lambda: _cos().list_containers())

    @app.post("/api/console/azure-cosmos/containers", include_in_schema=False)
    def api_console_cos_create(payload: dict = Body(default=None)):
        p = payload or {}
        name = (p.get("table_name") or p.get("name") or "").strip()
        if not name:
            raise HTTPException(400, detail="ValidationError table_name is required")
        return _cosguard(lambda: _cos().create_container(name))

    @app.get("/api/console/azure-cosmos/containers/{name}", include_in_schema=False)
    def api_console_cos_get(name: str):
        return _cosguard(lambda: _cos().get_container(name))

    @app.delete("/api/console/azure-cosmos/containers/{name}", include_in_schema=False)
    def api_console_cos_delete(name: str):
        return _cosguard(lambda: _cos().delete_container(name))

    @app.get("/api/console/azure-cosmos/containers/{name}/items", include_in_schema=False)
    def api_console_cos_list_items(name: str):
        return _cosguard(lambda: _cos().list_documents(name))

    @app.post("/api/console/azure-cosmos/containers/{name}/items", include_in_schema=False)
    def api_console_cos_put_item(name: str, payload: dict = Body(default=None)):
        item = (payload or {}).get("item")
        if not isinstance(item, dict):
            raise HTTPException(400, detail="ValidationError item (object) is required")
        return _cosguard(lambda: _cos().put_document(name, item))

    @app.delete("/api/console/azure-cosmos/containers/{name}/items", include_in_schema=False)
    def api_console_cos_delete_item(name: str, payload: dict = Body(default=None)):
        key = (payload or {}).get("key")
        if not isinstance(key, dict):
            raise HTTPException(400, detail="ValidationError key (object) is required")
        return _cosguard(lambda: _cos().delete_document(name, key))

    @app.post("/api/console/azure-cosmos/containers/{name}/query", include_in_schema=False)
    def api_console_cos_query(name: str, payload: dict = Body(default=None)):
        p = payload or {}
        return _cosguard(lambda: _cos().query_documents(
            name, p.get("partition_key_value"), p.get("sort_key_begins_with", "")))

    # ── Firestore nosql-item-viewer (P3 — the GCP lens's NoSQL data plane) ── the
    #    SAME nosql-item-viewer widget renders Firestore under lens=gcp; the ONLY
    #    difference is the manifest `api` block pointing here (§15.2). This facade
    #    returns the SAME JSON response shapes as the DynamoDB console REST API so the
    #    widget is cloud-agnostic. A "table" is a Firestore COLLECTION and an "item"
    #    is a DOCUMENT (the document id is surfaced as the partition key). Purely
    #    additive; touches no existing Firestore handler.
    def _fs():
        from core import console_firestore as f
        return f

    def _fsguard(fn):
        from core.console_firestore import FirestoreError
        try:
            return fn()
        except FirestoreError as e:
            raise HTTPException(e.status, detail=e.message)

    @app.get("/api/console/firestore/collections", include_in_schema=False)
    def api_console_fs_list():
        return _fsguard(lambda: _fs().list_collections())

    @app.post("/api/console/firestore/collections", include_in_schema=False)
    def api_console_fs_create(payload: dict = Body(default=None)):
        p = payload or {}
        name = (p.get("table_name") or p.get("name") or "").strip()
        if not name:
            raise HTTPException(400, detail="ValidationError table_name is required")
        return _fsguard(lambda: _fs().create_collection(name))

    @app.get("/api/console/firestore/collections/{name}", include_in_schema=False)
    def api_console_fs_get(name: str):
        return _fsguard(lambda: _fs().get_collection(name))

    @app.delete("/api/console/firestore/collections/{name}", include_in_schema=False)
    def api_console_fs_delete(name: str):
        return _fsguard(lambda: _fs().delete_collection(name))

    @app.get("/api/console/firestore/collections/{name}/documents", include_in_schema=False)
    def api_console_fs_list_docs(name: str):
        return _fsguard(lambda: _fs().list_documents(name))

    @app.post("/api/console/firestore/collections/{name}/documents", include_in_schema=False)
    def api_console_fs_put_doc(name: str, payload: dict = Body(default=None)):
        item = (payload or {}).get("item")
        if not isinstance(item, dict):
            raise HTTPException(400, detail="ValidationError item (object) is required")
        return _fsguard(lambda: _fs().put_document(name, item))

    @app.delete("/api/console/firestore/collections/{name}/documents", include_in_schema=False)
    def api_console_fs_delete_doc(name: str, payload: dict = Body(default=None)):
        key = (payload or {}).get("key")
        if not isinstance(key, dict):
            raise HTTPException(400, detail="ValidationError key (object) is required")
        return _fsguard(lambda: _fs().delete_document(name, key))

    @app.post("/api/console/firestore/collections/{name}/query", include_in_schema=False)
    def api_console_fs_query(name: str, payload: dict = Body(default=None)):
        p = payload or {}
        return _fsguard(lambda: _fs().query_documents(
            name, p.get("partition_key_value"), p.get("sort_key_begins_with", "")))

    # ── SQS + SNS queue/topic-viewer (§13): ONE shared MessagingStore so the widget
    #    can show REAL SNS→SQS fan-out. Drives core/sqs_core + core/sns_core. ──
    def _msg():
        from core import console_messaging as m
        return m

    def _guard(fn):
        from core.console_messaging import MessagingError
        try:
            return fn()
        except MessagingError as e:
            raise HTTPException(e.status, detail=e.message)

    @app.get("/api/console/messaging/queues", include_in_schema=False)
    def api_console_mq_list():
        return _msg().list_queues()

    @app.post("/api/console/messaging/queues", include_in_schema=False)
    def api_console_mq_create(payload: dict = Body(default=None)):
        name = (payload or {}).get("name", "").strip()
        if not name:
            raise HTTPException(400, detail="ValidationError name is required")
        return _guard(lambda: _msg().create_queue(name))

    @app.delete("/api/console/messaging/queues/{name}", include_in_schema=False)
    def api_console_mq_delete(name: str):
        return _guard(lambda: _msg().delete_queue(name))

    @app.post("/api/console/messaging/queues/{name}/send", include_in_schema=False)
    def api_console_mq_send(name: str, payload: dict = Body(default=None)):
        body = (payload or {}).get("body", "")
        return _guard(lambda: _msg().send_message(name, body))

    @app.post("/api/console/messaging/queues/{name}/receive", include_in_schema=False)
    def api_console_mq_receive(name: str, payload: dict = Body(default=None)):
        p = payload or {}
        return _guard(lambda: _msg().receive_messages(
            name, int(p.get("max", 10)), int(p.get("visibility", 0))))

    @app.get("/api/console/messaging/queues/{name}/peek", include_in_schema=False)
    def api_console_mq_peek(name: str):
        return _guard(lambda: _msg().peek_messages(name))

    @app.post("/api/console/messaging/queues/{name}/purge", include_in_schema=False)
    def api_console_mq_purge(name: str):
        return _guard(lambda: _msg().purge_queue(name))

    @app.get("/api/console/messaging/topics", include_in_schema=False)
    def api_console_topics_list():
        return _msg().list_topics()

    @app.post("/api/console/messaging/topics", include_in_schema=False)
    def api_console_topics_create(payload: dict = Body(default=None)):
        name = (payload or {}).get("name", "").strip()
        if not name:
            raise HTTPException(400, detail="ValidationError name is required")
        return _guard(lambda: _msg().create_topic(name))

    # Topic ARNs contain ':' (and are awkward in a path segment), so the ARN travels
    # in the body/query for topic sub-operations — keeps the routes unambiguous.
    @app.post("/api/console/messaging/topics/delete", include_in_schema=False)
    def api_console_topics_delete(payload: dict = Body(default=None)):
        arn = (payload or {}).get("topic_arn", "").strip()
        return _guard(lambda: _msg().delete_topic(arn))

    @app.get("/api/console/messaging/topics/subscriptions", include_in_schema=False)
    def api_console_topics_subs(topic_arn: str = Query(...)):
        return _guard(lambda: _msg().list_subscriptions(topic_arn))

    @app.post("/api/console/messaging/topics/subscribe", include_in_schema=False)
    def api_console_topics_subscribe(payload: dict = Body(default=None)):
        p = payload or {}
        arn = p.get("topic_arn", "").strip()
        queue = p.get("queue", "").strip()
        if not arn or not queue:
            raise HTTPException(400, detail="ValidationError topic_arn and queue are required")
        return _guard(lambda: _msg().subscribe_queue(arn, queue))

    @app.post("/api/console/messaging/topics/publish", include_in_schema=False)
    def api_console_topics_publish(payload: dict = Body(default=None)):
        p = payload or {}
        arn = p.get("topic_arn", "").strip()
        if not arn:
            raise HTTPException(400, detail="ValidationError topic_arn is required")
        return _guard(lambda: _msg().publish(arn, p.get("message", ""), p.get("subject")))

    # ── GCP Pub/Sub queue-topic-viewer (P3 — the GCP lens's messaging data plane) ──
    #    The SAME queue-topic-viewer widget renders Pub/Sub under lens=gcp; the ONLY
    #    difference is the manifest `api` block pointing here instead of
    #    /api/console/messaging/* (§15.2 — no if(cloud) branching). A "queue" is a
    #    Pub/Sub SUBSCRIPTION (a pull-target with its own backlog) and the topic
    #    fans out to every attached subscription — the flagship fan-out stays REAL.
    #    Independent in-memory store (core/console_gcp_pubsub) so GCP messaging state
    #    is isolated from the AWS messaging facade; purely additive.
    def _ps():
        from core import console_gcp_pubsub as p
        return p

    def _psguard(fn):
        from core.console_gcp_pubsub import PubSubError
        try:
            return fn()
        except PubSubError as e:
            raise HTTPException(e.status, detail=e.message)

    @app.get("/api/console/gcp-pubsub/subscriptions", include_in_schema=False)
    def api_console_ps_list():
        return _ps().list_queues()

    @app.post("/api/console/gcp-pubsub/subscriptions", include_in_schema=False)
    def api_console_ps_create(payload: dict = Body(default=None)):
        name = (payload or {}).get("name", "").strip()
        if not name:
            raise HTTPException(400, detail="ValidationError name is required")
        return _psguard(lambda: _ps().create_queue(name))

    @app.delete("/api/console/gcp-pubsub/subscriptions/{name}", include_in_schema=False)
    def api_console_ps_delete(name: str):
        return _psguard(lambda: _ps().delete_queue(name))

    @app.post("/api/console/gcp-pubsub/subscriptions/{name}/send", include_in_schema=False)
    def api_console_ps_send(name: str, payload: dict = Body(default=None)):
        body = (payload or {}).get("body", "")
        return _psguard(lambda: _ps().send_message(name, body))

    @app.post("/api/console/gcp-pubsub/subscriptions/{name}/receive", include_in_schema=False)
    def api_console_ps_receive(name: str, payload: dict = Body(default=None)):
        p = payload or {}
        return _psguard(lambda: _ps().receive_messages(
            name, int(p.get("max", 10)), int(p.get("visibility", 0))))

    @app.get("/api/console/gcp-pubsub/subscriptions/{name}/peek", include_in_schema=False)
    def api_console_ps_peek(name: str):
        return _psguard(lambda: _ps().peek_messages(name))

    @app.post("/api/console/gcp-pubsub/subscriptions/{name}/purge", include_in_schema=False)
    def api_console_ps_purge(name: str):
        return _psguard(lambda: _ps().purge_queue(name))

    @app.get("/api/console/gcp-pubsub/topics", include_in_schema=False)
    def api_console_ps_topics_list():
        return _ps().list_topics()

    @app.post("/api/console/gcp-pubsub/topics", include_in_schema=False)
    def api_console_ps_topics_create(payload: dict = Body(default=None)):
        name = (payload or {}).get("name", "").strip()
        if not name:
            raise HTTPException(400, detail="ValidationError name is required")
        return _psguard(lambda: _ps().create_topic(name))

    # The topic identifier travels in the body/query (matches the AWS messaging
    # facade's convention) — keeps the routes unambiguous.
    @app.post("/api/console/gcp-pubsub/topics/delete", include_in_schema=False)
    def api_console_ps_topics_delete(payload: dict = Body(default=None)):
        arn = (payload or {}).get("topic_arn", "").strip()
        return _psguard(lambda: _ps().delete_topic(arn))

    @app.get("/api/console/gcp-pubsub/topics/subscriptions", include_in_schema=False)
    def api_console_ps_topics_subs(topic_arn: str = Query(...)):
        return _psguard(lambda: _ps().list_subscriptions(topic_arn))

    @app.post("/api/console/gcp-pubsub/topics/subscribe", include_in_schema=False)
    def api_console_ps_topics_subscribe(payload: dict = Body(default=None)):
        p = payload or {}
        arn = p.get("topic_arn", "").strip()
        queue = p.get("queue", "").strip()
        if not arn or not queue:
            raise HTTPException(400, detail="ValidationError topic_arn and queue are required")
        return _psguard(lambda: _ps().subscribe_queue(arn, queue))

    @app.post("/api/console/gcp-pubsub/topics/publish", include_in_schema=False)
    def api_console_ps_topics_publish(payload: dict = Body(default=None)):
        p = payload or {}
        arn = p.get("topic_arn", "").strip()
        if not arn:
            raise HTTPException(400, detail="ValidationError topic_arn is required")
        return _psguard(lambda: _ps().publish(arn, p.get("message", ""), p.get("subject")))

    # ── Azure Service Bus queue-topic-viewer (P4 — the Azure lens's messaging data
    #    plane) ── The SAME queue-topic-viewer widget renders Service Bus under
    #    lens=azure; the ONLY difference is the manifest `api` block pointing here
    #    instead of /api/console/messaging/* (§15.2 — no if(cloud) branching). A
    #    "queue" is a Service Bus queue (a pull-target with its own backlog) and a
    #    topic fans out to every attached subscription (an existing queue attached as
    #    the subscription) — the flagship fan-out stays REAL. Independent in-memory
    #    store (core/console_azure_servicebus) so Azure messaging state is isolated
    #    from the AWS/GCP messaging facades; purely additive.
    def _sb():
        from core import console_azure_servicebus as p
        return p

    def _sbguard(fn):
        from core.console_azure_servicebus import ServiceBusError
        try:
            return fn()
        except ServiceBusError as e:
            raise HTTPException(e.status, detail=e.message)

    @app.get("/api/console/azure-servicebus/queues", include_in_schema=False)
    def api_console_sb_list():
        return _sb().list_queues()

    @app.post("/api/console/azure-servicebus/queues", include_in_schema=False)
    def api_console_sb_create(payload: dict = Body(default=None)):
        name = (payload or {}).get("name", "").strip()
        if not name:
            raise HTTPException(400, detail="ValidationError name is required")
        return _sbguard(lambda: _sb().create_queue(name))

    @app.delete("/api/console/azure-servicebus/queues/{name}", include_in_schema=False)
    def api_console_sb_delete(name: str):
        return _sbguard(lambda: _sb().delete_queue(name))

    @app.post("/api/console/azure-servicebus/queues/{name}/send", include_in_schema=False)
    def api_console_sb_send(name: str, payload: dict = Body(default=None)):
        body = (payload or {}).get("body", "")
        return _sbguard(lambda: _sb().send_message(name, body))

    @app.post("/api/console/azure-servicebus/queues/{name}/receive", include_in_schema=False)
    def api_console_sb_receive(name: str, payload: dict = Body(default=None)):
        p = payload or {}
        return _sbguard(lambda: _sb().receive_messages(
            name, int(p.get("max", 10)), int(p.get("visibility", 0))))

    @app.get("/api/console/azure-servicebus/queues/{name}/peek", include_in_schema=False)
    def api_console_sb_peek(name: str):
        return _sbguard(lambda: _sb().peek_messages(name))

    @app.post("/api/console/azure-servicebus/queues/{name}/purge", include_in_schema=False)
    def api_console_sb_purge(name: str):
        return _sbguard(lambda: _sb().purge_queue(name))

    @app.get("/api/console/azure-servicebus/topics", include_in_schema=False)
    def api_console_sb_topics_list():
        return _sb().list_topics()

    @app.post("/api/console/azure-servicebus/topics", include_in_schema=False)
    def api_console_sb_topics_create(payload: dict = Body(default=None)):
        name = (payload or {}).get("name", "").strip()
        if not name:
            raise HTTPException(400, detail="ValidationError name is required")
        return _sbguard(lambda: _sb().create_topic(name))

    # The topic identifier travels in the body/query (matches the AWS messaging
    # facade's convention) — keeps the routes unambiguous.
    @app.post("/api/console/azure-servicebus/topics/delete", include_in_schema=False)
    def api_console_sb_topics_delete(payload: dict = Body(default=None)):
        arn = (payload or {}).get("topic_arn", "").strip()
        return _sbguard(lambda: _sb().delete_topic(arn))

    @app.get("/api/console/azure-servicebus/topics/subscriptions", include_in_schema=False)
    def api_console_sb_topics_subs(topic_arn: str = Query(...)):
        return _sbguard(lambda: _sb().list_subscriptions(topic_arn))

    @app.post("/api/console/azure-servicebus/topics/subscribe", include_in_schema=False)
    def api_console_sb_topics_subscribe(payload: dict = Body(default=None)):
        p = payload or {}
        arn = p.get("topic_arn", "").strip()
        queue = p.get("queue", "").strip()
        if not arn or not queue:
            raise HTTPException(400, detail="ValidationError topic_arn and queue are required")
        return _sbguard(lambda: _sb().subscribe_queue(arn, queue))

    @app.post("/api/console/azure-servicebus/topics/publish", include_in_schema=False)
    def api_console_sb_topics_publish(payload: dict = Body(default=None)):
        p = payload or {}
        arn = p.get("topic_arn", "").strip()
        if not arn:
            raise HTTPException(400, detail="ValidationError topic_arn is required")
        return _sbguard(lambda: _sb().publish(arn, p.get("message", ""), p.get("subject")))

    # ── Secrets Manager kv-secret-viewer (§13): clean JSON facade over the
    #    substrate-agnostic secrets_core + a shared KvStore (core/console_secrets).
    #    Values are only fetched on a deliberate reveal; the widget masks by default.
    def _sec():
        from core import console_secrets as s
        return s

    def _sguard(fn):
        from core.console_secrets import SecretsError
        try:
            return fn()
        except SecretsError as e:
            raise HTTPException(e.status, detail=e.message)

    @app.get("/api/console/secrets", include_in_schema=False)
    def api_console_secrets_list():
        return _sguard(lambda: _sec().list_secrets())

    @app.post("/api/console/secrets", include_in_schema=False)
    def api_console_secrets_create(payload: dict = Body(default=None)):
        p = payload or {}
        name = (p.get("name") or "").strip()
        if not name:
            raise HTTPException(400, detail="ValidationError name is required")
        return _sguard(lambda: _sec().create_secret(
            name, p.get("secret_string", ""), (p.get("description") or "").strip()))

    @app.get("/api/console/secrets/{name}", include_in_schema=False)
    def api_console_secrets_describe(name: str):
        return _sguard(lambda: _sec().describe_secret(name))

    @app.delete("/api/console/secrets/{name}", include_in_schema=False)
    def api_console_secrets_delete(name: str):
        return _sguard(lambda: _sec().delete_secret(name))

    @app.get("/api/console/secrets/{name}/value", include_in_schema=False)
    def api_console_secrets_value(name: str,
                                  version_id: str = Query(default=None),
                                  version_stage: str = Query(default=None)):
        return _sguard(lambda: _sec().get_secret_value(name, version_id, version_stage))

    @app.post("/api/console/secrets/{name}/value", include_in_schema=False)
    def api_console_secrets_put(name: str, payload: dict = Body(default=None)):
        p = payload or {}
        return _sguard(lambda: _sec().put_secret_value(name, p.get("secret_string", "")))

    # ── GCP Secret Manager kv-secret-viewer (§13): the GCP lens's data plane for the
    #    SAME kv-secret-viewer widget — the manifest `api` block points here instead
    #    of /api/console/secrets/* (§15.2 — no if(cloud) branching). GCP secrets carry
    #    versions too (newest = current, prior = previous), so describe/reveal/put all
    #    return the SAME JSON shapes the widget consumes. Independent in-memory store
    #    (core/console_gcp_secrets) so GCP secrets state is isolated from the AWS
    #    Secrets facade; purely additive. Values are only fetched on a deliberate
    #    reveal; the widget masks by default.
    def _gsec():
        from core import console_gcp_secrets as g
        return g

    def _gsecguard(fn):
        from core.console_gcp_secrets import GcpSecretsError
        try:
            return fn()
        except GcpSecretsError as e:
            raise HTTPException(e.status, detail=e.message)

    @app.get("/api/console/gcp-secrets/secrets", include_in_schema=False)
    def api_console_gcp_secrets_list():
        return _gsecguard(lambda: _gsec().list_secrets())

    @app.post("/api/console/gcp-secrets/secrets", include_in_schema=False)
    def api_console_gcp_secrets_create(payload: dict = Body(default=None)):
        p = payload or {}
        name = (p.get("name") or "").strip()
        if not name:
            raise HTTPException(400, detail="ValidationError name is required")
        return _gsecguard(lambda: _gsec().create_secret(
            name, p.get("secret_string", ""), (p.get("description") or "").strip()))

    @app.get("/api/console/gcp-secrets/secrets/{name}", include_in_schema=False)
    def api_console_gcp_secrets_describe(name: str):
        return _gsecguard(lambda: _gsec().describe_secret(name))

    @app.delete("/api/console/gcp-secrets/secrets/{name}", include_in_schema=False)
    def api_console_gcp_secrets_delete(name: str):
        return _gsecguard(lambda: _gsec().delete_secret(name))

    @app.get("/api/console/gcp-secrets/secrets/{name}/value", include_in_schema=False)
    def api_console_gcp_secrets_value(name: str,
                                      version_id: str = Query(default=None),
                                      version_stage: str = Query(default=None)):
        return _gsecguard(lambda: _gsec().get_secret_value(name, version_id, version_stage))

    @app.post("/api/console/gcp-secrets/secrets/{name}/value", include_in_schema=False)
    def api_console_gcp_secrets_put(name: str, payload: dict = Body(default=None)):
        p = payload or {}
        return _gsecguard(lambda: _gsec().put_secret_value(name, p.get("secret_string", "")))

    # ── Azure Key Vault (secrets) kv-secret-viewer (P4 — the Azure lens's data plane
    #    for the SAME kv-secret-viewer widget) ── the manifest `api` block points here
    #    instead of /api/console/secrets/* (§15.2 — no if(cloud) branching). Key Vault
    #    secrets carry versions too (newest = current, prior = previous), so
    #    describe/reveal/put all return the SAME JSON shapes the widget consumes.
    #    Independent in-memory store (core/console_azure_kv_secrets) so Azure secrets
    #    state is isolated from the AWS/GCP Secrets facades; purely additive. Values
    #    are only fetched on a deliberate reveal; the widget masks by default.
    def _azsec():
        from core import console_azure_kv_secrets as g
        return g

    def _azsecguard(fn):
        from core.console_azure_kv_secrets import AzureKvSecretsError
        try:
            return fn()
        except AzureKvSecretsError as e:
            raise HTTPException(e.status, detail=e.message)

    @app.get("/api/console/azure-kv-secrets/secrets", include_in_schema=False)
    def api_console_az_secrets_list():
        return _azsecguard(lambda: _azsec().list_secrets())

    @app.post("/api/console/azure-kv-secrets/secrets", include_in_schema=False)
    def api_console_az_secrets_create(payload: dict = Body(default=None)):
        p = payload or {}
        name = (p.get("name") or "").strip()
        if not name:
            raise HTTPException(400, detail="ValidationError name is required")
        return _azsecguard(lambda: _azsec().create_secret(
            name, p.get("secret_string", ""), (p.get("description") or "").strip()))

    @app.get("/api/console/azure-kv-secrets/secrets/{name}", include_in_schema=False)
    def api_console_az_secrets_describe(name: str):
        return _azsecguard(lambda: _azsec().describe_secret(name))

    @app.delete("/api/console/azure-kv-secrets/secrets/{name}", include_in_schema=False)
    def api_console_az_secrets_delete(name: str):
        return _azsecguard(lambda: _azsec().delete_secret(name))

    @app.get("/api/console/azure-kv-secrets/secrets/{name}/value", include_in_schema=False)
    def api_console_az_secrets_value(name: str,
                                     version_id: str = Query(default=None),
                                     version_stage: str = Query(default=None)):
        return _azsecguard(lambda: _azsec().get_secret_value(name, version_id, version_stage))

    @app.post("/api/console/azure-kv-secrets/secrets/{name}/value", include_in_schema=False)
    def api_console_az_secrets_put(name: str, payload: dict = Body(default=None)):
        p = payload or {}
        return _azsecguard(lambda: _azsec().put_secret_value(name, p.get("secret_string", "")))

    # ── KMS kms-crypto-view (§13): clean JSON facade over the substrate-agnostic
    #    kms_core + a shared KeyStore (core/console_kms). Reuses the REAL crypto core
    #    (no fake crypto); plaintext/ciphertext cross the wire base64-encoded (the
    #    native KMS shape). Purely additive — touches no existing KMS handlers.
    def _kms():
        from core import console_kms as k
        return k

    def _kguard(fn):
        from core.console_kms import KmsError
        try:
            return fn()
        except KmsError as e:
            raise HTTPException(e.status, detail=e.message)

    @app.get("/api/console/kms/keys", include_in_schema=False)
    def api_console_kms_list():
        return _kguard(lambda: _kms().list_keys())

    @app.post("/api/console/kms/keys", include_in_schema=False)
    def api_console_kms_create(payload: dict = Body(default=None)):
        p = payload or {}
        return _kguard(lambda: _kms().create_key((p.get("description") or "").strip()))

    @app.get("/api/console/kms/keys/{key_id}", include_in_schema=False)
    def api_console_kms_describe(key_id: str):
        return _kguard(lambda: _kms().describe_key(key_id))

    @app.post("/api/console/kms/encrypt", include_in_schema=False)
    def api_console_kms_encrypt(payload: dict = Body(default=None)):
        p = payload or {}
        key_id = (p.get("key_id") or "").strip()
        if not key_id:
            raise HTTPException(400, detail="ValidationError key_id is required")
        return _kguard(lambda: _kms().encrypt(key_id, p.get("plaintext", "")))

    @app.post("/api/console/kms/decrypt", include_in_schema=False)
    def api_console_kms_decrypt(payload: dict = Body(default=None)):
        p = payload or {}
        blob = p.get("ciphertext_blob", "")
        if not blob:
            raise HTTPException(400, detail="ValidationError ciphertext_blob is required")
        return _kguard(lambda: _kms().decrypt(blob, (p.get("key_id") or "").strip() or None))

    @app.post("/api/console/kms/data-key", include_in_schema=False)
    def api_console_kms_data_key(payload: dict = Body(default=None)):
        p = payload or {}
        key_id = (p.get("key_id") or "").strip()
        if not key_id:
            raise HTTPException(400, detail="ValidationError key_id is required")
        return _kguard(lambda: _kms().generate_data_key(key_id, p.get("key_spec", "AES_256")))

    # ── GCP Cloud KMS kms-crypto-view (§13): the GCP lens's data plane for the SAME
    #    kms-crypto-view widget — the manifest `api` block points here instead of
    #    /api/console/kms/* (§15.2 — no if(cloud) branching). Reuses the REAL crypto
    #    core (core/kms_core, no fake crypto) over an INDEPENDENT KeyStore
    #    (core/console_gcp_kms) so GCP key state is isolated from the AWS KMS facade,
    #    mirroring the console_gcp_secrets independent-store approach. Purely additive.
    def _gkms():
        from core import console_gcp_kms as k
        return k

    def _gkguard(fn):
        from core.console_gcp_kms import GcpKmsError
        try:
            return fn()
        except GcpKmsError as e:
            raise HTTPException(e.status, detail=e.message)

    @app.get("/api/console/gcp-kms/keys", include_in_schema=False)
    def api_console_gcp_kms_list():
        return _gkguard(lambda: _gkms().list_keys())

    @app.post("/api/console/gcp-kms/keys", include_in_schema=False)
    def api_console_gcp_kms_create(payload: dict = Body(default=None)):
        p = payload or {}
        return _gkguard(lambda: _gkms().create_key((p.get("description") or "").strip()))

    @app.get("/api/console/gcp-kms/keys/{key_id}", include_in_schema=False)
    def api_console_gcp_kms_describe(key_id: str):
        return _gkguard(lambda: _gkms().describe_key(key_id))

    @app.post("/api/console/gcp-kms/encrypt", include_in_schema=False)
    def api_console_gcp_kms_encrypt(payload: dict = Body(default=None)):
        p = payload or {}
        key_id = (p.get("key_id") or "").strip()
        if not key_id:
            raise HTTPException(400, detail="ValidationError key_id is required")
        return _gkguard(lambda: _gkms().encrypt(key_id, p.get("plaintext", "")))

    @app.post("/api/console/gcp-kms/decrypt", include_in_schema=False)
    def api_console_gcp_kms_decrypt(payload: dict = Body(default=None)):
        p = payload or {}
        blob = p.get("ciphertext_blob", "")
        if not blob:
            raise HTTPException(400, detail="ValidationError ciphertext_blob is required")
        return _gkguard(lambda: _gkms().decrypt(blob, (p.get("key_id") or "").strip() or None))

    @app.post("/api/console/gcp-kms/data-key", include_in_schema=False)
    def api_console_gcp_kms_data_key(payload: dict = Body(default=None)):
        p = payload or {}
        key_id = (p.get("key_id") or "").strip()
        if not key_id:
            raise HTTPException(400, detail="ValidationError key_id is required")
        return _gkguard(lambda: _gkms().generate_data_key(key_id, p.get("key_spec", "AES_256")))

    # ── Azure Key Vault (keys) kms-crypto-view (P4 — the Azure lens's data plane for
    #    the SAME kms-crypto-view widget) ── the manifest `api` block points here
    #    instead of /api/console/kms/* (§15.2 — no if(cloud) branching). Reuses the
    #    REAL crypto core (core/kms_core, no fake crypto) over an INDEPENDENT KeyStore
    #    (core/console_azure_kv_keys) so Azure key state is isolated from the AWS/GCP
    #    KMS facades, mirroring the console_gcp_kms independent-store approach. Purely
    #    additive.
    def _azkms():
        from core import console_azure_kv_keys as k
        return k

    def _azkguard(fn):
        from core.console_azure_kv_keys import AzureKvKeysError
        try:
            return fn()
        except AzureKvKeysError as e:
            raise HTTPException(e.status, detail=e.message)

    @app.get("/api/console/azure-kv-keys/keys", include_in_schema=False)
    def api_console_az_kms_list():
        return _azkguard(lambda: _azkms().list_keys())

    @app.post("/api/console/azure-kv-keys/keys", include_in_schema=False)
    def api_console_az_kms_create(payload: dict = Body(default=None)):
        p = payload or {}
        return _azkguard(lambda: _azkms().create_key((p.get("description") or "").strip()))

    @app.get("/api/console/azure-kv-keys/keys/{key_id}", include_in_schema=False)
    def api_console_az_kms_describe(key_id: str):
        return _azkguard(lambda: _azkms().describe_key(key_id))

    @app.post("/api/console/azure-kv-keys/encrypt", include_in_schema=False)
    def api_console_az_kms_encrypt(payload: dict = Body(default=None)):
        p = payload or {}
        key_id = (p.get("key_id") or "").strip()
        if not key_id:
            raise HTTPException(400, detail="ValidationError key_id is required")
        return _azkguard(lambda: _azkms().encrypt(key_id, p.get("plaintext", "")))

    @app.post("/api/console/azure-kv-keys/decrypt", include_in_schema=False)
    def api_console_az_kms_decrypt(payload: dict = Body(default=None)):
        p = payload or {}
        blob = p.get("ciphertext_blob", "")
        if not blob:
            raise HTTPException(400, detail="ValidationError ciphertext_blob is required")
        return _azkguard(lambda: _azkms().decrypt(blob, (p.get("key_id") or "").strip() or None))

    @app.post("/api/console/azure-kv-keys/data-key", include_in_schema=False)
    def api_console_az_kms_data_key(payload: dict = Body(default=None)):
        p = payload or {}
        key_id = (p.get("key_id") or "").strip()
        if not key_id:
            raise HTTPException(400, detail="ValidationError key_id is required")
        return _azkguard(lambda: _azkms().generate_data_key(key_id, p.get("key_spec", "AES_256")))

    # ── GCS console-facade (P3 — the GCP lens's object-browser data plane) ──
    #    The SAME object-browser widget renders GCS under lens=gcp; the ONLY
    #    difference is the manifest `api` block pointing here (§15.2). This facade
    #    returns the SAME response shape as the S3 facade (/api/s3/*) so the widget
    #    is cloud-agnostic. It reads/writes the SAME space-scoped gcp_storage_state
    #    the native GCP JSON API (`/storage/v1/b/...`) uses — so a bucket/object made
    #    in the console is visible to an unmodified google-cloud-storage SDK, and
    #    vice-versa. Purely additive; touches no existing GCS handler.
    from core.app_context import gcp_storage_state as _gcs_state, now as _gcs_now

    def _gcs_fmt_size(n) -> str:
        size = float(int(n or 0))
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024 or unit == "TB":
                return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{int(size)} B"

    def _gcs_buckets() -> dict:
        b = _gcs_state.get("buckets")
        if not isinstance(b, dict):
            b = {}
            _gcs_state["buckets"] = b
        return b

    def _gcs_objects(bucket: str) -> dict:
        objs = _gcs_state.setdefault("objects", {})
        return objs.setdefault(bucket, {})

    @app.get("/api/console/gcs/buckets", include_in_schema=False)
    def api_console_gcs_list_buckets():
        buckets = _gcs_buckets()
        return {
            "owner": "cloudlearn-simulator",
            "buckets": [{"name": n,
                         "location": (m or {}).get("location", "US"),
                         "storage_class": (m or {}).get("storageClass", "STANDARD"),
                         "created": (m or {}).get("timeCreated", "")}
                        for n, m in sorted(buckets.items())],
            "count": len(buckets),
        }

    @app.post("/api/console/gcs/buckets/{name}", include_in_schema=False)
    def api_console_gcs_create_bucket(name: str):
        name = (name or "").strip()
        if not name:
            raise HTTPException(400, detail="ValidationError bucket name is required")
        buckets = _gcs_buckets()
        if name in buckets:
            raise HTTPException(409, detail="Conflict bucket already exists")
        buckets[name] = {
            "name": name, "project": "cloudlearn", "location": "US",
            "locationType": "multi-region", "storageClass": "STANDARD",
            "timeCreated": _gcs_now(), "updated": _gcs_now(), "metageneration": "1",
        }
        _gcs_state.setdefault("objects", {}).setdefault(name, {})
        return {"message": f"Bucket '{name}' created", "location": f"/{name}"}

    @app.get("/api/console/gcs/buckets/{bucket}/objects", include_in_schema=False)
    def api_console_gcs_list_objects(bucket: str, prefix: str = Query(default="")):
        if bucket not in _gcs_buckets():
            raise HTTPException(404, detail="NoSuchBucket")
        result = []
        for name in sorted(_gcs_objects(bucket)):
            if prefix and not name.startswith(prefix):
                continue
            obj = _gcs_objects(bucket)[name]
            size = int(obj.get("size", 0) or 0)
            result.append({
                "key": name,
                "size": size,
                "size_human": _gcs_fmt_size(size),
                "content_type": obj.get("contentType", "application/octet-stream"),
                "last_modified": obj.get("updated", obj.get("timeCreated", "")),
                "etag": obj.get("etag", "") or obj.get("md5Hash", ""),
                "storage_class": obj.get("storageClass", "STANDARD"),
            })
        return {"bucket": bucket, "prefix": prefix, "objects": result, "count": len(result)}

    @app.post("/api/console/gcs/buckets/{bucket}/objects", include_in_schema=False)
    async def api_console_gcs_upload(bucket: str, request: Request):
        if bucket not in _gcs_buckets():
            raise HTTPException(404, detail="NoSuchBucket")
        ctype = (request.headers.get("content-type") or "").lower()
        key = "unnamed"
        data = b""
        content_type = "application/octet-stream"
        if ctype.startswith("multipart/form-data"):
            form = await request.form()
            upload = form.get("file")
            if upload is None or not hasattr(upload, "read"):
                raise HTTPException(422, detail="Unprocessable field 'file' required")
            data = await upload.read()
            key = getattr(upload, "filename", None) or "unnamed"
            content_type = getattr(upload, "content_type", None) or content_type
        else:
            try:
                body = await request.json()
            except Exception:
                body = {}
            if not isinstance(body, dict):
                body = {}
            key = str(body.get("key") or body.get("name") or "console-object")
            content = body.get("content", body.get("body", ""))
            data = content.encode() if isinstance(content, str) else bytes(content or b"")
            content_type = str(body.get("content_type") or "text/plain")
        import base64 as _b64, hashlib as _hl
        obj = {
            "bucket": bucket, "name": key, "contentType": content_type,
            "size": len(data), "timeCreated": _gcs_now(), "updated": _gcs_now(),
            "storageClass": "STANDARD", "metadata": {},
            # Store bytes base64 so binary uploads round-trip via the facade; the
            # native GCS view ignores extra keys (it never echoes `data`).
            "data_b64": _b64.b64encode(data).decode("ascii"),
            "md5Hash": _b64.b64encode(_hl.md5(data).digest()).decode("ascii"),
            "etag": _hl.md5(data).hexdigest(),
        }
        _gcs_objects(bucket)[key] = obj
        return {"message": f"Object '{key}' uploaded", "etag": obj["etag"],
                "size": len(data)}

    def _gcs_get_object(bucket: str, key: str) -> dict:
        if bucket not in _gcs_buckets():
            raise HTTPException(404, detail="NoSuchBucket")
        obj = _gcs_objects(bucket).get(key)
        if obj is None:
            raise HTTPException(404, detail="NoSuchKey")
        return obj

    def _gcs_object_bytes(obj: dict) -> bytes:
        import base64 as _b64
        if "data_b64" in obj:
            try:
                return _b64.b64decode(obj["data_b64"])
            except Exception:
                pass
        d = obj.get("data", "")
        return d.encode() if isinstance(d, str) else bytes(d or b"")

    @app.get("/api/console/gcs/buckets/{bucket}/objects/{key:path}/meta", include_in_schema=False)
    def api_console_gcs_object_meta(bucket: str, key: str):
        obj = _gcs_get_object(bucket, key)
        size = int(obj.get("size", 0) or 0)
        return {
            "key": key, "bucket": bucket,
            "content_type": obj.get("contentType", "application/octet-stream"),
            "size": size, "size_human": _gcs_fmt_size(size),
            "etag": obj.get("etag", "") or obj.get("md5Hash", ""),
            "last_modified": obj.get("updated", obj.get("timeCreated", "")),
            "storage_class": obj.get("storageClass", "STANDARD"),
        }

    @app.get("/api/console/gcs/buckets/{bucket}/objects/{key:path}/download", include_in_schema=False)
    def api_console_gcs_object_download(bucket: str, key: str):
        obj = _gcs_get_object(bucket, key)
        from starlette.responses import Response as _Resp
        return _Resp(content=_gcs_object_bytes(obj),
                     media_type=obj.get("contentType", "application/octet-stream"))

    # ── Azure Blob console-facade (P4 — the Azure lens's object-browser data plane) ──
    #    The SAME object-browser widget renders Azure Blob under lens=azure; the ONLY
    #    difference is the manifest `api` block pointing here (§15.2 — no if(cloud)
    #    branching). This facade returns the SAME response shapes as the S3/GCS facades
    #    so the widget is cloud-agnostic. A "container" is the bucket, a "blob" the
    #    object. Independent in-memory store (core/console_azure_blob) so Azure object
    #    state is isolated from the AWS/GCP facades; purely additive.
    def _ab():
        from core import console_azure_blob as b
        return b

    def _abguard(fn):
        from core.console_azure_blob import AzureBlobError
        try:
            return fn()
        except AzureBlobError as e:
            raise HTTPException(e.status, detail=e.message)

    @app.get("/api/console/azure-blob/containers", include_in_schema=False)
    def api_console_azure_blob_list_containers():
        return _abguard(lambda: _ab().list_buckets())

    @app.post("/api/console/azure-blob/containers/{name}", include_in_schema=False)
    def api_console_azure_blob_create_container(name: str):
        return _abguard(lambda: _ab().create_bucket(name))

    @app.get("/api/console/azure-blob/containers/{bucket}/blobs", include_in_schema=False)
    def api_console_azure_blob_list_blobs(bucket: str, prefix: str = Query(default="")):
        return _abguard(lambda: _ab().list_objects(bucket, prefix))

    @app.post("/api/console/azure-blob/containers/{bucket}/blobs", include_in_schema=False)
    async def api_console_azure_blob_upload(bucket: str, request: Request):
        ctype = (request.headers.get("content-type") or "").lower()
        key = "unnamed"
        data = b""
        content_type = "application/octet-stream"
        if ctype.startswith("multipart/form-data"):
            form = await request.form()
            upload = form.get("file")
            if upload is None or not hasattr(upload, "read"):
                raise HTTPException(422, detail="Unprocessable field 'file' required")
            data = await upload.read()
            key = getattr(upload, "filename", None) or "unnamed"
            content_type = getattr(upload, "content_type", None) or content_type
        else:
            try:
                body = await request.json()
            except Exception:
                body = {}
            if not isinstance(body, dict):
                body = {}
            key = str(body.get("key") or body.get("name") or "console-blob")
            content = body.get("content", body.get("body", ""))
            data = content.encode() if isinstance(content, str) else bytes(content or b"")
            content_type = str(body.get("content_type") or "text/plain")
        return _abguard(lambda: _ab().put_object(bucket, key, data, content_type))

    @app.get("/api/console/azure-blob/containers/{bucket}/blobs/{key:path}/meta", include_in_schema=False)
    def api_console_azure_blob_blob_meta(bucket: str, key: str):
        return _abguard(lambda: _ab().object_meta(bucket, key))

    @app.get("/api/console/azure-blob/containers/{bucket}/blobs/{key:path}/download", include_in_schema=False)
    def api_console_azure_blob_blob_download(bucket: str, key: str):
        data, media = _abguard(lambda: _ab().object_bytes(bucket, key))
        from starlette.responses import Response as _Resp
        return _Resp(content=data, media_type=media)

    # ── GCP Cloud Functions serverless-invoke (P3 — the GCP lens's serverless data
    #    plane) ── the SAME serverless-invoke widget renders Cloud Functions under
    #    lens=gcp; the ONLY difference is the manifest `api` block pointing here
    #    instead of /api/lambda/* (§15.2 — no if(cloud) branching). This facade
    #    returns the SAME JSON response shapes the widget consumes (list / get config
    #    / create / invoke → payload + status + logs) and runs the REAL sandboxed
    #    handler (core/console_gcf executes the user code in a subprocess, exactly like
    #    the Lambda runtime). Independent in-memory store so GCP function state is
    #    isolated from the AWS Lambda facade; purely additive.
    def _gcf():
        from core import console_gcf as g
        return g

    def _gcfguard(fn):
        from core.console_gcf import GcfError
        try:
            return fn()
        except GcfError as e:
            raise HTTPException(e.status, detail=e.message)

    @app.get("/api/console/gcf/functions", include_in_schema=False)
    def api_console_gcf_list():
        return _gcfguard(lambda: _gcf().list_functions())

    @app.post("/api/console/gcf/functions", include_in_schema=False)
    def api_console_gcf_create(payload: dict = Body(default=None)):
        p = payload or {}
        name = (p.get("function_name") or p.get("name") or "").strip()
        if not name:
            raise HTTPException(400, detail="ValidationError function_name is required")
        return _gcfguard(lambda: _gcf().create_function(
            name, p.get("code", ""), (p.get("entry_point") or "").strip()))

    @app.get("/api/console/gcf/functions/{name}", include_in_schema=False)
    def api_console_gcf_get(name: str):
        return _gcfguard(lambda: _gcf().get_function(name))

    @app.delete("/api/console/gcf/functions/{name}", include_in_schema=False)
    def api_console_gcf_delete(name: str):
        return _gcfguard(lambda: _gcf().delete_function(name))

    @app.post("/api/console/gcf/functions/{name}/invoke", include_in_schema=False)
    def api_console_gcf_invoke(name: str, payload: dict = Body(default=None)):
        p = payload or {}
        return _gcfguard(lambda: _gcf().invoke(name, p.get("payload")))

    # ── Azure Functions serverless-invoke (P4 — the Azure lens's serverless data
    #    plane) ── the SAME serverless-invoke widget renders Azure Functions under
    #    lens=azure; the ONLY difference is the manifest `api` block pointing here
    #    instead of /api/lambda/* (§15.2 — no if(cloud) branching). Mirrors the GCF
    #    facade: returns the SAME JSON response shapes the widget consumes and runs
    #    the REAL sandboxed handler (core/console_azure_functions executes the user
    #    code in a subprocess, exactly like the Lambda / Cloud Functions runtimes).
    #    Independent in-memory store so Azure function state is isolated from the AWS
    #    Lambda / GCP Cloud Functions facades; purely additive.
    def _azfn():
        from core import console_azure_functions as a
        return a

    def _azfnguard(fn):
        from core.console_azure_functions import AzureFunctionError
        try:
            return fn()
        except AzureFunctionError as e:
            raise HTTPException(e.status, detail=e.message)

    @app.get("/api/console/azure-functions/functions", include_in_schema=False)
    def api_console_azfn_list():
        return _azfnguard(lambda: _azfn().list_functions())

    @app.post("/api/console/azure-functions/functions", include_in_schema=False)
    def api_console_azfn_create(payload: dict = Body(default=None)):
        p = payload or {}
        name = (p.get("function_name") or p.get("name") or "").strip()
        if not name:
            raise HTTPException(400, detail="ValidationError function_name is required")
        return _azfnguard(lambda: _azfn().create_function(
            name, p.get("code", ""), (p.get("entry_point") or "").strip()))

    @app.get("/api/console/azure-functions/functions/{name}", include_in_schema=False)
    def api_console_azfn_get(name: str):
        return _azfnguard(lambda: _azfn().get_function(name))

    @app.delete("/api/console/azure-functions/functions/{name}", include_in_schema=False)
    def api_console_azfn_delete(name: str):
        return _azfnguard(lambda: _azfn().delete_function(name))

    @app.post("/api/console/azure-functions/functions/{name}/invoke", include_in_schema=False)
    def api_console_azfn_invoke(name: str, payload: dict = Body(default=None)):
        p = payload or {}
        return _azfnguard(lambda: _azfn().invoke(name, p.get("payload")))

    # ── Snapshots (§12.6): capture / list / restore / FORK of the console's
    #    in-process backend store state. Control-plane-first. No substrate
    #    branching — the registry walks a common store table
    #    (core/console_snapshots.py). ──
    @app.post("/api/console/snapshots", include_in_schema=False)
    def api_console_snapshots_capture(payload: dict = Body(default=None)):
        from core import console_snapshots as snaps
        p = payload or {}
        return snaps.capture(name=(p.get("name") or "").strip(),
                             note=(p.get("note") or "").strip())

    @app.get("/api/console/snapshots", include_in_schema=False)
    def api_console_snapshots_list():
        from core import console_snapshots as snaps
        return {"snapshots": snaps.list_snapshots()}

    @app.post("/api/console/snapshots/{snap_id}/restore", include_in_schema=False)
    def api_console_snapshots_restore(snap_id: str):
        from core import console_snapshots as snaps
        try:
            return snaps.restore(snap_id)
        except snaps.SnapshotError as e:
            raise HTTPException(e.status, detail=e.message)

    # ── Fork (§12.6): branch a new named line of state off an existing snapshot.
    #    Additive; reuses the same registry/store table (capture+restore internals). ──
    @app.post("/api/console/snapshots/{snap_id}/fork", include_in_schema=False)
    def api_console_snapshots_fork(snap_id: str, payload: dict = Body(default=None)):
        from core import console_snapshots as snaps
        name = ((payload or {}).get("name") or "").strip()
        try:
            return snaps.fork(snap_id, name=name)
        except snaps.SnapshotError as e:
            raise HTTPException(e.status, detail=e.message)

    # ── The SPA shell — serves index.html at /console-next and any sub-path so the
    #    client-side router can own deep-links. Asset refs inside index.html are
    #    relative to /console-next-assets/, base-path-friendly. ──
    @app.get("/console-next", include_in_schema=False)
    @app.get("/console-next/", include_in_schema=False)
    @app.get("/console-next/{path:path}", include_in_schema=False)
    def console_next_spa(path: str = ""):
        try:
            with open(_INDEX, "rb") as f:
                html = f.read().decode("utf-8")
        except FileNotFoundError:
            return HTMLResponse("<h1>console-next not built</h1>", status_code=500)
        return HTMLResponse(content=html, headers={"Cache-Control": "no-store, max-age=0"})
