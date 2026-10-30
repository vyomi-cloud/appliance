"""Cloud Scheduler httpTarget jobs must send a real HTTP request (method, headers, body)
when run, record 2xx as OK and a 5xx/connection failure on the job's `status`, and a later
success clears it (#148)."""
import base64
import http.server
import os
import sys
import threading
import time
import uuid

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
try:   # the GCP space's project ID
    PROJECT = requests.get(f"{BASE}/api/gcp/catalog", timeout=60).json()["project"]
except Exception:   # appliance not up yet (collection)
    PROJECT = "vyomi-project"
failed = False
hits = []
mode = {"code": 200}


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' ' + str(extra)}")
    failed = failed or not ok


class H(http.server.BaseHTTPRequestHandler):
    def _h(self):
        n = int(self.headers.get("Content-Length") or 0)
        hits.append((self.command, self.path, dict(self.headers), self.rfile.read(n) if n else b""))
        self.send_response(mode["code"])
        self.send_header("Content-Length", "0")
        self.end_headers()
    do_POST = do_PUT = do_GET = _h

    def log_message(self, *a):
        pass


def wait(pred, secs=20):
    end = time.time() + secs
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(0.5)
    return None


def main():
    srv = http.server.ThreadingHTTPServer(("0.0.0.0", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    # The appliance runs in Docker: reach the host's listener as host.docker.internal (the product
    # maps it to loopback when it isn't resolvable, i.e. a non-Docker run).
    host = os.environ.get("HTTP_TARGET_HOST", "host.docker.internal")
    url = f"http://{host}:{srv.server_address[1]}/hook"
    jobs = f"{BASE}/v1/projects/{PROJECT}/locations/us-central1/jobs"
    jid = f"http-{uuid.uuid4().hex[:6]}"
    r = requests.post(jobs, json={
        "name": f"projects/{PROJECT}/locations/us-central1/jobs/{jid}", "schedule": "0 0 1 1 *",
        "httpTarget": {"uri": url, "httpMethod": "PUT", "headers": {"X-Vyomi": "yes"},
                       "body": base64.b64encode(b"payload-1").decode(), "oidcToken": {"serviceAccountEmail": "a@b.iam"}}},
        timeout=60)
    check("create httpTarget job", r.status_code < 300, r.text[:160])
    r = requests.post(f"{jobs}/{jid}:run", json={}, timeout=60)
    check("run job", r.status_code < 300, r.text[:160])
    check("target received the request", wait(lambda: hits) is not None, "no request")
    if hits:
        m, p, h, b = hits[0]
        check("method and path", (m, p) == ("PUT", "/hook"), (m, p))
        check("custom header sent", h.get("X-Vyomi") == "yes", h)
        check("body decoded", b == b"payload-1", b)
        check("bearer token header present", h.get("Authorization", "").startswith("Bearer "), h)
    j = wait(lambda: (lambda x: x if x.get("lastAttemptTime") and not x.get("status") else None)(
        requests.get(f"{jobs}/{jid}", timeout=60).json()), 10)
    check("2xx leaves status OK", j is not None)

    mode["code"] = 500
    requests.post(f"{jobs}/{jid}:run", json={}, timeout=60)
    j = wait(lambda: (lambda x: x if x.get("status", {}).get("code") else None)(requests.get(f"{jobs}/{jid}", timeout=60).json()))
    check("500 target shows failed status", j is not None and j["status"]["code"] == 13, j)
    mode["code"] = 200
    requests.post(f"{jobs}/{jid}:run", json={}, timeout=60)
    j = wait(lambda: (lambda x: x if not x.get("status") else None)(requests.get(f"{jobs}/{jid}", timeout=60).json()))
    check("later success clears status", j is not None, j)
    requests.delete(f"{jobs}/{jid}", timeout=60)
    srv.shutdown()
    sys.exit(1 if failed else 0)


main()
