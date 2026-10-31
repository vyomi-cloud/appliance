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
}


def _core_slot_stores():
    return [(n, c) for n, c in vars(aps).items()
            if inspect.isclass(c) and issubclass(c, aps._CoreSlotStore) and c is not aps._CoreSlotStore]


def test_every_core_slot_store_is_listed():
    assert {n for n, _ in _core_slot_stores()} == set(_CORE_USERS)


@pytest.mark.parametrize("name,cls", _core_slot_stores(), ids=lambda x: x if isinstance(x, str) else "")
def test_core_slot_store_covers_every_field(name, cls):
    base = cls._BASE()
    inst = cls()
    for k, v in vars(base).items():
        if k in cls._FIELDS:
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
