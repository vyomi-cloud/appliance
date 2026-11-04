"""Every offline space-backed store must expose every state field of the core store it wraps.

A core gaining a field (e.g. gcp_compute_instances_core.ComputeStore.instance_group_managers)
while the appliance's AppState* subclass only maps the old ones makes that feature 500 offline
(AttributeError) while Nano works — this happened three times in the v4 depth pass.
"""
from __future__ import annotations

import inspect

import pytest

from core import appliance_stores as aps


def _slot_stores():
    for name, cls in vars(aps).items():
        if inspect.isclass(cls) and name.startswith("AppState") and isinstance(getattr(cls, "_KEYS", None), (dict, tuple)):
            core_bases = [b for b in cls.__mro__[1:] if b.__module__.startswith("core.") and b.__module__ != aps.__name__]
            if core_bases:
                yield name, cls, core_bases[0]


@pytest.mark.parametrize("name,cls,base", list(_slot_stores()), ids=lambda x: x if isinstance(x, str) else "")
def test_store_maps_every_core_field(name, cls, base):
    try:
        fields = set(vars(base()).keys())
    except TypeError:
        pytest.skip(f"{base.__name__}() needs arguments")
    keys = set(cls._KEYS) if not isinstance(cls._KEYS, dict) else set(cls._KEYS.keys())
    missing = {f for f in fields - keys if not f.startswith("_") and not isinstance(getattr(cls, f, None), property)
               and not callable(getattr(base(), f, None))}
    missing = {f for f in missing if not hasattr(cls, f) or f not in vars(cls)}
    # attributes the AppState store sets itself (engine, account id, …) are not slot state
    init_src = inspect.getsource(cls.__init__) if "__init__" in vars(cls) else ""
    missing = {f for f in missing if f"self.{f} =" not in init_src}
    assert not missing, f"{name} does not map core fields {sorted(missing)} of {base.__name__}"


# ── _CoreSlotStore (the net-new cores: durable space slots) ─────────────────────────────

import json  # noqa: E402
import re  # noqa: E402

# store → the core modules that read/write it (their lazily-created attributes must be slot fields)
_CORE_USERS = {
    "AppStateApiGwV2Store": ("apigatewayv2_core",), "AppStateSsmStore": ("ssm_core",),
    "AppStateStepFunctionsStore": ("stepfunctions_core",),
    "AppStateCloudSchedulerStore": ("gcp_cloudscheduler_core",), "AppStateRedisStore": ("gcp_redis_core",),
    "AppStateContainerStore": ("gcp_container_core",), "AppStateIamCredentialsStore": ("gcp_iamcredentials_core",),
    "AppStateMonitoringStore": ("gcp_monitoring_core",), "AppStateResourceManagerStore": ("gcp_resourcemanager_core",),
    "AppStateGcpIamStore": ("gcp_iam_core",), "AppStateAzureRbacStore": ("azure_iam_core",),
    "AppStateAzureSqlStore": ("azure_sql_core",),
    "AppStateRdsStore": ("rds_core",), "AppStateCloudSqlRowsStore": ("gcp_cloudsql_core",),
    "AppStateDaxStore": ("dax_core",), "AppStateDlmStore": ("dlm_core",), "AppStateRamStore": ("ram_core",),
    "AppStateCloudFormationStore": ("cloudformation_core",),
    "AppStateAzureQueueSlot": (),   # JSON form of AppStateAzureQueueStore's live queues (no lazy core attrs)
}


def _core_slot_stores():
    return [(n, c) for n, c in vars(aps).items()
            if inspect.isclass(c) and issubclass(c, aps._CoreSlotStore) and c is not aps._CoreSlotStore
            and getattr(c, "_SLOT", "")]   # abstract mixins (e.g. _FileRowsSqlStore) bind no slot


def test_every_core_slot_store_is_listed():
    assert {n for n, _ in _core_slot_stores()} == set(_CORE_USERS)


@pytest.mark.parametrize("name,cls", _core_slot_stores(), ids=lambda x: x if isinstance(x, str) else "")
def test_core_slot_store_covers_every_field(name, cls):
    base = cls._BASE()
    inst = cls()
    for k, v in vars(base).items():
        if k in cls._FIELDS:
            continue
        if k in cls._LINKS:   # a runtime link the wire router sets: a class attribute, never slot data
            assert k in vars(cls) and k not in cls._FIELDS, f"{name}.{k} link must be a class attribute"
            continue
        # not slot state: must be private or not JSON-safe (an engine / lock / connection) …
        assert k.startswith("_") or not aps._state_json_safe(v), f"{name}.{k} is data but not a slot field"
        # … and still present on the instance (the core uses it)
        assert k in vars(inst) or isinstance(getattr(cls, k, None), property), f"{name} lost {k}"
    # the core's lazily-created attributes (getattr(store, "x", None) … store.x = …) persist too
    import importlib
    for mod in _CORE_USERS[name]:
        src = inspect.getsource(importlib.import_module(f"core.{mod}"))
        lazy = set(re.findall(r'getattr\(\s*(?:store|st|s|obj)\s*,\s*"([A-Za-z_][A-Za-z0-9_]*)"', src))
        lazy |= set(re.findall(r'\bstore\.(_[A-Za-z][A-Za-z0-9_]*)\s*=[^=]', src))
        missing = {a for a in lazy if a not in cls._FIELDS and a not in vars(base) and not hasattr(cls, a)}
        assert not missing, f"{name}: {mod} keeps {sorted(missing)} lazily on the store, not in _EXTRA"
    # the seeded slot survives the state codec (one bad object breaks every save)
    assert aps._state_json_safe(dict(cls._DEFAULTS))
    json.dumps(sorted(cls._FIELDS))


# _SlotStore adapters skip the base store's __init__ (their dicts ARE the space slot), so every
# field the base store's __init__ creates must be declared in _KEYS + a slot attr — otherwise
# the shared core hits AttributeError OFFLINE only (the in-memory dev server/Nano never see it).
# Seen: gcp_firestore_core's Query Insights / Key Visualizer counters (key_access, …).
import pytest as _pytest

_SLOT_ADAPTERS = [c for c in vars(aps).values()
                  if isinstance(c, type) and issubclass(c, aps._SlotStore) and c is not aps._SlotStore
                  and getattr(c, "_KEYS", None)]


@_pytest.mark.parametrize("cls", _SLOT_ADAPTERS, ids=lambda c: c.__name__)
def test_slot_adapter_covers_base_store_fields(cls):
    base = next(b for b in cls.__mro__[1:] if b is not aps._SlotStore and not issubclass(b, aps._SlotStore)
                and b is not object)
    try:
        inst = base()
    except TypeError:
        _pytest.skip(f"{base.__name__}() needs args")
    own_init = inspect.getsource(cls.__init__) if "__init__" in vars(cls) else ""   # config the adapter sets itself
    missing = sorted(k for k, v in vars(inst).items()
                     if not k.startswith("_") and aps._state_json_safe(v)
                     and k not in cls._KEYS and not isinstance(getattr(cls, k, None), property)
                     and f"self.{k} =" not in own_init)
    assert not missing, f"{cls.__name__} lacks durable slots for {base.__name__} fields {missing}"


# Route-level space stores (routes/*.py `class Space<X>Store(<core store>)`) expose a FIXED set of
# persisted keys over the active space's slot and skip the base __init__ — a field a sweep adds to
# the core store is then missing offline (AttributeError / lost on restart). Seen: Cloud Run
# triggers/builds (Functions sweep). Every base-store data field must be reachable on the space store.
import importlib as _importlib
import re as _re
from pathlib import Path as _Path

# Fields on a SHARED base store that this route store genuinely doesn't own (another cloud's state).
_ROUTE_STORE_NOT_OWNED = {"SpaceSnsStore": {"pubsub"}}   # GCP Pub/Sub snapshots/schemas — this store serves AWS SNS only
_ROUTE_SPACE_STORES = []
for _f in sorted((_Path(__file__).resolve().parent.parent / "routes").glob("*.py")):
    for _m in _re.finditer(r"^class (Space\w+Store)\(", _f.read_text(), _re.M):
        _ROUTE_SPACE_STORES.append((f"routes.{_f.stem}", _m.group(1)))


@_pytest.mark.parametrize("mod,cls_name", _ROUTE_SPACE_STORES, ids=[c for _, c in _ROUTE_SPACE_STORES])
def test_route_space_store_covers_base_fields(mod, cls_name):
    m = _importlib.import_module(mod)
    cls = getattr(m, cls_name)
    base = next(b for b in cls.__mro__[1:] if b is not object)
    try:
        inst = base()
    except TypeError:
        _pytest.skip(f"{base.__name__}() needs args")
    keys = set(getattr(m, "_KEYS", ()) or ())
    keys |= _ROUTE_STORE_NOT_OWNED.get(cls_name, set())
    missing = sorted(k for k, v in vars(inst).items()
                     if not k.startswith("_") and isinstance(v, (dict, list))
                     and k not in _ROUTE_STORE_NOT_OWNED.get(cls_name, set()) and k != "seq"
                     and not isinstance(getattr(cls, k, None), property))   # must be a slot-backed property
    assert not missing, f"{mod}.{cls_name} doesn't persist {base.__name__} fields {missing} (add to _KEYS)"


# The same gap on the remaining hand-written adapters (AppState* classes outside the two families
# above that skip the base __init__). Seen: Azure Blob's soft-delete/metrics state — every blob call
# 500'd offline with AttributeError request_counters.
# Fields on a store base SHARED across clouds that this adapter's cloud doesn't use.
_ADAPTER_NOT_OWNED = {
    "AppStateKeyStore": {"custom_key_stores"},       # AWS KMS only (AppStateAwsKeyStore has it); this one is Cloud KMS / Key Vault
    "AppStateMessagingStore": {"pubsub"},            # AWS SQS/SNS: no GCP Pub/Sub state
    "AppStateServiceBusStore": {"pubsub", "queues", "sns"},   # Azure Service Bus keeps its own entities
    "AppStatePubsubStore": {"sns"},                  # GCP Pub/Sub: no AWS SNS state
}
_OTHER_ADAPTERS = [c for n, c in vars(aps).items()
                   if isinstance(c, type) and n.startswith("AppState") and not issubclass(c, (aps._SlotStore, aps._CoreSlotStore))
                   and "__init__" in vars(c) and "super().__init__" not in inspect.getsource(c.__init__).replace("no super().__init__", "")]


@_pytest.mark.parametrize("cls", _OTHER_ADAPTERS, ids=lambda c: c.__name__)
def test_other_adapters_expose_base_store_fields(cls):
    base = next((b for b in cls.__mro__[1:] if b is not object and not b.__name__.startswith("_")), None)
    if base is None:
        _pytest.skip("no base store")
    try:
        inst = base()
    except TypeError:
        _pytest.skip(f"{base.__name__}() needs args")
    own_init = inspect.getsource(cls.__init__)
    missing = sorted(k for k, v in vars(inst).items()
                     if not k.startswith("_") and isinstance(v, (dict, list, set))
                     and k not in _ADAPTER_NOT_OWNED.get(cls.__name__, set())
                     and not isinstance(getattr(cls, k, None), property) and f"self.{k} =" not in own_init)
    assert not missing, f"{cls.__name__} lacks {base.__name__} fields {missing}"
