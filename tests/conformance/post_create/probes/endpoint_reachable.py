#!/usr/bin/env python3
"""Post-create probe (offline): the endpoint/URL/host:port a service SHOWS must work from the USER'S machine.

  python3 endpoint_reachable.py redis|registry|... http://localhost:9000

Create the resource through the API, read the endpoint the API shows, then really call it from this
machine (RESP over TCP, `docker push`, HTTP). One [PASS]/[FAIL] line per check, exit 1 on any failure.
Findings: CONNECT_INFO_UNREACHABLE, POST_CREATE_UNUSABLE. Run on the host, not inside the appliance.
"""
import json, os, shutil, socket, subprocess, sys, time, urllib.error, urllib.request

WHAT = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("http") else "redis"
BASE = (sys.argv[-1] if sys.argv[-1].startswith("http") else os.environ.get("VYOMI_ENDPOINT", "http://localhost:9000")).rstrip("/")
fails = 0
SFX = str(int(time.time()) % 100000)


def check(ok, name, why=""):
    global fails
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f" :: {why}"), flush=True)
    fails += 0 if ok else 1
    return ok


def http(method, url, body=None, headers=None, timeout=30):
    h = {"content-type": "application/json"}
    h.update(headers or {})
    data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
    req = urllib.request.Request(url, method=method, data=data, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)
    except Exception as e:  # unreachable host etc.
        return 0, str(e).encode(), {}


def jcall(method, path, body=None):
    s, d, _ = http(method, BASE + path, body)
    try:
        return s, json.loads(d) if d else {}
    except Exception:
        return s, {"raw": d[:200].decode("utf8", "replace")}


def resp(sock, *args):
    out = b"*%d\r\n" % len(args) + b"".join(b"$%d\r\n%s\r\n" % (len(a), a) for a in map(lambda x: x.encode(), args))
    sock.sendall(out)
    time.sleep(0.2)
    return sock.recv(4096)


def redis():
    iid = f"pc-redis-{SFX}"
    p = "/v1/projects/vyomi-project/locations/us-central1/instances"
    s, op = jcall("POST", p + f"?instanceId={iid}", {"tier": "BASIC", "memorySizeGb": 1})
    check(s == 200, "create Memorystore instance", f"{s} {op}")
    inst = {}
    for _ in range(30):
        s, inst = jcall("GET", p + "/" + iid)
        if inst.get("state") == "READY":
            break
        time.sleep(1)
    host, port = inst.get("host"), inst.get("port")
    check(bool(host and port), "instance shows host+port", str(inst)[:200])
    try:
        sk = socket.create_connection((host, int(port)), timeout=5)
    except Exception as e:
        check(False, f"TCP connect to shown endpoint {host}:{port} from this machine", str(e))
        return
    check(True, f"TCP connect to shown endpoint {host}:{port} from this machine")
    with sk:
        check(resp(sk, "PING").startswith(b"+PONG"), "RESP PING -> PONG")
        resp(sk, "SET", f"pc:{iid}", "v1")
        check(b"v1" in resp(sk, "GET", f"pc:{iid}"), "SET then GET round trip")
        resp(sk, "DEL", f"pc:{iid}")
    jcall("DELETE", p + "/" + iid)


def registry():
    rid = f"pc-repo-{SFX}"
    p = "/v1/projects/vyomi-project/locations/us-central1/repositories"
    s, op = jcall("POST", p + f"?repositoryId={rid}", {"format": "DOCKER"})
    check(s == 200, "create Artifact Registry repo", f"{s} {op}")
    s, repo = jcall("GET", p + "/" + rid)
    hp = repo.get("vyomiPushHost")
    check(bool(hp), "repository record shows a push host:port", str(repo)[:200])
    if not hp:
        return
    st, body, hd = http("GET", f"http://{hp}/v2/", timeout=5)
    check(st in (200, 401) and "registry" in json.dumps(hd).lower() or st == 200, f"http://{hp}/v2/ answers like a registry", f"{st} {body[:80]}")
    if shutil.which("docker"):
        img = subprocess.run(["docker", "images", "-q", "registry:2.8.3"], capture_output=True, text=True).stdout.strip()
        if img:
            ref = f"{hp}/vyomi-project/{rid}/tiny:1"
            subprocess.run(["docker", "tag", img, ref], check=False)
            r = subprocess.run(["docker", "push", ref], capture_output=True, text=True, timeout=180)
            check(r.returncode == 0, "docker push to the shown host", (r.stdout + r.stderr)[-300:])
            subprocess.run(["docker", "rmi", ref], capture_output=True)
            time.sleep(4)
            s, pk = jcall("GET", p + f"/{rid}/packages")
            check("tiny" in json.dumps(pk), "pushed image appears in the repository", str(pk)[:200])
    jcall("DELETE", p + "/" + rid)


if __name__ == "__main__":
    globals()[WHAT]()
    sys.exit(1 if fails else 0)
