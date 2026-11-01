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


def _arm(rg_type, name, props=None, ns="Microsoft.KeyVault", ver="2023-07-01"):
    jcall("POST", "/api/spaces/space-azure-default/switch")      # ARM + /azure-data serve the active Azure space
    sub, rg = "00000000-0000-0000-0000-cloudlearn01", f"pc-rg-{SFX}"
    http("PUT", f"{BASE}/subscriptions/{sub}/resourceGroups/{rg}?api-version=2021-04-01", {"location": "eastus"})
    s, r = jcall("PUT", f"/subscriptions/{sub}/resourceGroups/{rg}/providers/{ns}/{rg_type}/{name}?api-version={ver}",
                 {"location": "eastus", "properties": props or {}})
    return s, r


def azure_keyvault():
    name = f"pckv{SFX}"
    s, r = _arm("vaults", name, {"tenantId": "00000000-0000-0000-0000-000000000000", "sku": {"family": "A", "name": "standard"}})
    uri = (r.get("properties") or {}).get("vaultUri", "")
    check(s in (200, 201), "create Key Vault", f"{s}")
    check(uri.startswith(BASE), "vaultUri is on the simulator origin, not a fake azure hostname", uri)
    if not uri.startswith("http"):
        return
    st, _, _ = http("PUT", uri.rstrip("/") + "/secrets/s1", {"value": "topsecret"})
    st2, body, _ = http("GET", uri.rstrip("/") + "/secrets/s1")
    check(st in (200, 201) and st2 == 200 and b"topsecret" in body, "set+get a secret through the shown vaultUri", f"{st} {st2} {body[:80]}")


def azure_eventgrid():
    name = f"pceg{SFX}"
    s, r = _arm("topics", name, {}, "Microsoft.EventGrid", "2024-06-01-preview")
    ep = (r.get("properties") or {}).get("endpoint", "")
    check(s in (200, 201) and bool(ep), "create Event Grid topic shows an endpoint", f"{s} {ep}")
    if not ep.startswith("http"):
        return
    st, body, _ = http("POST", ep, [{"id": "1", "subject": "s", "eventType": "t", "eventTime": "2026-01-01T00:00:00Z", "data": {}, "dataVersion": "1"}])
    check(st == 200, "publish an event to the shown endpoint", f"{st} {body[:80]}")


def azure_servicebus():
    name = f"pcsb{SFX}"
    s, r = _arm("namespaces", name, {}, "Microsoft.ServiceBus", "2022-10-01-preview")
    ep = (r.get("properties") or {}).get("serviceBusEndpoint", "")
    check(ep.startswith(BASE), "serviceBusEndpoint is the origin the client reached (not hard-coded :9000)", ep)
    if not ep.startswith("http"):
        return
    st, body, _ = http("POST", ep.rstrip("/") + "/q1/messages", {"body": "hi"})
    check(st < 300, "send a message under the shown endpoint", f"{st} {body[:80]}")


def azure_sql():
    name = f"pcsql{SFX}"
    s, r = _arm("servers", name, {"administratorLogin": "sqladmin", "administratorLoginPassword": "P@ssw0rd123!"}, "Microsoft.Sql", "2023-05-01-preview")
    p = r.get("properties") or {}
    fq = p.get("fullyQualifiedDomainName", "")
    if not fq.startswith("http"):
        check(False, "fullyQualifiedDomainName shown", str(p)[:200])
        return
    st, body, hd = http("GET", fq)
    check(st == 200 and b"NoSuchBucket" not in body, "fullyQualifiedDomainName answers (not an S3 NoSuchBucket page)", f"{fq} -> {st} {body[:80]}")
    acc = p.get("vyomiAccess") or {}
    check("no TDS" in json.dumps(acc) or "HTTP" in json.dumps(acc), "properties say the real access path (HTTP only, no TDS)", str(acc)[:200])


if __name__ == "__main__":
    globals()[WHAT]()
    sys.exit(1 if fails else 0)
