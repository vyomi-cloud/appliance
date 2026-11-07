"""Booster shell (core/booster_shell.py + server.py resolver). Script-style: prints [PASS]/[FAIL], exit 1 on any failure.
   PYTHONPATH=. python tests/conformance/test_booster_shell.py
The full tab->relay->link->PTY chain is wasm/relay/test-booster-shell.mjs; this covers the appliance side against the real app."""
import os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
os.environ.update(VYOMI_ROLE="booster", VYOMI_BOOSTER_SESSION_KEY="shell-test-key",
                  VYOMI_DOCKER_BIN=os.path.join(ROOT, "wasm/relay/test-fixtures/fake-docker.sh"), VYOMI_SHELL_NETWORK="vyomi-net")
os.environ.pop("VYOMI_BOOSTER_SESSION_TOKEN", None)
bad = 0
def check(n, ok, d=""):
    global bad
    bad += 0 if ok else 1
    print(f"[{'PASS' if ok else 'FAIL'}] {n}" + (f" - {d}" if d and not ok else ""))

import server
from core import booster_session as bs, booster_shell as sh
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

recs = {
    ("aws", "i-1"): {"instance_id": "i-1", "container_name": "vyomi-i-i-1", "console_backend": "docker-exec"},
    ("aws", "i-lxd"): {"instance_id": "i-lxd", "container_name": "cloudlearn-i-lxd", "console_backend": "lxd-exec"},
    ("gcp", "vm1"): {"name": "vm1", "container_name": "vyomi-i-gcp1", "console_backend": "docker-exec"},
    ("azure", "vm-az1"): {"name": "vm-az1", "properties": {"runtime": {"backend": "docker", "containerName": "vyomi-i-az1"}}},
    ("azure", "vm-lxd"): {"name": "vm-lxd", "properties": {"runtime": {"backend": "lxd", "containerName": "cloudlearn-x"}}},
}
orig = server._find_instance_across_spaces
server._find_instance_across_spaces = lambda cloud, ref: (recs.get((cloud, ref)), None)
try:
    check("resolver: aws docker instance -> its container", server._shell_container("aws", "i-1") == "vyomi-i-i-1")
    check("resolver: gcp docker instance -> its container", server._shell_container("gcp", "vm1") == "vyomi-i-gcp1")
    check("resolver: azure docker VM -> its container (adminUsername/ssh keys are NOT consulted)", server._shell_container("azure", "vm-az1") == "vyomi-i-az1")
    check("resolver: non-docker (LXD) aws instance is not shell-able here", server._shell_container("aws", "i-lxd") is None)
    check("resolver: non-docker azure VM is not shell-able here", server._shell_container("azure", "vm-lxd") is None)
    check("resolver: unknown instance -> None", server._shell_container("aws", "i-none") is None)

    now = time.time()
    tok = bs.mint("acct", "pro", now + 600, session_id="s1", key="shell-test-key")
    H = {"x-vyomi-session-token": tok}
    c = TestClient(server.app)
    r = c.get("/booster/shell/target?cloud=gcp&ref=vm1", headers=H)
    check("GET /booster/shell/target with a valid token: ok + container", r.status_code == 200 and r.json().get("ok") and r.json()["container"] == "vyomi-i-gcp1", r.text[:200])
    r = c.get("/booster/shell/target?cloud=aws&ref=i-none", headers=H)
    check("target: unknown instance -> ok:false InstanceNotFound", r.status_code == 200 and r.json().get("code") == "InstanceNotFound", r.text[:200])
    r = c.get("/booster/shell/target?cloud=gcp&ref=vm1")
    check("target: no session token -> refused by the booster session middleware", r.status_code in (401, 403), r.status_code)
    r = c.get("/booster/shell/target?cloud=gcp&ref=vm1", headers={"x-vyomi-session-token": bs.mint("a", "pro", now + 600, session_id="s", key="wrong")})
    check("target: bad-signature token -> refused", r.status_code in (401, 403), r.status_code)
    try:
        with c.websocket_connect("/booster/shell?cloud=gcp&ref=vm1") as w:
            w.receive_text()
        refused = False
    except WebSocketDisconnect:
        refused = True
    check("websocket /booster/shell without a token is refused", refused)
    with c.websocket_connect("/booster/shell?cloud=gcp&ref=vm1&cols=100&rows=30", headers=H) as w:
        first = w.receive_json()
        banner = b""
        for _ in range(20):
            m = w.receive()
            if m.get("bytes"):
                banner += m["bytes"]
                if b"FAKE-VM:vyomi-i-gcp1" in banner:
                    break
        w.send_bytes(b"echo ok-$((6*7))\n")
        out = b""
        for _ in range(40):
            m = w.receive()
            if m.get("bytes"):
                out += m["bytes"]
                if b"ok-42" in out:
                    break
        w.send_text('{"t":"close"}')
    check("real app: token-authed websocket opens a PTY in the resolved container and echoes", first.get("t") == "opened" and b"FAKE-VM:vyomi-i-gcp1" in banner and b"ok-42" in out, f"{first} {banner[:80]!r}")
    check("clamp_size bounds resize values", sh.clamp_size(99999, 0) == (sh.MAX_COLS, 3) and sh.clamp_size("x", None) == (100, 30))
    check("container name regex rejects traversal / shell metacharacters / foreign names",
          all(not sh.NAME_RE.match(n) for n in ["nginx", "vyomi-i-", "vyomi-i-a b", "vyomi-i-a;rm", "vyomi-i-../x", "/vyomi-i-x", "vyomi-i-x\n"]) and bool(sh.NAME_RE.match("vyomi-i-i-0abc")))
    # not-a-booster appliance: the endpoint is off
    os.environ["VYOMI_ROLE"] = ""
    check("outside the booster role the endpoint reports ShellNotAvailable", sh.allowed() is False)
finally:
    server._find_instance_across_spaces = orig
print(f"\n{'' if not bad else str(bad) + ' FAILED'}")
sys.exit(1 if bad else 0)
