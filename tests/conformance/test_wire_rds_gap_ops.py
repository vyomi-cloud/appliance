"""RDS gap ops over the router with a real boto3 `rds` client: Aurora clusters whose members are real DB instances,
cluster snapshots / parameter groups / endpoints / global clusters, DB snapshot attributes + copy, PITR, subnet-group /
option-group / subscription modification, proxy endpoints + target groups, pending maintenance, catalogs."""
import os
import sys

import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, os.path.dirname(__file__))
from _wire_boto import make_clients  # noqa: E402


def _code(e):
    return e.value.response["Error"]["Code"]


def _rds():
    _, client = make_clients()
    return client("rds")


def _cluster(rds, cid="c1", **kw):
    return rds.create_db_cluster(DBClusterIdentifier=cid, Engine="aurora-postgresql", MasterUsername="admin", MasterUserPassword="Passw0rd!", **kw)["DBCluster"]


def test_cluster_lifecycle_with_real_member_instances():
    rds = _rds()
    c = _cluster(rds)
    assert c["Status"] == "available" and c["Port"] == 5432 and c["DBClusterMembers"] == []
    with pytest.raises(ClientError) as e:
        _cluster(rds)
    assert _code(e) == "DBClusterAlreadyExistsFault"
    w = rds.create_db_instance(DBInstanceIdentifier="w", DBInstanceClass="db.r5.large", Engine="aurora-postgresql", DBClusterIdentifier="c1")["DBInstance"]
    assert w["DBClusterIdentifier"] == "c1"
    rds.create_db_instance(DBInstanceIdentifier="r", DBInstanceClass="db.r5.large", Engine="aurora-postgresql", DBClusterIdentifier="c1")
    mem = {m["DBInstanceIdentifier"]: m["IsClusterWriter"] for m in rds.describe_db_clusters(DBClusterIdentifier="c1")["DBClusters"][0]["DBClusterMembers"]}
    assert mem == {"w": True, "r": False}
    assert set({i["DBInstanceIdentifier"] for i in rds.describe_db_instances(Filters=[{"Name": "db-cluster-id", "Values": ["c1"]}])["DBInstances"]}) == {"w", "r"}
    rds.failover_db_cluster(DBClusterIdentifier="c1", TargetDBInstanceIdentifier="r")
    mem = {m["DBInstanceIdentifier"]: m["IsClusterWriter"] for m in rds.describe_db_clusters(DBClusterIdentifier="c1")["DBClusters"][0]["DBClusterMembers"]}
    assert mem == {"w": False, "r": True}
    with pytest.raises(ClientError) as e:
        rds.delete_db_cluster(DBClusterIdentifier="c1", SkipFinalSnapshot=True)
    assert _code(e) == "InvalidDBClusterStateFault"
    rds.stop_db_cluster(DBClusterIdentifier="c1")
    assert rds.describe_db_instances(DBInstanceIdentifier="w")["DBInstances"][0]["DBInstanceStatus"] == "stopped"
    assert rds.describe_db_clusters(DBClusterIdentifier="c1")["DBClusters"][0]["Status"] == "stopped"
    rds.start_db_cluster(DBClusterIdentifier="c1")
    assert rds.describe_db_instances(DBInstanceIdentifier="w")["DBInstances"][0]["DBInstanceStatus"] == "available"
    rds.modify_db_cluster(DBClusterIdentifier="c1", BackupRetentionPeriod=5, DeletionProtection=True)
    assert rds.describe_db_clusters(DBClusterIdentifier="c1")["DBClusters"][0]["BackupRetentionPeriod"] == 5
    rds.delete_db_instance(DBInstanceIdentifier="w", SkipFinalSnapshot=True)
    with pytest.raises(ClientError) as e:
        rds.delete_db_cluster(DBClusterIdentifier="c1", SkipFinalSnapshot=True)
    assert _code(e) == "InvalidParameterCombination"   # deletion protection
    rds.modify_db_cluster(DBClusterIdentifier="c1", DeletionProtection=False)
    rds.delete_db_instance(DBInstanceIdentifier="r", SkipFinalSnapshot=True)
    rds.delete_db_cluster(DBClusterIdentifier="c1", SkipFinalSnapshot=True)
    assert rds.describe_db_clusters()["DBClusters"] == []


def test_cluster_snapshots_params_endpoints_global():
    rds = _rds()
    _cluster(rds)
    rds.create_db_instance(DBInstanceIdentifier="w", DBInstanceClass="db.r5.large", Engine="aurora-postgresql", DBClusterIdentifier="c1")
    s = rds.create_db_cluster_snapshot(DBClusterSnapshotIdentifier="s1", DBClusterIdentifier="c1")["DBClusterSnapshot"]
    assert s["Status"] == "available" and s["Engine"] == "aurora-postgresql"
    rds.copy_db_cluster_snapshot(SourceDBClusterSnapshotIdentifier="s1", TargetDBClusterSnapshotIdentifier="s2")
    rds.modify_db_cluster_snapshot_attribute(DBClusterSnapshotIdentifier="s1", AttributeName="restore", ValuesToAdd=["123456789012"])
    attrs = rds.describe_db_cluster_snapshot_attributes(DBClusterSnapshotIdentifier="s1")["DBClusterSnapshotAttributesResult"]["DBClusterSnapshotAttributes"]
    assert attrs[0]["AttributeValues"] == ["123456789012"]
    assert len(rds.describe_db_cluster_snapshots(DBClusterIdentifier="c1")["DBClusterSnapshots"]) == 2
    r = rds.restore_db_cluster_from_snapshot(DBClusterIdentifier="c2", SnapshotIdentifier="s1", Engine="aurora-postgresql")["DBCluster"]
    assert r["DBClusterIdentifier"] == "c2" and r["MasterUsername"] == "admin"
    rds.delete_db_cluster_snapshot(DBClusterSnapshotIdentifier="s2")
    with pytest.raises(ClientError) as e:
        rds.describe_db_cluster_snapshots(DBClusterSnapshotIdentifier="s2")
    assert _code(e) == "DBClusterSnapshotNotFoundFault"
    rds.create_db_cluster_parameter_group(DBClusterParameterGroupName="pg", DBParameterGroupFamily="aurora-postgresql16", Description="d")
    rds.modify_db_cluster_parameter_group(DBClusterParameterGroupName="pg", Parameters=[{"ParameterName": "max_connections", "ParameterValue": "250", "ApplyMethod": "immediate"}])
    ps = {p["ParameterName"]: p for p in rds.describe_db_cluster_parameters(DBClusterParameterGroupName="pg", Source="user")["Parameters"]}
    assert ps["max_connections"]["ParameterValue"] == "250"
    rds.reset_db_cluster_parameter_group(DBClusterParameterGroupName="pg", ResetAllParameters=True)
    assert rds.describe_db_cluster_parameters(DBClusterParameterGroupName="pg", Source="user")["Parameters"] == []
    rds.copy_db_cluster_parameter_group(SourceDBClusterParameterGroupIdentifier="pg", TargetDBClusterParameterGroupIdentifier="pg2", TargetDBClusterParameterGroupDescription="x")
    assert len(rds.describe_db_cluster_parameter_groups()["DBClusterParameterGroups"]) == 2
    ep = rds.create_db_cluster_endpoint(DBClusterIdentifier="c1", DBClusterEndpointIdentifier="ro", EndpointType="READER")
    assert ep["CustomEndpointType"] == "READER" and ep["Status"] == "available"
    assert rds.describe_db_cluster_endpoints(DBClusterIdentifier="c1")["DBClusterEndpoints"][0]["DBClusterEndpointIdentifier"] == "ro"
    rds.delete_db_cluster_endpoint(DBClusterEndpointIdentifier="ro")
    g = rds.create_global_cluster(GlobalClusterIdentifier="g", SourceDBClusterIdentifier="c1")["GlobalCluster"]
    assert g["GlobalClusterMembers"][0]["IsWriter"] is True
    with pytest.raises(ClientError) as e:
        rds.delete_global_cluster(GlobalClusterIdentifier="g")
    assert _code(e) == "InvalidGlobalClusterStateFault"
    arn = rds.describe_db_clusters(DBClusterIdentifier="c1")["DBClusters"][0]["DBClusterArn"]
    rds.remove_from_global_cluster(GlobalClusterIdentifier="g", DbClusterIdentifier=arn)
    rds.delete_global_cluster(GlobalClusterIdentifier="g")


def test_instance_level_gap_ops():
    rds = _rds()
    rds.create_db_instance(DBInstanceIdentifier="i", DBInstanceClass="db.t3.micro", Engine="postgres", MasterUsername="a", MasterUserPassword="Passw0rd!", AllocatedStorage=20)
    rds.create_db_snapshot(DBInstanceIdentifier="i", DBSnapshotIdentifier="s")
    rds.copy_db_snapshot(SourceDBSnapshotIdentifier="s", TargetDBSnapshotIdentifier="s-copy")
    rds.modify_db_snapshot_attribute(DBSnapshotIdentifier="s", AttributeName="restore", ValuesToAdd=["all"])
    a = rds.describe_db_snapshot_attributes(DBSnapshotIdentifier="s")["DBSnapshotAttributesResult"]["DBSnapshotAttributes"]
    assert a[0]["AttributeValues"] == ["all"]
    r = rds.restore_db_instance_to_point_in_time(SourceDBInstanceIdentifier="i", TargetDBInstanceIdentifier="i2", UseLatestRestorableTime=True)["DBInstance"]
    assert r["DBInstanceIdentifier"] == "i2"
    rds.create_db_instance_read_replica(DBInstanceIdentifier="rep", SourceDBInstanceIdentifier="i")
    rds.promote_read_replica(DBInstanceIdentifier="rep")
    rds.create_db_instance_read_replica(DBInstanceIdentifier="rep2", SourceDBInstanceIdentifier="i")
    rds.switchover_read_replica(DBInstanceIdentifier="rep2")
    assert rds.describe_db_instances(DBInstanceIdentifier="i")["DBInstances"][0]["ReadReplicaSourceDBInstanceIdentifier"] == "rep2"
    rds.create_db_subnet_group(DBSubnetGroupName="sg", DBSubnetGroupDescription="d", SubnetIds=["subnet-1", "subnet-2"])
    rds.modify_db_subnet_group(DBSubnetGroupName="sg", SubnetIds=["subnet-1", "subnet-2", "subnet-3"])
    assert len(rds.describe_db_subnet_groups(DBSubnetGroupName="sg")["DBSubnetGroups"][0]["Subnets"]) == 3
    rds.create_option_group(OptionGroupName="og", EngineName="mysql", MajorEngineVersion="8.0", OptionGroupDescription="d")
    og = rds.modify_option_group(OptionGroupName="og", OptionsToInclude=[{"OptionName": "MEMCACHED", "Port": 11211}], ApplyImmediately=True)["OptionGroup"]
    assert og["Options"][0]["OptionName"] == "MEMCACHED"
    rds.copy_option_group(SourceOptionGroupIdentifier="og", TargetOptionGroupIdentifier="og2", TargetOptionGroupDescription="d")
    rds.create_db_parameter_group(DBParameterGroupName="pg", DBParameterGroupFamily="postgres16", Description="d")
    rds.modify_db_parameter_group(DBParameterGroupName="pg", Parameters=[{"ParameterName": "max_connections", "ParameterValue": "300", "ApplyMethod": "immediate"}])
    rds.reset_db_parameter_group(DBParameterGroupName="pg", Parameters=[{"ParameterName": "max_connections", "ApplyMethod": "immediate"}])
    assert {p["ParameterName"]: p for p in rds.describe_db_parameters(DBParameterGroupName="pg")["Parameters"]}["max_connections"]["ParameterValue"] == "100"
    rds.copy_db_parameter_group(SourceDBParameterGroupIdentifier="pg", TargetDBParameterGroupIdentifier="pg2", TargetDBParameterGroupDescription="d")
    rds.create_event_subscription(SubscriptionName="es", SnsTopicArn="arn:aws:sns:us-east-1:000000000000:t")
    rds.add_source_identifier_to_subscription(SubscriptionName="es", SourceIdentifier="i")
    es = rds.modify_event_subscription(SubscriptionName="es", Enabled=False)["EventSubscription"]
    assert es["Enabled"] is False
    rds.remove_source_identifier_from_subscription(SubscriptionName="es", SourceIdentifier="i")
    rds.create_db_security_group(DBSecurityGroupName="dsg", DBSecurityGroupDescription="d")
    sg = rds.authorize_db_security_group_ingress(DBSecurityGroupName="dsg", CIDRIP="10.0.0.0/24")["DBSecurityGroup"]
    assert sg["IPRanges"][0]["CIDRIP"] == "10.0.0.0/24"
    rds.revoke_db_security_group_ingress(DBSecurityGroupName="dsg", CIDRIP="10.0.0.0/24")
    assert rds.describe_db_security_groups(DBSecurityGroupName="dsg")["DBSecurityGroups"][0]["IPRanges"] == []


def test_proxy_pending_maintenance_catalogs():
    rds = _rds()
    rds.create_db_proxy(DBProxyName="px", EngineFamily="POSTGRESQL", Auth=[{"AuthScheme": "SECRETS", "SecretArn": "arn:aws:secretsmanager:us-east-1:000000000000:secret:s"}],
                        RoleArn="arn:aws:iam::000000000000:role/r", VpcSubnetIds=["subnet-1", "subnet-2"])
    rds.modify_db_proxy(DBProxyName="px", RequireTLS=True)
    tg = rds.describe_db_proxy_target_groups(DBProxyName="px")["TargetGroups"][0]
    assert tg["TargetGroupName"] == "default"
    rds.modify_db_proxy_target_group(TargetGroupName="default", DBProxyName="px", ConnectionPoolConfig={"MaxConnectionsPercent": 80, "MaxIdleConnectionsPercent": 20})
    assert rds.describe_db_proxy_target_groups(DBProxyName="px")["TargetGroups"][0]["ConnectionPoolConfig"]["MaxConnectionsPercent"] == 80
    with pytest.raises(ClientError) as e:
        rds.modify_db_proxy_target_group(TargetGroupName="default", DBProxyName="px", ConnectionPoolConfig={"MaxConnectionsPercent": 10, "MaxIdleConnectionsPercent": 50})
    assert _code(e) == "InvalidParameterValue"
    rds.create_db_proxy_endpoint(DBProxyName="px", DBProxyEndpointName="ro", VpcSubnetIds=["subnet-1", "subnet-2"], TargetRole="READ_ONLY")
    assert rds.describe_db_proxy_endpoints(DBProxyName="px")["DBProxyEndpoints"][0]["TargetRole"] == "READ_ONLY"
    rds.delete_db_proxy_endpoint(DBProxyEndpointName="ro")
    rds.create_db_instance(DBInstanceIdentifier="old", DBInstanceClass="db.t3.micro", Engine="postgres", MasterUsername="a", MasterUserPassword="Passw0rd!", CACertificateIdentifier="rds-ca-2019")
    pm = rds.describe_pending_maintenance_actions()["PendingMaintenanceActions"]
    assert pm and pm[0]["PendingMaintenanceActionDetails"][0]["Action"] == "ca-certificate-rotation"
    arn = rds.describe_db_instances(DBInstanceIdentifier="old")["DBInstances"][0]["DBInstanceArn"]
    rds.apply_pending_maintenance_action(ResourceIdentifier=arn, ApplyAction="ca-certificate-rotation", OptInType="immediate")
    assert rds.describe_pending_maintenance_actions()["PendingMaintenanceActions"] == []
    assert rds.describe_db_instances(DBInstanceIdentifier="old")["DBInstances"][0]["CACertificateIdentifier"] == "rds-ca-rsa2048-g1"
    opts = rds.describe_orderable_db_instance_options(Engine="postgres")["OrderableDBInstanceOptions"]
    assert any(o["DBInstanceClass"] == "db.m5.large" for o in opts)
    assert rds.describe_event_categories(SourceType="db-instance")["EventCategoriesMapList"][0]["EventCategories"]
    assert rds.describe_reserved_db_instances_offerings(DBInstanceClass="db.t3.micro")["ReservedDBInstancesOfferings"]
    assert rds.describe_engine_default_parameters(DBParameterGroupFamily="postgres16")["EngineDefaults"]["Parameters"]
    v = rds.describe_valid_db_instance_modifications(DBInstanceIdentifier="old")["ValidDBInstanceModificationsMessage"]
    assert v["Storage"][0]["StorageSize"][0]["From"] == 20
    assert rds.describe_source_regions()["SourceRegions"]
