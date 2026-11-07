"""Glue Data Catalog / crawlers / jobs through a real boto3 `glue` client over the router. The crawler test uploads real
objects with a real boto3 `s3` client and asserts the catalog the crawler produced matches what is in the bucket."""
import os
import sys

import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, os.path.dirname(__file__))
from _wire_boto import make_clients  # noqa: E402


@pytest.fixture()
def env():
    router, client = make_clients()
    return router, client("glue"), client("s3")


def code(fn, **kw):
    with pytest.raises(ClientError) as e:
        fn(**kw)
    return e.value.response["Error"]["Code"]


def test_catalog_databases_tables_versions_partitions(env):
    _, g, _ = env
    g.create_database(DatabaseInput={"Name": "Sales", "Description": "d", "Parameters": {"owner": "x"}})
    assert code(g.create_database, DatabaseInput={"Name": "sales"}) == "AlreadyExistsException"
    assert g.get_database(Name="SALES")["Database"]["Description"] == "d"
    g.update_database(Name="sales", DatabaseInput={"Name": "sales", "Description": "d2"})
    assert [d["Name"] for d in g.get_databases()["DatabaseList"]] == ["sales"]

    cols = [{"Name": "id", "Type": "int"}, {"Name": "amount", "Type": "double"}]
    g.create_table(DatabaseName="sales", TableInput={"Name": "orders", "StorageDescriptor": {"Columns": cols, "Location": "s3://b/orders/"},
                                                      "PartitionKeys": [{"Name": "year", "Type": "string"}, {"Name": "month", "Type": "string"}]})
    assert code(g.create_table, DatabaseName="sales", TableInput={"Name": "orders"}) == "AlreadyExistsException"
    assert code(g.create_table, DatabaseName="nope", TableInput={"Name": "t"}) == "EntityNotFoundException"
    g.update_table(DatabaseName="sales", TableInput={"Name": "orders", "StorageDescriptor": {"Columns": cols + [{"Name": "c", "Type": "string"}], "Location": "s3://b/orders/"}})
    t = g.get_table(DatabaseName="sales", Name="orders")["Table"]
    assert len(t["StorageDescriptor"]["Columns"]) == 3 and t["VersionId"] == "1"
    versions = g.get_table_versions(DatabaseName="sales", TableName="orders")["TableVersions"]
    assert [v["VersionId"] for v in versions] == ["1", "0"] and len(versions[1]["Table"]["StorageDescriptor"]["Columns"]) == 2
    assert code(g.delete_table_version, DatabaseName="sales", TableName="orders", VersionId="1") == "InvalidInputException"
    g.delete_table_version(DatabaseName="sales", TableName="orders", VersionId="0")
    g.create_table(DatabaseName="sales", TableInput={"Name": "returns"})
    assert [x["Name"] for x in g.get_tables(DatabaseName="sales", Expression="ord.*")["TableList"]] == ["orders"]

    pv = lambda y, m: {"Values": [y, m], "StorageDescriptor": {"Location": f"s3://b/orders/year={y}/month={m}/", "Columns": cols}}
    g.create_partition(DatabaseName="sales", TableName="orders", PartitionInput=pv("2024", "01"))
    assert code(g.create_partition, DatabaseName="sales", TableName="orders", PartitionInput=pv("2024", "01")) == "AlreadyExistsException"
    assert code(g.create_partition, DatabaseName="sales", TableName="orders", PartitionInput={"Values": ["2024"]}) == "InvalidInputException"
    r = g.batch_create_partition(DatabaseName="sales", TableName="orders", PartitionInputList=[pv("2024", "02"), pv("2024", "01"), pv("2025", "01")])
    assert len(r["Errors"]) == 1 and r["Errors"][0]["ErrorDetail"]["ErrorCode"] == "AlreadyExistsException"
    assert len(g.get_partitions(DatabaseName="sales", TableName="orders")["Partitions"]) == 3
    assert len(g.get_partitions(DatabaseName="sales", TableName="orders", Expression="year = '2024' AND month >= '02'")["Partitions"]) == 1
    assert g.get_partition(DatabaseName="sales", TableName="orders", PartitionValues=["2025", "01"])["Partition"]["Values"] == ["2025", "01"]
    assert g.batch_get_partition(DatabaseName="sales", TableName="orders", PartitionsToGet=[{"Values": ["2024", "01"]}, {"Values": ["9", "9"]}])["UnprocessedKeys"]
    g.delete_partition(DatabaseName="sales", TableName="orders", PartitionValues=["2025", "01"])
    assert code(g.delete_partition, DatabaseName="sales", TableName="orders", PartitionValues=["2025", "01"]) == "EntityNotFoundException"

    arn = "arn:aws:glue:us-east-1:123456789012:database/sales"
    g.tag_resource(ResourceArn=arn, TagsToAdd={"env": "dev"})
    assert g.get_tags(ResourceArn=arn)["Tags"] == {"env": "dev"}
    assert code(g.tag_resource, ResourceArn="arn:aws:glue:us-east-1:123456789012:database/ghost", TagsToAdd={"a": "b"}) == "EntityNotFoundException"
    g.delete_table(DatabaseName="sales", Name="returns")
    g.delete_database(Name="sales")                       # cascades tables + partitions
    assert g.get_databases()["DatabaseList"] == []
    assert code(g.get_table, DatabaseName="sales", Name="orders") == "EntityNotFoundException"


def test_crawler_reads_real_s3_objects(env):
    _, g, s3 = env
    s3.create_bucket(Bucket="lake")
    s3.put_object(Bucket="lake", Key="raw/users/part-0.csv", Body=b"user_id,name,score,active\n1,ann,9.5,true\n2,bob,7.25,false\n3,cy,8.0,true\n")
    for y, n in (("2024", 2), ("2025", 1)):
        s3.put_object(Bucket="lake", Key=f"raw/events/year={y}/e.json", Body=b"\n".join(b'{"id": %d, "kind": "click", "meta": {"ok": true}}' % i for i in range(n)))
    g.create_database(DatabaseInput={"Name": "lakedb"})
    assert code(g.create_crawler, Name="c", Role="arn:aws:iam::123456789012:role/g", DatabaseName="lakedb", Targets={}) == "InvalidInputException"
    g.create_crawler(Name="c1", Role="arn:aws:iam::123456789012:role/g", DatabaseName="lakedb", Targets={"S3Targets": [{"Path": "s3://lake/raw/"}]}, TablePrefix="raw_")
    assert g.get_crawler(Name="c1")["Crawler"]["State"] == "READY"
    g.start_crawler(Name="c1")
    c = g.get_crawler(Name="c1")["Crawler"]
    assert c["LastCrawl"]["Status"] == "SUCCEEDED" and g.get_crawler_metrics(CrawlerNameList=["c1"])["CrawlerMetricsList"][0]["TablesCreated"] == 2

    tables = {t["Name"]: t for t in g.get_tables(DatabaseName="lakedb")["TableList"]}
    assert set(tables) == {"raw_users", "raw_events"}
    users = tables["raw_users"]
    assert users["Parameters"]["classification"] == "csv" and users["Parameters"]["recordCount"] == "3"
    assert [(c_["Name"], c_["Type"]) for c_ in users["StorageDescriptor"]["Columns"]] == [("user_id", "int"), ("name", "string"), ("score", "double"), ("active", "boolean")]
    assert users["StorageDescriptor"]["Location"] == "s3://lake/raw/users"
    ev = tables["raw_events"]
    assert ev["Parameters"]["classification"] == "json" and ev["Parameters"]["recordCount"] == "3"
    assert [p["Name"] for p in ev["PartitionKeys"]] == ["year"]
    assert sorted(p["Values"][0] for p in g.get_partitions(DatabaseName="lakedb", TableName="raw_events")["Partitions"]) == ["2024", "2025"]
    assert {c_["Name"]: c_["Type"] for c_ in ev["StorageDescriptor"]["Columns"]}["meta"] == "struct<ok:boolean>"

    # new data + a new column -> a re-crawl updates the table (version bump), and a partition appears
    s3.put_object(Bucket="lake", Key="raw/users/part-1.csv", Body=b"user_id,name,score,active\n4,di,6.0,true\n")
    s3.put_object(Bucket="lake", Key="raw/events/year=2026/e.json", Body=b'{"id": 1, "kind": "view", "meta": {"ok": true}}')
    g.start_crawler(Name="c1")
    assert g.get_table(DatabaseName="lakedb", Name="raw_users")["Table"]["Parameters"]["recordCount"] == "4"
    assert len(g.get_partitions(DatabaseName="lakedb", TableName="raw_events")["Partitions"]) == 3
    assert g.list_crawlers()["CrawlerNames"] == ["c1"]

    # missing bucket -> failed crawl, recorded
    g.create_crawler(Name="c2", Role="arn:aws:iam::123456789012:role/g", DatabaseName="lakedb", Targets={"S3Targets": [{"Path": "s3://nope/x/"}]})
    g.start_crawler(Name="c2")
    assert g.get_crawler(Name="c2")["Crawler"]["LastCrawl"]["Status"] == "FAILED"
    assert code(g.stop_crawler, Name="c2") == "CrawlerNotRunningException"
    g.delete_crawler(Name="c2")


def test_jobs_runs_triggers_connections(env):
    _, g, s3 = env
    s3.create_bucket(Bucket="scripts")
    s3.put_object(Bucket="scripts", Key="ok.py", Body=b"print('hello')\n")
    s3.put_object(Bucket="scripts", Key="bad.py", Body=b"def (:\n")
    role = "arn:aws:iam::123456789012:role/glue"
    assert code(g.create_job, Name="j", Role=role, Command={"Name": "nope", "ScriptLocation": "s3://scripts/ok.py"}) == "InvalidInputException"
    assert code(g.create_job, Name="j", Role=role, Command={"Name": "glueetl", "ScriptLocation": "s3://scripts/ok.py"}, WorkerType="G.1X") == "InvalidInputException"
    g.create_job(Name="etl", Role=role, Command={"Name": "glueetl", "ScriptLocation": "s3://scripts/ok.py", "PythonVersion": "3"}, WorkerType="G.1X", NumberOfWorkers=2,
                 DefaultArguments={"--k": "v"})
    assert code(g.create_job, Name="etl", Role=role, Command={"Name": "glueetl", "ScriptLocation": "s3://scripts/ok.py"}) == "IdempotentParameterMismatchException"
    assert g.get_job(JobName="etl")["Job"]["GlueVersion"] == "4.0"
    g.update_job(JobName="etl", JobUpdate={"Role": role, "Command": {"Name": "glueetl", "ScriptLocation": "s3://scripts/bad.py"}, "WorkerType": "G.1X", "NumberOfWorkers": 2})
    rid = g.start_job_run(JobName="etl", Arguments={"--x": "1"})["JobRunId"]
    run = g.get_job_run(JobName="etl", RunId=rid)["JobRun"]
    assert run["JobRunState"] == "FAILED" and "SyntaxError" in run["ErrorMessage"] and run["Arguments"] == {"--k": "v", "--x": "1"}
    g.update_job(JobName="etl", JobUpdate={"Role": role, "Command": {"Name": "glueetl", "ScriptLocation": "s3://scripts/missing.py"}, "WorkerType": "G.1X", "NumberOfWorkers": 2})
    rid2 = g.start_job_run(JobName="etl")["JobRunId"]
    assert "ScriptNotFound" in g.get_job_run(JobName="etl", RunId=rid2)["JobRun"]["ErrorMessage"]
    g.update_job(JobName="etl", JobUpdate={"Role": role, "Command": {"Name": "glueetl", "ScriptLocation": "s3://scripts/ok.py"}, "WorkerType": "G.1X", "NumberOfWorkers": 2})
    rid3 = g.start_job_run(JobName="etl")["JobRunId"]
    assert g.get_job_run(JobName="etl", RunId=rid3)["JobRun"]["JobRunState"] == "SUCCEEDED"
    assert len(g.get_job_runs(JobName="etl")["JobRuns"]) == 3
    assert g.list_jobs()["JobNames"] == ["etl"]
    assert code(g.get_job_run, JobName="etl", RunId="jr_nope") == "EntityNotFoundException"

    g.create_connection(ConnectionInput={"Name": "pg", "ConnectionType": "JDBC", "ConnectionProperties": {"JDBC_CONNECTION_URL": "jdbc:postgresql://h/db", "USERNAME": "u", "PASSWORD": "secret"}})
    assert "PASSWORD" not in g.get_connection(Name="pg", HidePassword=True)["Connection"]["ConnectionProperties"]
    assert code(g.create_connection, ConnectionInput={"Name": "pg", "ConnectionType": "JDBC", "ConnectionProperties": {}}) == "AlreadyExistsException"

    assert code(g.create_trigger, Name="t", Type="SCHEDULED", Actions=[{"JobName": "etl"}]) == "InvalidInputException"
    assert code(g.create_trigger, Name="t", Type="ON_DEMAND", Actions=[{"JobName": "ghost"}]) == "EntityNotFoundException"
    g.create_trigger(Name="t", Type="ON_DEMAND", Actions=[{"JobName": "etl"}])
    g.start_trigger(Name="t")
    assert len(g.get_job_runs(JobName="etl")["JobRuns"]) == 4          # an on-demand trigger really starts its job
    assert g.get_trigger(Name="t")["Trigger"]["State"] == "ACTIVATED"
    g.delete_trigger(Name="t")
    g.delete_job(JobName="etl")
    assert g.get_jobs()["Jobs"] == []

    g.put_resource_policy(PolicyInJson='{"Version":"2012-10-17","Statement":[]}')
    assert g.get_resource_policy()["PolicyInJson"].startswith("{")
    assert code(g.put_resource_policy, PolicyInJson="nope") == "MalformedPolicyException"
    g.delete_resource_policy()


def test_zero_etl_operations_still_reach_zeroetl_core(env):
    _, g, _ = env
    # DescribeIntegrations is a zero-ETL op: it must fall through to zeroetl_core, not answer UnknownOperation
    assert g.describe_integrations()["Integrations"] == []
