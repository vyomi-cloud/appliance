"""Trivy runner with a stubbed docker CLI (hermetic): archive export, report parsing, preference over the bundled engine, honest unavailability.
Run: PYTHONPATH=. <venv python> tests/conformance/test_trivy_runner.py"""
import hashlib
import io
import json
import tarfile
import time
from types import SimpleNamespace

from core import azure_acr_core as acr
from core import vuln_scan_core as vs
from providers import trivy_runner as tr

n = 0


def check(c, m):
    global n
    assert c, m
    n += 1


cfg = json.dumps({"history": [{"created_by": "pip install requests==2.19.0"}]}).encode()
layer = b"layer-bytes"
cd, ld = "sha256:" + hashlib.sha256(cfg).hexdigest(), "sha256:" + hashlib.sha256(layer).hexdigest()
man = {"schemaVersion": 2, "config": {"digest": cd}, "layers": [{"digest": ld}]}
blobs = {cd: cfg, ld: layer}
arc = tr.build_docker_archive("web:v1", man, blobs.get)
with tarfile.open(fileobj=io.BytesIO(arc)) as tf:
    names = tf.getnames()
    m = json.loads(tf.extractfile("manifest.json").read())
check({"manifest.json", "config.json", "layer0.tar"} <= set(names) and m[0]["RepoTags"] == ["web:v1"], "docker-archive layout")
check(tr.build_docker_archive("x", man, {cd: cfg}.get) is None, "missing layer -> no archive (never a partial scan)")

REPORT = {"Metadata": {"TrivyVersion": "0.58.1"}, "Results": [{"Type": "pip", "Vulnerabilities": [{"VulnerabilityID": "CVE-2018-18074", "PkgName": "requests", "InstalledVersion": "2.19.0", "FixedVersion": "2.20.0", "Severity": "HIGH", "CVSS": {"nvd": {"V3Score": 7.5}}, "Title": "auth header leak"}]}]}
calls = []


def fake_docker(args, *, input_bytes=None, timeout=60):
    calls.append(args[0])
    if args[0] == "cp" and args[1].endswith("report.json"):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            data = json.dumps(REPORT).encode(); ti = tarfile.TarInfo("report.json"); ti.size = len(data); tf.addfile(ti, io.BytesIO(data))
        return SimpleNamespace(returncode=0, stdout=buf.getvalue(), stderr=b"")
    if args[0] == "create":
        check("--network" in args and args[args.index("--network") + 1] == "none", "scan container has no network")
    return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")


tr._docker = fake_docker
rep, why = tr.scan_archive(arc)
check(rep == REPORT and calls[-1] == "rm", "scan_archive returns the report and always removes the container")
parsed = vs.parse_trivy_report(rep)
check(parsed["trivyVersion"] == "0.58.1" and parsed["findings"][0]["ecosystem"] == "pypi" and parsed["findings"][0]["cvss"] == 7.5, "parsed")

# store walk: request_scan -> background -> cached_reports; engine switches to trivy for that digest
store = acr.AcrRegistryStore()
repo = acr._get_or_create_repo(store, "web")
repo["blobs"].update(blobs)
dg = acr._push_manifest(store, "web", "v1", json.dumps(man).encode(), "application/vnd.docker.distribution.manifest.v2+json")
tr.preflight = lambda: None
tr.request_scan(store)
for _ in range(50):
    if dg in tr.cached_reports():
        break
    time.sleep(0.05)
check(dg in tr.cached_reports() and tr.status()["state"] == "ok", "background scan finished")
imgs = vs.scan_acr_store(store, tr.cached_reports())
check(imgs[0]["scan"]["engine"] == "trivy", "Trivy report takes over from the bundled engine")
check(vs.scan_acr_store(store)[0]["scan"]["engine"] == "vyomi-advisory", "without a report the bundled engine is used (and says so)")

# unavailable -> honest status, no crash
tr._REPORTS.clear(); tr._PRE.update(at=0.0, reason="")
tr.preflight = lambda: "The Trivy image aquasec/trivy:0.58.1 is not present locally"
tr.request_scan(store)
check(tr.status()["state"] == "unavailable" and "not present" in tr.status()["reason"], "unavailable is reported with its reason")
print(f"OK {n} checks")
