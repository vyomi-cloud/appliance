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
