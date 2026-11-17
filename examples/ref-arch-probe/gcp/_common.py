"""Shared helpers for the GCP reference-arch probes: start (or attach to) the simulator, build real Google SDK clients pointed at it.
Exit codes: 0 PASS, 1 FAIL, 2 BLOCKED. A probe never reports PASS for something it did not see."""
import json, os, sys, traceback, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "vyomi-project")
LOC = "us-central1"
TAG = uuid.uuid4().hex[:6]

_EP = None


def endpoint():
    global _EP
    if _EP:
        return _EP
    if os.environ.get("VYOMI_ENDPOINT"):
        _EP = os.environ["VYOMI_ENDPOINT"].rstrip("/")
        return _EP
    sys.path.insert(0, os.path.join(REPO, "examples", "enterprise-facilities-agent"))
    from facilities.server import start_in_process   # same in-process front door the AWS app uses
    cwd = os.getcwd()
    _EP = start_in_process()
    os.chdir(cwd)
    return _EP


class Blocked(Exception):
    pass


class Step:
    def __init__(self):
        self.rows = []

    def __call__(self, name, fn):
        try:
            out = fn()
            self.rows.append(("PASS", name, str(out)[:200] if out is not None else ""))
            print(f"  [PASS] {name} {'-> ' + str(out)[:160] if out is not None else ''}")
            return out
        except Blocked as e:
            self.rows.append(("BLOCKED", name, str(e)[:400]))
            print(f"  [BLOCKED] {name}: {e}")
        except Exception as e:  # noqa: BLE001
            self.rows.append(("FAIL", name, f"{type(e).__name__}: {str(e)[:500]}"))
            print(f"  [FAIL] {name}: {type(e).__name__}: {str(e)[:300]}")
        return None

    def finish(self):
        res = os.environ.get("PROBE_STEPS_OUT")
        if res:
            json.dump([{"status": s, "step": n, "detail": d} for s, n, d in self.rows], open(res, "w"))
        if any(s == "FAIL" for s, _, _ in self.rows):
            sys.exit(1)
        if any(s == "BLOCKED" for s, _, _ in self.rows):
            sys.exit(2)
        sys.exit(0)


def http():
    import requests
    s = requests.Session()
    s.headers["Authorization"] = "Bearer vyomi-local"
    s.headers["Content-Type"] = "application/json"
    return s


def call(method, path, body=None, params=None, expect=(200, 201, 204)):
    """REST call to the simulator with the same path the google API would take (used where no Python SDK exists for the API)."""
    r = http().request(method, endpoint() + path, json=body, params=params, timeout=120)
    if r.status_code not in expect:
        raise RuntimeError(f"{method} {path} -> HTTP {r.status_code}: {r.text[:400]}")
    try:
        return r.json()
    except Exception:
        return r.text


def creds():
    from google.auth.credentials import AnonymousCredentials
    return AnonymousCredentials()


def genai_client():
    from google import genai
    from google.genai import types
    from google.auth.credentials import Credentials

    class Dummy(Credentials):
        def refresh(self, request):
            self.token = "vyomi-local"
    return genai.Client(vertexai=True, project=PROJECT, location=LOC, credentials=Dummy(),
                        http_options=types.HttpOptions(base_url=endpoint(), api_version="v1"))


def rest_client(cls, **kw):
    """Official google-cloud client, REST transport, endpoint changed only (http scheme kept)."""
    from google.api_core.client_options import ClientOptions
    c = cls(credentials=creds(), transport="rest", client_options=ClientOptions(api_endpoint=endpoint()), **kw)
    try:
        c._transport._host = endpoint()
    except Exception:
        pass
    return c


def pubsub():
    """Official google-cloud-pubsub clients on the REST transport (gRPC is not served by the in-process front door)."""
    from google.cloud import pubsub_v1
    from google.api_core.client_options import ClientOptions
    opts = ClientOptions(api_endpoint=endpoint())
    pub = pubsub_v1.PublisherClient(credentials=creds(), transport="rest", client_options=opts)
    sub = pubsub_v1.SubscriberClient(credentials=creds(), transport="rest", client_options=opts)
    for c in (pub, sub):
        c._transport._host = endpoint()
    return pub, sub


DB = f"projects/{PROJECT}/databases/(default)"


def firestore_rest():
    """google-cloud-firestore's gapic client on the REST transport. (The high-level firestore.Client is gRPC-only: see probe_05.)"""
    from google.cloud.firestore_v1.services.firestore import FirestoreClient
    return rest_client(FirestoreClient)


def fs_val(v):
    if isinstance(v, bool):
        return {"booleanValue": v}
    if isinstance(v, int):
        return {"integerValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    return {"stringValue": str(v)}


def fs_set(fs, coll, doc_id, data):
    """Write a document with Commit (the gapic create_document REST binding rejects a top-level parent, so real REST users commit)."""
    from google.cloud.firestore_v1.types import Document, Write
    doc = Document(name=f"{DB}/documents/{coll}/{doc_id}", fields={k: _pv(v) for k, v in data.items()})
    return fs.commit(request={"database": DB, "writes": [Write(update=doc)]})


def fs_get(fs, coll, doc_id):
    d = fs.get_document(request={"name": f"{DB}/documents/{coll}/{doc_id}"})
    out = {}
    for k, v in d.fields.items():
        kind = v._pb.WhichOneof("value_type")
        out[k] = getattr(v, kind)
    return out


def deploy_function(name, code, env=None, runtime="python312", entry="handler"):
    """Create a Cloud Function (gen2) with the official google-cloud-functions client: generateUploadUrl -> PUT zip -> create_function."""
    import io, zipfile, requests
    from google.cloud import functions_v2 as f2
    c = rest_client(f2.FunctionServiceClient)
    parent = f"projects/{PROJECT}/locations/{LOC}"
    up = c.generate_upload_url(request={"parent": parent})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("main.py", code)
        z.writestr("requirements.txt", "functions-framework\n")
    requests.put(up.upload_url, data=buf.getvalue(), headers={"content-type": "application/zip"}, timeout=60).raise_for_status()
    fn = f2.Function(name=f"{parent}/functions/{name}", build_config=f2.BuildConfig(runtime=runtime, entry_point=entry,
                     source=f2.Source(storage_source=up.storage_source)),
                     service_config=f2.ServiceConfig(environment_variables=env or {}, available_memory="256M", timeout_seconds=60))
    res = c.create_function(request={"parent": parent, "function": fn, "function_id": name}).result(timeout=120)
    return res


def invoke_function(name, payload):
    import requests
    r = requests.post(f"{endpoint()}/gcf/{PROJECT}/{LOC}/{name}", json=payload, headers={"Authorization": "Bearer vyomi-local"}, timeout=60)
    return r


def _pv(v):
    from google.cloud.firestore_v1.types import Value
    if isinstance(v, bool):
        return Value(boolean_value=v)
    if isinstance(v, int):
        return Value(integer_value=v)
    if isinstance(v, float):
        return Value(double_value=v)
    return Value(string_value=str(v))


def storage():
    from google.cloud import storage
    from google.api_core.client_options import ClientOptions
    return storage.Client(project=PROJECT, credentials=creds(), client_options=ClientOptions(api_endpoint=endpoint()))


DOC = ("Boiler pressure limit: the boiler must not exceed 30 psi. If pressure exceeds 30 psi, shut the burner and call the duty engineer. "
       "Chiller plant on level 3 is serviced every quarter. Elevator maintenance contract renews in March.")


def vertex_client(api_version="v1beta1"):
    """vertexai.Client (google-cloud-aiplatform 2.x, HTTP via google-genai) pointed at the simulator."""
    import vertexai
    from google.genai import types
    from google.auth.credentials import Credentials

    class Dummy(Credentials):
        def refresh(self, request):
            self.token = "vyomi-local"
    return vertexai.Client(project=PROJECT, location=LOC, credentials=Dummy(), http_options=types.HttpOptions(base_url=endpoint(), api_version=api_version))
