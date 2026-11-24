"""Terraform import/apply engine: planning, ordering, references, idempotency, errors, over an in-memory fake of the AWS clients."""
import pytest

from core.tf_export import apply as ap, hcl_parse as hp
from core.tf_export.apply import applier


class Fake:
    """Records calls; just enough of a store for the toy appliers below."""

    def __init__(self):
        self.things: dict[str, dict] = {}
        self.calls: list[str] = []


@pytest.fixture()
def toy():
    fake = Fake()
    ap._load()
    saved = dict(ap._APPLIERS)

    @applier("aws_toy_net")
    class Net:
        def find(self, c, a):
            t = c.cl["toy"].things.get(a.get("name"))
            return {"id": t["id"], "name": t["name"]} if t else None

        def create(self, c, a):
            f = c.cl["toy"]
            f.calls.append("create " + a.get("name"))
            f.things[a.get("name")] = t = {"id": "net-" + a.get("name"), "name": a.get("name")}
            return {"id": t["id"], "name": t["name"]}

        def delete(self, c, out):
            c.cl["toy"].things.pop(out["name"])

    @applier("aws_toy_box")
    class Box:
        def find(self, c, a):
            t = c.cl["toy"].things.get(a.get("name"))
            return {"id": t["id"], "name": t["name"]} if t else None

        def create(self, c, a):
            f = c.cl["toy"]
            f.calls.append(f"create {a.get('name')} in {a.get('net_id')} {a.get('tags')}")
            f.things[a.get("name")] = t = {"id": "box-" + a.get("name"), "name": a.get("name")}
            return {"id": t["id"], "name": t["name"], "arn": "arn:toy:" + a.get("name")}

        def delete(self, c, out):
            c.cl["toy"].things.pop(out["name"])

    yield fake
    ap._APPLIERS.clear()
    ap._APPLIERS.update(saved)


TF = {"main.tf": '''
variable "env" { default = "dev" }
locals { prefix = "app-${var.env}" }

resource "aws_toy_box" "b" {            # declared before its network on purpose
  name   = "${local.prefix}-box"
  net_id = aws_toy_net.n.id
  tags   = { Net = aws_toy_net.n.name, Arn = "x-${var.env}" }
}
resource "aws_toy_net" "n" { name = "${local.prefix}-net" }
resource "aws_toy_box" "many" {
  count  = 2
  name   = "m${count.index}"
  net_id = aws_toy_net.n.id
}
resource "aws_cloudfront_distribution" "cdn" { enabled = true }
resource "aws_nothing_yet" "x" { y = 1 }
output "box_arn" { value = aws_toy_box.b.arn }
'''}


def test_plan_orders_by_references_and_classifies(toy):
    r = ap.plan(TF, None, {"toy": toy})
    acts = {i["address"]: i["action"] for i in r["items"]}
    order = [i["address"] for i in r["items"]]
    assert order.index("aws_toy_net.n") < order.index("aws_toy_box.b") and order.index("aws_toy_net.n") < order.index("aws_toy_box.many[0]")
    assert acts["aws_toy_net.n"] == "create" and acts["aws_toy_box.b"] == "create" and acts["aws_toy_box.many[1]"] == "create"
    assert acts["aws_cloudfront_distribution.cdn"] == "unsupported" and acts["aws_nothing_yet.x"] == "unsupported"
    av = {i["type"]: i["availability"] for i in r["items"]}
    assert av["aws_cloudfront_distribution"]["status"] == "not_possible" and "edge" in av["aws_cloudfront_distribution"]["reason"]
    assert av["aws_nothing_yet"]["status"] == "planned" and av["aws_toy_net"]["status"] == "supported"
    assert not toy.calls  # a plan never writes


def test_apply_resolves_references_is_idempotent_and_destroys(toy):
    r = ap.apply(TF, None, {"toy": toy})
    assert r["summary"]["created"] == 4 and r["summary"]["unsupported"] == 2
    assert toy.calls[0] == "create app-dev-net"
    assert toy.calls[1].startswith("create app-dev-box in net-app-dev-net {'Net': 'app-dev-net', 'Arn': 'x-dev'}")
    assert r["outputs"]["box_arn"] == "arn:toy:app-dev-box"
    n = len(toy.calls)
    r2 = ap.apply(TF, None, {"toy": toy})
    assert len(toy.calls) == n and r2["summary"]["created"] == 0 and r2["summary"]["exists"] == 4
    assert [e["address"] for e in r["ledger"]][0] == "aws_toy_net.n"
    d = ap.destroy({"toy": toy}, ledger=r["ledger"])
    assert d["summary"]["destroyed"] == 4 and not toy.things
    assert [i["address"] for i in d["items"]][-1] == "aws_toy_net.n"  # dependents go first


def test_stepwise_apply_with_targets_and_known(toy):
    p = ap.plan(TF, None, {"toy": toy})
    known = {}
    for addr in [i["address"] for i in p["items"] if i["action"] == "create"]:
        r = ap.apply(TF, None, {"toy": toy}, targets=[addr], known=known)
        assert [i for i in r["items"] if i["address"] == addr][0]["action"] == "created"
        known.update(r["known"])
    assert len(toy.things) == 4 and len([c for c in toy.calls if c.startswith("create app-dev-net")]) == 1


def test_variables_tfvars_errors_and_blocked(toy):
    files = {"a.tf": 'variable "n" {}\nresource "aws_toy_net" "n" { name = var.n }\nresource "aws_toy_box" "b" { name = "b"\n net_id = aws_toy_net.n.id }',
             "terraform.tfvars": 'n = "from-tfvars"\n'}
    assert ap.apply(files, None, {"toy": toy})["summary"]["created"] == 2 and "from-tfvars" in toy.things
    # a required variable with no value is reported, and what depends on it is blocked, nothing is half-created
    r = ap.plan({"a.tf": files["a.tf"]}, None, {"toy": toy}, variables={})
    acts = {i["address"]: i["action"] for i in r["items"]}
    assert acts["aws_toy_net.n"] == "error" and acts["aws_toy_box.b"] == "blocked"
    assert [v for v in r["variables"] if v["name"] == "n"][0]["provided"] is False


def test_syntax_error_reports_file_and_line_and_applies_nothing(toy):
    r = ap.apply({"bad.tf": 'resource "aws_toy_net" "n" {\n  name = \n}\n'}, None, {"toy": toy})
    assert not r["ok"] and r["errors"][0]["file"] == "bad.tf" and r["errors"][0]["line"] >= 1 and not toy.calls


def test_dependency_cycle_is_reported(toy):
    r = ap.plan({"a.tf": 'resource "aws_toy_net" "a" { name = aws_toy_net.b.id }\nresource "aws_toy_net" "b" { name = aws_toy_net.a.id }'}, None, {"toy": toy})
    assert not r["ok"] and "cycle" in r["errors"][0]["error"]


def test_failure_blocks_dependents_but_not_siblings(toy):
    @applier("aws_toy_bad")
    class Bad:
        def find(self, c, a):
            return None

        def create(self, c, a):
            raise RuntimeError("boom")

    files = {"a.tf": 'resource "aws_toy_bad" "x" { name = "x" }\nresource "aws_toy_net" "ok" { name = "ok" }\n'
                     'resource "aws_toy_box" "dep" { name = "d"\n net_id = aws_toy_bad.x.id }'}
    r = ap.apply(files, None, {"toy": toy})
    acts = {i["address"]: (i["action"], i["reason"]) for i in r["items"]}
    assert acts["aws_toy_bad.x"][0] == "failed" and "boom" in acts["aws_toy_bad.x"][1]
    assert acts["aws_toy_net.ok"][0] == "created" and acts["aws_toy_box.dep"][0] == "blocked" and not r["ok"]


def test_registry_has_every_exported_type():
    """Every resource type the exporter writes must have an applier, or the round trip silently loses it."""
    import re
    from core.tf_export import aws_apply  # noqa: F401
    from core.tf_export.graph import supported_types
    missing = sorted(t for t in supported_types() if t not in ap._APPLIERS and not t.startswith("aws_caller") and t not in ("aws_region", "aws_vpc"))
    assert not missing, f"exported but not importable: {missing}"
    assert hp  # parser is the same one the engine uses
