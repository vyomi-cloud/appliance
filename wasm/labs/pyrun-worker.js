/* Browser Python runner for Vyomi Labs (module worker). Loads Pyodide + the AWS SDK for Python and runs a lab block against the in-browser Nano backend.
 * Same-origin, so the Nano service worker answers the SDK's calls exactly as it answers the console's. Messages in: {id, files:{name:code}, run:"python x.py", env:{}}.
 * Messages out: {id, type:"log"|"done", text|ok}. */
const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.26.2/full/";
let py = null, ready = null;
async function boot(post) {
  const { loadPyodide } = await import(PYODIDE + "pyodide.mjs");
  py = await loadPyodide({ indexURL: PYODIDE });
  post("Loading the AWS SDK for Python (first run only)...");
  await py.loadPackage(["micropip", "ssl", "urllib3", "six", "python-dateutil", "jmespath"]);
  await py.runPythonAsync("import micropip\nawait micropip.install(['botocore','boto3','s3transfer'], deps=False)");
}
self.onmessage = async (ev) => {
  const { id, files, run, env } = ev.data;
  const out = (text) => self.postMessage({ id, type: "log", text });
  try {
    ready = ready || boot(out);
    await ready;
    for (const [n, c] of Object.entries(files || {})) py.FS.writeFile("/home/pyodide/" + n, c);
    py.globals.set("_env", py.toPy(env || {}));
    py.globals.set("_cmd", run);
    py.setStdout({ batched: (s) => out(s) }); py.setStderr({ batched: (s) => out(s) });
    await py.runPythonAsync(`
import os, sys, runpy
os.chdir("/home/pyodide"); sys.path.insert(0, "/home/pyodide")
os.environ.update({k: str(v) for k, v in _env.to_py().items()})
runpy.run_path(_cmd.split()[1], run_name="__main__")
`);
    self.postMessage({ id, type: "done", ok: true });
  } catch (e) { out(String(e.message || e).split("\n").slice(-6).join("\n")); self.postMessage({ id, type: "done", ok: false }); }
};
