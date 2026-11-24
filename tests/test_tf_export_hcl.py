"""Faithful Terraform exporter: HCL writer, references, id interpolation, deterministic output."""
from core.tf_export import hcl
from core.tf_export.core import Ctx, render_files


def test_refs_render_unquoted_and_strings_escape_templates():
    assert hcl.value(hcl.Ref("aws_vpc.main.id")) == "aws_vpc.main.id"
    assert hcl.value("a${b}") == '"a$${b}"'


def test_nested_blocks_two_levels():
    out = hcl.block("resource", ["aws_x", "y"], {"a": 1}, [("rule", {}, [("inner", {"k": "v"})])])
    assert "rule {" in out and "inner {" in out and 'k = "v"' in out


def test_jsonencode_is_key_sorted_so_exports_are_stable():
    a = hcl.jsonencode({"Version": "1", "Statement": []}).expr
    b = hcl.jsonencode({"Statement": [], "Version": "1"}).expr
    assert a == b and a.startswith("jsonencode(")


def test_known_ids_inside_strings_become_interpolations():
    ctx = Ctx({}, "us-east-1")
    addr = ctx.add("aws_api_gateway_rest_api", "abc1234567", "api", {"name": "api"})
    ctx.interp["abc1234567"] = f"{addr}.id"
    ctx.add("aws_lambda_permission", "p", "perm", {"source_arn": "arn:aws:execute-api:us-east-1:1:abc1234567/*/*"})
    text = render_files(ctx)["main.tf"]
    assert '"arn:aws:execute-api:us-east-1:1:${aws_api_gateway_rest_api.api.id}/*/*"' in text


def test_output_is_sorted_and_stable_regardless_of_discovery_order():
    def build(order):
        c = Ctx({}, "us-east-1")
        for n in order:
            c.add("aws_subnet", n, n, {"cidr_block": n, "subnet_ids": [hcl.Ref("b.x"), hcl.Ref("a.x")]})
        return render_files(c)["main.tf"]
    assert build(["10.0.2.0", "10.0.1.0"]) == build(["10.0.1.0", "10.0.2.0"])


def test_secret_values_go_to_tfvars_not_main():
    c = Ctx({}, "us-east-1")
    ref = c.variable("secret_db", "s3cret", "db secret")
    c.add("aws_secretsmanager_secret_version", "x", "db", {"secret_string": ref}, file="secrets.tf")
    files = render_files(c)
    assert "s3cret" not in files["secrets.tf"] and "var.secret_db" in files["secrets.tf"]
    assert "s3cret" in files["terraform.tfvars"] and 'variable "secret_db"' in files["variables.tf"]
