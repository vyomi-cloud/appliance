/* Browser Python runner for Vyomi Labs (module worker). Loads Pyodide + the AWS SDK for Python and runs a lab block against the in-browser Nano backend.
 * Same-origin, so the Nano service worker answers the SDK's calls exactly as it answers the console's. Messages in: {id, files:{name:code}, run:"python x.py", env:{}}.
 * Messages out: {id, type:"log"|"done", text|ok}. */
const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.26.2/full/";

/* Browser transport for the AWS SDK: botocore's own connection class cannot run in a browser, so its send() is replaced by a synchronous XHR (allowed in workers).
 * The URL/headers are routed like the console does: local = the Nano service worker answers; mesh = the request goes to the Mesh (all of it when a Mesh-homed
 * space is active, only compute/AI calls when a portal session Mesh is running). _route is set by the page before each run. */
const SHIM = `
import io, re, js
from pyodide.ffi import to_js
import botocore.httpsession as hs
from botocore.awsrequest import AWSResponse
from botocore.exceptions import EndpointConnectionError

ROUTE = {"mesh": None}
class _Raw(io.BytesIO):
    def stream(self, amt=1024, decode_content=None):
        while True:
            b = self.read(amt)
            if not b: break
            yield b

def _target(request):
    url, headers = request.url, dict(request.headers.items())
    m = ROUTE.get("mesh")
    if m:
        i = url.find("/_wire")
        path = url[i + 6:] if i >= 0 else ""
        compute = re.search(m["scope"], headers.get("Authorization", "") or "") or re.search(m["path"], path)
        if m["all"] or compute:
            url = m["base"] + "/_wire" + path
            headers.update(m["headers"])
    return url, headers

def _send(self, request):
    url, headers = _target(request)
    x = js.XMLHttpRequest.new()
    x.open(request.method, url, False)
    x.responseType = "arraybuffer"
    for k, v in headers.items():
        if k.lower() in ("host", "content-length", "connection", "user-agent", "accept-encoding", "expect"): continue
        x.setRequestHeader(k, v if isinstance(v, str) else v.decode())
    body = request.body
    if body is None: x.send()
    elif isinstance(body, str): x.send(body)
    else: x.send(to_js(bytes(body)))
    if x.status == 0:
        raise EndpointConnectionError(endpoint_url=url)
    data = bytes(js.Uint8Array.new(x.response).to_py())
    hdrs = {}
    for line in str(x.getAllResponseHeaders()).strip().splitlines():
        if ":" in line:
            k, v = line.split(":", 1); hdrs[k.strip()] = v.strip()
    return AWSResponse(url, int(x.status), hdrs, _Raw(data))

hs.URLLib3Session.send = _send
`;
let py = null, ready = null;
async function boot(post) {
  const { loadPyodide } = await import(PYODIDE + "pyodide.mjs");
  py = await loadPyodide({ indexURL: PYODIDE });
  post("Loading the AWS SDK for Python (first run only)...");
  await py.loadPackage(["micropip", "ssl", "urllib3", "six", "python-dateutil", "requests"]);
  await py.runPythonAsync("import micropip\nawait micropip.install(['jmespath','botocore','boto3','s3transfer'], deps=False)");
  await py.runPythonAsync(SHIM);
}
self.onmessage = async (ev) => {
  const { id, files, run, env, route } = ev.data;
  const out = (text) => self.postMessage({ id, type: "log", text });
  try {
    ready = ready || boot(out);
    await ready;
    for (const [n, c] of Object.entries(files || {})) py.FS.writeFile("/home/pyodide/" + n, c);
    py.globals.set("_env", py.toPy(env || {}));
    py.globals.set("_routecfg", py.toPy(route || null));
    py.globals.set("_cmd", run || "");
    py.setStdout({ batched: (s) => out(s) }); py.setStderr({ batched: (s) => out(s) });
    await py.runPythonAsync(`
import os, sys, runpy
os.chdir("/home/pyodide"); sys.path.insert(0, "/home/pyodide")
os.environ.update({k: str(v) for k, v in dict(_env).items()})
import __main__ as _m
_m.ROUTE['mesh'] = dict(_routecfg) if _routecfg else None
if _cmd:
    runpy.run_path(_cmd.split()[1], run_name="__main__")
`);
    self.postMessage({ id, type: "done", ok: true });
  } catch (e) { out(String(e.message || e).split("\n").slice(-6).join("\n")); self.postMessage({ id, type: "done", ok: false }); }
};
