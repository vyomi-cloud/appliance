"""Export template core (core/azure_templates_core.py + AzureArm exportTemplate action)."""
from core.azure_arm_core import AzureArm

SUB = "00000000-0000-0000-0000-cloudlearn01"
Q = {"api-version": "2021-04-01"}


def _arm():
    a = AzureArm()
    a._base = "http://x"
    a.handle("PUT", f"/subscriptions/{SUB}/resourcegroups/rg1", Q, {"location": "eastus"})
    return a


def _export(a, body):
    r = a.handle("POST", f"/subscriptions/{SUB}/resourcegroups/rg1/exportTemplate", Q, body)
    return r["status"], r["body"]


def test_export_group_roundtrips_real_resource():
    a = _arm()
    r = a.handle("PUT", f"/subscriptions/{SUB}/resourcegroups/rg1/providers/Microsoft.Network/dnszones/z1.com",
                 {"api-version": "2018-05-01"}, {"location": "global", "tags": {"env": "dev"}, "properties": {"zoneType": "Public"}})
    assert r["status"] < 300, r
    st, b = _export(a, {"resources": ["*"]})
    assert st == 200
    res = [x for x in b["template"]["resources"] if x["type"].lower() == "microsoft.network/dnszones"]
    assert res and res[0]["tags"] == {"env": "dev"} and res[0]["properties"]["zoneType"] == "Public"
    assert "param z1_com_name string = 'z1.com'" in b["bicep"]
    assert "resource z1_com 'Microsoft.Network/dnszones@" in b["bicep"] and "zoneType: 'Public'" in b["bicep"]
    assert 'resource "azapi_resource" "z1_com"' in b["terraform"] and "var.z1_com_name" in b["terraform"]
    assert 'zoneType = "Public"' in b["terraform"]


def test_single_resource_and_no_params_and_missing():
    a = _arm()
    rid = f"/subscriptions/{SUB}/resourceGroups/rg1/providers/Microsoft.Network/dnszones/z2.com"
    a.handle("PUT", rid, {"api-version": "2018-05-01"}, {"location": "global", "properties": {"zoneType": "Public"}})
    st, b = _export(a, {"resources": [rid], "vyomiIncludeParameters": False})
    assert st == 200 and "parameters" not in b["template"] and b["template"]["resources"][0]["name"] == "z2.com"
    assert "param " not in b["bicep"]
    st, b = _export(a, {"resources": ["/subscriptions/x/resourceGroups/rg1/providers/Microsoft.Network/dnszones/nope"]})
    assert st == 404 and b["error"]["code"] == "ResourceNotFound"


def test_bicep_literals():
    from core.azure_templates_core import _bval
    assert _bval({"a-b": [1, True, None, "it's"]}) == "{\n  'a-b': [\n    1\n    true\n    null\n    'it\\'s'\n  ]\n}"
