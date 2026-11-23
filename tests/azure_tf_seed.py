"""Shared seed for the Azure export/import tests: builds a resource group through the REAL ARM wire
(AzureArm.handle) covering every resource type the Terraform exporter maps to azurerm."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION  # noqa: E402

SUB = DEFAULT_SUBSCRIPTION
SP = f"/subscriptions/{SUB}"


def rgid(rg):
    return f"{SP}/resourceGroups/{rg}"


# (relative path under the rg, api-version, body)
def seed_items(rg):
    r = rgid(rg)
    loc = "eastus"
    return [
        ("Microsoft.ManagedIdentity/userAssignedIdentities/uami1", "2023-01-31", {"location": loc}),
        ("Microsoft.Network/networkSecurityGroups/nsg1", "2023-05-01", {"location": loc, "properties": {"securityRules": [
            {"name": "allow-ssh", "properties": {"priority": 100, "direction": "Inbound", "access": "Allow", "protocol": "Tcp",
                                                   "sourcePortRange": "*", "destinationPortRange": "22",
                                                   "sourceAddressPrefix": "10.0.0.0/8", "destinationAddressPrefix": "*"}}]}}),
        ("Microsoft.Network/virtualNetworks/vnet1", "2023-05-01", {"location": loc, "properties": {
            "addressSpace": {"addressPrefixes": ["10.0.0.0/16"]},
            "subnets": [{"name": "app", "properties": {"addressPrefix": "10.0.1.0/24",
                                                          "networkSecurityGroup": {"id": f"{r}/providers/Microsoft.Network/networkSecurityGroups/nsg1"}}},
                        {"name": "data", "properties": {"addressPrefix": "10.0.2.0/24"}}]}}),
        ("Microsoft.Network/publicIPAddresses/pip1", "2023-05-01", {"location": loc, "sku": {"name": "Standard"},
                                                                    "properties": {"publicIPAllocationMethod": "Static"}}),
        ("Microsoft.Storage/storageAccounts/stvyomi01", "2023-01-01", {"location": loc, "kind": "StorageV2", "sku": {"name": "Standard_LRS"},
                                                                       "properties": {"minimumTlsVersion": "TLS1_2", "supportsHttpsTrafficOnly": True}}),
        ("Microsoft.KeyVault/vaults/kvvyomi01", "2023-02-01", {"location": loc, "properties": {
            "tenantId": "11111111-1111-1111-1111-111111111111", "sku": {"family": "A", "name": "standard"},
            "enableRbacAuthorization": True, "enableSoftDelete": True, "softDeleteRetentionInDays": 7}}),
        ("Microsoft.OperationalInsights/workspaces/law1", "2022-10-01", {"location": loc, "properties": {"sku": {"name": "PerGB2018"}, "retentionInDays": 30}}),
        ("Microsoft.Insights/components/appi1", "2020-02-02", {"location": loc, "kind": "web", "properties": {
            "Application_Type": "web", "WorkspaceResourceId": f"{r}/providers/Microsoft.OperationalInsights/workspaces/law1"}}),
        ("Microsoft.ServiceBus/namespaces/sbvyomi01", "2022-10-01-preview", {"location": loc, "sku": {"name": "Standard", "tier": "Standard"}}),
        ("Microsoft.ServiceBus/namespaces/sbvyomi01/queues/orders", "2022-10-01-preview", {"properties": {"maxDeliveryCount": 5, "lockDuration": "PT1M"}}),
        ("Microsoft.ServiceBus/namespaces/sbvyomi01/topics/events", "2022-10-01-preview", {"properties": {"defaultMessageTimeToLive": "P1D"}}),
        ("Microsoft.Sql/servers/sqlvyomi01", "2022-05-01-preview", {"location": loc, "properties": {
            "administratorLogin": "sqladmin", "administratorLoginPassword": "S3cret-Pass-123!", "version": "12.0"}}),
        ("Microsoft.Sql/servers/sqlvyomi01/databases/appdb", "2022-05-01-preview", {"location": loc, "sku": {"name": "S0", "tier": "Standard"},
                                                                                    "properties": {"collation": "SQL_Latin1_General_CP1_CI_AS", "maxSizeBytes": 2147483648}}),
        ("Microsoft.DocumentDB/databaseAccounts/cosmosvyomi01", "2023-04-15", {"location": loc, "kind": "GlobalDocumentDB", "properties": {
            "databaseAccountOfferType": "Standard", "locations": [{"locationName": loc, "failoverPriority": 0}],
            "consistencyPolicy": {"defaultConsistencyLevel": "Session"}}}),
        ("Microsoft.Web/serverfarms/plan1", "2022-09-01", {"location": loc, "kind": "linux", "sku": {"name": "B1", "tier": "Basic"},
                                                           "properties": {"reserved": True}}),
        ("Microsoft.Web/sites/webvyomi01", "2022-09-01", {"location": loc, "kind": "app,linux", "properties": {
            "serverFarmId": f"{r}/providers/Microsoft.Web/serverfarms/plan1", "httpsOnly": True,
            "siteConfig": {"linuxFxVersion": "NODE|18-lts", "alwaysOn": True}}}),
        ("Microsoft.Web/sites/funcvyomi01", "2022-09-01", {"location": loc, "kind": "functionapp,linux", "properties": {
            "serverFarmId": f"{r}/providers/Microsoft.Web/serverfarms/plan1", "httpsOnly": True,
            "siteConfig": {"linuxFxVersion": "PYTHON|3.11"}}}),
        ("Microsoft.ContainerRegistry/registries/acrvyomi01", "2023-07-01", {"location": loc, "sku": {"name": "Basic"},
                                                                             "properties": {"adminUserEnabled": False}}),
        ("Microsoft.ContainerService/managedClusters/aks1", "2023-08-01", {"location": loc, "identity": {"type": "SystemAssigned"}, "properties": {
            "dnsPrefix": "aks1", "kubernetesVersion": "1.27.3",
            "agentPoolProfiles": [{"name": "system", "count": 2, "vmSize": "Standard_DS2_v2", "mode": "System", "osType": "Linux"}]}}),
        ("Microsoft.Network/dnszones/vyomi.example.com", "2018-05-01", {"location": "global"}),
        ("Microsoft.Network/dnszones/vyomi.example.com/A/www", "2018-05-01", {"properties": {"TTL": 300, "ARecords": [{"ipv4Address": "10.1.2.3"}]}}),
        ("Microsoft.Network/dnszones/vyomi.example.com/CNAME/blog", "2018-05-01", {"properties": {"TTL": 300, "CNAMERecord": {"cname": "www.vyomi.example.com"}}}),
    ]


def seed_group(arm, rg, items=None):
    """Create the RG and every seed resource; returns [(path, status, body)] for failures."""
    fails = []
    r = arm.handle("PUT", rgid(rg), {"api-version": "2021-04-01"}, {"location": "eastus"})
    assert r["status"] in (200, 201), r
    for rel, ver, body in (items or seed_items(rg)):
        p = f"{rgid(rg)}/providers/{rel}"
        r = arm.handle("PUT", p, {"api-version": ver}, body)
        if r["status"] >= 400:
            fails.append((rel, r["status"], str(r["body"])[:200]))
    return fails


def export(arm, rg):
    r = arm.handle("POST", f"{rgid(rg)}/exportTemplate", {"api-version": "2021-04-01"}, {"resources": ["*"]})
    assert r["status"] == 200, r
    return r["body"]
