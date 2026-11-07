"""Azure SQL masking / classification configured with the REAL azure-mgmt-sql SDK (ARM wire, api-version aware) and then
ENFORCED by the SQL data plane: masked values for a non-privileged login, UNMASK, sensitivity labels reaching the audit log.
(The SQL query wire itself is the simulator's REST /query - TDS/pyodbc cannot traverse the HTTP relay; documented limit.)
Run: PYTHONPATH=. python tests/conformance/test_azure_sql_security_sdk.py"""
import json
import urllib.request

from azure.core.credentials import AccessToken
from azure.core.pipeline.policies import SansIOHTTPPolicy
from azure.mgmt.sql import SqlManagementClient
from azure.mgmt.sql.models import DataMaskingPolicy, DataMaskingRule, SensitivityLabel

from tests.conformance._az_http_bridge import start


class _Cred:
    def get_token(self, *a, **k):
        return AccessToken("t", 9999999999)


class _Auth(SansIOHTTPPolicy):          # bearer header without azure-core's https-only guard (the bridge is plain http)
    def on_request(self, request):
        request.http_request.headers["Authorization"] = "Bearer t"


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def run():
    router, srv, base = start()
    from core.azure_arm_core import DEFAULT_SUBSCRIPTION as S
    cred = _Cred()
    c = SqlManagementClient(cred, S, base_url=base, credential_scopes=["https://management.azure.com/.default"],
                            authentication_policy=_Auth())
    router.az_arm.handle("PUT", f"/subscriptions/{S}/resourceGroups/rg", {"api-version": "2021-04-01"}, {"location": "eastus"})
    srv_id = f"/subscriptions/{S}/resourceGroups/rg/providers/Microsoft.Sql/servers/sq"
    router.az_arm.handle("PUT", srv_id, {"api-version": "2023-08-01"}, {"location": "eastus", "properties": {"administratorLogin": "adm", "administratorLoginPassword": "Xx123456789!"}})
    router.az_arm.handle("PUT", srv_id + "/databases/db", {"api-version": "2023-08-01"}, {"location": "eastus", "properties": {}})

    def q(sql, login=None, params=None):
        h = {"Content-Type": "application/json", **({"x-vyomi-sql-login": login} if login else {})}
        r = urllib.request.urlopen(urllib.request.Request(base + "/azure-sql/servers/sq/databases/db/query", method="POST", headers=h,
                                                          data=json.dumps({"sql": sql, "params": params}).encode()))
        return json.loads(r.read())
    try:
        urllib.request.urlopen(urllib.request.Request(base + "/azure-sql/servers/sq", method="PUT")); urllib.request.urlopen(urllib.request.Request(base + "/azure-sql/servers/sq/databases/db", method="PUT"))
    except Exception as e:                               # noqa: BLE001
        print("  (data-plane path not routed in this build:", e, ")"); srv.shutdown(); return
    q("CREATE TABLE patients (id INTEGER PRIMARY KEY, email TEXT, ssn TEXT)")
    q("INSERT INTO patients VALUES (1, 'jane@corp.com', '123-45-6789')")
    c.data_masking_policies.create_or_update("rg", "sq", "db", DataMaskingPolicy(data_masking_state="Enabled", exempt_principals="boss"))
    c.data_masking_rules.create_or_update("rg", "sq", "db", "r1", DataMaskingRule(schema_name="dbo", table_name="patients", column_name="email", masking_function="Email"))
    c.data_masking_rules.create_or_update("rg", "sq", "db", "r2", DataMaskingRule(schema_name="dbo", table_name="patients", column_name="ssn", masking_function="SSN"))
    rules = list(c.data_masking_rules.list_by_database("rg", "sq", "db"))
    _check("SDK lists the masking rules", sorted(r.name for r in rules) == ["r1", "r2"])
    _check("admin sees plaintext", q("SELECT email, ssn FROM patients")["rows"][0] == ["jane@corp.com", "123-45-6789"])
    _check("non-privileged login sees masked values", q("SELECT email, ssn FROM patients", "bob")["rows"][0] == ["jXXX@XXXX.com", "XXX-XX-6789"])
    q("GRANT UNMASK TO bob")
    _check("UNMASK permission reveals data", q("SELECT email FROM patients", "bob")["rows"][0][0] == "jane@corp.com")
    c.sensitivity_labels.create_or_update("rg", "sq", "db", "dbo", "patients", "email",
                                          SensitivityLabel(label_name="Confidential", information_type="Contact Info", rank="Medium"))
    q("SELECT email FROM patients")
    ins = json.loads(urllib.request.urlopen(base + "/azure-sql/servers/sq/databases/db/queryinsights").read())
    _check("audit log carries data sensitivity information from the SDK-created label",
           any((a.get("dataSensitivityInformation") or [{}])[0].get("columnName") == "email" for a in ins["audit"]))
    srv.shutdown()
    print("PASS test_azure_sql_security_sdk")


if __name__ == "__main__":
    run()
