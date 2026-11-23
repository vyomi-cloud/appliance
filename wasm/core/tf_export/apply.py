# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Terraform IMPORT / APPLY: the inverse of the exporter. Takes a Terraform bundle (the exporter's own output or hand-written
configs), plans what it would create in Vyomi, and creates it through the SAME native AWS API the SDK uses (boto3-shaped clients,
see ``wire_clients``), resolving references to the real ids created earlier. Re-applying changes nothing (existing resources are found by
their natural keys and skipped) and what an import created can be destroyed.

Types are added with a small decorator, like the exporter's ``@exporter``::

    @applier("aws_x")
    class X:
        def find(self, c, a): ...      # outputs of the existing object, or None   (outputs hold what delete() needs: ids, names)
        def create(self, c, a): ...    # make it, return its outputs (always include "id")
        def delete(self, c, out): ...  # remove it from its outputs

``c`` is the run context (``c.cl["ec2"]`` clients, ``c.region``, ``c.account``); ``a`` is the evaluated resource (``a.attrs``,
``a.blocks``, ``a.get(k)``, ``a.tags``).
"""
from __future__ import annotations

import base64
from typing import Any, Callable

from core.tf_export import hcl_parse as hp

ACCOUNT_ID = "123456789012"
_META_ATTRS = frozenset({"count", "for_each", "depends_on", "provider", "lifecycle", "provisioner", "connection", "timeouts"})
_META_BLOCKS = frozenset({"lifecycle", "provisioner", "connection", "timeouts"})

_APPLIERS: dict[str, Any] = {}
_DATA: dict[str, Callable] = {}


def applier(rtype: str):
    """Register an applier class (or a bare ``create(c, a)`` function) for a Terraform resource type."""
    def deco(obj):
        _APPLIERS[rtype] = obj() if isinstance(obj, type) else _FnApplier(obj)
        return obj
    return deco


def data_source(rtype: str):
    """Register a data-source reader: ``fn(c, attrs) -> dict``."""
    def deco(fn):
        _DATA[rtype] = fn
        return fn
    return deco


class _FnApplier:
    def __init__(self, create):
        self.create = create

    def find(self, c, a):
        return None

    def delete(self, c, out):
        raise NotImplementedError("no delete for this type")


def applier_types() -> set[str]:
    _load()
    return set(_APPLIERS)


def _load() -> None:
    import core.tf_export  # noqa: F401  (imports every aws_*.py, each registers its exporter/applier)
    from core.tf_export import aws_apply  # noqa: F401


# --------------------------------------------------------------------------------------------------------- run context
_THROTTLE = ("Throttl", "RequestLimitExceeded", "SlowDown", "TooManyRequests", "Rate exceeded")


class _Retry:
    """Wraps a boto3-shaped client: retries throttled calls with backoff (the free tier allows 10 requests/second, Terraform's provider does the same)."""

    def __init__(self, client):
        self._c = client

    def __getattr__(self, name):
        attr = getattr(self._c, name)
        if name.startswith("_") or not callable(attr) or name == "get_paginator":
            return attr

        def call(**kw):
            import time
            delay = 0.12
            for attempt in range(9):
                try:
                    return attr(**kw)
                except Exception as exc:  # noqa: BLE001
                    resp = getattr(exc, "response", None) or {}
                    code = str((resp.get("Error") or {}).get("Code") or "")
                    msg = str((resp.get("Error") or {}).get("Message") or "")
                    if attempt == 8 or not any(t in code or t in msg for t in _THROTTLE):
                        raise
                    time.sleep(delay)
                    delay = min(delay * 1.7, 2.0)
        return call


class Ctx:
    def __init__(self, clients: dict[str, Any], region: str):
        self.cl = {k: _Retry(v) for k, v in clients.items()}
        self.region = region
        self.account = ACCOUNT_ID
        self.claimed: set[str] = set()   # ids already matched by another resource in this run (duplicates with identical keys)
        self.file_bytes = lambda path: (_ for _ in ()).throw(hp.HclError(f"file not found in the bundle: {path}"))

    def __getattr__(self, name):
        if name in ("cl", "region", "account") or name.startswith("_"):
            raise AttributeError(name)
        return self.cl[name.rstrip("_")]


class Inst:
    """One evaluated resource instance handed to an applier."""

    def __init__(self, rtype, name, key, attrs, blocks, address):
        self.type, self.name, self.key, self.attrs, self.blocks, self.address = rtype, name, key, attrs, blocks, address

    def get(self, k, default=None):
        v = self.attrs.get(k)
        return default if v is None else v

    def blocks_of(self, btype):
        return [b for b in self.blocks if b[0] == btype]

    @property
    def tags(self) -> dict:
        return {str(k): ("" if v is None else str(v)) for k, v in (self.attrs.get("tags") or {}).items()}

    def subst(self, v, **outputs):
        """Replace references this resource made to itself (``SelfRef``) with its real outputs."""
        if isinstance(v, hp.SelfRef):
            return outputs[v.attr]
        if isinstance(v, dict):
            return {k: self.subst(x, **outputs) for k, x in v.items()}
        if isinstance(v, list):
            return [self.subst(x, **outputs) for x in v]
        if isinstance(v, tuple):
            return tuple(self.subst(x, **outputs) for x in v)
        return v


class _SelfObj(dict):
    def __contains__(self, k):
        return True

    def __getitem__(self, k):
        return hp.SelfRef(k)


def _scalars(d: dict) -> dict:
    return {k: v for k, v in d.items() if isinstance(v, (str, int, float, bool)) or v is None}


# ---------------------------------------------------------------------------------------------------------------- scope
class _Scope:
    def __init__(self, run: "Run"):
        self.run = run
        self.cur: str | None = None  # base address of the resource being evaluated
        self._each = None
        self._idx = None
        self._self: dict | None = None
        self._locals_busy: set[str] = set()

    def each(self):
        if self._each is None:
            raise hp.HclError("each.key used outside for_each")
        return self._each

    def count_index(self):
        if self._idx is None:
            raise hp.HclError("count.index used outside count")
        return self._idx

    def var(self, name):
        return self.run.var(name)

    def local(self, name):
        r = self.run
        if name in r.local_cache:
            return r.local_cache[name]
        if name not in r.cfg.locals:
            raise hp.HclError(f"undefined local.{name}")
        if name in self._locals_busy:
            raise hp.HclError(f"local.{name} refers to itself")
        self._locals_busy.add(name)
        try:
            v = hp.Evaluator(self).ev(r.cfg.locals[name])
        finally:
            self._locals_busy.discard(name)
        r.local_cache[name] = v
        return v

    def resource(self, rtype, name):
        base = f"{rtype}.{name}"
        if base == self.cur:
            return _SelfObj()
        if base not in self.run.cfg.resources:
            raise hp.HclError(f"reference to undeclared resource {base}")
        st = self.run.state.get(base)
        if st is None:
            raise hp.Unknown([base])
        return st

    def data(self, rtype, name):
        key = f"data.{rtype}.{name}"
        return self.run.data(key)

    def self_attr(self, name):
        raise hp.HclError("self is not supported")

    def file(self, path):
        return self.run.file_bytes(path).decode("utf-8")

    def file_bytes(self, path):
        return self.run.file_bytes(path)


# -------------------------------------------------------------------------------------------------------------------- run
class Run:
    def __init__(self, files: dict[str, str], binaries: dict[str, bytes] | None, variables: dict | None, clients, region: str):
        self.files = {k: v for k, v in files.items() if isinstance(v, str)}
        self.binaries = binaries or {}
        self.cfg = hp.parse_config(self.files)
        self.overrides = variables or {}
        self.c = Ctx(clients, region)
        self.c.file_bytes = self.file_bytes
        self.state: dict[str, Any] = {}      # base address -> value as seen by references
        self.local_cache: dict[str, Any] = {}
        self.var_cache: dict[str, Any] = {}
        self.data_cache: dict[str, Any] = {}
        self.scope = _Scope(self)

    # --- inputs
    def file_bytes(self, path: str) -> bytes:
        p = str(path).replace("\\", "/")
        while p.startswith("./"):
            p = p[2:]
        for cand in (p, p.lstrip("/")):
            if cand in self.binaries:
                return self.binaries[cand]
            if cand in self.files:
                return self.files[cand].encode("utf-8")
        raise hp.HclError(f"file not found in the bundle: {path}")

    def var(self, name: str):
        if name in self.var_cache:
            return self.var_cache[name]
        if name not in self.cfg.variables:
            raise hp.HclError(f"undeclared variable var.{name}")
        body = self.cfg.variables[name]
        if name in self.overrides:
            v = self.overrides[name]
        elif name in self.cfg.tfvars:
            v = self.cfg.tfvars[name]
        elif "default" in body.attrs:
            v = hp.Evaluator(self.scope).ev(body.attrs["default"])
        else:
            raise hp.HclError(f"No value for required variable {name} (add it to terraform.tfvars or the variables box)")
        t = body.attrs.get("type")
        if t and t[0] == "name":
            if t[1] == "string" and isinstance(v, (int, float)) and not isinstance(v, bool):
                v = hp._tostr(v)
            elif t[1] == "number" and isinstance(v, str):
                v = hp._num(v)
        self.var_cache[name] = v
        return v

    def required_variables(self) -> list[dict]:
        out = []
        for n, b in sorted(self.cfg.variables.items()):
            has = n in self.overrides or n in self.cfg.tfvars
            out.append({"name": n, "has_default": "default" in b.attrs, "provided": has,
                        "sensitive": bool(b.attrs.get("sensitive") and b.attrs["sensitive"] == ("lit", True))})
        return out

    def data(self, key: str):
        if key in self.data_cache:
            return self.data_cache[key]
        d = self.cfg.data.get(key)
        if d is None:
            raise hp.HclError(f"reference to undeclared data source {key}")
        fn = _DATA.get(d.type)
        if fn is None:
            raise hp.HclError(f"data source {d.type} is not supported yet")
        ev = hp.Evaluator(self.scope)
        attrs, _blocks = hp.eval_body(d.body, ev)
        v = fn(self.c, attrs)
        self.data_cache[key] = v
        return v

    # --- structure
    def expand(self, d: hp.ResourceDef) -> list[tuple[Any, Any]]:
        """[(key, each_value)] for a resource definition; ``[(None, None)]`` for a plain one."""
        ev = hp.Evaluator(self.scope)
        self.scope.cur = None
        if "count" in d.body.attrs:
            n = int(hp._num(ev.ev(d.body.attrs["count"])))
            return [(i, None) for i in range(n)]
        if "for_each" in d.body.attrs:
            fe = ev.ev(d.body.attrs["for_each"])
            if isinstance(fe, dict):
                return [(k, {"key": k, "value": v}) for k, v in fe.items()]
            return [(str(x), {"key": str(x), "value": x}) for x in fe]
        return [(None, None)]

    def deps_of(self, d: hp.ResourceDef) -> set[str]:
        refs = hp.body_references(d.body)
        out = set()
        for r in refs:
            if r in self.cfg.resources and r != d.addr:
                out.add(r)
        return out

    def order(self) -> list[str]:
        deps = {a: self.deps_of(d) for a, d in self.cfg.resources.items()}
        rank: dict[str, int] = {}
        done: list[str] = []
        remaining = set(deps)
        while remaining:
            ready = sorted(a for a in remaining if deps[a] <= set(done))
            if not ready:
                raise hp.HclError("dependency cycle between: " + ", ".join(sorted(remaining)))
            done.extend(ready)
            remaining -= set(ready)
        return done


def _addr(base: str, key) -> str:
    return base if key is None else f"{base}[{key}]" if isinstance(key, int) else f'{base}["{key}"]'


def _availability(rtype: str) -> dict:
    from core.tf_export.graph import NOT_POSSIBLE, supported_types
    if rtype in NOT_POSSIBLE:
        return {"status": "not_possible", "reason": NOT_POSSIBLE[rtype]}
    if rtype in _APPLIERS:
        return {"status": "supported", "reason": ""}
    if rtype in supported_types():
        return {"status": "planned", "reason": "Vyomi exports this type but cannot import it yet."}
    return {"status": "planned", "reason": "Not simulated or imported yet."}


def _run(files, binaries, variables, clients, region, mode: str, targets=None, known=None, ledger=None) -> dict:
    _load()
    run = Run(files, binaries, variables, clients, region)
    res: dict[str, Any] = {"mode": mode, "region": region, "errors": list(run.cfg.errors)}
    if run.cfg.errors:
        return {**res, "ok": False, "items": [], "summary": _summary([]), "ledger": [], "variables": run.required_variables()}
    try:
        order = run.order()
    except hp.HclError as exc:
        return {**res, "ok": False, "errors": [{"file": "", "line": 0, "error": exc.msg}], "items": [], "summary": _summary([]),
                "ledger": [], "variables": run.required_variables()}
    items: list[dict] = []
    new_ledger: list[dict] = []
    targets = set(targets) if targets else None
    known = known or {}
    scope = run.scope
    failed_bases: set[str] = set()
    for base in order:
        d = run.cfg.resources[base]
        avail = _availability(d.type)
        impl = _APPLIERS.get(d.type)
        try:
            instances = run.expand(d)
        except hp.Unknown as exc:
            items.append(_item(base, d, None, "blocked", avail, f"waits for {', '.join(exc.refs)}"))
            failed_bases.add(base)
            continue
        except (hp.HclError, ValueError, TypeError) as exc:
            items.append(_item(base, d, None, "error", avail, f"count/for_each: {exc}"))
            failed_bases.add(base)
            continue
        per_key: dict[Any, dict] = {}
        all_known = True
        for key, each in instances:
            address = _addr(base, key)
            if impl is None:
                items.append(_item(address, d, key, "unsupported", avail, avail["reason"] or "No applier for this type."))
                all_known = False
                continue
            scope.cur, scope._each, scope._idx = base, each, key if isinstance(key, int) else None
            try:
                ev = hp.Evaluator(scope)
                attrs, blocks = hp.eval_body(d.body, ev, _META_ATTRS)
                blocks = [b for b in blocks if b[0] not in _META_BLOCKS]
            except hp.Unknown as exc:
                refs = [r for r in exc.refs if r in failed_bases or r in run.cfg.resources]
                blocked = any(r in failed_bases for r in refs)
                items.append(_item(address, d, key, "blocked" if blocked else ("create" if mode == "plan" else "blocked"), avail,
                                   f"depends on {', '.join(refs)}" if refs else "depends on a value not known yet"))
                all_known = False
                if blocked or mode != "plan":
                    failed_bases.add(base)
                continue
            except (hp.HclError, KeyError, IndexError, TypeError, ValueError) as exc:
                items.append(_item(address, d, key, "error", avail, f"{type(exc).__name__}: {exc}"[:300]))
                all_known = False
                failed_bases.add(base)
                continue
            inst = Inst(d.type, d.name, key, attrs, blocks, address)
            acting = targets is None or address in targets
            outputs = None
            if not acting and address in known:
                outputs = dict(known[address])
                action = "exists"
            else:
                try:
                    outputs = impl.find(run.c, inst)
                except Exception as exc:  # noqa: BLE001 - a lookup failure must not abort the whole run
                    items.append(_item(address, d, key, "error", avail, f"lookup failed: {_msg(exc)}"))
                    all_known = False
                    failed_bases.add(base)
                    continue
                action = "exists" if outputs is not None else "create"
            if action == "create":
                if mode == "plan" or not acting:
                    items.append(_item(address, d, key, "create" if acting else "pending", avail))
                    all_known = False
                    continue
                try:
                    outputs = impl.create(run.c, inst)
                except Exception as exc:  # noqa: BLE001
                    items.append(_item(address, d, key, "failed", avail, _msg(exc)))
                    all_known = False
                    failed_bases.add(base)
                    continue
                action = "created"
                new_ledger.append({"address": address, "type": d.type, "outputs": _scalars(outputs)})
            items.append(_item(address, d, key, action, avail, outputs=_scalars(outputs or {})))
            per_key[key] = _visible(attrs, blocks, outputs or {})
        scope.cur = None
        if all_known and (per_key or not instances):
            if instances and instances[0][0] is None:
                run.state[base] = per_key[None]
            elif instances and isinstance(instances[0][0], int):
                run.state[base] = [per_key[k] for k, _e in instances]
            else:
                run.state[base] = {k: per_key[k] for k, _e in instances}
        elif any(i["action"] in ("failed", "error", "unsupported", "blocked") for i in items if i["base"] == base):
            failed_bases.add(base)
    out_vals: dict[str, Any] = {}
    if mode == "apply":
        for name, body in run.cfg.outputs.items():
            try:
                v = hp.Evaluator(scope).ev(body.attrs["value"]) if "value" in body.attrs else None
                sens = body.attrs.get("sensitive") == ("lit", True)
                out_vals[name] = "(sensitive)" if sens else v
            except Exception:  # noqa: BLE001
                out_vals[name] = None
    summary = _summary(items)
    return {**res, "ok": summary["failed"] == 0 and summary["error"] == 0, "items": items, "summary": summary, "ledger": new_ledger,
            "order": [i["address"] for i in items], "variables": run.required_variables(), "outputs": out_vals,
            "known": {i["address"]: i["outputs"] for i in items if i["action"] in ("created", "exists") and i.get("outputs")}}


def _msg(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:400]


def _visible(attrs: dict, blocks: list, outputs: dict) -> dict:
    """What a reference like ``aws_x.y.attr`` sees: configured attributes, nested blocks as lists, then computed outputs."""
    v = dict(attrs)
    for b in blocks:
        v.setdefault(b[0], []).append(b[1])
    v.update(outputs)
    return v


def _item(address, d, key, action, avail, reason="", outputs=None) -> dict:
    return {"address": address, "base": f"{d.type}.{d.name}", "type": d.type, "name": d.name, "key": key, "action": action,
            "availability": avail, "reason": reason, "id": (outputs or {}).get("id"), "outputs": outputs or {}, "file": d.file}


def _summary(items: list[dict]) -> dict:
    s = {"total": len(items), "create": 0, "created": 0, "exists": 0, "unsupported": 0, "blocked": 0, "failed": 0, "error": 0, "pending": 0}
    for i in items:
        s[i["action"]] = s.get(i["action"], 0) + 1
    s["no_changes"] = bool(items) and s["create"] == 0 and s["created"] == 0 and s["failed"] == 0 and s["unsupported"] == 0 and s["blocked"] == 0 and s["error"] == 0
    return s


# --------------------------------------------------------------------------------------------------------------- public API
def plan(files: dict[str, str], binaries: dict[str, bytes] | None, clients, region: str = "us-east-1", variables: dict | None = None) -> dict:
    """What an apply would do: per resource create | exists | unsupported | blocked | error, in dependency order."""
    return _run(files, binaries, variables, clients, region, "plan")


def apply(files: dict[str, str], binaries: dict[str, bytes] | None, clients, region: str = "us-east-1", variables: dict | None = None,
          targets=None, known=None) -> dict:
    """Create what is missing (idempotent). ``targets`` limits which instances are acted on (for step-wise progress), ``known``
    carries the outputs of earlier steps so they need not be looked up again."""
    return _run(files, binaries, variables, clients, region, "apply", targets, known)


def destroy(clients, region: str = "us-east-1", ledger: list[dict] | None = None, files=None, binaries=None, variables=None) -> dict:
    """Remove what an import created: ``ledger`` (from an apply, newest first) or, without one, whatever the config describes."""
    _load()
    c = Ctx(clients, region)
    results: list[dict] = []
    if ledger is None:
        p = _run(files or {}, binaries, variables, clients, region, "plan")
        ledger = [{"address": i["address"], "type": i["type"], "outputs": i["outputs"]} for i in p["items"] if i["action"] == "exists"]
    for e in reversed(ledger):
        impl = _APPLIERS.get(e["type"])
        if impl is None or not hasattr(impl, "delete"):
            results.append({"address": e["address"], "type": e["type"], "action": "unsupported", "reason": "no destroyer"})
            continue
        try:
            impl.delete(c, e.get("outputs") or {})
            results.append({"address": e["address"], "type": e["type"], "action": "destroyed", "reason": ""})
        except Exception as exc:  # noqa: BLE001
            results.append({"address": e["address"], "type": e["type"], "action": "failed", "reason": _msg(exc)})
    failed = sum(1 for r in results if r["action"] == "failed")
    return {"ok": failed == 0, "items": results, "summary": {"destroyed": sum(1 for r in results if r["action"] == "destroyed"), "failed": failed,
                                                               "total": len(results)}}


def collect_inputs(payload: dict) -> tuple[dict[str, str], dict[str, bytes], dict]:
    """Request body -> (text files, binaries, variables). ``files``: name->text; ``binaries``: name->base64; ``variables``: overrides."""
    files = {str(k): v for k, v in (payload.get("files") or {}).items() if isinstance(v, str)}
    binaries = {str(k): base64.b64decode(v) for k, v in (payload.get("binaries") or {}).items() if isinstance(v, str)}
    return files, binaries, dict(payload.get("variables") or {})


def handle(op: str, payload: dict, clients, region: str = "us-east-1") -> dict:
    """The one entry both substrates call (appliance route, Nano ``_tf`` service): ``Plan`` | ``Apply`` | ``Destroy``."""
    payload = payload or {}
    region = payload.get("region") or region
    files, binaries, variables = collect_inputs(payload)
    if op == "Plan":
        return plan(files, binaries, clients, region, variables)
    if op == "Apply":
        return apply(files, binaries, clients, region, variables, payload.get("targets"), payload.get("known"))
    if op == "Destroy":
        return destroy(clients, region, payload.get("ledger"), files, binaries, variables)
    return {"ok": False, "code": "UnsupportedOperation", "operation": op}
