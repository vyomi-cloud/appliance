"""Azure export (ARM/Bicep/Terraform azurerm) + import (Terraform -> ARM -> deploy) against the real ARM core."""
import json
import re

import pytest

from tests.azure_tf_seed import AzureArm, SUB, export, rgid, seed_group
from core import azure_templates_core as T
from core import azure_tf_core as TF
from core import azure_tf_hcl as H

EXPECT_TF = ["azurerm_resource_group", "azurerm_virtual_network", "azurerm_subnet", "azurerm_subnet_network_security_group_association",
             "azurerm_network_security_group", "azurerm_public_ip", "azurerm_storage_account", "azurerm_key_vault", "azurerm_mssql_server",
             "azurerm_mssql_database", "azurerm_cosmosdb_account", "azurerm_servicebus_namespace", "azurerm_servicebus_queue",
             "azurerm_servicebus_topic", "azurerm_service_plan", "azurerm_linux_web_app", "azurerm_linux_function_app",
             "azurerm_container_registry", "azurerm_kubernetes_cluster", "azurerm_dns_zone", "azurerm_dns_a_record", "azurerm_dns_cname_record",
             "azurerm_log_analytics_workspace", "azurerm_application_insights", "azurerm_user_assigned_identity"]


@pytest.fixture(scope="module")
def seeded():
    a = AzureArm()
    assert seed_group(a, "rg1") == []
    return a, export(a, "rg1")


def test_every_mapped_type_emits_azurerm_and_no_azapi(seeded):
    _, b = seeded
    tf = b["terraform"]
    for t in EXPECT_TF:
        assert f'resource "{t}"' in tf, t
    assert "azapi_resource" not in tf          # nothing fell through
    assert 'source  = "hashicorp/azurerm"' in tf


def test_cross_references_and_secrets(seeded):
    _, b = seeded
    tf = b["terraform"]
    assert "virtual_network_name" in tf and "azurerm_virtual_network.vnet1.name" in tf
    assert "subnet_id                 = azurerm_subnet.vnet1_app.id" in tf
    assert "server_id   = azurerm_mssql_server.sqlvyomi01.id" in tf
    assert "service_plan_id" in tf and "azurerm_service_plan.plan1.id" in tf
    assert "workspace_id" in tf and "azurerm_log_analytics_workspace.law1.id" in tf
    # secrets are variables, never literals
    assert "var.sqlvyomi01_administrator_login_password" in tf
    assert "S3cret-Pass-123!" not in tf and "S3cret" not in json.dumps(b["template"])
    assert re.search(r'variable "sqlvyomi01_administrator_login_password" \{[^}]*sensitive\s+= true', tf, re.S)


def test_arm_template_has_resourceid_and_dependsOn_and_secure_param(seeded):
    _, b = seeded
    tpl = b["template"]
    sub = next(r for r in tpl["resources"] if r["type"] == "Microsoft.Network/virtualNetworks/subnets" and r["name"].endswith("'app')]"))
    assert sub["dependsOn"] and any("virtualNetworks" in d for d in sub["dependsOn"])
    assert sub["properties"]["networkSecurityGroup"]["id"].startswith("[resourceId('Microsoft.Network/networkSecurityGroups'")
    assert tpl["parameters"]["sqlvyomi01_administratorLoginPassword"] == {"type": "securestring"}
    assert tpl["parameters"]["vnet1_name"]["defaultValue"] == "vnet1"
    # canonical type case for children (the state stores lower-case)
    assert all(r["type"] != r["type"].lower() or "/" not in r["type"] for r in tpl["resources"])


def test_bicep_symbolic_references(seeded):
    _, b = seeded
    bicep = b["bicep"]
    assert "@secure()\nparam sqlvyomi01_administratorLoginPassword string" in bicep
    assert "resource vnet1 'Microsoft.Network/virtualNetworks@" in bicep
    assert "id: nsg1.id" in bicep
    assert "dependsOn: [" in bicep


def test_export_is_deterministic(seeded):
    a, b = seeded
    assert export(a, "rg1")["terraform"] == b["terraform"]
    assert export(a, "rg1")["bicep"] == b["bicep"]


def test_terraform_roundtrip_into_fresh_group_is_equal_modulo_names(seeded):
    _, b = seeded
    imp = T.import_terraform(b["terraform"])
    assert imp["unsupported"] == [] and imp["template"]
    a2 = AzureArm()
    a2.handle("PUT", rgid("rg2"), {"api-version": "2021-04-01"}, {"location": "eastus"})
    body = {"properties": {"mode": "Incremental", "template": imp["template"],
                           "parameters": {"sqlvyomi01_administrator_login_password": {"value": "Pw-12345!x"}}}}
    r = a2.handle("PUT", rgid("rg2") + "/providers/Microsoft.Resources/deployments/imp", {"api-version": "2021-04-01"}, body)
    assert r["body"]["properties"]["provisioningState"] == "Succeeded", r["body"]["properties"].get("error")
    b2 = export(a2, "rg2")
    norm = lambda s: s.replace("rg1", "X").replace("rg2", "X")
    assert norm(b["terraform"]) == norm(b2["terraform"])
    assert norm(json.dumps(b["template"]["resources"], sort_keys=True)) == norm(json.dumps(b2["template"]["resources"], sort_keys=True))


def test_unsupported_blocks_are_listed_not_guessed():
    tf = '''
resource "azurerm_resource_group" "rg" { name = "x" location = "eastus" }
resource "azurerm_bastion_host" "b" { name = "b" }
resource "azurerm_virtual_network" "v" {
  count               = 2
  name                = "v"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  address_space       = ["10.0.0.0/16"]
}
resource "azurerm_storage_account" "s" {
  name = lower(local.nm)
  resource_group_name = azurerm_resource_group.rg.name
  location = "eastus"
  account_tier = "Standard"
  account_replication_type = "LRS"
}
data "azurerm_key_vault" "kv" { name = "kv" resource_group_name = "x" }
'''
    r = T.import_terraform(tf)
    reasons = {u["address"]: u["reason"] for u in r["unsupported"]}
    assert "not supported by the importer" in reasons["azurerm_bastion_host.b"]
    assert "count" in reasons["azurerm_virtual_network.v"]
    assert "locals" in reasons["azurerm_storage_account.s"] or "local" in reasons["azurerm_storage_account.s"]
    assert "data.azurerm_key_vault.kv" in reasons
    assert r["template"]["resources"] == []


def test_syntax_error_is_reported():
    r = T.import_terraform('resource "azurerm_x" "y" {')
    assert r["template"] is None and "syntax" in r["error"]


def test_variables_and_interpolation_become_parameters():
    tf = '''
variable "env" { type = string default = "dev" }
variable "pw" { type = string sensitive = true }
resource "azurerm_storage_account" "s" {
  name = "st${var.env}01"
  resource_group_name = "rg"
  location = "westus2"
  account_tier = "Standard"
  account_replication_type = "GRS"
  tags = { env = var.env }
}
'''
    r = T.import_terraform(tf)
    assert r["template"]["parameters"]["env"] == {"type": "string", "defaultValue": "dev"}
    assert r["template"]["parameters"]["pw"]["type"] == "securestring"
    res = r["template"]["resources"][0]
    assert res["name"] == "[concat('st', parameters('env'), '01')]"
    assert res["sku"]["name"] == "Standard_GRS" and res["location"] == "westus2"
    assert res["tags"] == {"env": "[parameters('env')]"}


def test_azapi_fallback_for_unmapped_types_roundtrips():
    a = AzureArm()
    a.handle("PUT", rgid("rgz"), {"api-version": "2021-04-01"}, {"location": "eastus"})
    a.handle("PUT", rgid("rgz") + "/providers/Microsoft.Network/ddosProtectionPlans/ddos1", {"api-version": "2023-05-01"}, {"location": "eastus", "properties": {}})
    b = export(a, "rgz")
    assert 'resource "azapi_resource"' in b["terraform"] and "Microsoft.Network/ddosProtectionPlans@" in b["terraform"]
    assert "# Exported with the generic azapi_resource" in b["terraform"]
    imp = T.import_terraform(b["terraform"])
    assert imp["unsupported"] == [] and imp["template"]["resources"][0]["type"] == "Microsoft.Network/ddosProtectionPlans"


def test_coverage_report_counts():
    mapped = TF.mapped_types()
    assert len(mapped) >= 30
    for t in ("Microsoft.Network/virtualNetworks", "Microsoft.Sql/servers", "Microsoft.Web/sites", "Microsoft.Authorization/roleAssignments"):
        assert t in mapped


def test_role_assignment_roundtrip():
    a = AzureArm()
    a.handle("PUT", rgid("rgr"), {"api-version": "2021-04-01"}, {"location": "eastus"})
    a.handle("PUT", rgid("rgr") + "/providers/Microsoft.Authorization/roleAssignments/11111111-2222-3333-4444-555555555555", {"api-version": "2022-04-01"},
             {"properties": {"roleDefinitionId": f"/subscriptions/{SUB}/providers/Microsoft.Authorization/roleDefinitions/acdd72a7-3385-48ef-bd42-f606fba81ae7",
                             "principalId": "22222222-2222-2222-2222-222222222222", "principalType": "ServicePrincipal"}})
    b = export(a, "rgr")
    assert 'resource "azurerm_role_assignment"' in b["terraform"] and 'role_definition_name = "Reader"' in b["terraform"]
    assert "scope" in b["terraform"] and "azurerm_resource_group.rg.id" in b["terraform"]
    imp = T.import_terraform(b["terraform"])
    assert imp["unsupported"] == []
    ra = imp["template"]["resources"][0]
    assert ra["type"] == "Microsoft.Authorization/roleAssignments" and ra["properties"]["roleDefinitionId"].endswith("'acdd72a7-3385-48ef-bd42-f606fba81ae7')]")


def test_hcl_parser_handles_heredoc_comments_and_objects():
    body = H.parse('''
# c
resource "a" "b" {
  x = 1 // t
  s = <<EOT
hello
EOT
  m = { k = "v", "q-r" = [1, 2] }
  blk { y = true }
}
''')
    t, labels, bd, _ = body.blocks[0]
    assert labels == ["a", "b"] and bd.attrs["x"] == 1 and bd.attrs["s"] == "hello\n"
    assert bd.attrs["m"] == {"k": "v", "q-r": [1, 2]} and bd.blocks[0][0] == "blk"


def test_extended_types_roundtrip_including_nic_vm_cycle():
    a = AzureArm()
    a.handle("PUT", rgid("rgx"), {"api-version": "2021-04-01"}, {"location": "eastus"})
    r = rgid("rgx")
    put = lambda rel, ver, body: a.handle("PUT", r + "/providers/" + rel, {"api-version": ver}, body)
    put("Microsoft.Network/virtualNetworks/v", "2023-05-01", {"location": "eastus", "properties": {"addressSpace": {"addressPrefixes": ["10.0.0.0/16"]},
        "subnets": [{"name": "s", "properties": {"addressPrefix": "10.0.1.0/24"}}]}})
    put("Microsoft.Network/networkInterfaces/nic1", "2023-05-01", {"location": "eastus", "properties": {"ipConfigurations": [
        {"name": "ipc", "properties": {"subnet": {"id": r + "/providers/Microsoft.Network/virtualNetworks/v/subnets/s"}, "privateIPAllocationMethod": "Dynamic"}}]}})
    put("Microsoft.Compute/virtualMachines/vm1", "2023-09-01", {"location": "eastus", "properties": {"hardwareProfile": {"vmSize": "Standard_B1s"},
        "osProfile": {"computerName": "vm1", "adminUsername": "azureuser", "linuxConfiguration": {"disablePasswordAuthentication": False}},
        "storageProfile": {"imageReference": {"publisher": "Canonical", "offer": "0001-com-ubuntu-server-jammy", "sku": "22_04-lts", "version": "latest"},
                           "osDisk": {"createOption": "FromImage", "managedDisk": {"storageAccountType": "Standard_LRS"}}},
        "networkProfile": {"networkInterfaces": [{"id": r + "/providers/Microsoft.Network/networkInterfaces/nic1"}]}}})
    put("Microsoft.Network/routeTables/rt1", "2023-05-01", {"location": "eastus", "properties": {"routes": [
        {"name": "r1", "properties": {"addressPrefix": "0.0.0.0/0", "nextHopType": "VirtualAppliance", "nextHopIpAddress": "10.0.0.4"}}]}})
    put("Microsoft.Cache/redis/redis1", "2023-08-01", {"location": "eastus", "properties": {"sku": {"name": "Basic", "family": "C", "capacity": 0}, "minimumTlsVersion": "1.2"}})
    b = export(a, "rgx")
    for t in ("azurerm_linux_virtual_machine", "azurerm_network_interface", "azurerm_route_table", "azurerm_redis_cache", "azurerm_managed_disk"):
        assert (f'resource "{t}"' in b["terraform"]) == (t != "azurerm_managed_disk"), t
    assert "network_interface_ids" in b["terraform"] and "azurerm_network_interface.nic1.id" in b["terraform"]
    assert "azapi_resource" not in b["terraform"]
    imp = T.import_terraform(b["terraform"])
    assert imp["unsupported"] == []
    a2 = AzureArm()
    a2.handle("PUT", rgid("rgy"), {"api-version": "2021-04-01"}, {"location": "eastus"})
    res = a2.handle("PUT", rgid("rgy") + "/providers/Microsoft.Resources/deployments/i", {"api-version": "2021-04-01"},
                    {"properties": {"mode": "Incremental", "template": imp["template"], "parameters": {"vm1_admin_password": {"value": "Pw-12345!x"}}}})
    assert res["body"]["properties"]["provisioningState"] == "Succeeded", res["body"]["properties"].get("error")
    b2 = export(a2, "rgy")
    strip = lambda t, g: re.sub(r"_OsDisk_1_[0-9a-f]+", "_OsDisk", t.replace(g, "X"))    # the OS disk name carries a random suffix (modulo names)
    assert strip(b["terraform"], "rgx") == strip(b2["terraform"], "rgy")
