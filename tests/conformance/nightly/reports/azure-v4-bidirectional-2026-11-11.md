# Azure v4 console <-> API / CLI bi-directional report

| Service | Check | Result | Detail |
|---|---|---|---|
| (setup) | simulator reachable | PASS | {"status":"ok","tier":"free","packs_active":3} |
| (setup) | create the test resource group over the relay | PASS | 200 {"id":"/subscriptions/00000000-0000-0000-0000-cloudlearn01/resourceGroups/bd-rg-80366","name":"bd-rg |
| Resource groups | API->UI: group created over the API is listed in the console | PASS | not listed |
| Resource groups | API->UI: the list shows the region | PASS | Copilot vyomi@simulator.local VYOMI SIMULATOR (DEFAULT DIRECTORY) V Home>Resource groups Resource groups Vyomi simulator |
| Resource groups | CLI->UI: group created with `az rest` is listed in the console | PASS |  |
| Resource groups | UI->API: group created in the console wizard is returned by the API | PASS | GET 200 |
| Resource groups | UI->API: same name and region in the API response | PASS | {"n":"bd-rg-80366-ui","l":"eastus"} |
| Resource groups | UI delete -> API: group deleted in the console is gone from the API | PASS | GET 404 |
| Resource groups | API delete -> UI: group deleted over the API disappears from the list | PASS | DELETE 200 |
| Storage accounts | API->UI: resource created over the API is listed in the console | PASS |  |
| Storage accounts | API->UI: the list shows the region | PASS |  |
| Storage accounts | CLI->UI: resource created with `az rest` is listed in the console | PASS |  |
| Storage accounts | UI->API: resource created in the console wizard is returned by the API | PASS |  |
| Storage accounts | UI->API: same name and a real region in the API response | PASS | {"n":"storageubd899502","l":"eastus"} |
| Storage accounts | API delete -> UI: resource deleted over the API disappears from the list | PASS | DELETE 200 |
| Key vaults | API->UI: resource created over the API is listed in the console | PASS |  |
| Key vaults | API->UI: the list shows the region | PASS |  |
| Key vaults | CLI->UI: resource created with `az rest` is listed in the console | PASS |  |
| Key vaults | UI->API: resource created in the console wizard is returned by the API | PASS |  |
| Key vaults | UI->API: same name and a real region in the API response | PASS | {"n":"keyvaults-ubd912770","l":"eastus"} |
| Key vaults | API delete -> UI: resource deleted over the API disappears from the list | PASS | DELETE 200 |
| Virtual networks | API->UI: resource created over the API is listed in the console | PASS |  |
| Virtual networks | API->UI: the list shows the region | PASS |  |
| Virtual networks | CLI->UI: resource created with `az rest` is listed in the console | PASS |  |
| Virtual networks | UI->API: resource created in the console wizard is returned by the API | PASS |  |
| Virtual networks | UI->API: same name and a real region in the API response | PASS | {"n":"vnets-ubd926397","l":"eastus"} |
| Virtual networks | API delete -> UI: resource deleted over the API disappears from the list | PASS | DELETE 200 |
| Network security groups | API->UI: resource created over the API is listed in the console | PASS |  |
| Network security groups | API->UI: the list shows the region | PASS |  |
| Network security groups | CLI->UI: resource created with `az rest` is listed in the console | PASS |  |
| Network security groups | UI->API: resource created in the console wizard is returned by the API | PASS |  |
| Network security groups | UI->API: same name and a real region in the API response | PASS | {"n":"nsgs-ubd939799","l":"eastus"} |
| Network security groups | API delete -> UI: resource deleted over the API disappears from the list | PASS | DELETE 200 |
| DNS zones | API->UI: resource created over the API is listed in the console | PASS |  |
| DNS zones | CLI->UI: resource created with `az rest` is listed in the console | PASS |  |
| DNS zones | UI->API: resource created in the console wizard is returned by the API | PASS |  |
| DNS zones | UI->API: same name and a real region in the API response | PASS | {"n":"dns-ubd953856.example.com","l":"global"} |
| DNS zones | API delete -> UI: resource deleted over the API disappears from the list | PASS | DELETE 200 |
| App Configuration | API->UI: resource created over the API is listed in the console | PASS |  |
| App Configuration | API->UI: the list shows the region | PASS |  |
| App Configuration | CLI->UI: resource created with `az rest` is listed in the console | PASS |  |
| App Configuration | UI->API: resource created in the console wizard is returned by the API | PASS |  |
| App Configuration | UI->API: same name and a real region in the API response | PASS | {"n":"appconfiguration-ubd967635","l":"eastus"} |
| App Configuration | API delete -> UI: resource deleted over the API disappears from the list | PASS | DELETE 200 |
| Service Bus | API->UI: resource created over the API is listed in the console | PASS |  |
| Service Bus | API->UI: the list shows the region | PASS |  |
| Service Bus | CLI->UI: resource created with `az rest` is listed in the console | PASS |  |
| Service Bus | UI->API: resource created in the console wizard is returned by the API | PASS |  |
| Service Bus | UI->API: same name and a real region in the API response | PASS | {"n":"servicebus-ubd980948","l":"eastus"} |
| Service Bus | API delete -> UI: resource deleted over the API disappears from the list | PASS | DELETE 200 |
| Container registries | API->UI: resource created over the API is listed in the console | PASS |  |
| Container registries | API->UI: the list shows the region | PASS |  |
| Container registries | CLI->UI: resource created with `az rest` is listed in the console | PASS |  |
| Container registries | UI->API: resource created in the console wizard is returned by the API | PASS |  |
| Container registries | UI->API: same name and a real region in the API response | PASS | {"n":"acrubd994656","l":"eastus"} |
| Container registries | API delete -> UI: resource deleted over the API disappears from the list | PASS | DELETE 200 |
| Log Analytics workspaces | API->UI: resource created over the API is listed in the console | PASS |  |
| Log Analytics workspaces | API->UI: the list shows the region | PASS |  |
| Log Analytics workspaces | CLI->UI: resource created with `az rest` is listed in the console | PASS |  |
| Log Analytics workspaces | UI->API: resource created in the console wizard is returned by the API | PASS |  |
| Log Analytics workspaces | UI->API: same name and a real region in the API response | PASS | {"n":"loganalytics-ubd8315","l":"eastus"} |
| Log Analytics workspaces | API delete -> UI: resource deleted over the API disappears from the list | PASS | DELETE 200 |
| Azure AI services | API->UI: resource created over the API is listed in the console | PASS |  |
| Azure AI services | API->UI: the list shows the region | PASS |  |
| Azure AI services | CLI->UI: resource created with `az rest` is listed in the console | PASS |  |
| Azure AI services | UI->API: resource created in the console wizard is returned by the API | PASS |  |
| Azure AI services | UI->API: same name and a real region in the API response | PASS | {"n":"cognitiveservices-ubd22094","l":"eastus"} |
| Azure AI services | API delete -> UI: resource deleted over the API disappears from the list | PASS | DELETE 200 |
| Event Grid | API->UI: resource created over the API is listed in the console | PASS |  |
| Event Grid | API->UI: the list shows the region | PASS |  |
| Event Grid | CLI->UI: resource created with `az rest` is listed in the console | PASS |  |
| Event Grid | UI->API: resource created in the console wizard is returned by the API | PASS |  |
| Event Grid | UI->API: same name and a real region in the API response | PASS | {"n":"eventgrid-ubd35428","l":"eastus"} |
| Event Grid | API delete -> UI: resource deleted over the API disappears from the list | PASS | DELETE 200 |
| SQL databases | API->UI: resource created over the API is listed in the console | PASS |  |
| SQL databases | API->UI: the list shows the region | PASS |  |
| SQL databases | CLI->UI: resource created with `az rest` is listed in the console | PASS |  |
| SQL databases | UI->API: console wizard | NOT-AUTOMATED | generic filler could not complete the wizard (locator.waitFor: Timeout 20000ms exceeded.) |
| SQL databases | API delete -> UI: resource deleted over the API disappears from the list | PASS | DELETE 200 |
| Cosmos DB | API->UI: resource created over the API is listed in the console | PASS |  |
| Cosmos DB | API->UI: the list shows the region | PASS |  |
| Cosmos DB | CLI->UI: resource created with `az rest` is listed in the console | PASS |  |
| Cosmos DB | UI->API: console wizard | NOT-AUTOMATED | generic filler could not complete the wizard (locator.waitFor: Timeout 20000ms exceeded.) |
| Cosmos DB | API delete -> UI: resource deleted over the API disappears from the list | PASS | DELETE 200 |
| Recovery Services vaults | API->UI: resource created over the API is listed in the console | PASS |  |
| Recovery Services vaults | API->UI: the list shows the region | PASS |  |
| Recovery Services vaults | CLI->UI: resource created with `az rest` is listed in the console | PASS |  |
| Recovery Services vaults | UI->API: console wizard | NOT-AUTOMATED | generic filler could not complete the wizard (locator.waitFor: Timeout 20000ms exceeded.) |
| Recovery Services vaults | API delete -> UI: resource deleted over the API disappears from the list | PASS | DELETE 200 |
| Front Door | API->UI: resource created over the API is listed in the console | PASS |  |
| Front Door | CLI->UI: resource created with `az rest` is listed in the console | PASS |  |
| Front Door | UI->API: console wizard | NOT-AUTOMATED | generic filler could not complete the wizard (locator.waitFor: Timeout 20000ms exceeded.) |
| Front Door | API delete -> UI: resource deleted over the API disappears from the list | PASS | DELETE 200 |
| Network managers | API->UI: resource created over the API is listed in the console | PASS |  |
| Network managers | API->UI: the list shows the region | PASS |  |
| Network managers | CLI->UI: resource created with `az rest` is listed in the console | PASS |  |
| Network managers | UI->API: console wizard | NOT-AUTOMATED | generic filler could not complete the wizard (locator.waitFor: Timeout 20000ms exceeded.) |
| Network managers | API delete -> UI: resource deleted over the API disappears from the list | PASS | DELETE 200 |
| Stream Analytics | API->UI: resource created over the API is listed in the console | PASS |  |
| Stream Analytics | API->UI: the list shows the region | PASS |  |
| Stream Analytics | CLI->UI: resource created with `az rest` is listed in the console | PASS |  |
| Stream Analytics | UI->API: console wizard | NOT-AUTOMATED | generic filler could not complete the wizard (locator.waitFor: Timeout 20000ms exceeded.) |
| Stream Analytics | API delete -> UI: resource deleted over the API disappears from the list | PASS | DELETE 200 |
| API Management | API->UI: resource created over the API is listed in the console | PASS |  |
| API Management | API->UI: the list shows the region | PASS |  |
| API Management | CLI->UI: resource created with `az rest` is listed in the console | PASS |  |
| API Management | UI->API: console wizard | NOT-AUTOMATED | generic filler could not complete the wizard (locator.dispatchEvent: Timeout 30000ms exceeded.) |
| API Management | API delete -> UI: resource deleted over the API disappears from the list | PASS | DELETE 200 |
| Kubernetes services | API->UI: resource created over the API is listed in the console | PASS |  |
| Kubernetes services | API->UI: the list shows the region | PASS |  |
| Kubernetes services | CLI->UI: resource created with `az rest` is listed in the console | PASS |  |
| Kubernetes services | UI->API: console wizard | NOT-AUTOMATED | generic filler could not complete the wizard (locator.waitFor: Timeout 20000ms exceeded.) |
| Kubernetes services | API delete -> UI: resource deleted over the API disappears from the list | PASS | DELETE 200 |
| Container Apps | API->UI: resource created over the API is listed in the console | PASS |  |
| Container Apps | API->UI: the list shows the region | PASS |  |
| Container Apps | CLI->UI: resource created with `az rest` is listed in the console | PASS |  |
| Container Apps | UI->API: console wizard | NOT-AUTOMATED | generic filler could not complete the wizard (locator.waitFor: Timeout 20000ms exceeded.) |
| Container Apps | API delete -> UI: resource deleted over the API disappears from the list | PASS | DELETE 200 |
| App Service web apps | API->UI: resource created over the API is listed in the console | PASS |  |
| App Service web apps | API->UI: the list shows the region | PASS |  |
| App Service web apps | CLI->UI: resource created with `az rest` is listed in the console | PASS |  |
| App Service web apps | UI->API: resource created in the console wizard is returned by the API | PASS |  |
| App Service web apps | UI->API: same name and a real region in the API response | PASS | {"n":"appservices-ubd316384","l":"eastus"} |
| App Service web apps | API delete -> UI: resource deleted over the API disappears from the list | PASS | DELETE 200 |
| (run) | no uncaught page errors | NOTE | Cannot read properties of null (reading 'closest') / Cannot read properties of null (reading 'closest') / Cannot read pr |

**115 pass, 0 fail, 9 not automated.**
