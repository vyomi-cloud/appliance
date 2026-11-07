"""DMS wire gaps closed by core/dms_gap_core.py, driven by a real boto3 `dms` client over the router."""
import os
import sys

import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, os.path.dirname(__file__))
from _wire_boto import make_clients  # noqa: E402


@pytest.fixture()
def env():
    router, client = make_clients()
    rds = client("rds")
    rds.create_db_instance(DBInstanceIdentifier="src-db", DBInstanceClass="db.t3.micro", Engine="postgres", MasterUsername="admin",
                           MasterUserPassword="secret123", AllocatedStorage=20)
    rds.create_db_instance(DBInstanceIdentifier="tgt-db", DBInstanceClass="db.t3.micro", Engine="postgres", MasterUsername="admin",
                           MasterUserPassword="secret123", AllocatedStorage=20)
    router.rds.execute_sql("src-db", "CREATE TABLE orders (id INTEGER PRIMARY KEY, item TEXT)")
    for i in range(3):
        router.rds.execute_sql("src-db", "INSERT INTO orders VALUES (?, ?)", [i, f"i{i}"])
    return router, client("dms")


def _ep(d, ident, typ, host):
    return d.create_endpoint(EndpointIdentifier=ident, EndpointType=typ, EngineName="postgres", ServerName=host, Port=5432,
                             DatabaseName="app", Username="admin", Password="secret123")["Endpoint"]


def test_tags_modify_move_reload_schemas(env):
    router, d = env
    ri = d.create_replication_instance(ReplicationInstanceIdentifier="ri1", ReplicationInstanceClass="dms.t3.micro")["ReplicationInstance"]
    ri2 = d.create_replication_instance(ReplicationInstanceIdentifier="ri2", ReplicationInstanceClass="dms.t3.micro")["ReplicationInstance"]
    src = _ep(d, "src", "source", "src-db.nano-rds.local")
    tgt = _ep(d, "tgt", "target", "tgt-db.nano-rds.local")
    for ep in (src, tgt):
        d.test_connection(ReplicationInstanceArn=ri["ReplicationInstanceArn"], EndpointArn=ep["EndpointArn"])

    d.add_tags_to_resource(ResourceArn=ri["ReplicationInstanceArn"], Tags=[{"Key": "env", "Value": "dev"}, {"Key": "team", "Value": "data"}])
    d.remove_tags_from_resource(ResourceArn=ri["ReplicationInstanceArn"], TagKeys=["team"])
    assert d.list_tags_for_resource(ResourceArn=ri["ReplicationInstanceArn"])["TagList"] == [{"Key": "env", "Value": "dev"}]
    with pytest.raises(ClientError) as e:
        d.add_tags_to_resource(ResourceArn="arn:aws:dms:us-east-1:123456789012:rep:NOPE", Tags=[{"Key": "a", "Value": "b"}])
    assert e.value.response["Error"]["Code"] == "ResourceNotFoundFault"

    m = d.modify_replication_instance(ReplicationInstanceArn=ri["ReplicationInstanceArn"], ReplicationInstanceClass="dms.c5.large", AllocatedStorage=100)
    assert m["ReplicationInstance"]["ReplicationInstanceClass"] == "dms.c5.large"
    assert d.describe_replication_instances()["ReplicationInstances"][0]["AllocatedStorage"] == 100
    with pytest.raises(ClientError):
        d.modify_replication_instance(ReplicationInstanceArn=ri["ReplicationInstanceArn"], AllocatedStorage=1)
    d.reboot_replication_instance(ReplicationInstanceArn=ri["ReplicationInstanceArn"])

    # a modified endpoint must be re-tested before a task can use it
    d.modify_endpoint(EndpointArn=src["EndpointArn"], Port=5433)
    assert [x for x in d.describe_endpoints()["Endpoints"] if x["EndpointIdentifier"] == "src"][0]["Port"] == 5433
    with pytest.raises(ClientError) as e:
        d.create_replication_task(ReplicationTaskIdentifier="t1", SourceEndpointArn=src["EndpointArn"], TargetEndpointArn=tgt["EndpointArn"],
                                  ReplicationInstanceArn=ri["ReplicationInstanceArn"], MigrationType="full-load",
                                  TableMappings='{"rules":[{"rule-type":"selection","rule-id":"1","rule-name":"1","object-locator":{"schema-name":"%","table-name":"%"},"rule-action":"include"}]}')
    assert e.value.response["Error"]["Code"] == "InvalidResourceStateFault"
    d.test_connection(ReplicationInstanceArn=ri["ReplicationInstanceArn"], EndpointArn=src["EndpointArn"])
    d.test_connection(ReplicationInstanceArn=ri2["ReplicationInstanceArn"], EndpointArn=src["EndpointArn"])
    d.test_connection(ReplicationInstanceArn=ri2["ReplicationInstanceArn"], EndpointArn=tgt["EndpointArn"])
    maps = '{"rules":[{"rule-type":"selection","rule-id":"1","rule-name":"1","object-locator":{"schema-name":"%","table-name":"%"},"rule-action":"include"}]}'
    t = d.create_replication_task(ReplicationTaskIdentifier="t1", SourceEndpointArn=src["EndpointArn"], TargetEndpointArn=tgt["EndpointArn"],
                                  ReplicationInstanceArn=ri["ReplicationInstanceArn"], MigrationType="full-load", TableMappings=maps)["ReplicationTask"]
    mt = d.modify_replication_task(ReplicationTaskArn=t["ReplicationTaskArn"], MigrationType="full-load-and-cdc")["ReplicationTask"]
    assert mt["MigrationType"] == "full-load-and-cdc"
    d.move_replication_task(ReplicationTaskArn=t["ReplicationTaskArn"], TargetReplicationInstanceArn=ri2["ReplicationInstanceArn"])
    assert d.describe_replication_tasks()["ReplicationTasks"][0]["ReplicationInstanceArn"] == ri2["ReplicationInstanceArn"]
    d.start_replication_task(ReplicationTaskArn=t["ReplicationTaskArn"], StartReplicationTaskType="start-replication")
    d.reload_tables(ReplicationTaskArn=t["ReplicationTaskArn"], TablesToReload=[{"SchemaName": "public", "TableName": "orders"}])
    assert router.rds.execute_sql("tgt-db", "SELECT COUNT(*) FROM orders")["rows"][0][0] == 3
    with pytest.raises(ClientError):
        d.modify_replication_task(ReplicationTaskArn=t["ReplicationTaskArn"], MigrationType="cdc")   # running

    with pytest.raises(ClientError):
        d.describe_schemas(EndpointArn=src["EndpointArn"])   # needs RefreshSchemas first
    assert d.refresh_schemas(EndpointArn=src["EndpointArn"], ReplicationInstanceArn=ri["ReplicationInstanceArn"])["RefreshSchemasStatus"]["Status"] == "successful"
    assert d.describe_schemas(EndpointArn=src["EndpointArn"])["Schemas"] == ["app"]
    assert d.describe_refresh_schemas_status(EndpointArn=src["EndpointArn"])["RefreshSchemasStatus"]["Status"] == "successful"
    ev = d.describe_events(SourceType="replication-task")["Events"]
    assert any(x["SourceIdentifier"] == "t1" for x in ev)
    d.delete_connection(ReplicationInstanceArn=ri["ReplicationInstanceArn"], EndpointArn=src["EndpointArn"])


def test_subnet_groups_subscriptions_certs_and_projects(env):
    _, d = env
    with pytest.raises(ClientError) as e:
        d.create_replication_subnet_group(ReplicationSubnetGroupIdentifier="sg1", ReplicationSubnetGroupDescription="d", SubnetIds=["subnet-1"])
    assert e.value.response["Error"]["Code"] == "InvalidSubnet"
    g = d.create_replication_subnet_group(ReplicationSubnetGroupIdentifier="sg1", ReplicationSubnetGroupDescription="d", SubnetIds=["subnet-1", "subnet-2"])
    assert len(g["ReplicationSubnetGroup"]["Subnets"]) == 2
    d.modify_replication_subnet_group(ReplicationSubnetGroupIdentifier="sg1", SubnetIds=["subnet-1", "subnet-2", "subnet-3"], ReplicationSubnetGroupDescription="d2")
    assert len(d.describe_replication_subnet_groups()["ReplicationSubnetGroups"][0]["Subnets"]) == 3
    d.delete_replication_subnet_group(ReplicationSubnetGroupIdentifier="sg1")
    assert d.describe_replication_subnet_groups()["ReplicationSubnetGroups"] == []

    d.create_event_subscription(SubscriptionName="sub1", SnsTopicArn="arn:aws:sns:us-east-1:123456789012:t", SourceType="replication-task")
    d.modify_event_subscription(SubscriptionName="sub1", Enabled=False)
    assert d.describe_event_subscriptions(SubscriptionName="sub1")["EventSubscriptionsList"][0]["Enabled"] is False
    d.delete_event_subscription(SubscriptionName="sub1")
    assert d.describe_event_subscriptions()["EventSubscriptionsList"] == []
    assert d.describe_event_categories()["EventCategoryGroupList"]

    with pytest.raises(ClientError) as e:
        d.import_certificate(CertificateIdentifier="c1", CertificatePem="not a pem")
    assert e.value.response["Error"]["Code"] == "InvalidCertificateFault"
    d.import_certificate(CertificateIdentifier="c1", CertificatePem="-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----")
    arn = d.describe_certificates()["Certificates"][0]["CertificateArn"]
    d.delete_certificate(CertificateArn=arn)

    dp = d.create_data_provider(DataProviderName="dp-src", Engine="postgres", Settings={"PostgreSqlSettings": {"ServerName": "x", "Port": 5432, "DatabaseName": "a", "SslMode": "none"}})["DataProvider"]
    ip = d.create_instance_profile(InstanceProfileName="ip1")["InstanceProfile"]
    mp = d.create_migration_project(MigrationProjectName="mp1", InstanceProfileIdentifier="ip1",
                                    SourceDataProviderDescriptors=[{"DataProviderIdentifier": "dp-src"}], TargetDataProviderDescriptors=[{"DataProviderIdentifier": "dp-src"}])["MigrationProject"]
    assert d.describe_migration_projects()["MigrationProjects"][0]["MigrationProjectArn"] == mp["MigrationProjectArn"]
    d.add_tags_to_resource(ResourceArn=dp["DataProviderArn"], Tags=[{"Key": "k", "Value": "v"}])
    d.modify_data_provider(DataProviderIdentifier="dp-src", Description="changed")
    assert d.describe_data_providers()["DataProviders"][0]["Description"] == "changed"
    d.delete_migration_project(MigrationProjectIdentifier="mp1")
    d.delete_instance_profile(InstanceProfileIdentifier=ip["InstanceProfileArn"])
    d.delete_data_provider(DataProviderIdentifier=dp["DataProviderArn"])
    assert d.describe_data_providers()["DataProviders"] == []

    q = {x["AccountQuotaName"]: x for x in d.describe_account_attributes()["AccountQuotas"]}
    assert q["ReplicationInstances"]["Max"] == 20 and q["Endpoints"]["Used"] == 0
    assert d.describe_endpoint_types()["SupportedEndpointTypes"] and d.describe_engine_versions()["EngineVersions"]
    assert d.describe_orderable_replication_instances()["OrderableReplicationInstances"]
