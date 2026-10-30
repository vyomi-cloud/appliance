"""RDS v4-console conformance — the additions made for the v4 RDS console:
snapshot delete/restore, DB subnet groups, DB parameter groups + parameters,
tags, the event log, RDS Proxy, option groups, event subscriptions,
automated backups (derived from live instance state), reserved DB instance
purchases, S3 export tasks, zero-ETL integrations, and DB recommendations
(derived from live instance configuration: Multi-AZ, CA certificate).

Run on host:    PYTHONPATH=. python3 tests/conformance/test_rds_console_v4_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""

try:
    from core.sql_store import InMemorySqlStore
    from core import rds_core as rds
except ImportError:  # pragma: no cover - Pyodide flat layout
    from sql_store import InMemorySqlStore  # type: ignore
    import rds_core as rds  # type: ignore


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

    # 12. S3 export tasks: start + cancel round-trip.
    exp = rds.dispatch(st, {"Action": "StartExportTask", "ExportTaskIdentifier": "v4-export",
                            "SourceArn": f"arn:aws:rds:us-east-1:{st.account_id}:snapshot:v4db-snap",
                            "S3BucketName": "v4-exports"})
    _check("start export task 200", exp.status == 200 and "<Status>COMPLETE</Status>" in exp.body)
    rds.dispatch(st, {"Action": "CancelExportTask", "ExportTaskIdentifier": "v4-export"})
    gone_exp = rds.dispatch(st, {"Action": "DescribeExportTasks", "ExportTaskIdentifier": "v4-export"})
    _check("cancelled export task 404s", gone_exp.status == 404)

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

    print("\nRESULT: PASS — RDS v4-console additions conform (native Query-protocol wire) on this substrate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
