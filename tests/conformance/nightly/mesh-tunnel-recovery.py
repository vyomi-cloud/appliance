#!/usr/bin/env python3
"""Mesh tunnel conformance + auto-recovery (check 6) against a LIVE Mesh Codespace, using lib/tunnel_recovery.run_recovery.

Needs: `vyomi-tunnel` logged in with a Mesh key, a running Mesh (ssh host.vyomi works). Starts its OWN `vyomi-tunnel forward` on 19100 so it never touches another
test's forward. Faults (select with --faults): transport (kill the gh/ssh transport processes under the forward), restart (docker restart of the appliance
in the Codespace). Never prints the session token. Marker = an EC2 key pair created through the link.
  python3 mesh-tunnel-recovery.py [--faults transport,restart] [--deadline 120]
"""
import argparse, os, signal, subprocess, sys, time, urllib.parse, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))
from tunnel_recovery import run_recovery  # noqa: E402

PORT = 19100
BASE = f"http://127.0.0.1:{PORT}"
AUTH = "AWS4-HMAC-SHA256 Credential=test/20261111/us-east-1/ec2/aws4_request, SignedHeaders=host, Signature=x"


def ssh(cmd, timeout=60):
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=25", "host.vyomi", cmd], capture_output=True, text=True, timeout=timeout)


def token():
    r = ssh('docker exec vyomi-mesh-simulator-1 sh -c "printf %s \\"\\$VYOMI_MESH_SESSION_TOKEN\\""')
    return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""


def children(pid):
    out = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True).stdout.split()
    res = []
    for c in out:
        res.append(int(c)); res += children(int(c))
    return res


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--faults", default="transport,restart"); ap.add_argument("--deadline", type=float, default=120)
    a = ap.parse_args()
    tok = token()
    if not tok:
        print("FAIL: could not read the Mesh session token (is Mesh up?)"); return 2
    fwd = subprocess.Popen(["vyomi-tunnel", "forward", "vyomi-mesh-simulator-1", f"{PORT}:9000"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def get(path):
        req = urllib.request.Request(BASE + path, headers={"X-Vyomi-Session-Token": tok})
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status, r.read().decode("utf-8", "replace")

    def post(form):
        req = urllib.request.Request(BASE + "/", data=urllib.parse.urlencode(form).encode(), method="POST",
                                     headers={"X-Vyomi-Session-Token": tok, "Authorization": AUTH, "Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode("utf-8", "replace")

    def link_ok():
        try:
            s, b = get("/healthz"); return s == 200 and '"status":"ok"' in b.replace(" ", "")
        except Exception:
            return False

    marker_name = f"rec-marker-{int(time.time())}"

    def write_marker():
        s, _ = post({"Action": "CreateKeyPair", "KeyName": marker_name, "Version": "2016-11-15"}); assert s == 200, s
        return marker_name

    def marker_ok(name):
        try:
            s, b = post({"Action": "DescribeKeyPairs", "Version": "2016-11-15"}); return s == 200 and name in b
        except Exception:
            return False

    def fault_transport():
        # the forward has no child processes (it dials in itself), so drop the SSH sessions from the SERVER side: kill every vscode sshd-session on the
        # Codespace host (the command's own session dies too; that is expected and ignored). The forward must redial with no user action.
        ssh("pkill -f 'sshd-session: vscode' ; true", timeout=40)

    def fault_restart():
        r = ssh("docker restart vyomi-mesh-simulator-1", timeout=120)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip()[-200:])

    allf = {"transport": ("drop the transport (kill the SSH sessions on the Codespace host)", fault_transport), "restart": ("restart the appliance container", fault_restart)}
    faults = {allf[k][0]: allf[k][1] for k in a.faults.split(",") if k in allf}
    try:
        for _ in range(30):             # the forward needs a few seconds to dial in
            if link_ok(): break
            time.sleep(2)
        fails = run_recovery(link_ok, write_marker, marker_ok, faults, deadline=a.deadline)
    finally:
        try: post({"Action": "DeleteKeyPair", "KeyName": marker_name, "Version": "2016-11-15"})
        except Exception: pass
        fwd.terminate()
    print(f"{len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
