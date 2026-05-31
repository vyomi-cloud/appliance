"""Azure facade for the pack architecture (parity with providers/aws.py + gcp.py).

Backfilled 2026-06-01 to close the design gap identified during the MVP review:
Azure had been built directly on ``core/provider_registry`` + ``providers/azure_services``
+ ``static/azure-console.html``, bypassing the per-service pack metadata model
that AWS and GCP both use.

After this module:
  /api/providers/azure/matrix   → full Azure surface (11 services + 3 tooling packs)
  /api/providers/azure/cli      → az CLI tool metadata
  /api/providers/azure/sdk/java → Azure SDK for Java metadata
  /api/providers/azure/sdk/go   → Azure SDK for Go metadata
  /api/providers/azure/cli/resolve → az command → ARM route mapper

See ``packs/azure/`` for the per-service pack definitions.
"""
from __future__ import annotations

from core.provider_registry import get_provider, provider_matrix
from core.pack_catalog import packs_for_provider


def matrix() -> dict:
    packs = packs_for_provider("azure")
    matrix_data = provider_matrix("azure", packs)
    matrix_data["catalog"] = {
        "service": [pack for pack in packs if pack.get("type") == "service"],
        "tooling": [pack for pack in packs if pack.get("type") == "tooling"],
    }
    return matrix_data


def tool_response(tool: str) -> dict:
    tool = tool.lower()
    provider_info = get_provider("azure")
    endpoint = "http://127.0.0.1:9000"
    if tool == "cli":
        return {
            "provider": "azure",
            "tool": "az",
            "status": "partial",
            "endpoint": endpoint,
            "help": [
                # az speaks ARM at https://management.azure.com — the simulator
                # serves the same paths under its own host. Use --output for
                # JSON; auth is bypassed in dev mode.
                "az vm list --resource-group rg-demo",
                "az storage account list --resource-group rg-demo",
                "az sql server list --resource-group rg-demo",
                "az servicebus namespace list --resource-group rg-demo",
                "az cosmosdb list --resource-group rg-demo",
                "az functionapp list --resource-group rg-demo",
                "az apim list --resource-group rg-demo",
                "az network vnet list --resource-group rg-demo",
                "az eventgrid topic list --resource-group rg-demo",
                "az keyvault list --resource-group rg-demo",
                "az role assignment list",
            ],
            "config": {
                "ARM endpoint": "set AZURE_RESOURCE_MANAGER_HOSTNAME to the simulator host (e.g. 192.168.252.7:9000) — the simulator serves /subscriptions/... ARM routes",
                "auth": "subscription_id can be any string (e.g. 'sub-001'); the simulator gates by space, not by Azure AD tokens",
            },
            "notes": "Azure CLI dev usage in the simulator: point ARM at the simulator host. Real az CLI binaries work for any service whose ARM operation is implemented (covered by the 11 service packs in packs/azure/).",
            "provider_surface": provider_info.get("surface", {}),
        }
    if tool == "sdk/java":
        return {
            "provider": "azure",
            "tool": "azure-sdk-for-java",
            "status": "integrated",
            "endpoint": endpoint,
            "dependency": "com.azure:azure-resourcemanager-* (com.azure:azure-resourcemanager-compute, -storage, -sql, -servicebus, -cosmos, -appservice, -apimanagement, -network, -eventgrid, -keyvault, -authorization)",
            "config": {
                "ARM endpoint": endpoint,
                "AzureProfile": "AzureProfile(AzureEnvironment.AZURE).withSubscription('sub-001')",
                "credentials": "AzureCliCredential or DefaultAzureCredential — simulator accepts any",
            },
            "help": [
                "Use AzureResourceManager.authenticate() with a profile that points HttpClient at the simulator.",
                "Real conformance test in tests/conformance/azure-sdk-java/ proves armcompute/armstorage/armsql/armservicebus/armcosmos round-trip.",
            ],
            "provider_surface": provider_info.get("surface", {}),
        }
    if tool == "sdk/go":
        return {
            "provider": "azure",
            "tool": "azure-sdk-for-go",
            "status": "integrated",
            "endpoint": endpoint,
            "dependency": "github.com/Azure/azure-sdk-for-go/sdk/resourcemanager/* (armcompute, armstorage, armsql, armservicebus, armcosmos, armappservice, armapimanagement, armnetwork, armeventgrid, armkeyvault, armauthorization)",
            "config": {
                "ARM endpoint": endpoint,
                "ClientOptions": "arm.ClientOptions{ClientOptions: azcore.ClientOptions{Cloud: cloud.Configuration{Services: map[cloud.ServiceName]cloud.ServiceConfiguration{cloud.ResourceManager: {Endpoint: endpoint, Audience: endpoint}}}}}",
                "credentials": "azidentity.NewDefaultAzureCredential — simulator accepts any token",
            },
            "help": [
                "Configure cloud.Configuration to point ResourceManager at the simulator base URL.",
                "Real conformance test in tests/conformance/azure-sdk-go/ proves armcompute/armstorage/armsql/armservicebus/armcosmos round-trip.",
            ],
            "provider_surface": provider_info.get("surface", {}),
        }
    raise KeyError(tool)
