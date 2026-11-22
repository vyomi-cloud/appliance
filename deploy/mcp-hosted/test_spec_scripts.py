#!/usr/bin/env python3
"""Checks for the two spec helpers (run: python3 deploy/mcp-hosted/test_spec_scripts.py).

The thing worth proving is the dangerous part: adding or bumping the hosted MCP component must never change
anything else in the portal's App Platform spec.
"""
import copy
import os
import pathlib
import subprocess
import sys
import tempfile

import yaml

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
COMPONENT = HERE / "portal-app-component.yaml"

# A portal spec shaped like the real one: a source-built service, a static site, and a catch-all ingress rule.
PORTAL = {
    "name": "vyomi-portal",
    "region": "blr",
    "services": [{
        "name": "portal",
        "github": {"repo": "vyomi-cloud/portal", "branch": "main", "deploy_on_push": True},
        "run_command": "gunicorn app.main:app",
        "instance_size_slug": "basic-xs",
        "instance_count": 1,
        "http_port": 8080,
        "envs": [{"key": "SECRET_KEY", "scope": "RUN_TIME", "type": "SECRET", "value": "EV[1:nope]"}],
    }],
    "static_sites": [{"name": "docs", "github": {"repo": "vyomi-cloud/portal", "branch": "main"}}],
    "ingress": {"rules": [{"match": {"path": {"prefix": "/"}}, "component": {"name": "portal"}}]},
}

fails = []


def check(ok, what, detail=""):
    print(("PASS  " if ok else "FAIL  ") + what + (f"\n      {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(what)


TOKEN = "bot-user:ghp_TESTONLY0000000000000000000000000000"


def run(script, *args, creds=TOKEN):
    """Run a helper; by default with GHCR_PULL_CREDENTIALS set, as the runbook does (the package is private)."""
    env = {k: v for k, v in os.environ.items() if k != "GHCR_PULL_CREDENTIALS"}
    if creds is not None:
        env["GHCR_PULL_CREDENTIALS"] = creds
    r = subprocess.run([sys.executable, str(HERE / script), *map(str, args)], capture_output=True, text=True, env=env)
    return r.returncode, r.stdout + r.stderr


def mcp_image(spec):
    return [x for x in spec["services"] if x["name"] == "mcp"][0]["image"]


def write(spec):
    fh = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
    yaml.safe_dump(spec, fh, sort_keys=False)
    fh.close()
    return pathlib.Path(fh.name)


def load(path):
    return yaml.safe_load(pathlib.Path(path).read_text())


def strip_mcp(spec):
    s = copy.deepcopy(spec)
    s["services"] = [x for x in s.get("services", []) if x.get("name") != "mcp"]
    rules = s.get("ingress", {}).get("rules")
    if rules is not None:
        s["ingress"]["rules"] = [r for r in rules if r.get("component", {}).get("name") != "mcp"]
    return s


# ── the component spec itself ────────────────────────────────────────────────
piece = load(COMPONENT)
svc = piece["services"][0]
check(svc["name"] == "mcp", "the component is named mcp", svc["name"])
check(svc["image"] == {"registry_type": "GHCR", "registry": "vyomi-cloud", "repository": "mcp-hosted",
                       "tag": svc["image"].get("tag")}, "the image is a pinned GHCR image", str(svc["image"]))
check(isinstance(svc["image"].get("tag"), str) and svc["image"]["tag"] not in ("", "latest"),
      "the image tag is pinned, never latest", str(svc["image"].get("tag")))
check("registry_credentials" not in svc["image"] and "username" not in svc["image"],
      "no registry credentials are committed: add-component.py adds them from GHCR_PULL_CREDENTIALS")
check(svc["instance_size_slug"] == "basic-xxs" and svc["instance_count"] == 1, "basic-xxs, one instance")
check(svc["http_port"] == 8080, "http_port 8080", str(svc.get("http_port")))
check(svc["health_check"]["http_path"] == "/healthz", "health check on /healthz")
rule = piece["ingress"]["rules"][0]
check(rule["match"]["path"]["prefix"] == "/mcp" and rule["component"]["name"] == "mcp",
      "the ingress rule sends /mcp to the component")
check("preserve_path_prefix" not in rule["component"],
      "preserve_path_prefix is absent, so App Platform trims /mcp (D-I6)")

# ── add-component.py ─────────────────────────────────────────────────────────
p = write(PORTAL)
rc, out = run("add-component.py", p)
check(rc == 0 and "check only" in out, "a check-only run exits 0 and says so", out)
check(load(p) == PORTAL, "a check-only run writes nothing")
check("portal" in out, "it reports the components it leaves alone", out)

rc, out = run("add-component.py", p, "--apply", creds=None)
check(rc != 0 and "private" in out and "GHCR_PULL_CREDENTIALS" in out,
      "without credentials it refuses (the package is private) and says what to set", out)
check(load(p) == PORTAL, "the refused run wrote nothing")

rc, out = run("add-component.py", p, "--apply")
after = load(p)
check(rc == 0, "--apply exits 0", out)
check(mcp_image(after).get("registry_credentials") == TOKEN, "--apply adds the pull credentials from the env")
check("ghp_" not in out and TOKEN not in out, "the token is never printed", out)
check((os.stat(p).st_mode & 0o777) == 0o600, "a file holding the token is written mode 600", oct(os.stat(p).st_mode))
check(strip_mcp(after) == PORTAL, "everything but the mcp component is byte-identical")
check([s["name"] for s in after["services"]] == ["portal", "mcp"], "the mcp service was appended")
rules = after["ingress"]["rules"]
check([r["component"]["name"] for r in rules] == ["mcp", "portal"],
      "the /mcp rule goes BEFORE the portal's catch-all", str(rules))

rc, out = run("add-component.py", p, "--apply")
check(rc == 0 and "nothing to do" in out, "re-running is a no-op", out)
check(load(p) == after, "a no-op run leaves the file alone")

rc, out = run("add-component.py", p, "--apply", "--tag", "9.9.9")
pinned = load(p)
check(rc == 0 and [s for s in pinned["services"] if s["name"] == "mcp"][0]["image"]["tag"] == "9.9.9",
      "--tag pins a version", out)
check(strip_mcp(pinned) == PORTAL, "--tag changes nothing outside the component")

# An existing spec whose catch-all is not last still gets a working order.
odd = copy.deepcopy(PORTAL)
odd["ingress"]["rules"] = [
    {"match": {"path": {"prefix": "/api"}}, "component": {"name": "portal"}},
    {"match": {"path": {"prefix": "/"}}, "component": {"name": "portal"}},
]
p2 = write(odd)
run("add-component.py", p2, "--apply")
prefixes = [r["match"]["path"]["prefix"] for r in load(p2)["ingress"]["rules"]]
check(prefixes == ["/api", "/mcp", "/"], "it inserts before the catch-all, keeping the other rules in order", str(prefixes))

# What App Platform returns after the first apply: the credentials encrypted.
enc = copy.deepcopy(load(p))
mcp_image(enc)["registry_credentials"] = "EV[1:encrypted]"
p4 = write(enc)
rc, out = run("add-component.py", p4, "--apply", "--tag", "9.9.9", creds=None)
check(rc == 0 and "nothing to do" in out, "without the env, encrypted credentials are kept and the re-run is a no-op", out)
check(mcp_image(load(p4))["registry_credentials"] == "EV[1:encrypted]", "the EV[...] value is kept as it is")
rc, out = run("add-component.py", p4, "--apply", "--tag", "9.9.9", creds="bot-user:ghp_ROTATED")
check(rc == 0 and mcp_image(load(p4))["registry_credentials"] == "bot-user:ghp_ROTATED",
      "setting the env again rotates the token", out)
check(strip_mcp(load(p4)) == PORTAL, "rotating the token changes nothing outside the component")
rc, out = run("add-component.py", write(PORTAL), "--apply", creds="no-colon-here")
check(rc != 0 and "<github-user>:<token>" in out, "a malformed credential is refused", out)
p5 = write(PORTAL)
rc, out = run("add-component.py", p5, "--apply", "--public", creds=None)
check(rc == 0 and "registry_credentials" not in mcp_image(load(p5)), "--public adds no credentials", out)

# ── set-image-tag.py ─────────────────────────────────────────────────────────
rc, out = run("set-image-tag.py", p4, "0.3.0", creds=None)
check(rc == 0 and mcp_image(load(p4))["registry_credentials"] == "bot-user:ghp_ROTATED",
      "set-image-tag.py keeps the pull credentials", out)
rc, out = run("set-image-tag.py", p, "0.2.0")
bumped = load(p)
check(rc == 0, "set-image-tag.py exits 0 on a spec that has the component", out)
check([s for s in bumped["services"] if s["name"] == "mcp"][0]["image"]["tag"] == "0.2.0", "it sets the tag")
check(strip_mcp(bumped) == PORTAL, "it changes nothing else")
other = [s for s in bumped["services"] if s["name"] == "portal"][0]
check(other["envs"][0]["value"] == "EV[1:nope]", "the portal's encrypted env values survive a round trip")

p3 = write(PORTAL)
rc, out = run("set-image-tag.py", p3, "0.2.0")
check(rc != 0 and "add it first" in out, "it refuses a spec with no mcp component, and says what to do", out)
check(load(p3) == PORTAL, "the refused run wrote nothing")

rc, out = run("set-image-tag.py", p)
check(rc != 0 and "usage" in out, "it refuses the wrong number of arguments", out)

# ── the Dockerfile and the workflow agree with all of this ───────────────────
docker = (HERE / "Dockerfile").read_text()
check("gcr.io/distroless/static" in docker, "the runtime image is distroless")
check("nonroot" in docker, "it runs as a non-root user")
check("CGO_ENABLED=0" in docker and "-trimpath" in docker, "a static, trimmed build")
check('ENTRYPOINT ["/vyomi", "mcp", "--hosted"]' in docker, "the entrypoint is the hosted server")
check("EXPOSE 8080" in docker, "it exposes 8080")

wf = (ROOT / ".github/workflows/mcp-hosted-release.yml").read_text()
check("tags: ['mcp-hosted-v*']" in wf, "the workflow triggers on mcp-hosted-v* tags only")
check("branches" not in wf.split("on:")[1].split("permissions:")[0], "it never triggers on a branch push")
check("packages: write" in wf, "it asks for packages: write")
check("registry: ghcr.io" in wf and "ghcr.io/${{ github.repository_owner }}/mcp-hosted" in wf,
      "it pushes to ghcr.io/<org>/mcp-hosted")
check("DOCKERHUB" not in wf, "no Docker Hub secrets are referenced")
check("platforms: linux/amd64" in wf and "arm64" not in wf, "linux/amd64 only")
check("set-image-tag.py" in wf, "it bumps the tag with set-image-tag.py, not by hand")
check("mcp-hosted-smoke.sh https://vyomi.cloud/mcp" in wf, "it smokes production after deploying")
check(not any("mcp-hosted:latest" in l or l.strip().startswith("tags:") and "latest" in l
              for l in wf.splitlines()), "it never pushes a floating tag")

print()
if fails:
    print(f"{len(fails)} check(s) failed")
    sys.exit(1)
print("all deploy spec checks passed")
