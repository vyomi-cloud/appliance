#!/usr/bin/env python3
"""Post-create probe (offline): an EC2 instance must be usable over SSH from the
USER'S machine with the connect info the console shows.

  python3 ec2_ssh.py http://localhost:9000

Create -> wait running -> read the shown connect info -> reach the shown host:port ->
fetch the key the way the console says -> ssh in, run a command, write+read a file -> terminate.
Prints one [PASS]/[FAIL] line per check, exits 1 on any failure.
Findings (PLAN.md): CONNECT_INFO_MISSING, CONNECT_INFO_UNREACHABLE, POST_CREATE_UNUSABLE.
Run it on the machine a user would use (not inside the appliance container).
"""
import json, os, re, shlex, socket, subprocess, sys, tempfile, time, urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("VYOMI_ENDPOINT", "http://localhost:9000")).rstrip("/")
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


def main():
    name = f"pc-ssh-{int(time.time())}"
    iid = None
    tmp = tempfile.mkdtemp(prefix="pc-ssh-")
    try:
        inst = call("POST", "/api/ec2/instances", {"name": name, "instance_type": "t3.micro", "image_id": "ami-amzn2023-x86_64"})
        iid = (inst.get("instance") or inst).get("instance_id")
        if not check(bool(iid), "create instance", f"no instance_id in {str(inst)[:200]}"):
            return
        for _ in range(90):
            cur = call("GET", f"/api/ec2/instances/{iid}")
            cur = cur.get("instance") or cur
            if cur.get("state") == "running" and cur.get("launch_status") in (None, "ready", ""):
                break
            time.sleep(2)
        check(cur.get("state") == "running", "instance reaches running", f"state={cur.get('state')} launch={cur.get('launch_status')}")

        ci = call("GET", f"/api/aws/ec2/instances/{iid}/connect-info")
        if not check(bool(ci.get("ok")), "connect-info available (CONNECT_INFO_MISSING)", str(ci)[:200]):
            return
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
            except Exception as e:
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
        if iid:
            try:
                call("DELETE", f"/api/ec2/instances/{iid}")
            except Exception as e:
                print(f"[note] cleanup failed for {iid}: {e}", flush=True)


try:
    main()
except Exception as e:  # noqa: BLE001
    check(False, "probe ran without error", repr(e)[:300])
sys.exit(1 if fails else 0)
