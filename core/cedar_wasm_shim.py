"""cedarpy-compatible facade over the OSS Cedar engine for substrates where the native binding is absent.

Thumb rule: no hand-written policy evaluator. On the Mesh / host the real ``cedarpy`` (Rust, Apache-2.0) is used. Under
Nano (Pyodide) cedarpy cannot load, so the same Cedar Rust core is used compiled to WebAssembly (``@cedar-policy/cedar-wasm``
4.14.0, Apache-2.0, 4.4 MB, vendored same-origin in wasm/cedar/). The page / relay worker installs
``globalThis.__vyomi_cedar_eval(json) -> json`` (wasm/cedar/cedar-eval.mjs); this module calls it synchronously.

``cedarpy`` below is the real module when importable, else a facade (Pyodide only), else None.
"""
import json
import re

_UID = re.compile(r'^(.*)::"((?:[^"\\]|\\.)*)"$')


class CedarUnavailable(RuntimeError):
    pass


class _Diag:
    def __init__(self, d):
        self.reason = list(d.get("reason") or [])
        self.errors = [e.get("error", e) if isinstance(e, dict) else e for e in (d.get("errors") or [])]


class _Result:
    def __init__(self, resp):
        self.decision = "Decision." + ("Allow" if str(resp.get("decision")).lower() == "allow" else "Deny")
        self.diagnostics = _Diag(resp.get("diagnostics") or {})
        self.allowed = self.decision == "Decision.Allow"


def _uid(s):
    if isinstance(s, dict):
        return s
    m = _UID.match(str(s))
    if not m:
        raise ValueError(f"bad entity uid {s!r}")
    return {"type": m.group(1), "id": m.group(2).replace('\\"', '"').replace("\\\\", "\\")}


class _WasmCedar:
    engine = "cedar-wasm"

    @staticmethod
    def _fn():
        try:
            import js  # type: ignore
        except ImportError:
            raise CedarUnavailable("not a browser substrate")
        fn = getattr(js.globalThis, "__vyomi_cedar_eval", None)
        if fn is None:
            raise CedarUnavailable("the in-browser Cedar evaluator (cedar-wasm) is not loaded in this context")
        return fn

    def is_authorized(self, request, policies, entities, schema=None, verbose=False):
        fn = self._fn()
        call = {"principal": _uid(request["principal"]), "action": _uid(request["action"]), "resource": _uid(request["resource"]),
                "context": request.get("context") or {}, "policies": {"staticPolicies": policies}, "entities": entities or [],
                "validateRequest": False}
        ans = json.loads(str(fn(json.dumps(call))))
        if ans.get("type") != "success":
            msgs = "; ".join(str(e.get("message", e)) if isinstance(e, dict) else str(e) for e in ans.get("errors") or [])
            raise ValueError(msgs or "cedar evaluation failed")
        return _Result(ans["response"])


try:
    import cedarpy  # type: ignore
except ImportError:
    try:
        import js  # type: ignore  # noqa: F401  (Pyodide only)
        cedarpy = _WasmCedar()
    except ImportError:
        cedarpy = None  # type: ignore[assignment]
