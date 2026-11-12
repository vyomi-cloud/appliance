# v4/gap-c-azure

Closes the "class C" Azure console gaps with real local engines where one can exist.

| Page | Engine | Substrates |
|---|---|---|
| Cosmos DB Power BI | OData v4 feed + CSV/JSON/Parquet export over real container data (`core/azure_cosmos_core.py`) | OData/CSV/JSON on both; Parquet offline (pyarrow) |
| SQL Mirror database | Worker replicating SQL tables to Parquet in the Blob store, incremental (`core/azure_sql_mirror_core.py`) | offline only (needs sync Parquet); Nano answers 501 |
| Event Grid topic / Resource group Tasks | Logic-style tasks that run on ARM (`core/azure_tasks_core.py`) plus a Docker script runner (`core/container_runner.py`) | ARM tasks both; container template offline only |
| Defender DevOps security | Trivy (`aquasec/trivy`) over each resource group's exported ARM template | offline with Docker + image |
| Defender Workload protections / Data security / Firewall Manager | Rule engine over live ARM state (`core/azure_devsimplified_core.py`) - Dev Simplified | both |
| Entra Users | Bulk create/delete over the Graph store | both |

Not in scope (vendor-cloud only): Power BI service, Microsoft Fabric service, Defender cloud threat intelligence, source-repo connectors. Not built: Gitea-backed Boards, Checkov, Entra Edit / Per-user MFA / Preview features / Export Data Settings / feedback.

Tests: `tests/conformance/test_azure_devsimplified.py` (needs Docker, `alpine:latest`, `aquasec/trivy:0.57.1` for the real-engine checks), `test_azure_sql_mirror.py` and `test_azure_cosmos_export.py` (pyarrow for Parquet).
