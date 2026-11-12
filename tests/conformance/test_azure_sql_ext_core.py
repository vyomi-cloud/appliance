"""SQL server connection policy + Dynamic Data Masking + ledger round-trip as real ARM resources."""
try:
    from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as S
except ImportError:  # pragma: no cover
    from azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as S  # type: ignore


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def run():
    a = AzureArm()
    av = {"api-version": "2023-08-01"}
    a.handle("PUT", f"/subscriptions/{S}/resourceGroups/r", {"api-version": "2021-04-01"}, {"location": "eastus"})
    srv = f"/subscriptions/{S}/resourceGroups/r/providers/Microsoft.Sql/servers/sqlx"
    a.handle("PUT", srv, av, {"location": "eastus", "properties": {"administratorLogin": "a", "administratorLoginPassword": "Xx123456789!"}})
    db = f"{srv}/databases/d1"
    a.handle("PUT", db, av, {"location": "eastus", "properties": {"isLedgerOn": True, "preferredEnclaveType": "VBS"}})
    _check("ledger flag + enclave type stored", a.handle("GET", db, av)["body"]["properties"].get("isLedgerOn") is True)
    r = a.handle("PUT", f"{srv}/connectionPolicies/default", av, {"properties": {"connectionType": "Redirect"}})
    _check("connection policy stored", r["status"] in (200, 201) and a.handle("GET", f"{srv}/connectionPolicies/default", av)["body"]["properties"]["connectionType"] == "Redirect")
    a.handle("PUT", f"{db}/dataMaskingPolicies/Default", av, {"properties": {"dataMaskingState": "Enabled"}})
    a.handle("PUT", f"{db}/dataMaskingPolicies/Default/rules/r1", av, {"properties": {"schemaName": "dbo", "tableName": "T", "columnName": "email", "maskingFunction": "Email"}})
    lst = a.handle("GET", f"{db}/dataMaskingPolicies/Default/rules", av)["body"]["value"]
    _check("masking rule listed", len(lst) == 1 and lst[0]["properties"]["maskingFunction"] == "Email")
    _check("masking policy state stored", a.handle("GET", f"{db}/dataMaskingPolicies/Default", av)["body"]["properties"]["dataMaskingState"] == "Enabled")
    a.handle("DELETE", f"{db}/dataMaskingPolicies/Default/rules/r1", av)
    _check("masking rule deleted", a.handle("GET", f"{db}/dataMaskingPolicies/Default/rules", av)["body"]["value"] == [])
    print("PASS test_azure_sql_ext_core")


if __name__ == "__main__":
    run()
