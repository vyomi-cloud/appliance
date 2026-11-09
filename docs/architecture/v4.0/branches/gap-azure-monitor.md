# v4/gap-azure-monitor

Closes the "Not simulated in Vyomi" pages of the Azure Monitor console (offline + Nano share the cores).

## What changed
- **Metrics Add filter / Apply splitting** (core/azure_monitor_core.py): the `ActivityOperations` metric now has real dimensions
  `OperationName` and `Status` (the Activity-log row columns being counted). Metrics `$filter` supports `eq`/`ne`/`or` and `Dim eq '*'`
  (split); split series carry `metadatavalues`. Other metrics have no dimensions (400 if filtered).
- **Save to dashboard**: `Microsoft.Portal/dashboards` added to the ARM catalog (core/azure_arm_data.py); the Metrics page writes a
  `MonitorChartPart` into a real dashboard resource and lists/deletes pinned dashboards.
- **Azure Local** (`Microsoft.AzureStackHCI/clusters`) and **SCOM managed instance** (`Microsoft.Scom/managedInstances`) in
  core/azure_monitorproducts_core.py: validated ARM records with real console pages.
- Registry: `core/capabilities/azure/monitor.json` (`metric_dimensions`, `metrics_dashboards` full; `azure_local_insights` limited;
  `scom_managed_instance` config_only).
- Tests: tests/conformance/test_azure_monitor_core.py, test_azure_monitorproducts.py, consoles/tests/smoke-azure-monitor-gaps.mjs.

## Design decisions
- No new containers: dimensions come from data already recorded; Grafana/Prometheus/OTel work stays on the existing /_obs path.
- Azure Local and SCOM cannot be real without hardware / a System Center server + SQL MI + AD domain, so they are clearly labelled
  Vyomi-simulated records (nodes are declared by the user; nothing is monitored).

## Open issues
- Nano in-browser (Pyodide) run of the changed cores is not exercised here (pyodide not vendored in the worktree).
- Pinned dashboards are listed on the Metrics page only; there is no portal dashboard canvas to render them.
