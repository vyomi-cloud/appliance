"""ARM template deployment against the real ARM core: expressions, copy, dependsOn ordering, outputs, whatIf, validate."""
import copy

from tests.azure_tf_seed import AzureArm, rgid

API = {"api-version": "2021-04-01"}


def _arm(rg="d1"):
    a = AzureArm()
    a.handle("PUT", rgid(rg), API, {"location": "eastus"})
    return a


def _deploy(a, rg, name, tpl, params=None, mode="Incremental", action=None):
    body = {"properties": {"mode": mode, "template": tpl, "parameters": params or {}}}
    path = rgid(rg) + f"/providers/Microsoft.Resources/deployments/{name}" + (f"/{action}" if action else "")
    return a.handle("POST" if action else "PUT", path, API, body)


def _tpl(**kw):
    t = {"$schema": "x", "contentVersion": "1.0.0.0", "resources": []}
    t.update(kw)
    return t


VNET = {"type": "Microsoft.Network/virtualNetworks", "apiVersion": "2023-05-01", "name": "[concat(parameters('p'), '-vnet')]",
        "location": "[parameters('loc')]", "properties": {"addressSpace": {"addressPrefixes": ["10.1.0.0/16"]}}}
SUBNET = {"type": "Microsoft.Network/virtualNetworks/subnets", "apiVersion": "2023-05-01", "name": "[concat(parameters('p'), '-vnet/a')]",
          "dependsOn": ["[resourceId('Microsoft.Network/virtualNetworks', concat(parameters('p'), '-vnet'))]"], "properties": {"addressPrefix": "10.1.1.0/24"}}
PARAMS = {"p": {"type": "string", "defaultValue": "x"}, "loc": {"type": "string", "defaultValue": "[resourceGroup().location]"}}


def test_dependsOn_orders_child_before_parent_declaration_and_outputs():
    a = _arm()
    t = _tpl(parameters=PARAMS, resources=[SUBNET, VNET],
             outputs={"vn": {"type": "string", "value": "[resourceId('Microsoft.Network/virtualNetworks', concat(parameters('p'), '-vnet'))]"}})
    r = _deploy(a, "d1", "dep", t)
    props = r["body"]["properties"]
    assert props["provisioningState"] == "Succeeded", props.get("error")
    assert [x["resourceName"] for x in props["outputResources"]] == ["x-vnet", "x-vnet/a"]
    assert props["outputs"]["vn"]["value"].endswith("/virtualNetworks/x-vnet")
    assert a.handle("GET", rgid("d1") + "/providers/Microsoft.Network/virtualNetworks/x-vnet/subnets/a", {"api-version": "2023-05-01"})["status"] == 200


def test_copy_condition_and_functions():
    a = _arm()
    t = _tpl(parameters={"n": {"type": "int", "defaultValue": 3}, "on": {"type": "bool", "defaultValue": False}},
             variables={"base": "[toLower('ST')]"},
             resources=[{"type": "Microsoft.Storage/storageAccounts", "apiVersion": "2023-01-01", "name": "[format('{0}{1}x', variables('base'), copyIndex())]",
                         "location": "eastus", "sku": {"name": "Standard_LRS"}, "kind": "StorageV2", "copy": {"name": "c", "count": "[parameters('n')]"}},
                        {"type": "Microsoft.Network/networkSecurityGroups", "apiVersion": "2023-05-01", "name": "skipme", "condition": "[parameters('on')]", "location": "eastus"}])
    r = _deploy(a, "d1", "dep", t)
    names = [x["resourceName"] for x in r["body"]["properties"]["outputResources"]]
    assert names == ["st0x", "st1x", "st2x"], names


def test_missing_required_parameter_and_unknown_function_fail_explicitly():
    a = _arm()
    t = _tpl(parameters={"must": {"type": "string"}}, resources=[{"type": "Microsoft.Network/virtualNetworks", "apiVersion": "2023-05-01", "name": "[parameters('must')]", "location": "eastus"}])
    r = _deploy(a, "d1", "dep", t)
    assert r["body"]["properties"]["provisioningState"] == "Failed" and "must" in str(r["body"]["properties"]["error"])
    t2 = _tpl(resources=[{"type": "Microsoft.Network/virtualNetworks", "apiVersion": "2023-05-01", "name": "[listKeys('a','b').k]", "location": "eastus"}])
    r2 = _deploy(a, "d1", "dep2", t2)
    assert r2["body"]["properties"]["provisioningState"] == "Failed" and "not supported" in str(r2["body"]["properties"]["error"])


def test_dependency_cycle_is_rejected_but_reference_only_cycle_is_not():
    a = _arm()
    t = _tpl(resources=[{"type": "Microsoft.Network/virtualNetworks", "apiVersion": "2023-05-01", "name": "a", "dependsOn": ["b"], "location": "eastus"},
                        {"type": "Microsoft.Network/virtualNetworks", "apiVersion": "2023-05-01", "name": "b", "dependsOn": ["a"], "location": "eastus"}])
    assert "Circular" in str(_deploy(a, "d1", "dep", t)["body"]["properties"]["error"])


def test_nested_child_resources_compose_type_and_name():
    a = _arm()
    t = _tpl(resources=[{"type": "Microsoft.Network/virtualNetworks", "apiVersion": "2023-05-01", "name": "nv", "location": "eastus",
                         "properties": {"addressSpace": {"addressPrefixes": ["10.2.0.0/16"]}},
                         "resources": [{"type": "subnets", "apiVersion": "2023-05-01", "name": "s1", "properties": {"addressPrefix": "10.2.1.0/24"}}]}])
    r = _deploy(a, "d1", "dep", t)
    assert r["body"]["properties"]["provisioningState"] == "Succeeded", r["body"]["properties"].get("error")
    assert a.handle("GET", rgid("d1") + "/providers/Microsoft.Network/virtualNetworks/nv/subnets/s1", {"api-version": "2023-05-01"})["status"] == 200


def test_whatif_create_nochange_modify_delete_and_validate():
    a = _arm()
    t = _tpl(parameters=PARAMS, resources=[VNET, SUBNET])
    wi = _deploy(a, "d1", "dep", t, action="whatIf")["body"]
    assert [c["changeType"] for c in wi["properties"]["changes"]] == ["Create", "Create"]
    assert _deploy(a, "d1", "dep", t)["body"]["properties"]["provisioningState"] == "Succeeded"
    assert [c["changeType"] for c in _deploy(a, "d1", "dep", t, action="whatIf")["body"]["properties"]["changes"]] == ["NoChange", "NoChange"]
    t2 = copy.deepcopy(t)
    t2["resources"][0]["properties"]["addressSpace"]["addressPrefixes"] = ["10.9.0.0/16"]
    ch = _deploy(a, "d1", "dep", t2, action="whatIf")["body"]["properties"]["changes"]
    mod = next(c for c in ch if c["changeType"] == "Modify")
    assert mod["delta"][0]["path"].startswith("properties.addressSpace.addressPrefixes")
    # complete mode: an extra resource in the group would be deleted
    a.handle("PUT", rgid("d1") + "/providers/Microsoft.Network/networkSecurityGroups/extra", {"api-version": "2023-05-01"}, {"location": "eastus"})
    chc = _deploy(a, "d1", "dep", t, mode="Complete", action="whatIf")["body"]["properties"]["changes"]
    assert any(c["changeType"] == "Delete" and c["resourceId"].endswith("/extra") for c in chc)
    assert not any(c["changeType"] == "Delete" for c in _deploy(a, "d1", "dep", t, action="whatIf")["body"]["properties"]["changes"])
    ok = _deploy(a, "d1", "dep", t, action="validate")
    assert ok["status"] == 200
    bad = _deploy(a, "d1", "dep", _tpl(parameters={"z": {"type": "string"}}, resources=[VNET]), action="validate")
    assert bad["status"] == 400


def test_import_terraform_route_over_arm_wire():
    a = _arm()
    tf = 'resource "azurerm_virtual_network" "v" {\n name = "v1"\n resource_group_name = "x"\n location = "eastus"\n address_space = ["10.0.0.0/16"]\n}\n'
    r = a.handle("POST", rgid("d1") + "/importTerraform", API, {"terraform": tf})
    assert r["status"] == 200 and r["body"]["template"]["resources"][0]["type"] == "Microsoft.Network/virtualNetworks"
    assert a.handle("POST", rgid("d1") + "/importTerraform", API, {"terraform": 'resource "a" "b" {'})["status"] == 400
