"""Nano IAM hook (WP nano-hook): package imports under Pyodide-like constraints, lazy catalog loader, Python bridge with a fake gate,
vendoring. Run: /Users/sudhirganti/Applications/simulator/portal-run/.venv/bin/python -m pytest -p no:cacheprovider tests/conformance/test_iam_nano_hook.py"""
import ast
import base64
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "core" / "iam_engine"
sys.path.insert(0, str(ROOT))

BLOCKED = ["fastapi", "starlette", "uvicorn", "socket", "_socket", "subprocess", "requests", "httpx", "boto3", "botocore", "aiohttp", "sqlite3", "ssl"]
# Modules engine code may NOT import even lazily inside functions. `os` is allowed ONLY inside filesystem_reader (Mesh adapter, lazy).
FORBIDDEN_NAMES = set(BLOCKED) | {"multiprocessing"}      # threading is importable in Pyodide (audit.py uses a Lock)


def _modules():
    return sorted(p.stem for p in ENGINE.glob("*.py"))


def test_no_forbidden_imports_or_environ_static():
    bad = []
    for p in ENGINE.glob("*.py"):
        tree = ast.parse(p.read_text())
        for n in ast.walk(tree):
            names = []
            if isinstance(n, ast.Import):
                names = [a.name.split(".")[0] for a in n.names]
            elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
                names = [n.module.split(".")[0]]
            bad += [f"{p.name}: import {x}" for x in names if x in FORBIDDEN_NAMES]
            if isinstance(n, ast.Attribute) and n.attr in ("environ", "getenv") and isinstance(n.value, ast.Name) and n.value.id == "os":
                bad.append(f"{p.name}: os.{n.attr}")
    assert not bad, bad


def test_package_imports_with_blocked_modules_and_empty_environ():
    """Fresh interpreter: block the server/socket stack, wipe os.environ, import EVERY module of core.iam_engine; no catalog may load."""
    code = f"""
import sys, os
sys.path.insert(0, {str(ROOT)!r})
for m in {BLOCKED!r}: sys.modules[m] = None          # `import m` raises ImportError, like a Pyodide build without it
os.environ.clear()
import importlib
mods = {_modules()!r}
for m in mods: importlib.import_module("core.iam_engine." + (m if m != "__init__" else "")) if m != "__init__" else importlib.import_module("core.iam_engine")
from core.iam_engine import catalog_loader
assert catalog_loader.loaded() == [], catalog_loader.loaded()      # lazy: importing loads NO catalog
print("OK", len(mods))
"""
    r = subprocess.run([sys.executable, "-I", "-c", code], cwd=ROOT, env={"PYTHONPATH": str(ROOT)}, capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.startswith("OK"), r.stdout + r.stderr


def test_catalog_loader_lazy_reader_and_preload(tmp_path):
    from core.iam_engine import catalog_loader as cl
    cl.reset(); cl.set_reader(None)
    assert cl.loaded() == []
    with pytest.raises(cl.CatalogUnavailable) as e:          # Nano before the JS prefetch
        cl.load("aws", "s3")
    assert e.value.need == ["aws", "s3"]
    cl.preload("aws", "s3", json.dumps({"cloud": "aws", "service": "s3", "actions": []}))
    assert cl.load("aws", "s3")["service"] == "s3" and cl.loaded() == ["aws/s3"]
    cl.reset()
    cl.set_reader(cl.filesystem_reader(str(ROOT / "core" / "iam_catalog")))      # Mesh
    assert cl.load("aws", "s3")["actions"] and cl.load("gcp", "aiplatform")["permissions"] and cl.load("azure", "Microsoft.App")["actions"]
    assert set(cl.loaded()) == {"aws/s3", "gcp/aiplatform", "azure/Microsoft.App"}      # only what was asked for
    for bad in ("../x", "a/b", ".hidden", ""):
        with pytest.raises(ValueError):
            cl.relpath("aws", bad)
    with pytest.raises(ValueError):
        cl.relpath("oci", "s3")
    cl.reset(); cl.set_reader(None)


REF = "origin/v4/iam-enforce-mesh"
OVERLAY_FILES = ("modes.py", "audit.py", "gate.py", "api.py")


@pytest.fixture
def overlay(tmp_path, monkeypatch):
    """modes/audit/gate/api live on the enforce-mesh branch, not here: fetch them from that ref into a temp dir that joins the package path
    (skips when the ref or the files are absent; once merged the real files win because the package dir is searched first)."""
    import core.iam_engine as pkg
    need = [f for f in OVERLAY_FILES if not (ENGINE / f).exists()]
    for f in need:
        r = subprocess.run(["git", "show", f"{REF}:core/iam_engine/{f}"], cwd=ROOT, capture_output=True, text=True)
        if r.returncode:
            pytest.skip(f"{REF} not available: {r.stderr.strip()[:80]}")
        (tmp_path / f).write_text(r.stdout)
    monkeypatch.setattr(pkg, "__path__", list(pkg.__path__) + [str(tmp_path)])
    for m in ("modes", "audit", "gate", "api", "nano_bridge"):
        monkeypatch.delitem(sys.modules, f"core.iam_engine.{m}", raising=False)
    return pkg


class FakeHost:
    """Stands in for the JS host: per-cloud settings cache + shared audit ring."""

    def __init__(self, docs=None):
        self.docs, self.ring = docs or {}, []

    def get_settings(self, c): return json.dumps(self.docs[c]) if c in self.docs else None
    def put_settings(self, c, j): self.docs[c] = json.loads(j)
    def audit_push(self, j): self.ring.insert(0, json.loads(j))
    def audit_list(self, c): return json.dumps([r for r in self.ring if not c or r["cloud"] == c])
    def audit_clear(self): self.ring.clear()


class FakeMap:
    @staticmethod
    def required(hr):
        if hr["method"] == "GET":
            return [{"action": "s3:GetObject", "resource": "arn:aws:s3:::b/k", "service": "s3"}]
        return [{"action": "s3:PutObject", "resource": "arn:aws:s3:::b/k", "service": "s3"}]


class FakeEngine:
    @staticmethod
    def evaluate(req, state):
        from core.iam_engine.types import decision
        ok = req["action"] in state.get("allow", ())
        return decision(ok, "allow" if ok else "implicit_deny")


REQ = {"cloud": "aws", "method": "GET", "path": "/b/k", "query": {}, "headers": {"host": "s3.amazonaws.com"}, "body_b64": ""}
DOC = {"services": {"s3": "enforce"}}


@pytest.fixture
def bridge(overlay, monkeypatch):
    from core.iam_engine import nano_bridge as nb, catalog_loader as cl, gate
    cl.reset(); cl.set_reader(None)
    host = FakeHost({"aws": DOC})
    monkeypatch.setattr(nb, "_apis", {}); monkeypatch.setattr(nb, "_have", set()); monkeypatch.setattr(nb, "_audit_log", None)
    nb.configure(host, json.dumps({"aws": ["s3"]}))
    monkeypatch.setitem(sys.modules, "core.iam_engine.map_aws", FakeMap)
    monkeypatch.setitem(sys.modules, "core.iam_engine.aws_eval", FakeEngine)
    nb.set_state_override(lambda cloud, h, q: ({"allow": ("s3:GetObject",)}, {"arn": "arn:aws:iam::1:user/ro", "type": "user"}))
    yield nb, host, cl
    nb.set_state_override(None); cl.reset()


def test_bridge_check_need_then_allow_then_deny_and_audit(bridge):
    nb, host, cl = bridge
    S = json.dumps(DOC)
    assert json.loads(nb.check(json.dumps(REQ), S)) == {"need": [["aws", "s3"]]}       # first use of s3: prefetch asked, nothing loaded at boot
    nb.preload("aws", "s3", "{}")
    assert json.loads(nb.check(json.dumps(REQ), S)) == {"ok": True}
    put = dict(REQ, method="PUT", headers={"host": "s3.amazonaws.com"})
    d = json.loads(nb.check(json.dumps(put), S))["deny"]
    body = base64.b64decode(d["body_b64"]).decode()
    assert d["status"] == 403 and "<Code>AccessDenied</Code>" in body and "s3:PutObject" in body and d["headers"]["content-type"] == "application/xml"
    assert [r["decision"] for r in host.ring] == ["deny", "allow"] and host.ring[0]["principal"] == "arn:aws:iam::1:user/ro"      # shared ring, newest first
    host.docs["aws"] = {"services": {"s3": "audit"}}
    assert json.loads(nb.check(json.dumps(put), json.dumps(host.docs["aws"]))) == {"ok": True}
    assert host.ring[0]["decision"] == "would_deny"


def test_bridge_does_not_gate_when_off_and_reports_errors(bridge, monkeypatch):
    nb, host, cl = bridge
    nb.preload("aws", "s3", "{}")
    assert json.loads(nb.check(json.dumps(REQ), json.dumps({"services": {"s3": "off"}}))) == {"ok": True} and host.ring == []
    import core.iam_engine as pkg
    monkeypatch.delattr(pkg, "gate", raising=False)
    monkeypatch.setitem(sys.modules, "core.iam_engine.gate", None)
    assert "gate unavailable" in json.loads(nb.check(json.dumps(REQ), "{}"))["error"]


def test_bridge_api_routes_same_as_mesh(bridge):
    nb, host, cl = bridge
    call = lambda m, p, q=None, b=None: json.loads(nb.api(m, p, json.dumps(q or {}), json.dumps(b)))
    r = call("GET", "/api/iam/aws/enforcement")
    assert r["status"] == 200 and r["body"]["services"] == {"s3": "enforce"} and r["body"]["global"] == "off"
    r = call("PUT", "/api/iam/aws/enforcement", None, {"space": "audit", "services": {"s3": "enforce"}})
    assert r["status"] == 200 and host.docs["aws"]["space"] == "audit"                       # persisted through the JS host
    assert call("PUT", "/api/iam/aws/enforcement", None, {"space": "bogus"})["status"] == 400
    nb.check(json.dumps(REQ), json.dumps(host.docs["aws"]))
    assert call("GET", "/api/iam/aws/audit", {"limit": "5"})["body"]["records"] == host.ring[:5]
    assert call("DELETE", "/api/iam/aws/audit")["body"] == {"cleared": True} and host.ring == []
    assert json.loads(nb.api("GET", "/api/iam/aws/catalog/s3", "{}", "null")).get("need") == [["aws", "s3"]]     # catalog route also lazy
    nb.preload("aws", "s3", json.dumps({"cloud": "aws", "service": "s3", "actions": {}}))
    assert json.loads(nb.api("GET", "/api/iam/aws/catalog/s3", "{}", "null")).get("need") == [["_inventory", "service-inventory"]]
    nb.preload_inventory("null")                       # bundle without service-inventory.json: simulated is unknown, not an error
    r = call("GET", "/api/iam/aws/catalog/s3")
    assert r["status"] == 200 and r["body"]["vyomi"] == {"simulated": None, "inventory": False}
    nb.preload_inventory(json.dumps({"services": [{"cloud": "aws", "id": "s3"}]}))
    assert call("GET", "/api/iam/aws/catalog/s3")["body"]["vyomi"]["simulated"] is True
    assert call("GET", "/api/iam/oci/enforcement")["status"] == 404
    r = call("POST", "/api/iam/aws/evaluate", None, {"principal": {"arn": "x"}, "action": "s3:GetObject", "resource": "arn:aws:s3:::b/k"})
    assert r["status"] == 200 and r["body"]["allowed"] is True


def test_oserror_on_missing_catalog_file_becomes_need(bridge, monkeypatch):
    nb, host, cl = bridge
    class M:
        @staticmethod
        def required(hr):
            raise FileNotFoundError(2, "No such file", "/core/iam_catalog/aws/s3.json")
    monkeypatch.setitem(sys.modules, "core.iam_engine.map_aws", M)
    assert json.loads(nb.check(json.dumps(REQ), json.dumps(DOC))) == {"need": [["aws", "s3"]]}


def test_vendored_copy_is_current():
    r = subprocess.run([sys.executable, "wasm/build_cores.py", "--check"], cwd=ROOT, capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(ROOT)})
    assert r.returncode == 0 and "vendored engine + catalogs are current" in r.stdout, r.stdout + r.stderr
    man = json.loads((ROOT / "wasm/core/iam_engine/manifest.json").read_text())
    assert "catalog_loader.py" in man["engine"] and "nano_bridge.py" in man["engine"] and "s3" in man["catalogs"]["aws"]


def test_not_fetched_at_boot():
    """The boot loaders list neither the engine nor any catalog (lazy only)."""
    for f in ("wasm/nano-boot.js", "wasm/relay/relay-shared-worker.js", "wasm/relay/nano-endpoint.html"):
        t = (ROOT / f).read_text()
        assert "iam_catalog" not in t and '"iam_engine/' not in t, f
