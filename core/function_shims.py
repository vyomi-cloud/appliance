"""Shim modules + request/response plumbing for user function code (flask / functions_framework / azure.functions).

Pure Python, no I/O imports: used by the offline subprocess harness (core/gcp_function_runtime) AND by Nano's
in-browser Pyodide sandbox (core/gcp_console_tabs.run_python_function), so a function behaves the same in both.
"""
import types as _types

FLASK_SHIM = '''
import json as _json
class Response:
    def __init__(self, response=b"", status=200, headers=None, mimetype=None, content_type=None):
        self.data = response if isinstance(response, (bytes, bytearray)) else str(response).encode()
        self.status_code = int(status)
        self.headers = dict(headers or {})
        ct = content_type or mimetype
        if ct:
            self.headers["Content-Type"] = ct
    status = property(lambda s: s.status_code)
def jsonify(*a, **kw):
    obj = a[0] if len(a) == 1 and not kw else (list(a) if a else kw)
    return Response(_json.dumps(obj), 200, mimetype="application/json")
def make_response(*a):
    if len(a) == 1 and isinstance(a[0], Response):
        return a[0]
    body = a[0] if a else ""
    status = a[1] if len(a) > 1 and isinstance(a[1], int) else 200
    hdrs = a[-1] if len(a) > 1 and isinstance(a[-1], dict) else None
    if isinstance(body, (dict, list)):
        return Response(_json.dumps(body), status, hdrs, mimetype="application/json")
    return Response(body, status, hdrs, mimetype="text/html; charset=utf-8")
def abort(code, description=None):
    raise _Abort(code, description)
class _Abort(Exception):
    def __init__(self, code, description=None):
        super().__init__(description or str(code)); self.code = code; self.description = description
'''

FF_SHIM = '''
def http(fn):
    return fn
def cloud_event(fn):
    return fn
'''

AZ_FUNCTIONS_SHIM = '''
import json as _json
class AuthLevel:
    ANONYMOUS = "anonymous"; FUNCTION = "function"; ADMIN = "admin"
class HttpRequest:
    def __init__(self, method, url, headers=None, params=None, route_params=None, body=b""):
        self.method = method; self.url = url; self.headers = headers or {}
        self.params = params or {}; self.route_params = route_params or {}; self._body = body or b""
    def get_body(self):
        return self._body
    def get_json(self):
        try:
            return _json.loads(self._body.decode("utf-8"))
        except Exception:
            raise ValueError("req_body is not JSON serializable")
class HttpResponse:
    def __init__(self, body=None, *, status_code=200, headers=None, mimetype=None, charset="utf-8"):
        if isinstance(body, str): body = body.encode(charset)
        self._body = body or b""
        self.status_code = int(status_code); self.headers = dict(headers or {})
        if mimetype: self.headers["Content-Type"] = mimetype
        elif "Content-Type" not in self.headers and "content-type" not in self.headers:
            self.headers["Content-Type"] = "text/plain; charset=utf-8"
    def get_body(self): return self._body
    data = property(lambda s: s._body)
class FunctionApp:
    def __init__(self, http_auth_level=None):
        self.fns = {}
    def _reg(self, fn): self.fns[fn.__name__] = fn; return fn
    def route(self, route=None, methods=None, auth_level=None, **kw):
        def deco(fn):
            fn._route = route or fn.__name__; return self._reg(fn)
        return deco
    def function_name(self, name=None, **kw):
        def deco(fn): self.fns[name or fn.__name__] = fn; return fn
        return deco
    def __getattr__(self, n):   # timer_trigger / queue_trigger / ... decorators: register, return fn
        def trig(*a, **k):
            return lambda fn: self._reg(fn)
        return trig
'''

# Request / response plumbing. Expects `_flask` (the flask shim module) plus json, base64, urllib.parse in scope.
SUPPORT_SRC = r'''class _Headers(dict):
    def __init__(self, d):
        super().__init__({k.title(): v for k, v in d.items()})
    def get(self, k, default=None):
        return dict.get(self, str(k).title(), default)
    def __getitem__(self, k):
        return dict.__getitem__(self, str(k).title())
    def __contains__(self, k):
        return dict.__contains__(self, str(k).title())

class Request:
    def __init__(self, r):
        self.method = r["method"]; self.path = r["path"]
        self.query_string = r["query"].encode(); self.full_path = r["path"] + "?" + r["query"]
        self.url = r.get("url", ""); self.base_url = self.url.split("?")[0]
        self.headers = _Headers(r["headers"])
        self.data = base64.b64decode(r["body_b64"])
        self.args = _Args(urllib.parse.parse_qs(r["query"], keep_blank_values=True))
        self.content_type = self.headers.get("Content-Type", "")
        self.mimetype = self.content_type.split(";")[0].strip()
        self.is_json = self.mimetype == "application/json" or self.mimetype.endswith("+json")
        self.remote_addr = r.get("remote_addr", "")
        self.cookies = {}; self.files = {}
        self.form = _Args(urllib.parse.parse_qs(self.data.decode("utf-8", "replace"), keep_blank_values=True)) \
            if self.mimetype == "application/x-www-form-urlencoded" else _Args({})
        self.values = _Args({**{k: v for k, v in self.args.lists()}, **{k: v for k, v in self.form.lists()}})
    def get_data(self, as_text=False, cache=True, parse_form_data=False):
        return self.data.decode("utf-8", "replace") if as_text else self.data
    def get_json(self, force=False, silent=False, cache=True):
        if not (force or self.is_json):
            if silent: return None
            raise _flask._Abort(415, "Content-Type was not 'application/json'")
        try:
            return json.loads(self.data.decode("utf-8")) if self.data else None
        except Exception:
            if silent: return None
            raise _flask._Abort(400, "Failed to decode JSON object")
    json = property(lambda s: s.get_json())
    text = property(lambda s: s.data.decode("utf-8", "replace"))

class _Args(dict):
    def __init__(self, m):
        super().__init__({k: v[0] if isinstance(v, list) and v else v for k, v in m.items()})
        self._m = m
    def getlist(self, k): return list(self._m.get(k, []))
    def lists(self): return self._m.items()
    def to_dict(self, flat=True): return dict(self)

def _norm(rv):
    status, headers = 200, {}
    if isinstance(rv, tuple):
        if len(rv) == 3: rv, status, headers = rv
        elif len(rv) == 2:
            rv, x = rv
            if isinstance(x, dict): headers = x
            else: status = x
        else: rv = rv[0]
    if isinstance(rv, _flask.Response):
        h = dict(rv.headers); h.update(headers or {})
        return rv.status_code if status == 200 else int(status), h, rv.data
    if hasattr(rv, "status_code") and hasattr(rv, "data"):     # a real framework Response
        return int(rv.status_code), dict(getattr(rv, "headers", {}) or {}), bytes(rv.data)
    h = dict(headers or {})
    if rv is None:
        return 500, {"Content-Type": "text/html; charset=utf-8"}, b"The view function did not return a valid response."
    if isinstance(rv, (dict, list)):
        h.setdefault("Content-Type", "application/json"); body = json.dumps(rv).encode()
    elif isinstance(rv, (bytes, bytearray)):
        h.setdefault("Content-Type", "application/octet-stream"); body = bytes(rv)
    else:
        h.setdefault("Content-Type", "text/html; charset=utf-8"); body = str(rv).encode()
    return int(status), h, body

class CloudEvent(dict):
    """functions_framework CloudEvent: dict of attributes + .data"""
    def __init__(self, attributes, data=None):
        super().__init__(attributes); self.data = data; self._attributes = dict(attributes)
    def get_attributes(self): return dict(self._attributes)
    def get_data(self): return self.data

'''


def make_modules():
    """name -> module for the sandbox's import hook (flask, functions_framework, azure, azure.functions)."""
    mods = {}
    for name, src in (("flask", FLASK_SHIM), ("functions_framework", FF_SHIM)):
        m = _types.ModuleType(name)
        exec(compile(src, name, "exec"), m.__dict__)
        mods[name] = m
    fn = _types.ModuleType("azure.functions")
    exec(compile(AZ_FUNCTIONS_SHIM, "azure.functions", "exec"), fn.__dict__)
    az = _types.ModuleType("azure")
    az.functions = fn
    mods["azure"] = az
    mods["azure.functions"] = fn
    return mods


def support_namespace(mods=None):
    """Namespace with Request, _norm, CloudEvent ready to use (Nano sandbox)."""
    import base64, json, urllib.parse
    mods = mods or make_modules()
    ns = {"_flask": mods["flask"], "json": json, "base64": base64, "urllib": urllib}
    exec(compile(SUPPORT_SRC, "support", "exec"), ns)
    return ns
