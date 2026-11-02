#!/usr/bin/env python3
"""Post-create probe (offline): a VM (EC2 / Compute Engine / Azure VM) must be usable over SSH
from the USER'S machine with the connect info the console/API shows.

  python3 vm_ssh.py aws|gcp|azure http://localhost:9000

Create -> wait running -> read the shown connect info -> reach the shown host:port ->
fetch the key the way the console says -> ssh in, run a command, write+read a file ->
delete -> the instance's Docker container must be gone (no leak).
Prints one [PASS]/[FAIL] line per check, exits 1 on any failure.
Findings (PLAN.md): CONNECT_INFO_MISSING, CONNECT_INFO_UNREACHABLE, POST_CREATE_UNUSABLE.
Run it on the machine a user would use (not inside the appliance container).
"""
import json, os, re, shlex, shutil, socket, subprocess, sys, tempfile, time, urllib.error, urllib.request

CLOUD = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in ("aws", "gcp", "azure") else "aws"
BASE = (sys.argv[-1] if len(sys.argv) > 1 and sys.argv[-1].startswith("http") else os.environ.get("VYOMI_ENDPOINT", "http://localhost:9000")).rstrip("/")
fails = 0


def check(ok, name, why=""):
    global fails
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f" :: {why}"), flush=True)
    fails += 0 if ok else 1
    return ok


def call(method, path, body=None, raw=False):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
        return data if raw else (json.loads(data) if data else {})


def provision(name):
    """Create the VM via the same API the console/SDK uses. Returns (ref, wait(), connect_path, delete())."""
    if CLOUD == "aws":
        inst = call("POST", "/api/ec2/instances", {"name": name, "instance_type": "t3.micro", "image_id": "ami-amzn2023-x86_64"})
        iid = (inst.get("instance") or inst).get("instance_id")

        def wait():
            cur = {}
            for _ in range(90):
                cur = call("GET", f"/api/ec2/instances/{iid}"); cur = cur.get("instance") or cur
                if cur.get("state") == "running" and cur.get("launch_status") in (None, "ready", ""):
                    return True, ""
                time.sleep(2)
            return False, f"state={cur.get('state')} launch={cur.get('launch_status')}"
        return iid, wait, f"/api/aws/ec2/instances/{iid}/connect-info", lambda: call("DELETE", f"/api/ec2/instances/{iid}")
    if CLOUD == "gcp":
        proj = call("GET", "/v1/projects")["projects"][0]["projectId"]
        base = f"/compute/v1/projects/{proj}/zones/us-central1-a/instances"
        call("POST", base, {"name": name, "machineType": "zones/us-central1-a/machineTypes/e2-micro"})

        def wait():
            cur = {}
            for _ in range(90):
                cur = call("GET", f"{base}/{name}")
                if cur.get("status") == "RUNNING":
                    return True, ""
                time.sleep(2)
            return False, f"status={cur.get('status')}"
        return name, wait, f"/api/gcp/compute/instances/{name}/connect-info", lambda: call("DELETE", f"{base}/{name}")
    sub = call("GET", "/subscriptions?api-version=2020-01-01")["value"][0]["subscriptionId"]
    rg = f"/subscriptions/{sub}/resourceGroups/{name}-rg"
    call("PUT", rg + "?api-version=2021-04-01", {"location": "eastus"})
    vm = f"{rg}/providers/Microsoft.Compute/virtualMachines/{name}?api-version=2023-09-01"
    call("PUT", vm, {"location": "eastus", "properties": {"hardwareProfile": {"vmSize": "Standard_B1s"},
        "storageProfile": {"imageReference": {"publisher": "Canonical", "offer": "ubuntu-24_04-lts", "sku": "server", "version": "latest"}},
        "osProfile": {"computerName": name, "adminUsername": "azureuser"}}})

    def wait():
        for _ in range(60):   # connect-info answers 409 until the VM runs
            try:
                call("GET", f"/api/azure/vm/{name}/connect-info"); return True, ""
            except urllib.error.HTTPError as e:
                last = f"HTTP {e.code}"
            time.sleep(2)
        return False, last

    def delete():
        call("DELETE", vm); call("DELETE", f"{rg}?api-version=2021-04-01")
    return name, wait, f"/api/azure/vm/{name}/connect-info", delete


def main():
    name = f"pc{int(time.time()) % 100000}-{CLOUD}"
    ref = delete = container = None
    tmp = tempfile.mkdtemp(prefix="pc-ssh-")
    try:
        ref, wait, ci_path, delete = provision(name)
        if not check(bool(ref), f"[{CLOUD}] create VM", "no id"):
            return
        ok, why = wait()
        check(ok, f"[{CLOUD}] VM reaches running", why)
        try:
            ci = call("GET", ci_path)
        except urllib.error.HTTPError as e:
            ci = {"ok": False, "http": e.code, "body": e.read()[:200].decode(errors="replace")}
        if not check(bool(ci.get("ok")), "connect-info available (CONNECT_INFO_MISSING)", str(ci)[:200]):
            return
        container = ci.get("container_name")
        ssh = ci.get("ssh") or {}
        cmd = ssh.get("command") or ""
        host, port = ssh.get("host"), int(ssh.get("port") or 22)
        check(bool(cmd and host), "console shows an ssh command (CONNECT_INFO_MISSING)", f"ssh={ssh}")

        # The shown host:port must be reachable from THIS machine.
        try:
            socket.create_connection((host, port), timeout=6).close(); reach = True; why = ""
        except OSError as e:
            reach, why = False, f"{host}:{port} -> {e} (shown command: {cmd})"
        if not check(reach, "shown host:port reachable from the user's machine (CONNECT_INFO_UNREACHABLE)", why):
            return

        # The key must be obtainable the way the console says.
        m = re.search(r"-i\s+(\S+)", cmd)
        shown_key = os.path.expanduser(m.group(1)) if m else ""
        keyfile = os.path.join(tmp, "key.pem")
        fetch = ssh.get("key_fetch_command")
        if shown_key and os.path.exists(shown_key):
            key_ok = True; keyfile = shown_key
        else:
            try:
                open(keyfile, "wb").write(call("GET", ssh.get("key_download_url", ""), raw=True)); os.chmod(keyfile, 0o600)
                key_ok = os.path.getsize(keyfile) > 100 and bool(fetch or ssh.get("key_download_url"))
            except Exception:
                key_ok = False
        check(key_ok and (os.path.exists(shown_key) or bool(fetch)),
              "key obtainable from what the console shows (CONNECT_INFO_MISSING)",
              f"-i {shown_key!r} not on this machine and no key_fetch_command; download_url={ssh.get('key_download_url')!r}")
        if shown_key and fetch:
            check(shown_key.startswith(("~", "/")) and "/root/" not in shown_key, "shown -i path is not an appliance-internal path",
                  f"{shown_key}")

        argv = shlex.split(cmd)
        if "-i" in argv:
            argv[argv.index("-i") + 1] = keyfile
        argv += ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "echo POSTCREATE-OK; whoami; echo vyomi > /tmp/pc.txt; cat /tmp/pc.txt"]
        r = subprocess.run(argv, capture_output=True, text=True, timeout=40)
        out = r.stdout
        check(r.returncode == 0 and "POSTCREATE-OK" in out, "ssh with the shown command runs a command (POST_CREATE_UNUSABLE)",
              f"rc={r.returncode} {r.stderr.strip()[-200:]}")
        check("vyomi" in out.split("POSTCREATE-OK", 1)[-1], "file write + read back on the instance", out[-120:])
    finally:
        if delete:
            try:
                delete()
            except Exception as e:
                print(f"[note] cleanup failed for {ref}: {e}", flush=True)
            if container and shutil.which("docker"):
                time.sleep(4)
                left = subprocess.run(["docker", "ps", "-a", "--filter", f"name=^{container}$", "--format", "{{.Names}}"],
                                      capture_output=True, text=True).stdout.strip()
                check(not left, "delete removes the instance's container (no leak)", f"{left} still exists")
                if left:
                    subprocess.run(["docker", "rm", "-f", left], capture_output=True)


try:
    main()
except Exception as e:  # noqa: BLE001
    check(False, "probe ran without error", repr(e)[:300])
sys.exit(1 if fails else 0)
