"""boot-mesh.sh selfcheck: runs the checks in the simulator container, adds the host DNS check, posts ONE valid JSON report to the portal.
docker / getent are shimmed (no Docker or Codespace needed); the portal is a local HTTP server that records what it receives."""
import json
import os
import stat
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
MESH = os.path.join(HERE, "..", "..", "codespace", ".devcontainer", "mesh")

CONTAINER_OK = json.dumps({"ok": True, "checked_at": 1, "items": [
    {"id": "dns", "label": "DNS resolution", "ok": True, "detail": "resolved", "hint": ""},
    {"id": "appliance", "label": "Appliance healthy", "ok": True, "detail": "v4", "hint": ""}]})


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"[PASS] {name}")


def _run(container_out, getent_ok=True, portal_status=200):
    got = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            got.append((self.path, json.loads(self.rfile.read(int(self.headers["content-length"])))))
            self.send_response(portal_status); self.end_headers(); self.wfile.write(b"{}")
        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    with tempfile.TemporaryDirectory() as d:
        def shim(name, body):
            p = os.path.join(d, name)
            open(p, "w").write("#!/bin/sh\n" + body + "\n"); os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)
        shim("docker", f"cat >/dev/null\nprintf '%s\\n' '{container_out}'" if container_out else "cat >/dev/null; exit 1")
        shim("getent", "exit 0" if getent_ok else "exit 2")
        shim("sleep", "exit 0")
        env = dict(os.environ, PATH=d + os.pathsep + os.environ["PATH"], VYOMI_LICENSE_BACKEND_URL=f"http://127.0.0.1:{srv.server_port}",
                   CODESPACE_NAME="cs-test", HOME=d)
        r = subprocess.run(["bash", os.path.join(MESH, "boot-mesh.sh"), "selfcheck"], env=env, capture_output=True, text=True, timeout=60)
    srv.shutdown()
    return got, r


def run():
    got, r = _run(CONTAINER_OK)
    _check("posts exactly one report to /api/mesh/session/selfcheck", len(got) == 1 and got[0][0] == "/api/mesh/session/selfcheck")
    body = got[0][1]
    ids = [i["id"] for i in body["items"]]
    _check("report is valid JSON naming the codespace", body["codespace_id"] == "cs-test")
    _check("host DNS check comes first, then the container's checks", ids == ["host_dns", "dns", "appliance"])
    _check("healthy host + healthy container -> every item ok", all(i["ok"] is True for i in body["items"]))

    got, _ = _run(CONTAINER_OK, getent_ok=False)
    host = got[0][1]["items"][0]
    _check("broken host DNS is reported as a failure with an apt-get hint", host["ok"] is False and "apt-get" in host["hint"])

    got, _ = _run("")
    items = got[0][1]["items"]
    _check("checks that cannot run inside the container are a FAILED item, never silence", items[-1]["id"] == "selfcheck" and items[-1]["ok"] is False)

    got, _ = _run("not json at all")
    _check("garbage from the container is treated as a failed check", got[0][1]["items"][-1]["ok"] is False)

    got, r = _run(CONTAINER_OK, portal_status=500)
    _check("a portal that rejects the report is retried 3 times then logged, not fatal", len(got) == 3 and "could not post" in r.stdout)
    print("BOOT SELFCHECK OK")


if __name__ == "__main__":
    run()
