"""Azure generic sub-resource core (Nano): create_child / list_children /
update_child / delete_child semantics, durability via the shared store's public
``nano_sub`` bag (what nano_persist snapshots), and per-parent isolation.

Run: PYTHONPATH=wasm:wasm/core python3 tests/conformance/test_azure_subresource_core.py
"""
import sys

try:
    from core import azure_subresource_core as sub
except ImportError:  # flat layout
    import azure_subresource_core as sub  # type: ignore


class Store:  # stands in for the registry store (public attrs are persisted)
    pass


fails = 0


def check(name, ok):
    global fails
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    fails += 0 if ok else 1


s = Store()
r = sub.create_child(s, "sql", "srv1", "Database", "db1", {"sku": "S0"})
check("create_child returns ok with attrs", r["ok"] and r["name"] == "db1" and r["sku"] == "S0")
check("create_child duplicate -> AlreadyExists", sub.create_child(s, "sql", "srv1", "Database", "db1")["code"] == "AlreadyExists")
check("create_child blank name -> InvalidName", sub.create_child(s, "sql", "srv1", "Database", " ")["code"] == "InvalidName")
sub.create_child(s, "sql", "srv2", "Database", "other")
check("list_children isolated per parent",
      [c["name"] for c in sub.list_children(s, "sql", "srv1", "Database")] == ["db1"])
check("list_children isolated per child type", sub.list_children(s, "sql", "srv1", "FirewallRule") == [])
u = sub.update_child(s, "sql", "srv1", "Database", "db1", {"sku": "S1"})
check("update_child merges attrs", u["ok"] and sub.list_children(s, "sql", "srv1", "Database")[0]["sku"] == "S1")
check("update_child missing -> NotFound", sub.update_child(s, "sql", "srv1", "Database", "nope")["code"] == "NotFound")
check("state lives in public nano_sub attr (persisted)", bool(getattr(s, "nano_sub", None)))
check("delete_child removes", sub.delete_child(s, "sql", "srv1", "Database", "db1")["ok"]
      and sub.list_children(s, "sql", "srv1", "Database") == [])
check("delete_child missing -> NotFound", sub.delete_child(s, "sql", "srv1", "Database", "db1")["code"] == "NotFound")
sys.exit(1 if fails else 0)
