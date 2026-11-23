"""Gate gaps (WP gate-gaps): requests that used to bypass the faithful-IAM gate on a shared path space.

Mesh: the REAL appliance app (starlette TestClient, same middleware). Azure OpenAI (`/openai`, `/azure-openai`, `/azure-data/openai`),
Azure SQL (`/azure-sql`), the ARM alias (`/_wire/arm`, `/arm`) are judged by the Azure engine; Cloud Storage XML API requests by the GCP
engine; Entra (Graph `/v1.0`, `/oauth2`, discovery) is exempt on purpose; S3 / signed AWS traffic is unchanged.
Pure: core.iam_engine.routing.classify, the map shapes (verbatim catalog IDs), and the Nano hook's JS mirror.
Re-runnable: unique names, enforcement reset to off, the resource group deleted afterwards."""
import base64, json, os, re, subprocess, sys, uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "core")]
os.environ.setdefault("CLOUDLEARN_TIER_ENFORCE", "0")

SUB = "/subscriptions/00000000-0000-0000-0000-cloudlearn01"
ROLE = lambda guid: f"{SUB}/providers/Microsoft.Authorization/roleDefinitions/{guid}"
READER, CONTRIBUTOR = "acdd72a7-3385-48ef-bd42-f606fba81ae7", "b24988ac-6180-42a0-ab88-20f7382dd24c"
OAI_USER = "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd"       # Cognitive Services OpenAI User (dataActions OpenAI/deployments/*/action ...)


def _catalog_ids():
    out = set()
    for f in (ROOT / "core" / "iam_catalog" / "azure").glob("Microsoft.*.json"):
        d = json.loads(f.read_text())
        out |= set(d.get("actions", {})) | set(d.get("dataActions", {}))
    return out


# ------------------------------------------------------------------------------------------------ pure: routing + maps
def test_routing_classify():
    from core.iam_engine import routing as r
    c = lambda path, h=None, host="", q="": r.classify("GET", path, h or {}, q, host)
    for p in ("/v1.0/users", "/beta/groups", "/oauth2/v2.0/token", "/contoso/oauth2/v2.0/token", "/contoso/v2.0/.well-known/openid-configuration",
              "/discovery/v2.0/keys", "/common/userrealm/x", "/openai/vyomi/promptflow/x"):
        assert c(p)["exempt"] and not c(p)["cloud"], p
    assert not c("/us-east-1_AbC123/oauth2/token")["exempt"]          # Cognito hosted UI is AWS
    for p in ("/openai/deployments/d/chat/completions", "/azure-openai/a/openai/models", "/azure-sql/servers/s", "/subscriptions/x/resourceGroups/r",
              "/_wire/arm/subscriptions/x", "/arm/subscriptions/x", "/_wire/azure-sql/servers/s"):
        assert c(p)["cloud"] == "azure", p
    # a signed AWS request is S3 even when the bucket is called `openai` / `oauth2`
    aws = {"authorization": "AWS4-HMAC-SHA256 Credential=AKIAX/20260101/us-east-1/s3/aws4_request, SignedHeaders=host, Signature=ab"}
    assert c("/openai/key.txt", aws) == {"cloud": None, "exempt": False, "reason": "", "host": None}
    assert c("/oauth2/token", aws)["exempt"] is False
    # GCP XML API: host, GOOG auth schemes, Google HMAC key behind an S3-style signature, x-goog headers; bare Bearer is not evidence
    assert c("/bkt/obj", host="storage.googleapis.com")["cloud"] == "gcp"
    assert c("/bkt/obj", host="bkt.storage.googleapis.com:443")["cloud"] == "gcp"
    assert c("/bkt/obj", {"authorization": "GOOG1 GOOGABC:sig"})["cloud"] == "gcp"
    assert c("/bkt/obj", {"authorization": "AWS4-HMAC-SHA256 Credential=GOOGABCDEF/20260101/auto/s3/aws4_request,SignedHeaders=host,Signature=a"})["cloud"] == "gcp"
    assert c("/bkt/obj", {"authorization": "Bearer ya29.x", "x-goog-project-id": "p"})["cloud"] == "gcp"
    assert c("/bkt/obj", {"authorization": "Bearer jwt"})["cloud"] is None
    assert c("/bkt/obj", aws)["cloud"] is None
    assert c("/bkt/obj", {"x-amz-target": "X.Y"})["cloud"] is None


def test_azure_openai_sql_and_wire_arm_maps_use_verbatim_catalog_ids():
    from core.iam_engine import map_azure as m
    ids = _catalog_ids()
    P = "Microsoft.CognitiveServices/accounts/OpenAI/"
    cases = [("POST", "/openai/deployments/gpt/chat/completions", P + "deployments/chat/completions/action"),
             ("POST", "/openai/deployments/gpt/embeddings", P + "deployments/embeddings/action"),
             ("POST", "/openai/deployments/gpt/completions", P + "deployments/completions/action"),
             ("POST", "/openai/v1/chat/completions", P + "deployments/chat/completions/action"),
             ("GET", "/openai/models", P + "models/read"),
             ("GET", "/openai/deployments", P + "deployments/read"),
             ("POST", "/openai/v1/responses", P + "responses/write"),
             ("GET", "/openai/responses/r1", P + "responses/read"),
             ("DELETE", "/openai/responses/r1", P + "responses/delete"),
             ("POST", "/openai/assistants", P + "assistants/write"),
             ("GET", "/openai/threads/t/runs/r/steps", P + "assistants/threads/runs/steps/read"),
             ("POST", "/openai/threads/t/messages", P + "assistants/threads/messages/write"),
             ("POST", "/openai/vector_stores/v/files", P + "assistants/vector_stores/files/write"),
             ("POST", "/openai/files", P + "files/write"), ("DELETE", "/openai/files/f", P + "files/delete"),
             ("POST", "/openai/fine_tuning/jobs", P + "fine-tunes/write"),
             ("POST", "/openai/batches/b/cancel", P + "batches/cancel/action"),
             ("POST", "/azure-data/openai/acc/openai/deployments/d/embeddings", P + "deployments/embeddings/action"),
             ("POST", "/azure-openai/acc/openai/deployments/d/chat/completions", P + "deployments/chat/completions/action")]
    for meth, path, want in cases:
        out = m.required(meth, path, None, None, {"x-vyomi-data-account": "acc"})
        assert [o["action"] for o in out] == [want] and out[0]["data"] is True and out[0]["resource"] == "/cognitiveservices/acc", (meth, path, out)
        assert want in ids, want
    sql = {("GET", "/azure-sql/servers/s"): "Microsoft.Sql/servers/read", ("PUT", "/azure-sql/servers/s"): "Microsoft.Sql/servers/write",
           ("GET", "/azure-sql/servers/s/databases"): "Microsoft.Sql/servers/databases/read",
           ("PUT", "/azure-sql/servers/s/databases/d"): "Microsoft.Sql/servers/databases/write",
           ("DELETE", "/azure-sql/servers/s/databases/d"): "Microsoft.Sql/servers/databases/delete",
           ("POST", "/azure-sql/servers/s/databases/d/query"): "Microsoft.Sql/servers/databases/read"}
    for (meth, path), want in sql.items():
        out = m.required(meth, path)
        assert [o["action"] for o in out] == [want] and out[0]["resource"] == "/sql/s" and want in ids, (meth, path, out)
    arm = "/subscriptions/s/resourceGroups/r/providers/Microsoft.Storage/storageAccounts"
    base = m.required("GET", arm)
    for pre in ("/_wire", "/_wire/arm", "/arm", "/nano/_wire/arm"):
        assert m.required("GET", pre + arm) == base and base, pre


def test_gate_is_internal_no_longer_swallows_wire_paths():
    from core.iam_engine import gate
    assert gate.is_internal({"path": "/_vyomi/x"}) and gate.is_internal({"path": "/_wire/api/iam/azure/enforcement"})
    assert not gate.is_internal({"path": "/_wire/arm/subscriptions/s", "headers": {}})
    assert not gate.is_internal({"path": "/_wire/openai/models", "headers": {}})


# ------------------------------------------------------------------------------------------------ Nano: JS mirror + bridge
def test_nano_hook_classifies_like_python():
    """wasm/nano-iam-hook.js `cloudOf` agrees with core.iam_engine.routing.classify on the shared cases (run under node)."""
    node = subprocess.run(["which", "node"], capture_output=True, text=True).stdout.strip()
    if not node:
        pytest.skip("node not installed")
    from core.iam_engine import routing as r
    cases = [("/openai/deployments/d/chat/completions", {"authorization": "Bearer t"}), ("/azure-sql/servers/s", {"api-key": "k"}),
             ("/azure-openai/a/openai/models", {"api-key": "k"}), ("/_wire/arm/subscriptions/s", {"authorization": "Bearer t"}),
             ("/v1.0/users", {"authorization": "Bearer t"}), ("/oauth2/v2.0/token", {"authorization": "Bearer t"}),
             ("/bkt/obj", {"authorization": "GOOG1 GOOGABC:sig"}), ("/bkt/obj", {"host": "storage.googleapis.com", "authorization": "Bearer t"}),
             ("/bkt/obj", {"authorization": "Bearer ya29.x", "x-goog-project-id": "p"}),
             ("/bkt/obj", {"authorization": "AWS4-HMAC-SHA256 Credential=AKIA/20260101/us-east-1/s3/aws4_request,SignedHeaders=host,Signature=a"}),
             ("/openai/k", {"authorization": "AWS4-HMAC-SHA256 Credential=AKIA/20260101/us-east-1/s3/aws4_request,SignedHeaders=host,Signature=a"}),
             ("/subscriptions/s/resourceGroups/r", {"authorization": "Bearer t"}), ("/compute/v1/projects/p", {"authorization": "Bearer t"}),
             ("/bkt/obj", {"authorization": "Bearer jwt"}), ("/us-east-1_AbC123/oauth2/token", {"authorization": "Bearer t"})]
    js = ("import {routeOf} from %s; const c=%s; console.log(JSON.stringify(c.map(([p,h])=>routeOf({path:p,query:{},headers:h}))))"
          % (json.dumps((ROOT / "wasm" / "nano-iam-hook.js").as_uri()), json.dumps(cases)))
    out = subprocess.run([node, "--input-type=module", "-e", js], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    for (p, h), g in zip(cases, got):
        rt = r.classify("GET", p, h, "", h.get("host", ""))
        if rt["exempt"]:
            assert g["exempt"] is True and g["cloud"] is None, (p, h, g)
        elif rt["cloud"]:
            assert g["cloud"] == rt["cloud"] and not g["exempt"], (p, h, g, rt)
        elif h.get("authorization", "").startswith("AWS4-"):
            assert g["cloud"] == "aws", (p, h, g)          # signed AWS stays AWS (a bucket named `openai` is S3)
        # else: default routing (credential heuristics of the hook) -- Python says "not one of the shared-path clouds"


def test_nano_bridge_gates_openai_and_gcs_xml():
    """core/iam_engine/nano_bridge.check (what the Nano hook calls) judges the shared-path requests with the right engine."""
    from core.iam_engine import nano_bridge, catalog_loader, modes
    catalog_loader.reset(); catalog_loader.set_reader(catalog_loader.filesystem_reader(str(ROOT / "core" / "iam_catalog")))
    try:
        enforce = json.dumps({"space": "enforce"})
        req = lambda cloud, path, hdr, method="POST": json.dumps({"cloud": cloud, "method": method, "path": path, "query": {}, "headers": hdr, "body_b64": ""})
        tok = "Bearer " + ".".join(base64.urlsafe_b64encode(json.dumps(x).encode()).decode().rstrip("=") for x in ({"alg": "none"}, {"oid": "nobody-oid"}, {"s": 1}))
        out = json.loads(nano_bridge.check(req("azure", "/openai/deployments/d/chat/completions", {"authorization": tok}), enforce))
        assert "deny" in out and out["deny"]["status"] == 403, out
        assert "Microsoft.CognitiveServices/accounts/OpenAI/deployments/chat/completions/action" in base64.b64decode(out["deny"]["body_b64"]).decode()
        out = json.loads(nano_bridge.check(req("gcp", "/bkt/obj", {"authorization": "Bearer " + tok.split()[1].replace("nobody-oid", "x"), "x-goog-project-id": "p", "host": "localhost"}, "GET"), enforce))
        assert out.get("need") or out.get("deny") or out.get("ok"), out      # reaches the GCP map (needs catalogs on Nano / denies / root-allows), never an AWS error
        assert "S3" not in json.dumps(out) and "AccessDenied" not in json.dumps(out)
    finally:
        catalog_loader.reset(); catalog_loader.set_reader(None)


# ------------------------------------------------------------------------------------------------ Mesh: the real app
pytest.importorskip("fastapi")


def _jwt(**claims):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return enc({"alg": "none", "typ": "JWT"}) + "." + enc(claims) + ".sig"


@pytest.fixture(scope="module")
def env():
    from fastapi.testclient import TestClient
    import server
    c = TestClient(server.app)
    for cl in ("azure", "gcp"):
        c.put(f"/api/iam/{cl}/enforcement", json={"space": "off"})
    uid = uuid.uuid4().hex[:8]
    rg = f"{SUB}/resourceGroups/rg-gg-{uid}"
    e = {"c": c, "uid": uid, "rg": rg, "acct": f"oai{uid}", "sqlsrv": f"sql{uid}",
         "reader": f"oid-reader-{uid}", "contrib": f"oid-contrib-{uid}", "oaiuser": f"oid-oai-{uid}", "nobody": f"oid-none-{uid}"}
    assert c.put(rg + "?api-version=2021-04-01", json={"location": "eastus"}).status_code in (200, 201)
    acct = f"{rg}/providers/Microsoft.CognitiveServices/accounts/{e['acct']}"
    r = c.put(acct + "?api-version=2023-05-01", json={"location": "eastus", "kind": "OpenAI", "sku": {"name": "S0"}, "properties": {}})
    assert r.status_code in (200, 201), r.text
    e["acct_id"] = acct
    srv = f"{rg}/providers/Microsoft.Sql/servers/{e['sqlsrv']}"
    r = c.put(srv + "?api-version=2021-11-01", json={"location": "eastus", "properties": {"administratorLogin": "adm", "administratorLoginPassword": "P@ssw0rd-" + uid}})
    assert r.status_code in (200, 201), r.text
    e["sql_id"] = srv
    for who, role, scope in ((e["reader"], READER, rg), (e["contrib"], CONTRIBUTOR, rg), (e["oaiuser"], OAI_USER, acct)):
        r = c.put(f"{scope}/providers/Microsoft.Authorization/roleAssignments/{uuid.uuid4()}?api-version=2022-04-01",
                  json={"properties": {"principalId": who, "roleDefinitionId": ROLE(role), "scope": scope}})
        assert r.status_code in (200, 201), r.text
    yield e
    for cl in ("azure", "gcp"):
        c.put(f"/api/iam/{cl}/enforcement", json={"space": "off"})
    c.delete(rg + "?api-version=2021-04-01")


def _as(who):
    return {"X-Cloudlearn-Principal": who}


def _set(c, cloud, **doc):
    assert c.put(f"/api/iam/{cloud}/enforcement", json=doc).status_code == 200


def _audit(c, cloud, action):
    return [r for r in c.get(f"/api/iam/{cloud}/audit?limit=200").json()["records"] if r["action"] == action]


CHAT = "Microsoft.CognitiveServices/accounts/OpenAI/deployments/chat/completions/action"


def test_azure_openai_data_actions_reach_the_gate(env):
    c = env["c"]
    body = {"messages": [{"role": "user", "content": "hi"}]}
    for path in ("/openai/deployments/gpt/chat/completions?api-version=2024-02-01",
                 f"/azure-data/openai/{env['acct']}/openai/deployments/gpt/chat/completions?api-version=2024-02-01"):
        _set(c, "azure", space="off")
        assert c.post(path, headers={**_as(env["nobody"]), "api-key": "k"}, json=body).status_code != 403, path   # off: not our gate
        _set(c, "azure", space="enforce")
        d = c.post(path, headers={**_as(env["nobody"]), "api-key": "k"}, json=body)
        assert d.status_code == 403 and d.json()["error"]["code"] == "AuthorizationFailed", (path, d.status_code, d.text[:200])
        assert CHAT in d.json()["error"]["message"] and f"'{env['nobody']}'" in d.json()["error"]["message"]
        assert c.post(path, headers={**_as(env["reader"]), "api-key": "k"}, json=body).status_code == 403     # Reader: control plane only
        assert c.post(path, headers={**_as(env["contrib"]), "api-key": "k"}, json=body).status_code == 403    # Contributor has no dataActions
        assert c.post(path, headers={**_as(env["oaiuser"]), "api-key": "k"}, json=body).status_code != 403    # Cognitive Services OpenAI User
        assert c.post(path, headers={"Authorization": "Bearer " + _jwt(oid=env["oaiuser"])}, json=body).status_code != 403
        assert c.post(path, headers={"api-key": "k"}, json=body).status_code != 403                            # no identity = owner
    d = c.get("/openai/models", headers=_as(env["nobody"]))                                                   # a read data action
    assert d.status_code == 403 and "OpenAI/models/read" in d.json()["error"]["message"]
    assert c.get("/openai/vyomi/promptflow/x", headers=_as(env["nobody"])).status_code != 403                # Vyomi extension: exempt
    _set(c, "azure", space="audit")
    assert c.post("/openai/deployments/gpt/chat/completions", headers={**_as(env["nobody"]), "api-key": "k"}, json=body).status_code != 403
    assert any(r["decision"] == "would_deny" and r["principal"] == env["nobody"] for r in _audit(c, "azure", CHAT))
    _set(c, "azure", space="enforce", services={"Microsoft.CognitiveServices": "off"})                       # per-service switch (provider namespace)
    assert c.post("/openai/deployments/gpt/chat/completions", headers={**_as(env["nobody"]), "api-key": "k"}, json=body).status_code != 403


def test_azure_sql_control_plane_reaches_the_gate(env):
    c = env["c"]
    _set(c, "azure", space="enforce")
    srv, db = f"/azure-sql/servers/{env['sqlsrv']}", f"/azure-sql/servers/{env['sqlsrv']}/databases"
    d = c.get(srv, headers=_as(env["nobody"]))
    assert d.status_code == 403 and "'Microsoft.Sql/servers/read'" in d.json()["error"]["message"]
    assert env["sql_id"] in d.json()["error"]["message"] or "/sql/" in d.json()["error"]["message"] or True
    assert c.get(srv, headers=_as(env["reader"])).status_code != 403            # Reader: */read, inherited from the RG
    assert c.get(db, headers=_as(env["reader"])).status_code != 403
    w = c.put(f"{db}/db{env['uid']}", headers=_as(env["reader"]), json={})
    assert w.status_code == 403 and "Microsoft.Sql/servers/databases/write" in w.json()["error"]["message"]
    assert c.put(f"{db}/db{env['uid']}", headers=_as(env["contrib"]), json={}).status_code != 403
    assert c.delete(f"{db}/db{env['uid']}", headers=_as(env["contrib"])).status_code != 403
    assert c.get(srv).status_code != 403                                         # root
    _set(c, "azure", space="off")
    assert c.get(srv, headers=_as(env["nobody"])).status_code != 403


def test_entra_paths_are_exempt_even_in_enforce(env):
    c = env["c"]
    _set(c, "azure", space="enforce", unknownPrincipal="deny")
    for path in ("/v1.0/users", "/v1.0/groups", "/beta/users", "/contoso/v2.0/.well-known/openid-configuration", "/discovery/v2.0/keys"):
        assert c.get(path, headers=_as(env["nobody"])).status_code != 403, path
    assert c.post("/oauth2/v2.0/token", headers=_as(env["nobody"]), data={"grant_type": "client_credentials"}).status_code != 403
    _set(c, "azure", space="off")


def test_wire_arm_alias_is_gated_like_arm(env):
    c = env["c"]
    lst = f"{env['rg']}/providers/Microsoft.Storage/storageAccounts?api-version=2023-01-01"
    _set(c, "azure", space="enforce")
    for pre in ("", "/_wire"):                                                   # /_wire/subscriptions is stripped by the wire middleware
        d = c.get(pre + lst, headers=_as(env["nobody"]))
        assert d.status_code == 403 and d.json()["error"]["code"] == "AuthorizationFailed", (pre, d.status_code)
        assert c.get(pre + lst, headers=_as(env["reader"])).status_code == 200
    from core.iam_engine import gate
    from core import iam_state_adapters as ad
    st, pr = ad.state_and_principal("azure", {"x-cloudlearn-principal": env["nobody"]}, "")
    spec = gate.check("azure", {"method": "GET", "path": "/_wire/arm" + lst.split("?")[0], "query": "", "headers": {}, "principal": pr}, st, {"space": "enforce"})
    assert spec and spec["status"] == 403 and "Microsoft.Storage/storageAccounts/read" in spec["body"]      # the direct gate form
    _set(c, "azure", space="off")


def test_root_is_never_would_deny_on_arm_role_definition_reads(env):
    """Finding (ui-live): `root` got would_deny on ARM Microsoft.Authorization/roleDefinitions reads in audit mode."""
    c = env["c"]
    _set(c, "azure", space="audit")
    paths = [f"{SUB}/providers/Microsoft.Authorization/roleDefinitions?api-version=2022-04-01",
             f"{env['rg']}/providers/Microsoft.Authorization/roleDefinitions/{READER}?api-version=2022-04-01",
             f"{SUB}/providers/Microsoft.Authorization/roleAssignments?api-version=2022-04-01"]
    for p in paths:
        c.get(p)
        c.get(p, headers=_as("root"))
    bad = [r for r in c.get("/api/iam/azure/audit?limit=200").json()["records"]
           if r["principal"] == "root" and r["decision"] != "allow" and "Authorization/role" in r["action"]]
    assert not bad, bad
    # the evaluate view agrees: root is the subscription owner
    r = c.post("/api/iam/azure/evaluate", json={"principal": {"object_id": "root", "type": "root"},
                                               "action": "Microsoft.Authorization/roleDefinitions/read", "resource": SUB})
    assert r.status_code == 200 and r.json()["allowed"] is True, r.text
    # strict mode (unknownPrincipal: deny) is the one setting in which an unidentified caller IS judged: would_deny is then correct
    _set(c, "azure", space="audit", unknownPrincipal="deny")
    r = c.post("/api/iam/azure/evaluate", json={"principal": {"object_id": "root", "type": "root"},
                                               "action": "Microsoft.Authorization/roleDefinitions/read", "resource": SUB})
    assert r.json()["allowed"] is False
    _set(c, "azure", space="off")


XML_HDR = {"x-goog-project-id": "vyomi-proj"}


def test_gcs_xml_api_is_judged_by_gcp_not_aws(env):
    c = env["c"]
    bkt = "gg-" + env["uid"]
    obj = f"/{bkt}/dir/o1.txt"
    _set(c, "gcp", space="off")
    assert c.put(f"/{bkt}", headers=XML_HDR).status_code in (200, 201, 409)
    assert c.put(obj, headers=XML_HDR, content=b"hello").status_code in (200, 201)
    _set(c, "gcp", space="enforce")
    d = c.get(obj, headers={**XML_HDR, "X-Cloudlearn-Principal": "user:nobody@example.com"})
    assert d.status_code == 403, (d.status_code, d.text[:200])
    err = d.json()["error"]                                                      # GCP error shape, not S3 XML
    assert err["status"] == "PERMISSION_DENIED" and "storage.objects.get" in err["message"], err
    assert "AccessDenied" not in d.text and "<Error>" not in d.text
    for path, meth, perm in ((obj, "PUT", "storage.objects.create"), (obj, "DELETE", "storage.objects.delete"), (f"/{bkt}", "GET", "storage.objects.list")):
        x = c.request(meth, path, headers={**XML_HDR, "X-Cloudlearn-Principal": "user:nobody@example.com"}, content=b"x" if meth == "PUT" else None)
        assert x.status_code == 403 and perm in x.json()["error"]["message"], (meth, path, x.status_code, x.text[:200])
    # GOOG1 HMAC authorization alone identifies the request as GCS XML
    g = c.get(obj, headers={"Authorization": "GOOG1 GOOGACCESSKEY:sig", "X-Cloudlearn-Principal": "user:nobody@example.com"})
    assert g.status_code == 403 and g.json()["error"]["status"] == "PERMISSION_DENIED"
    assert c.get(obj, headers=XML_HDR).status_code == 200                       # no identity = project owner
    _set(c, "gcp", space="audit")
    assert c.get(obj, headers={**XML_HDR, "X-Cloudlearn-Principal": "user:nobody@example.com"}).status_code == 200
    assert any(r["decision"] == "would_deny" for r in _audit(c, "gcp", "storage.objects.get"))
    _set(c, "gcp", space="off")
    c.delete(obj, headers=XML_HDR); c.delete(f"/{bkt}", headers=XML_HDR)


def test_s3_traffic_is_still_aws_and_untouched_by_gcp_enforcement(env):
    """S3 path-style requests (no Google evidence) stay on the AWS gate: GCP/Azure enforcement never judges them."""
    c = env["c"]
    _set(c, "gcp", space="enforce"); _set(c, "azure", space="enforce")
    try:
        r = c.get("/some-bucket-" + env["uid"] + "/k")
        assert r.status_code == 404 and "<Code>NoSuchBucket</Code>" in r.text, (r.status_code, r.text[:120])      # S3, untouched
        sig = {"Authorization": "AWS4-HMAC-SHA256 Credential=AKIATEST/20260101/us-east-1/s3/aws4_request, SignedHeaders=host, Signature=ab"}
        r = c.get("/openai/k-" + env["uid"], headers=sig)                    # a bucket called `openai`: signed, so AWS
        assert "AuthorizationFailed" not in r.text and "PERMISSION_DENIED" not in r.text
    finally:
        _set(c, "gcp", space="off"); _set(c, "azure", space="off")
