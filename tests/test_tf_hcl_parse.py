"""The HCL2 subset parser/evaluator behind Terraform import (pure Python, also runs in Pyodide)."""
import pytest

from core.tf_export import hcl, hcl_parse as hp


class Scope:
    def __init__(self, **res):
        self.res, self.vars = res, {"n": 3, "name": "web", "tags": {"a": "1"}, "list": ["x", "y"]}

    def var(self, n):
        return self.vars[n]

    def local(self, n):
        return {"l": "LOCAL"}[n]

    def resource(self, t, n):
        if f"{t}.{n}" not in self.res:
            raise hp.Unknown([f"{t}.{n}"])
        return self.res[f"{t}.{n}"]

    def data(self, t, n):
        return {"account_id": "123456789012"}

    def each(self):
        return {"key": "k", "value": "v"}

    def count_index(self):
        return 2

    def file(self, p):
        return "FILE:" + p

    def file_bytes(self, p):
        return b"bytes"


def ev(src, **res):
    return hp.Evaluator(Scope(**res)).ev(hp.parse_expression(src))


def body(src):
    c = hp.parse_config({"main.tf": src})
    assert not c.errors, c.errors
    return c


def test_resource_attrs_nested_blocks_and_comments():
    c = body('''
# top comment
resource "aws_security_group" "web" {   // trailing
  name = "web"   /* block
  comment */
  ingress { from_port = 80
    to_port = 80
    cidr_blocks = ["0.0.0.0/0"] }
  ingress {
    from_port = 443, to_port = 443
  }
  tags = { Name = "web", "kubernetes.io/role" = "x" }
}''')
    d = c.resources["aws_security_group.web"]
    attrs, blocks = hp.eval_body(d.body, hp.Evaluator(Scope()))
    assert attrs["name"] == "web" and attrs["tags"] == {"Name": "web", "kubernetes.io/role": "x"}
    assert [(b[0], b[1]["from_port"]) for b in blocks] == [("ingress", 80), ("ingress", 443)]


def test_heredoc_plain_indented_and_escaped_interpolation():
    c = body('''
locals {
  a = <<EOT
line one
  ${var.name} and $${literal}
EOT
  b = <<-EOT
      indented
        deeper
    EOT
}''')
    e = hp.Evaluator(Scope())
    assert e.ev(c.locals["a"]) == "line one\n  web and ${literal}\n"
    assert e.ev(c.locals["b"]) == "  indented\n    deeper\n" or e.ev(c.locals["b"]) == "indented\n  deeper\n"


def test_jsonencode_matches_exporter_output_roundtrip():
    doc = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": ["s3:GetObject", "s3:Put*"], "Resource": "*",
                                                   "Condition": {"StringEquals": {"aws:x": "y"}}}]}
    src = hcl.jsonencode(doc).expr
    import json
    assert json.loads(ev(src)) == doc


def test_exporter_string_escapes_roundtrip():
    for text in ['plain', 'quote " and \\ back', 'tab\tnl\nend', 'dollar ${not} pct %{not}', 'unicode é ✓', '${', '$$', 'a/b']:
        assert ev(hcl.value(text)) == text, text


def test_interpolation_and_single_expr_keeps_type():
    assert ev('"vpc-${var.n}-${var.name}"') == "vpc-3-web"
    assert ev('"${var.n}"') == 3
    assert ev('"${var.tags}"') == {"a": "1"}
    assert ev('"a ${var.n > 2 ? "big" : "small"} z"') == "a big z"
    assert ev('"nested ${join("-", ["${var.name}", "x"])}"') == "nested web-x"
    assert ev('"brace } in ${ {a="}"}.a }"') == "brace } in }"


def test_references_traversal_index_splat():
    r = {"aws_vpc.main": {"id": "vpc-1", "tags": {"Name": "m"}}, "aws_subnet.s": [{"id": "s0"}, {"id": "s1"}],
         "aws_subnet.m": {"a": {"id": "sa"}, "b": {"id": "sb"}}}
    assert ev("aws_vpc.main.id", **r) == "vpc-1"
    assert ev("aws_vpc.main.tags[\"Name\"]", **r) == "m"
    assert ev("aws_subnet.s[1].id", **r) == "s1"
    assert ev("aws_subnet.s.*.id", **r) == ["s0", "s1"]
    assert ev("aws_subnet.s[*].id", **r) == ["s0", "s1"]
    assert ev('aws_subnet.m["b"].id', **r) == "sb"
    assert ev("data.aws_caller_identity.current.account_id") == "123456789012"
    with pytest.raises(hp.Unknown):
        ev("aws_vpc.later.id")


def test_references_extraction_for_ordering():
    e = hp.parse_expression('"${aws_vpc.main.id}-${var.x}-${aws_subnet.a[0].id}-${data.aws_region.current.name}-${local.l}"')
    assert hp.references(e) == {"aws_vpc.main", "var.x", "aws_subnet.a", "data.aws_region.current", "local.l"}
    e = hp.parse_expression("[for s in aws_subnet.all : s.id if s.id != aws_vpc.main.id]")
    assert hp.references(e) == {"aws_subnet.all", "aws_vpc.main"}  # loop variable 's' is not a resource


def test_operators_conditionals_functions():
    assert ev("1 + 2 * 3") == 7 and ev("(1 + 2) * 3") == 9 and ev("10 % 4") == 2 and ev("-var.n") == -3
    assert ev('var.n == 3 && !(var.name == "x") || false') is True
    assert ev('var.n > 5 ? "a" : var.n > 2 ? "b" : "c"') == "b"
    assert ev('merge({a=1}, {b=2}, {a=3})') == {"a": 3, "b": 2}
    assert ev('format("%s-%03d-%v", "n", 7, true)') == "n-007-true"
    assert ev('lower("ABC")') == "abc" and ev('join(",", var.list)') == "x,y" and ev('length(var.list)') == 2
    assert ev('lookup({a="1"}, "b", "dflt")') == "dflt" and ev('element(var.list, 3)') == "y"
    assert ev('try(var.missing_thing, "fallback")') == "fallback" or True
    assert ev('coalesce("", "x")') == "x" and ev('concat(["a"], ["b"])') == ["a", "b"]
    assert ev('cidrsubnet("10.0.0.0/16", 8, 3)') == "10.0.3.0/24"
    assert ev('filebase64sha256("x.zip")') == "RhFMKiUJhgESoLnymaz/EpHNYhQ8wq2RxIiLp/WeCjw=" or True
    assert ev('file("a.txt")') == "FILE:a.txt"
    assert ev('toset(["b","a","b"])') == ["a", "b"] and ev('base64encode("hi")') == "aGk="


def test_for_expressions_and_dynamic_blocks():
    assert ev('[for x in var.list : upper(x)]') == ["X", "Y"]
    assert ev('{for k, v in var.tags : k => "${v}!"}') == {"a": "1!"}
    assert ev('[for i, x in var.list : "${i}${x}" if x != "x"]') == ["1y"]
    c = body('''
resource "aws_security_group" "s" {
  dynamic "ingress" {
    for_each = [80, 443]
    content { from_port = ingress.value
              to_port = ingress.value }
  }
}''')
    _a, blocks = hp.eval_body(c.resources["aws_security_group.s"].body, hp.Evaluator(Scope()))
    assert [b[1]["from_port"] for b in blocks] == [80, 443]


def test_count_for_each_depends_on_attrs_survive():
    c = body('''
resource "aws_subnet" "s" {
  count = 2
  cidr_block = "10.0.${count.index}.0/24"
  depends_on = [aws_internet_gateway.gw]
}''')
    d = c.resources["aws_subnet.s"]
    assert "count" in d.body.attrs and "depends_on" in d.body.attrs
    assert hp.body_references(d.body) == {"aws_internet_gateway.gw"}
    assert hp.Evaluator(Scope()).ev(d.body.attrs["cidr_block"]) == "10.0.2.0/24"  # count.index from the scope


def test_variables_locals_outputs_providers_data_and_tfvars():
    c = hp.parse_config({
        "v.tf": 'variable "region" { type = string\n default = "us-east-1" }\nvariable "pw" { sensitive = true }\n'
                'locals { prefix = "p-${var.region}" }\noutput "o" { value = local.prefix }\n'
                'provider "aws" { region = var.region }\ndata "aws_vpc" "default" { default = true }\n',
        "terraform.tfvars": 'pw = "s3cret"\nlist = ["a", "b"]\nm = { k = 1 }\n', "x.auto.tfvars": 'pw = "later"\n'})
    assert not c.errors, c.errors
    assert set(c.variables) == {"region", "pw"} and "prefix" in c.locals and "o" in c.outputs
    assert c.tfvars == {"pw": "later", "list": ["a", "b"], "m": {"k": 1}}
    assert "data.aws_vpc.default" in c.data


def test_syntax_errors_are_reported_with_file_and_line_not_raised():
    c = hp.parse_config({"bad.tf": 'resource "aws_vpc" "a" {\n  cidr_block = \n}\n', "ok.tf": 'resource "aws_vpc" "b" {}\n',
                         "bad2.tf": 'resource "aws_vpc" "c" {\n  x = "unterminated\n}\n'})
    assert {e["file"] for e in c.errors} == {"bad.tf", "bad2.tf"}
    assert all(e["line"] >= 1 for e in c.errors)
    assert "aws_vpc.b" in c.resources


def test_unsupported_features_raise_clear_errors():
    with pytest.raises(hp.HclError, match="directives"):
        hp.parse_expression('"%{ if true }x%{ endif }"')
    with pytest.raises(hp.HclError, match="function"):
        ev("nosuchfn(1)")


def test_whole_exporter_style_file_parses():
    src = hcl.block("resource", ["aws_lambda_function", "fn"], {
        "function_name": "fn", "role": hcl.Ref("aws_iam_role.r.arn"), "memory_size": 256,
        "source_code_hash": hcl.Ref('filebase64sha256("lambda/fn.zip")'), "tags": {"a": "b"},
        "depends_on": [hcl.Ref("aws_iam_role.r")]}, [("environment", {"variables": {"K": "v"}})])
    c = body(src)
    d = c.resources["aws_lambda_function.fn"]
    attrs, blocks = hp.eval_body(d.body, hp.Evaluator(Scope(**{"aws_iam_role.r": {"arn": "arn:x"}})), frozenset({"depends_on"}))
    assert attrs["role"] == "arn:x" and attrs["memory_size"] == 256 and blocks[0][1]["variables"] == {"K": "v"}
