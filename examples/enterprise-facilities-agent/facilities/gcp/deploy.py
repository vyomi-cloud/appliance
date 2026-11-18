"""Provisioning helpers: deploy Cloud Run functions (gen2, google-cloud-functions: generateUploadUrl -> PUT zip -> CreateFunction), seed Firestore."""
import io, json, os, zipfile
from .runtime import NAMES, fixture_dir

FUNCS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "functions")


def main_py(module):
    """One self-contained main.py per function: the shared tool code (tools.py) is inlined ahead of the entry module, so a function never
    imports a sibling file."""
    tools = open(os.path.join(FUNCS, "tools.py")).read()
    entry = "".join(l for l in open(os.path.join(FUNCS, module + ".py")) if not l.startswith("from tools import"))
    return tools + "\n\n" + entry


def zip_of(module):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("main.py", main_py(module))
        z.write(os.path.join(FUNCS, "requirements.txt"), "requirements.txt")
    return b.getvalue()


def function_env(ctx, extra=None):
    """Environment a function needs on the simulator: the standard Firestore emulator variable plus the Vertex REST endpoint used by the RAG client."""
    env = dict(GOOGLE_CLOUD_PROJECT=ctx.project, GOOGLE_CLOUD_REGION=ctx.loc, FIRESTORE_EMULATOR_HOST=ctx.firestore_host,
               VERTEX_API_ENDPOINT=ctx.endpoint, RAG_CORPUS=ctx.state.get("rag_corpus", ""), ASSETS_COLLECTION=NAMES["assets"],
               WORK_ORDERS_COLLECTION=NAMES["work_orders"], LEDGER_COLLECTION=NAMES["ledger"], DOCS_BUCKET=NAMES["bucket"])
    env.update(extra or {})
    return env


def deploy_function(ctx, name, module, extra_env=None, event_trigger=None, cloudevent=False):
    """Create (or update) a function; returns its HTTPS URI."""
    import requests
    from google.api_core import exceptions as gex
    from google.cloud import functions_v2 as f2
    fc = ctx.rest(f2.FunctionServiceClient)
    up = fc.generate_upload_url(request={"parent": ctx.parent})
    requests.put(up.upload_url, data=zip_of(module), headers={"content-type": "application/zip"}, timeout=60).raise_for_status()
    fn = f2.Function(name=f"{ctx.parent}/functions/{name}",
                     build_config=f2.BuildConfig(runtime="python312", entry_point="handler", source=f2.Source(storage_source=up.storage_source),
                                                 environment_variables={"GOOGLE_FUNCTION_SIGNATURE_TYPE": "cloudevent"} if cloudevent else {}),
                     service_config=f2.ServiceConfig(environment_variables=function_env(ctx, extra_env), available_memory="512M", timeout_seconds=120))
    try:
        fc.get_function(request={"name": fn.name})
        res = fc.update_function(request={"function": fn}).result(timeout=120)
    except gex.NotFound:
        res = fc.create_function(request={"parent": ctx.parent, "function": fn, "function_id": name}).result(timeout=120)
    uri = res.service_config.uri or f"{ctx.endpoint}/gcf/{ctx.project}/{ctx.loc}/{name}"
    ctx.state.setdefault("_fn_module", {})[uri] = (module, function_env(ctx, extra_env))
    return uri


class _Req:
    """Minimal Flask-style request for the DEV local-function mode."""
    def __init__(self, body):
        self._b, self.headers = body, {}

    def get_json(self, silent=False):
        return self._b


def _call_local(ctx, uri, payload):
    """DEV ONLY (run_e2e.py --dev-local-functions): run the function's handler in THIS process instead of in the simulator's function sandbox, so the rest of the
    app logic can be exercised before the sandbox lane lands. A run in this mode is never a conformance result."""
    module, env = ctx.state["_fn_module"][uri]
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        ns = {"__name__": "function_main"}
        exec(compile(main_py(module), module + ".py", "exec"), ns)
        return ns["handler"](_Req(payload))
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def call_function(ctx, uri, payload, timeout=120):
    """HTTPS call to a function (google-auth AuthorizedSession; on real GCP the credential is an ID token for the function's audience)."""
    if getattr(ctx, "local_functions", False):
        return _call_local(ctx, uri, payload)
    r = ctx.authed_session().post(uri, json=payload, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"function {uri.rsplit('/', 1)[-1]} HTTP {r.status_code}: {r.text[:400]}")
    return r.json()


def fixture(name):
    with open(os.path.join(fixture_dir(), name)) as f:
        return json.load(f)


def seed(ctx, collection, rows, key):
    db = ctx.firestore()
    for r in rows:
        db.collection(collection).document(str(r[key])).set(r)
