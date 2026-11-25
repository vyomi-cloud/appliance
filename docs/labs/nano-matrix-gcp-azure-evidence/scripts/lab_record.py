"""Like vyomilabs.labrun but every lab block runs under a request recorder (requests + httpx) -> JSONL. Usage: lab_record.py <cloud> <out.jsonl> <layers...>"""
import os, sys, subprocess, tempfile, importlib, json
sys.path.insert(0, os.getcwd())
PRELUDE = r'''
import os, sys, json, base64, runpy, threading
_L = threading.Lock(); _OUT = os.environ["LABREC_OUT"]; _TAG = os.environ["LABREC_TAG"]
def _log(method, url, headers, body, status, rbody):
    try:
        if isinstance(body, str): body = body.encode()
        if body is not None and not isinstance(body, (bytes, bytearray)): body = b""
        rec = dict(tag=_TAG, method=method, url=str(url), headers={str(k): (v if isinstance(v, str) else v.decode()) for k, v in dict(headers or {}).items() if str(k).lower() not in ("host","content-length","connection","accept-encoding","user-agent","traceparent","x-ms-client-request-id","x-ms-date","x-ms-useragent")},
                   body_b64=base64.b64encode(bytes(body or b"")[:200000]).decode(), status=status, rhead=(rbody or b"")[:700].decode("utf8", "replace"))
        with _L, open(_OUT, "a") as f: f.write(json.dumps(rec) + "\n")
    except Exception: pass
try:
    import requests
    _o = requests.Session.send
    def _s(self, req, **kw):
        r = _o(self, req, **kw); _log(req.method, req.url, req.headers, req.body, r.status_code, r.content if not kw.get("stream") else b""); return r
    requests.Session.send = _s
except ImportError: pass
try:
    import httpx
    _ho = httpx.Client.send
    def _hs(self, req, **kw):
        r = _ho(self, req, **kw)
        try: rb = r.read() if not kw.get("stream") else b""
        except Exception: rb = b""
        _log(req.method, req.url, req.headers, req.content, r.status_code, rb); return r
    httpx.Client.send = _hs
except ImportError: pass
runpy.run_path(sys.argv[1], run_name="__main__")
'''
def main():
    cloud, out, layers = sys.argv[1], sys.argv[2], [int(x) for x in sys.argv[3:]]
    endpoint, env = importlib.import_module(f"vyomilabs.labenv_{cloud}").start(None)
    lab = importlib.import_module(f"vyomilabs.content.labs_{cloud}").LAB
    work = tempfile.mkdtemp(prefix="vy-labrec-"); env = dict(env, PYTHONPATH=work, LABREC_OUT=out)
    open(os.path.join(work, "_prelude.py"), "w").write(PRELUDE)
    open(out, "w").close()
    for lid in layers:
        for blk in lab[lid]:
            open(os.path.join(work, blk["file"]), "w").write(blk["code"])
            if not blk["run"]: continue
            if blk.get("needs_runtime"): continue
            tag = f"{lid}:{blk['file']}"
            p = subprocess.run([sys.executable, os.path.join(work, "_prelude.py"), blk["run"].split()[1]], cwd=work, env=dict(env, LABREC_TAG=tag), capture_output=True, text=True, timeout=180)
            ok = p.returncode == 0 and (not blk["expect"] or blk["expect"] in p.stdout)
            print(("PASS " if ok else "FAIL ") + tag, flush=True)
    print("endpoint", endpoint)
main()
