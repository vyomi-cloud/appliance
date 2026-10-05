"""Azure generic child-resource (sub-resource) store — registry-backed & durable.

The Azure console's detail-view "sub-resource" blades (SQL databases, SQL firewall
rules, Service Bus queues, …) need a child collection under a parent resource that:

  • persists across a reload (survives Pyodide restart), and
  • is cross-context visible (console tab ↔ relay tab),

exactly the way S3 buckets / DynamoDB tables do. Both properties come "for free"
when the state lives on a store that is ALREADY in the shared nano_registry and
therefore ALREADY captured/restored by nano_persist (which snapshots every public,
JSON-safe dict attr on each registered store and union-merges it back on restore).

So instead of adding a NEW registry key (registry.py + nano_persist.STORE_ATTRS are
frozen shared infra), this module hangs ONE extra public dict attribute —
``nano_sub`` — on an existing Azure registry store (``az_cosmos``). nano_persist
picks it up automatically. No registry / persist / sw.js edit required.

Shape of the ``nano_sub`` bag::

    { "<service>\\x1f<parent>\\x1f<childType>": { "<childName>": {<attrs>}, ... }, ... }

The console reaches this via the generic sub-resource route the SW already serves::

    GET    /api/azure/sub/<service>/list<Child>/<parent>
    POST   /api/azure/sub/<service>/create<Child>/<parent>   body {name, ...attrs}
    DELETE /api/azure/sub/<service>/delete<Child>/<parent>?child=<name>
    PATCH  /api/azure/sub/<service>/update<Child>/<parent>?child=<name>  body {...attrs}

which the SW turns into ``resource_op(service, "List<Child>"|…, name=<parent>, body)``
and the adapter funnels here. Pure stdlib → loads under Pyodide.
"""
from __future__ import annotations

_SEP = "\x1f"  # unit-separator: safe delimiter, never appears in a resource name


def _bag(store):
    """The sub-resource dict living on the shared (persisted) registry store.
    Created lazily as a public attr so nano_persist captures + restores it."""
    bag = getattr(store, "nano_sub", None)
    if bag is None:
        bag = {}
        store.nano_sub = bag  # public attr → captured by nano_persist._public_state
    return bag


def _key(service: str, parent: str, child_type: str) -> str:
    return f"{service}{_SEP}{parent}{_SEP}{child_type}"


def list_children(store, service, parent, child_type):
    coll = _bag(store).get(_key(service, parent, child_type), {})
    # newest-first-ish is not meaningful here; return insertion order with name folded in
    return [{"name": n, **(v or {})} for n, v in coll.items()]


def create_child(store, service, parent, child_type, name, attrs=None):
    name = str(name or "").strip()
    if not name:
        return {"ok": False, "code": "InvalidName"}
    bag = _bag(store)
    k = _key(service, parent, child_type)
    coll = bag.setdefault(k, {})
    if name in coll:
        return {"ok": False, "code": "AlreadyExists", "name": name}
    coll[name] = dict(attrs or {})
    store.persist() if hasattr(store, "persist") else None
    return {"ok": True, "name": name, **coll[name]}


def update_child(store, service, parent, child_type, name, attrs=None):
    bag = _bag(store)
    coll = bag.get(_key(service, parent, child_type), {})
    if name not in coll:
        return {"ok": False, "code": "NotFound", "name": name}
    coll[name].update(dict(attrs or {}))
    store.persist() if hasattr(store, "persist") else None
    return {"ok": True, "name": name, **coll[name]}


def delete_child(store, service, parent, child_type, name):
    bag = _bag(store)
    coll = bag.get(_key(service, parent, child_type), {})
    existed = coll.pop(name, None) is not None
    store.persist() if hasattr(store, "persist") else None
    return {"ok": existed, "code": None if existed else "NotFound", "name": name}
