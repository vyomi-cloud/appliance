"""RDS: ModifyDBInstance DeletionProtection toggles protection both ways (real RDS); delete is refused while it is on."""
import re
import types

try:
    from core import rds_core as r
except ImportError:  # pragma: no cover
    import rds_core as r  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"[PASS] {name}")


def run():
    s = r.SqlStore() if hasattr(r, "SqlStore") else types.SimpleNamespace()
    call = lambda **p: r.dispatch(s, p)  # noqa: E731
    body = lambda x: x.body.decode() if isinstance(x.body, bytes) else x.body  # noqa: E731
    base = dict(DBInstanceIdentifier="dp1", DBInstanceClass="db.t3.micro", Engine="postgres", MasterUsername="u", MasterUserPassword="password123", AllocatedStorage=20)
    call(Action="CreateDBInstance", DeletionProtection="true", **base)
    _check("starts protected", "<DeletionProtection>true</DeletionProtection>" in body(call(Action="DescribeDBInstances", DBInstanceIdentifier="dp1")))
    _check("delete refused while protected", call(Action="DeleteDBInstance", DBInstanceIdentifier="dp1", SkipFinalSnapshot="true").status >= 400)
    call(Action="ModifyDBInstance", DBInstanceIdentifier="dp1", DeletionProtection="false", ApplyImmediately="true")
    _check("modify clears protection", "<DeletionProtection>false</DeletionProtection>" in body(call(Action="DescribeDBInstances", DBInstanceIdentifier="dp1")))
    _check("delete allowed after modify", call(Action="DeleteDBInstance", DBInstanceIdentifier="dp1", SkipFinalSnapshot="true").status == 200)
    print("RDS DELETION PROTECTION OK")


if __name__ == "__main__":
    run()
