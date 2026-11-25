"""Import/export console backend: infrastructure graph, availability classifier, real-cloud export mode, portability report."""
from core.tf_export import hcl
from core.tf_export.core import Ctx, render_files
from core.tf_export.graph import build_graph, classify, portability


def _stack() -> Ctx:
    c = Ctx({}, "us-east-1")
    vpc = c.add("aws_vpc", "vpc-1", "main", {"cidr_block": "10.0.0.0/16", "tags": {"Name": "main"}}, file="network.tf")
    c.add("aws_subnet", "sub-1", "a", {"vpc_id": hcl.Ref(f"{vpc}.id"), "cidr_block": "10.0.1.0/24"}, file="network.tf")
    c.add("aws_s3_bucket", "b", "assets", {"bucket": "assets-001"}, file="storage.tf")
    c.add("aws_iam_role_policy_attachment", "att", "fn",
          {"role": "fn", "policy_arn": "arn:aws:iam::123456789012:policy/p"}, file="iam.tf")
    c.add("aws_db_instance", "db", "db", {"identifier": "db", "password": c.variable("db_password_db", "x", "pw")}, file="database.tf")
    return c


def test_classifier_distinguishes_supported_planned_and_not_possible():
    v = classify(["aws_vpc", "aws_cloudfront_distribution", "aws_kinesis_stream"])
    assert v["aws_vpc"]["status"] == "supported"
    assert v["aws_cloudfront_distribution"]["status"] == "not_possible" and v["aws_cloudfront_distribution"]["reason"]
    assert v["aws_kinesis_stream"]["status"] == "planned"


def test_graph_nests_subnet_in_vpc_group_and_has_no_containment_edge():
    g = build_graph(_stack())
    sub = next(n for n in g["nodes"] if n["type"] == "aws_subnet")
    assert sub["group"] == "group.main" and any(x["kind"] == "vpc" for x in g["groups"])
    assert not any(e["from"] == "aws_subnet.a" and e["to"] == "aws_vpc.main" for e in g["edges"])
    assert all(n["status"] == "supported" for n in g["nodes"])


def test_real_cloud_mode_replaces_account_id_and_region():
    sim = render_files(_stack())
    real = render_files(_stack(), real_cloud=True)
    assert "123456789012" in sim["iam.tf"]
    assert "123456789012" not in "".join(real.values())
    assert "${data.aws_caller_identity.current.account_id}" in real["iam.tf"]
    assert 'data "aws_caller_identity" "current"' in real["data.tf"] and 'data "aws_region" "current"' in real["data.tf"]


def test_portability_report_flags_account_id_unique_names_cost_and_secrets():
    c = _stack()
    codes = {p["code"] for p in portability(c, render_files(c), real_cloud=False)}
    assert {"account-id", "unique-name", "cost", "secret", "defaults"} <= codes
    c2 = _stack()
    real_codes = {p["code"] for p in portability(c2, render_files(c2, real_cloud=True), real_cloud=True)}
    assert "account-id" not in real_codes


def test_graph_handles_untagged_vpc():
    c = Ctx({}, "us-east-1")
    c.add("aws_vpc", "v", "vpc_10_0_0_0_16", {"cidr_block": "10.0.0.0/16", "tags": None}, file="network.tf")
    g = build_graph(c)
    assert g["groups"][0]["label"] == "vpc_10_0_0_0_16"


def test_real_cloud_mode_replaces_account_id_inside_jsonencode_policies():
    c = Ctx({}, "us-east-1")
    c.add("aws_iam_policy", "p", "p", {"name": "p", "policy": hcl.jsonencode({"Statement": [{"Principal": {"AWS": "arn:aws:iam::123456789012:root"}}]})}, file="iam.tf")
    sim, real = render_files(c)["iam.tf"], render_files(c, real_cloud=True)["iam.tf"]
    assert "123456789012" in sim
    assert "123456789012" not in real and "${data.aws_caller_identity.current.account_id}" in real
