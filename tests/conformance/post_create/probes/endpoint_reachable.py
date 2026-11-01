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
# An HTTP upstream the APPLIANCE (container) can reach, for HTTP-integration checks; set
# VYOMI_PROBE_UPSTREAM=http://host.docker.internal:<port>/healthz. Unset -> those checks are skipped, not faked.
UPSTREAM = os.environ.get("VYOMI_PROBE_UPSTREAM", "")
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


def gcp_apigateway():
    import base64
    P, sfx = "vyomi-project", SFX
    fn, api, cfg, gw = f"pcfn{sfx}", f"pcapi{sfx}", f"pccfg{sfx}", f"pcgw{sfx}"
    jcall("POST", "/api/spaces/space-gcp-default/switch")
    s, _ = jcall("POST", f"/api/gcp/cloudfunctions/v2/projects/{P}/locations/us-central1/functions",
                 {"name": fn, "runtime": "python312", "entryPoint": "h", "code": 'def h(request):\n    return {"ok": 1}\n', "httpsTrigger": {}})
    check(s < 300, "create backing function", str(s))
    s, _ = jcall("POST", f"/v1/projects/{P}/locations/global/apis?apiId={api}", {"name": api})
    doc = ("swagger: '2.0'\ninfo:\n  title: t\n  version: '1'\npaths:\n  /hello:\n    get:\n      operationId: hello\n"
           f"      x-google-backend:\n        address: https://us-central1-{P}.cloudfunctions.net/{fn}\n      responses:\n        '200':\n          description: ok\n")
    s, c = jcall("POST", f"/v1/projects/{P}/locations/global/apis/{api}/configs?apiConfigId={cfg}",
                 {"openapiDocuments": [{"document": {"path": "openapi.yaml", "contents": base64.b64encode(doc.encode()).decode()}}]})
    check(s < 300 and c.get("name", "").endswith(f"/apis/{api}/configs/{cfg}"), "native apiConfigs create is routed and keeps apiConfigId", f"{s} {str(c)[:200]}")
    s, g = jcall("POST", f"/v1/projects/{P}/locations/us-central1/gateways?gatewayId={gw}",
                 {"apiConfig": f"projects/{P}/locations/global/apis/{api}/configs/{cfg}"})
    check(s < 300 and g.get("name", "").endswith(f"/gateways/{gw}"), "native gateway create keeps gatewayId as the name", f"{s} {str(g)[:200]}")
    s, g = jcall("GET", f"/v1/projects/{P}/locations/us-central1/gateways/{gw}")
    hn = g.get("defaultHostname", "")
    check(s == 200 and bool(hn), "GET gateway by id", f"{s} {str(g)[:160]}")
    st, body, _ = http("GET", "http://" + hn + "/hello")
    check(st == 200 and b"ok" in body, "GET http://<shown defaultHostname>/hello invokes the gateway", f"{st} {body[:120]}")


def aws_apigateway():
    import base64, io, zipfile
    jcall("POST", "/api/spaces/space-legacy/switch") if False else None
    n = f"pcapi{SFX}"
    s, api = jcall("POST", "/restapis", {"name": n})
    check(s in (200, 201) and api.get("id"), "create_rest_api", f"{s} {str(api)[:120]}")
    aid = api.get("id")
    s, res = jcall("GET", f"/restapis/{aid}/resources")
    root = res["item"][0]["id"]
    # MOCK
    s, r1 = jcall("POST", f"/restapis/{aid}/resources/{root}", {"pathPart": "mock"})
    jcall("PUT", f"/restapis/{aid}/resources/{r1['id']}/methods/GET", {"authorizationType": "NONE"})
    jcall("PUT", f"/restapis/{aid}/resources/{r1['id']}/methods/GET/integration", {"type": "MOCK", "requestTemplates": {"application/json": '{"statusCode": 200}'}, "mockBody": "mock-ok", "mockStatus": 200})
    # HTTP -> the simulator's own health endpoint
    s, r2 = jcall("POST", f"/restapis/{aid}/resources/{root}", {"pathPart": "http"})
    jcall("PUT", f"/restapis/{aid}/resources/{r2['id']}/methods/GET", {"authorizationType": "NONE"})
    jcall("PUT", f"/restapis/{aid}/resources/{r2['id']}/methods/GET/integration", {"type": "HTTP", "httpMethod": "GET", "uri": UPSTREAM})
    # Lambda proxy
    fn = f"pcfn{SFX}"
    s, _ = jcall("POST", "/api/lambda/functions", {"function_name": fn, "runtime": "python3.12", "handler": "lambda_function.lambda_handler",
                 "code": "def lambda_handler(event, ctx):\n    return {'statusCode': 200, 'body': 'lambda-ok:' + event['path']}\n"})
    s, r3 = jcall("POST", f"/restapis/{aid}/resources/{root}", {"pathPart": "lam"})
    jcall("PUT", f"/restapis/{aid}/resources/{r3['id']}/methods/GET", {"authorizationType": "NONE"})
    jcall("PUT", f"/restapis/{aid}/resources/{r3['id']}/methods/GET/integration", {"type": "AWS_PROXY", "httpMethod": "POST",
          "uri": f"arn:aws:apigateway:us-east-1:lambda:path/2015-03-31/functions/arn:aws:lambda:us-east-1:123456789012:function:{fn}/invocations"})
    s, d = jcall("POST", f"/restapis/{aid}/deployments", {"stageName": "prod"})
    check(s in (200, 201), "create_deployment", f"{s} {str(d)[:120]}")
    u = f"{BASE}/restapis/{aid}/prod/_user_request_"
    for path, want, label in (("/mock", b"mock-ok", "MOCK"), ("/http", b"", "HTTP"), ("/lam", b"lambda-ok", "Lambda proxy")):
        if label == "HTTP" and not UPSTREAM:
            print("[SKIP] HTTP integration (set VYOMI_PROBE_UPSTREAM)")
            continue
        st, body, _ = http("GET", u + path)
        check(st == 200 and want in body, f"GET {u.replace(BASE, '<origin>')}{path} ({label} integration)", f"{st} {body[:100]}")
    jcall("DELETE", f"/restapis/{aid}")


def aws_apigatewayv2():
    n = f"pcv2{SFX}"
    s, api = jcall("POST", "/v2/apis", {"name": n, "protocolType": "HTTP"})
    ep = api.get("apiEndpoint", "")
    check(s in (200, 201) and ep.startswith(BASE), "create_api shows an ApiEndpoint on the simulator origin", f"{s} {ep}")
    aid = api.get("apiId")
    s, ig = jcall("POST", f"/v2/apis/{aid}/integrations", {"integrationType": "HTTP_PROXY", "integrationMethod": "GET", "integrationUri": UPSTREAM, "payloadFormatVersion": "1.0"})
    s, rt = jcall("POST", f"/v2/apis/{aid}/routes", {"routeKey": "GET /hi", "target": f"integrations/{ig.get('integrationId')}"})
    s, st = jcall("POST", f"/v2/apis/{aid}/stages", {"stageName": "$default", "autoDeploy": True})
    time.sleep(1)
    if not UPSTREAM:
        print("[SKIP] ApiEndpoint -> HTTP_PROXY integration (set VYOMI_PROBE_UPSTREAM)")
        jcall("DELETE", f"/v2/apis/{aid}")
        return
    code, body, _ = http("GET", ep + "/hi")
    check(code == 200, "GET <shown ApiEndpoint>/hi reaches the integration", f"{code} {body[:100]}")
    jcall("DELETE", f"/v2/apis/{aid}")


def aws_elb():
    import re, urllib.parse
    if not shutil.which("docker"):
        check(False, "docker available for the helper web target")
        return
    web = f"pc-elb-web-{SFX}"
    net = os.environ.get("VYOMI_PROBE_NETWORK", "vyomi-net")
    subprocess.run(["docker", "run", "-d", "--name", web, "--network", net, "registry:2.8.3"], capture_output=True)
    try:
        ip = subprocess.run(["docker", "inspect", "-f", "{{(index .NetworkSettings.Networks \"%s\").IPAddress}}" % net, web],
                            capture_output=True, text=True).stdout.strip()
        time.sleep(2)

        def q(**p):
            body = urllib.parse.urlencode({"Version": "2015-12-01", **p}).encode()
            st, d, _ = http("POST", BASE + "/", body, {"content-type": "application/x-www-form-urlencoded",
                            "Authorization": "AWS4-HMAC-SHA256 Credential=A/20260101/us-east-1/elasticloadbalancing/aws4_request, SignedHeaders=host, Signature=x"})
            return st, d.decode()
        nm = f"pc-lb-{SFX}"
        st, x = q(Action="CreateTargetGroup", Name=f"pc-tg-{SFX}", Protocol="HTTP", Port="5000", VpcId="vpc-0123456789abcdef0", TargetType="ip")
        tg = re.search(r"<TargetGroupArn>(.*?)</TargetGroupArn>", x).group(1)
        q(Action="RegisterTargets", TargetGroupArn=tg, **{"Targets.member.1.Id": ip, "Targets.member.1.Port": "5000"})
        st, x = q(Action="CreateLoadBalancer", Name=nm, **{"Subnets.member.1": "subnet-0aaaaaaaaaaaaaaa1", "Subnets.member.2": "subnet-0bbbbbbbbbbbbbbb2"})
        check(st == 200, "create_load_balancer", x[:200])
        lb = re.search(r"<LoadBalancerArn>(.*?)</LoadBalancerArn>", x).group(1)
        q(Action="CreateListener", LoadBalancerArn=lb, Protocol="HTTP", Port="80", **{"DefaultActions.member.1.Type": "forward", "DefaultActions.member.1.TargetGroupArn": tg})
        st, x = q(Action="DescribeLoadBalancers", **{"Names.member.1": nm})
        check("<Code>active</Code>" in x, "describe_load_balancers reports the LB active", re.sub(r"\s+", " ", x)[-300:])
        s, row = jcall("GET", "/api/aws/elbv2/load-balancers/" + nm)
        url = row.get("local_url", "")
        if not url:
            check(False, "console/API show a local URL on the simulator origin", str(row)[:200])
            return
        check(url.startswith(BASE), "console/API show a local URL on the simulator origin", str(row)[:200])
        st, body, _ = http("GET", url + "v2/")
        check(st == 200, "GET <local_url>v2/ is forwarded to the registered target", f"{st} {body[:100]}")
        jcall("DELETE", "/api/aws/elbv2/load-balancers/" + nm)
    finally:
        subprocess.run(["docker", "rm", "-f", web], capture_output=True)


if __name__ == "__main__":
    globals()[WHAT]()
    sys.exit(1 if fails else 0)
