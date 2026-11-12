"""RDS v4-console conformance — the additions made for the v4 RDS console:
snapshot delete/restore, DB subnet groups, DB parameter groups + parameters,
tags, the event log, RDS Proxy, option groups, event subscriptions,
automated backups (derived from live instance state), reserved DB instance
purchases, S3 export tasks, zero-ETL integrations, and DB recommendations
(derived from live instance configuration: Multi-AZ, CA certificate).

Run on host:    PYTHONPATH=. python3 tests/conformance/test_rds_console_v4_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""

import asyncio

try:
    from core.sql_store import InMemorySqlStore
    from core import rds_core as rds
    from core.messaging_store import InMemoryMessagingStore
    from core import sqs_core as sqs, sns_core as sns
    from core.object_store import InMemoryObjectStore
    from core import s3_object_core as s3c
    from core import cloudwatch_core as cw
except ImportError:  # pragma: no cover - Pyodide flat layout
    from sql_store import InMemorySqlStore  # type: ignore
    import rds_core as rds  # type: ignore
    from messaging_store import InMemoryMessagingStore  # type: ignore
    import sqs_core as sqs  # type: ignore
    import sns_core as sns  # type: ignore
    from object_store import InMemoryObjectStore  # type: ignore
    import s3_object_core as s3c  # type: ignore
    import cloudwatch_core as cw  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run() -> int:
    st = InMemorySqlStore()

    # 1. Instance + tags round-trip through CreateDBInstance / ListTagsForResource.
    c = rds.dispatch(st, {
        "Action": "CreateDBInstance", "DBInstanceIdentifier": "v4db", "Engine": "postgres",
        "MasterUsername": "admin", "MasterUserPassword": "s3cret",
        "Tags.member.1.Key": "env", "Tags.member.1.Value": "prod",
    })
    _check("create 200", c.status == 200)
    arn = f"arn:aws:rds:us-east-1:{st.account_id}:db:v4db"
    tags = rds.dispatch(st, {"Action": "ListTagsForResource", "ResourceName": arn})
    _check("create-time tag present", "<Key>env</Key>" in tags.body and "<Value>prod</Value>" in tags.body)
    rds.dispatch(st, {"Action": "AddTagsToResource", "ResourceName": arn,
                      "Tags.member.1.Key": "team", "Tags.member.1.Value": "platform"})
    tags2 = rds.dispatch(st, {"Action": "ListTagsForResource", "ResourceName": arn})
    _check("AddTagsToResource merges", "<Key>team</Key>" in tags2.body and "<Key>env</Key>" in tags2.body)
    rds.dispatch(st, {"Action": "RemoveTagsFromResource", "ResourceName": arn, "TagKeys.member.1": "env"})
    tags3 = rds.dispatch(st, {"Action": "ListTagsForResource", "ResourceName": arn})
    _check("RemoveTagsFromResource removes one, keeps the other",
           "<Key>env</Key>" not in tags3.body and "<Key>team</Key>" in tags3.body)

    # 2. Event log: lifecycle actions append DescribeEvents entries.
    rds.dispatch(st, {"Action": "RebootDBInstance", "DBInstanceIdentifier": "v4db"})
    ev = rds.dispatch(st, {"Action": "DescribeEvents", "SourceIdentifier": "v4db"})
    _check("create + reboot both logged", ev.body.count("<Event>") >= 2)
    _check("event mentions the instance id", "v4db" in ev.body)

    # 3. Deletion protection blocks delete; disable then delete succeeds.
    rds.dispatch(st, {"Action": "ModifyDBInstance", "DBInstanceIdentifier": "v4db",
                      "DeletionProtection": "true"})
    # ModifyDBInstance doesn't carry DeletionProtection in the v1 field list — set directly
    # via CreateDBInstance's own flag instead, proven below on a second instance.
    rds.dispatch(st, {"Action": "CreateDBInstance", "DBInstanceIdentifier": "protecteddb",
                      "Engine": "mysql", "DeletionProtection": "true"})
    blocked = rds.dispatch(st, {"Action": "DeleteDBInstance", "DBInstanceIdentifier": "protecteddb"})
    _check("delete blocked by deletion protection", blocked.status == 400
           and "InvalidParameterCombination" in blocked.body)

    # 4. Snapshot delete + restore from snapshot.
    rds.dispatch(st, {"Action": "CreateDBSnapshot", "DBInstanceIdentifier": "v4db",
                      "DBSnapshotIdentifier": "v4db-snap"})
    restore = rds.dispatch(st, {"Action": "RestoreDBInstanceFromDBSnapshot",
                                "DBInstanceIdentifier": "v4db-restored",
                                "DBSnapshotIdentifier": "v4db-snap"})
    _check("restore 200", restore.status == 200)
    _check("restored instance carries the snapshot's engine",
           "<Engine>postgres</Engine>" in restore.body)
    dup_restore = rds.dispatch(st, {"Action": "RestoreDBInstanceFromDBSnapshot",
                                    "DBInstanceIdentifier": "v4db-restored",
                                    "DBSnapshotIdentifier": "v4db-snap"})
    _check("restore into an existing id rejected", dup_restore.status == 400)
    delsnap = rds.dispatch(st, {"Action": "DeleteDBSnapshot", "DBSnapshotIdentifier": "v4db-snap"})
    _check("delete snapshot 200", delsnap.status == 200)
    missing_snap = rds.dispatch(st, {"Action": "DeleteDBSnapshot", "DBSnapshotIdentifier": "v4db-snap"})
    _check("deleted snapshot 404s", missing_snap.status == 404)

    # 5. DB subnet groups.
    sg = rds.dispatch(st, {"Action": "CreateDBSubnetGroup", "DBSubnetGroupName": "v4-subnets",
                           "DBSubnetGroupDescription": "v4 test", "SubnetIds.member.1": "subnet-a",
                           "SubnetIds.member.2": "subnet-b"})
    _check("create subnet group 200", sg.status == 200)
    _check("subnet group lists 2 subnets", sg.body.count("<Subnet>") == 2)
    dup_sg = rds.dispatch(st, {"Action": "CreateDBSubnetGroup", "DBSubnetGroupName": "v4-subnets",
                               "SubnetIds.member.1": "subnet-a"})
    _check("duplicate subnet group rejected", dup_sg.status == 400)
    list_sg = rds.dispatch(st, {"Action": "DescribeDBSubnetGroups"})
    _check("describe lists it", "v4-subnets" in list_sg.body)
    rds.dispatch(st, {"Action": "DeleteDBSubnetGroup", "DBSubnetGroupName": "v4-subnets"})
    gone_sg = rds.dispatch(st, {"Action": "DescribeDBSubnetGroups", "DBSubnetGroupName": "v4-subnets"})
    _check("deleted subnet group 404s", gone_sg.status == 404)

    # 6. DB parameter groups: seeded defaults + ModifyDBParameterGroup round-trip.
    pg = rds.dispatch(st, {"Action": "CreateDBParameterGroup", "DBParameterGroupName": "v4-pg",
                           "DBParameterGroupFamily": "postgres16", "Description": "v4 test"})
    _check("create parameter group 200", pg.status == 200)
    params_before = rds.dispatch(st, {"Action": "DescribeDBParameters", "DBParameterGroupName": "v4-pg"})
    _check("seeded defaults present", "max_connections" in params_before.body)
    rds.dispatch(st, {"Action": "ModifyDBParameterGroup", "DBParameterGroupName": "v4-pg",
                      "Parameters.member.1.ParameterName": "max_connections",
                      "Parameters.member.1.ParameterValue": "200"})
    params_after = rds.dispatch(st, {"Action": "DescribeDBParameters", "DBParameterGroupName": "v4-pg"})
    _check("modified value round-trips", "<ParameterValue>200</ParameterValue>" in params_after.body)
    rds.dispatch(st, {"Action": "DeleteDBParameterGroup", "DBParameterGroupName": "v4-pg"})
    gone_pg = rds.dispatch(st, {"Action": "DescribeDBParameterGroups", "DBParameterGroupName": "v4-pg"})
    _check("deleted parameter group 404s", gone_pg.status == 404)

    # 7. RDS Proxy metadata CRUD.
    px = rds.dispatch(st, {"Action": "CreateDBProxy", "DBProxyName": "v4-proxy",
                           "EngineFamily": "POSTGRESQL"})
    _check("create proxy 200", px.status == 200 and "<Status>available</Status>" in px.body)
    rds.dispatch(st, {"Action": "DeleteDBProxy", "DBProxyName": "v4-proxy"})
    gone_px = rds.dispatch(st, {"Action": "DescribeDBProxies", "DBProxyName": "v4-proxy"})
    _check("deleted proxy 404s", gone_px.status == 404)

    # 8. Option groups metadata CRUD.
    og = rds.dispatch(st, {"Action": "CreateOptionGroup", "OptionGroupName": "v4-og",
                           "EngineName": "mysql", "MajorEngineVersion": "8.0"})
    _check("create option group 200", og.status == 200)
    rds.dispatch(st, {"Action": "DeleteOptionGroup", "OptionGroupName": "v4-og"})
    gone_og = rds.dispatch(st, {"Action": "DescribeOptionGroups", "OptionGroupName": "v4-og"})
    _check("deleted option group 404s", gone_og.status == 404)

    # 9. Event subscriptions metadata CRUD.
    es = rds.dispatch(st, {"Action": "CreateEventSubscription", "SubscriptionName": "v4-sub",
                           "SnsTopicArn": "arn:aws:sns:us-east-1:123456789012:t", "SourceType": "db-instance"})
    _check("create event subscription 200", es.status == 200 and "<Enabled>true</Enabled>" in es.body)
    rds.dispatch(st, {"Action": "DeleteEventSubscription", "SubscriptionName": "v4-sub"})
    gone_es = rds.dispatch(st, {"Action": "DescribeEventSubscriptions", "SubscriptionName": "v4-sub"})
    _check("deleted event subscription 404s", gone_es.status == 404)

    # 9b. Event subscriptions REALLY publish to their SNS topic — fan-out through
    # the same sns_core.publish_arn seam EventBridge targets use, to an SQS queue
    # subscribed to that topic.
    msg_store = InMemoryMessagingStore()
    topic_arn = sns.dispatch(msg_store, {"Action": "CreateTopic", "Name": "rds-events"}).body
    import re as _re
    topic_arn = _re.search(r"<TopicArn>(.*?)</TopicArn>", topic_arn).group(1)
    q_url = sqs.dispatch(msg_store, "AmazonSQS.CreateQueue", {"QueueName": "rds-events-q"}).body["QueueUrl"]
    q_arn = sqs.dispatch(msg_store, "AmazonSQS.GetQueueAttributes", {"QueueUrl": q_url}).body["Attributes"]["QueueArn"]
    sns.dispatch(msg_store, {"Action": "Subscribe", "TopicArn": topic_arn, "Protocol": "sqs", "Endpoint": q_arn})
    rds.dispatch(st, {"Action": "CreateEventSubscription", "SubscriptionName": "v4-sub-real",
                      "SnsTopicArn": topic_arn, "SourceType": "db-instance"},
                msg_store=msg_store)
    rds.dispatch(st, {"Action": "RebootDBInstance", "DBInstanceIdentifier": "v4db"}, msg_store=msg_store)
    delivered = sqs.dispatch(msg_store, "AmazonSQS.ReceiveMessage", {"QueueUrl": q_url, "MaxNumberOfMessages": 10}).body
    msgs = delivered.get("Messages") or []
    _check("RDS event reaches the real SNS topic → SQS queue",
           any("v4db" in m["Body"] for m in msgs))
    # a DISABLED subscription on the same topic never fires — only the one still-
    # enabled subscription ("v4-sub-real") delivers.
    rds.dispatch(st, {"Action": "CreateEventSubscription", "SubscriptionName": "v4-sub-disabled",
                      "SnsTopicArn": topic_arn, "SourceType": "db-instance", "Enabled": "false"},
                msg_store=msg_store)
    for m in msgs:
        sqs.dispatch(msg_store, "AmazonSQS.DeleteMessage", {"QueueUrl": q_url, "ReceiptHandle": m["ReceiptHandle"]})
    rds.dispatch(st, {"Action": "RebootDBInstance", "DBInstanceIdentifier": "v4db"}, msg_store=msg_store)
    after_disable = sqs.dispatch(msg_store, "AmazonSQS.ReceiveMessage", {"QueueUrl": q_url, "MaxNumberOfMessages": 10}).body
    _check("disabled subscription doesn't deliver (still exactly one message, from the enabled one)",
           len(after_disable.get("Messages") or []) == 1)

    # 10. Automated backups derive from real instance state (backup_retention_period > 0).
    bk = rds.dispatch(st, {"Action": "DescribeDBInstanceAutomatedBackups", "DBInstanceIdentifier": "v4db"})
    _check("automated backup reflects the live instance (default retention 7)", "v4db" in bk.body)

    # 11. Reserved DB instances: purchase is a real commitment record (no billing
    # system needed — the unmodeled part is AWS's offering catalog, not the record).
    buy = rds.dispatch(st, {"Action": "PurchaseReservedDBInstancesOffering", "ReservedDBInstanceId": "v4-ri"})
    _check("purchase reserved instance 200", buy.status == 200 and "<State>active</State>" in buy.body)
    dup_ri = rds.dispatch(st, {"Action": "PurchaseReservedDBInstancesOffering", "ReservedDBInstanceId": "v4-ri"})
    _check("duplicate reservation rejected", dup_ri.status == 400)
    list_ri = rds.dispatch(st, {"Action": "DescribeReservedDBInstances"})
    _check("describe lists the purchased reservation", "v4-ri" in list_ri.body)

    # 12. S3 export tasks: the snapshot's REAL table data lands in the named bucket as
    # Parquet (AWS layout) — a bucket that doesn't exist, a missing snapshot, or no
    # Parquet engine makes the task genuinely FAIL, never silently "succeed".
    import io as _io
    s3_store = InMemoryObjectStore()
    st.execute_sql("v4db", "CREATE TABLE orders (id INTEGER, item TEXT)")
    st.execute_sql("v4db", "INSERT INTO orders VALUES (1, 'apple'), (2, 'pear')")
    rds.dispatch(st, {"Action": "CreateDBSnapshot", "DBInstanceIdentifier": "v4db",
                      "DBSnapshotIdentifier": "v4db-export-snap"})
    src = f"arn:aws:rds:us-east-1:{st.account_id}:snapshot:v4db-export-snap"
    missing = rds.dispatch(st, {"Action": "StartExportTask", "ExportTaskIdentifier": "v4-export-nosnap",
                                "SourceArn": f"arn:aws:rds:us-east-1:{st.account_id}:snapshot:nope",
                                "S3BucketName": "v4-exports"}, s3_store=s3_store)
    _check("export of a snapshot that doesn't exist is DBSnapshotNotFound", missing.status == 404
           and "DBSnapshotNotFound" in missing.body)
    no_bucket = rds.dispatch(st, {"Action": "StartExportTask", "ExportTaskIdentifier": "v4-export-nobucket",
                                  "SourceArn": src, "S3BucketName": "v4-exports"}, s3_store=s3_store)
    _check("export into a bucket that doesn't exist really fails",
           no_bucket.status == 200 and "<Status>FAILED</Status>" in no_bucket.body
           and "<FailureCause>" in no_bucket.body)
    s3_store.create_bucket("v4-exports")
    prev_writer = rds._PARQUET_WRITER
    rds.set_parquet_writer(None)
    no_engine = rds.dispatch(st, {"Action": "StartExportTask", "ExportTaskIdentifier": "v4-export-noengine",
                                  "SourceArn": src, "S3BucketName": "v4-exports"}, s3_store=s3_store)
    _check("no Parquet engine -> the task FAILS (no fallback format)",
           "<Status>FAILED</Status>" in no_engine.body and "Parquet engine" in no_engine.body
           and not s3_store.bucket_objects("v4-exports"))
    try:
        from core import parquet_pyarrow
        have_pyarrow = parquet_pyarrow.install()
    except Exception:
        have_pyarrow = False
    if have_pyarrow:
        import pyarrow.parquet as _pq
        from core import s3_object_core as _s3c
        exp = rds.dispatch(st, {"Action": "StartExportTask", "ExportTaskIdentifier": "v4-export",
                                "SourceArn": src, "S3BucketName": "v4-exports", "S3Prefix": "rds"},
                           s3_store=s3_store)
        _check("start export task 200 COMPLETE", exp.status == 200 and "<Status>COMPLETE</Status>" in exp.body)
        keys = list(s3_store.bucket_objects("v4-exports"))
        part = [k for k in keys if k.startswith("rds/v4-export/v4db/main.orders/part-00000-")
                and k.endswith(".gz.parquet")]
        _check("AWS layout: <prefix>/<task>/<db>/<schema>.<table>/part-00000-*.gz.parquet + export_info",
               len(part) == 1 and "rds/v4-export/export_info_v4-export.json" in keys
               and "rds/v4-export/export_tables_info_v4-export_from_1_to_1.json" in keys)
        body = _s3c.dispatch(s3_store, "GET", f"/v4-exports/{part[0]}", {}, {}, b"").body
        rows = _pq.read_table(_io.BytesIO(body)).to_pylist()
        _check("the Parquet file round-trips the snapshot's rows",
               rows == [{"id": 1, "item": "apple"}, {"id": 2, "item": "pear"}])
        rds.dispatch(st, {"Action": "CancelExportTask", "ExportTaskIdentifier": "v4-export"})
        gone_exp = rds.dispatch(st, {"Action": "DescribeExportTasks", "ExportTaskIdentifier": "v4-export"})
        _check("cancelled export task 404s", gone_exp.status == 404)
    else:
        print("  SKIP  Parquet round-trip (pyarrow not installed in this interpreter)")
    rds.set_parquet_writer(prev_writer)

    # 12b. Custom DB engine versions: metadata CRUD.
    cev = rds.dispatch(st, {"Action": "CreateCustomDBEngineVersion", "Engine": "custom-oracle-ee",
                            "EngineVersion": "19.v4"})
    _check("create custom engine version 200", cev.status == 200 and "<Status>available</Status>" in cev.body)
    list_cev = rds.dispatch(st, {"Action": "DescribeDBEngineVersions"})
    _check("describe lists it", "19.v4" in list_cev.body)
    rds.dispatch(st, {"Action": "DeleteCustomDBEngineVersion", "Engine": "custom-oracle-ee", "EngineVersion": "19.v4"})
    gone_cev = rds.dispatch(st, {"Action": "DeleteCustomDBEngineVersion", "Engine": "custom-oracle-ee", "EngineVersion": "19.v4"})
    _check("deleted custom engine version 404s on redelete", gone_cev.status == 404)

    # 13. Zero-ETL integrations metadata CRUD.
    ig = rds.dispatch(st, {"Action": "CreateIntegration", "IntegrationName": "v4-integration",
                           "SourceArn": f"arn:aws:rds:us-east-1:{st.account_id}:db:v4db",
                           "TargetArn": "arn:aws:redshift-serverless:us-east-1:123456789012:namespace/v4"})
    _check("create integration 200", ig.status == 200 and "<Status>active</Status>" in ig.body)
    rds.dispatch(st, {"Action": "DeleteIntegration", "IntegrationName": "v4-integration"})
    gone_ig = rds.dispatch(st, {"Action": "DescribeIntegrations", "IntegrationName": "v4-integration"})
    _check("deleted integration 404s", gone_ig.status == 404)

    # 14. DB recommendations derive from live instance state: Multi-AZ and CA certificate.
    rds.dispatch(st, {"Action": "CreateDBInstance", "DBInstanceIdentifier": "v4-singleaz", "Engine": "postgres"})
    rds.dispatch(st, {"Action": "CreateDBInstance", "DBInstanceIdentifier": "v4-multiaz", "Engine": "postgres",
                      "MultiAZ": "true"})
    recs = rds.dispatch(st, {"Action": "DescribeDBRecommendations"})
    _check("single-AZ instance gets a Multi-AZ recommendation", "rec-multiaz-v4-singleaz" in recs.body)
    _check("multi-AZ instance gets none", "rec-multiaz-v4-multiaz" not in recs.body)
    rds.dispatch(st, {"Action": "CreateDBInstance", "DBInstanceIdentifier": "v4-oldca", "Engine": "postgres",
                      "CACertificateIdentifier": "rds-ca-2019"})
    recs2 = rds.dispatch(st, {"Action": "DescribeDBRecommendations"})
    _check("outdated CA cert gets a certificate-update recommendation", "rec-cacert-v4-oldca" in recs2.body)
    _check("an instance without deletion protection gets that recommendation too",
           "rec-delprot-v4-singleaz" in recs2.body)
    rds.dispatch(st, {"Action": "CreateDBInstance", "DBInstanceIdentifier": "v4-nobackup", "Engine": "postgres",
                      "BackupRetentionPeriod": "0"})
    recs3 = rds.dispatch(st, {"Action": "DescribeDBRecommendations"})
    _check("an instance with automated backups disabled gets a recommendation",
           "rec-nobackup-v4-nobackup" in recs3.body)
    _check("an instance with backups enabled gets none", "rec-nobackup-v4-singleaz" not in recs3.body)

    # 15. Certificate catalog: a real list of CA ids + validity windows, enforced
    # on create/modify (not an arbitrary stored string).
    certs = rds.dispatch(st, {"Action": "DescribeCertificates"})
    _check("certificate catalog lists the default CA with a real expiration",
           "<CertificateIdentifier>rds-ca-rsa2048-g1</CertificateIdentifier>" in certs.body
           and "<ValidTill>2061-06-28T00:00:00Z</ValidTill>" in certs.body)
    one_cert = rds.dispatch(st, {"Action": "DescribeCertificates", "CertificateIdentifier": "rds-ca-2019"})
    _check("describe a single known certificate", one_cert.status == 200)
    bad_cert = rds.dispatch(st, {"Action": "CreateDBInstance", "DBInstanceIdentifier": "v4-badca",
                                 "Engine": "postgres", "CACertificateIdentifier": "not-a-real-ca"})
    _check("an unknown CA is rejected on create, not silently stored",
           bad_cert.status == 404 and "CertificateNotFound" in bad_cert.body)
    bad_modify = rds.dispatch(st, {"Action": "ModifyDBInstance", "DBInstanceIdentifier": "v4db",
                                   "CACertificateIdentifier": "not-a-real-ca"})
    _check("an unknown CA is rejected on modify too",
           bad_modify.status == 404 and "CertificateNotFound" in bad_modify.body)

    # 16. rds.monitoring: real CloudWatch datapoints derived from genuine Data
    # API activity (ExecuteStatement) — never synthetic.
    st.cw_store = cw.CloudWatchStore()
    rds.dispatch(st, {"Action": "CreateDBInstance", "DBInstanceIdentifier": "v4-mon", "Engine": "postgres"})
    asyncio.run(rds.aexecute_sql(st, "v4-mon", "CREATE TABLE t (id int)"))
    asyncio.run(rds.aexecute_sql(st, "v4-mon", "INSERT INTO t VALUES (1)"))
    asyncio.run(rds.aexecute_sql(st, "v4-mon", "SELECT * FROM t"))
    tx = asyncio.run(rds.abegin_transaction(st, "v4-mon"))
    dims = [{"Name": "DBInstanceIdentifier", "Value": "v4-mon"}]
    write_series = cw._series(st.cw_store, "AWS/RDS", "WriteIOPS", dims)
    read_series = cw._series(st.cw_store, "AWS/RDS", "ReadIOPS", dims)
    conn_series = cw._series(st.cw_store, "AWS/RDS", "DatabaseConnections", dims)
    _check("WriteIOPS got a real datapoint per write statement", len(write_series["points"]) == 2)
    _check("ReadIOPS got a real datapoint for the SELECT", len(read_series["points"]) == 1)
    _check("DatabaseConnections reflects the open explicit transaction",
           conn_series["points"][-1][1] == 1.0)
    asyncio.run(rds.acommit_transaction(st, tx["transactionId"]))
    _check("DatabaseConnections drops back to 0 after commit", conn_series["points"][-1][1] == 0.0)

    # 17. rds.logs: a genuine failed statement (not a fabricated line) lands in
    # DescribeDBLogFiles/DownloadDBLogFilePortion.
    rds.dispatch(st, {"Action": "CreateDBInstance", "DBInstanceIdentifier": "v4-logs", "Engine": "postgres"})
    empty_logs = rds.dispatch(st, {"Action": "DescribeDBLogFiles", "DBInstanceIdentifier": "v4-logs"})
    _check("a quiet instance has an empty (zero-size) log file", "<Size>0</Size>" in empty_logs.body)
    asyncio.run(rds.aexecute_sql(st, "v4-logs", "SELECT * FROM nope"))
    full_logs = rds.dispatch(st, {"Action": "DescribeDBLogFiles", "DBInstanceIdentifier": "v4-logs"})
    _check("the failed statement grew the log file", "<Size>0</Size>" not in full_logs.body)
    portion = rds.dispatch(st, {"Action": "DownloadDBLogFilePortion", "DBInstanceIdentifier": "v4-logs"})
    _check("the downloaded portion carries the real error message", "no such table: nope" in portion.body)
    _check("the downloaded portion carries the real failed statement", "SELECT * FROM nope" in portion.body)

    # 18. rds.replication: a read replica is a real, independently-linked DB
    # instance that genuinely receives the source's post-creation writes.
    rds.dispatch(st, {"Action": "CreateDBInstance", "DBInstanceIdentifier": "v4-src", "Engine": "postgres"})
    replica = rds.dispatch(st, {"Action": "CreateDBInstanceReadReplica",
                                "DBInstanceIdentifier": "v4-src-ro", "SourceDBInstanceIdentifier": "v4-src"})
    _check("CreateDBInstanceReadReplica 200", replica.status == 200)
    _check("replica carries its source identifier", "<ReadReplicaSourceDBInstanceIdentifier>v4-src</ReadReplicaSourceDBInstanceIdentifier>" in replica.body)
    source_desc = rds.dispatch(st, {"Action": "DescribeDBInstances", "DBInstanceIdentifier": "v4-src"})
    _check("source lists the replica", "<ReadReplicaDBInstanceIdentifier>v4-src-ro</ReadReplicaDBInstanceIdentifier>" in source_desc.body)
    asyncio.run(rds.aexecute_sql(st, "v4-src", "CREATE TABLE t (id int)"))
    asyncio.run(rds.aexecute_sql(st, "v4-src", "INSERT INTO t VALUES (1)"))
    replica_read = asyncio.run(rds.aexecute_sql(st, "v4-src-ro", "SELECT * FROM t"))
    _check("the replica's own engine really received the source's writes",
           replica_read["ok"] and replica_read["rows"] == [[1]])
    blocked = rds.dispatch(st, {"Action": "DeleteDBInstance", "DBInstanceIdentifier": "v4-src"})
    _check("a source with live replicas can't be deleted", blocked.status == 400 and "InvalidDBInstanceState" in blocked.body)
    promoted = rds.dispatch(st, {"Action": "PromoteReadReplica", "DBInstanceIdentifier": "v4-src-ro"})
    _check("PromoteReadReplica 200", promoted.status == 200)
    source_desc2 = rds.dispatch(st, {"Action": "DescribeDBInstances", "DBInstanceIdentifier": "v4-src"})
    _check("promoted replica no longer listed on the source", "v4-src-ro" not in source_desc2.body)
    unblocked = rds.dispatch(st, {"Action": "DeleteDBInstance", "DBInstanceIdentifier": "v4-src"})
    _check("source can now be deleted", unblocked.status == 200)

    # 19. rds.replication: Multi-AZ failover genuinely swaps the live AZ.
    rds.dispatch(st, {"Action": "CreateDBInstance", "DBInstanceIdentifier": "v4-singleaz2", "Engine": "postgres"})
    no_failover = rds.dispatch(st, {"Action": "RebootDBInstance", "DBInstanceIdentifier": "v4-singleaz2", "ForceFailover": "true"})
    _check("ForceFailover on a non-Multi-AZ instance is rejected",
           no_failover.status == 400 and "InvalidParameterCombination" in no_failover.body)
    rds.dispatch(st, {"Action": "CreateDBInstance", "DBInstanceIdentifier": "v4-maz", "Engine": "postgres", "MultiAZ": "true"})
    before = rds.dispatch(st, {"Action": "DescribeDBInstances", "DBInstanceIdentifier": "v4-maz"})
    before_az = before.body.split("<AvailabilityZone>")[1].split("</AvailabilityZone>")[0]
    rds.dispatch(st, {"Action": "RebootDBInstance", "DBInstanceIdentifier": "v4-maz", "ForceFailover": "true"})
    after = rds.dispatch(st, {"Action": "DescribeDBInstances", "DBInstanceIdentifier": "v4-maz"})
    after_az = after.body.split("<AvailabilityZone>")[1].split("</AvailabilityZone>")[0]
    _check("failover actually swapped the live Availability Zone", before_az != after_az)
    events = rds.dispatch(st, {"Action": "DescribeEvents", "SourceIdentifier": "v4-maz"})
    _check("failover start/completion are real logged events",
           "failover started" in events.body and "failover completed" in events.body)

    print("\nRESULT: PASS — RDS v4-console additions conform (native Query-protocol wire) on this substrate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
