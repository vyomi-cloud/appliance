# Layer 12: AgentOps and Observability

_Traces, metrics and logs you can read back_

**What you build:** See what the agent did: a trace per step, metrics for KPIs, and structured logs tied to the trace.

## Code, in order

### 1. Install the libraries

Chapter 8 lets you see what the agent did: one trace span per agent and tool step, a structured log line and a custom metric, all exported to Application Insights with the official OpenTelemetry exporter (`azure-monitor-opentelemetry-exporter`), then read back with KQL (Kusto) from the linked Log Analytics workspace (`azure-monitor-query`). It runs the supervisor graph from chapter 3, so it needs `agent_graph.py`, `app.py`, chapter 7 (tools), chapter 5 (approval) and chapter 6 (search).

- File: [`install8.sh`](./install8.sh)

### 2. Create the workspace and the Application Insights component

Azure's observability is two resources: a Log Analytics workspace (the store you query with KQL) and a *workspace-based* Application Insights component (the ingestion endpoint for traces, logs and metrics, which writes into that workspace). Created through Azure Resource Manager; the connection string and the workspace id are saved to `obs.json`.

- File: [`create_observability.py`](./create_observability.py)
- Run: `python create_observability.py` (or `./run_all.sh 12` from the project root)
- You should see: `application insights facilities-ai ready`

### 3. Write the full agent: the graph plus its tools

The chapter 3 graph, now with real tools plugged into its `tools` hook. Facilities calls the `kb-search` function, Maintenance calls `asset-status` and, when the question asks for a work order, parks an approval request (chapter 5), and Analytics counts work orders in Table storage. Each tool call is recorded as a span of kind `tool` next to the agent spans. The model is the repo's deterministic test stub, so its answers are short and fixed; the routing, the tool calls and the spans are real.

- File: [`full_agent.py`](./full_agent.py)

### 4. Run the agent once

One real run through every layer built so far: the supervisor routes to all three sub-agents, the tools run (search, asset lookup, an approval request, the statistics), and the spans come back in the state.

- File: [`run_agent.py`](./run_agent.py)
- Run: `python run_agent.py` (or `./run_all.sh 12` from the project root)
- You should see: `approval request parked: True`

### 5. Export the spans, a log line and a metric

With the OpenTelemetry SDK and the Azure Monitor exporters: the run becomes one root span `facilities-supervisor` with a child span per agent and tool step (their start and end times are the ones the graph measured); a structured JSON log line records the route and tools; and a counter `facilities.tool_calls` records how many tools ran. Every record carries the trace id, which is how you find them again.

- File: [`export_telemetry.py`](./export_telemetry.py)
- Run: `python export_telemetry.py` (or `./run_all.sh 12` from the project root)
- You should see: `the metric facilities.tool_calls = 4`

### 6. Read it back with KQL

`LogsQueryClient.query_workspace` runs Kusto queries against the workspace. Spans land in `AppDependencies`, log lines in `AppTraces`, the metric in `AppMetrics`; the trace id is `OperationId`. Telemetry takes a moment to be queryable, so the script retries for up to 20 seconds. Alert rules and workbooks are not simulated; the KQL subset covers these queries.

- File: [`query_telemetry.py`](./query_telemetry.py)
- Run: `python query_telemetry.py` (or `./run_all.sh 12` from the project root)
- You should see: `facilities.tool_calls total: 4`

### 7. Ingest into a custom table and summarise

For data that is not a trace, the Log Analytics HTTP Data Collector API writes rows straight into a custom table (`AgentRun_CL`; the suffixes `_s` mark string columns). Then KQL `summarize` counts calls per tool.

- File: [`custom_table.py`](./custom_table.py)
- Run: `python custom_table.py` (or `./run_all.sh 12` from the project root)
- You should see: `calls per tool: {'asset_status': 2, 'kb_search': 1, 'work_order_stats': 1}`

### 8. Read platform metrics from Azure Monitor

Azure resources publish their own metrics. `MonitorManagementClient.metrics.list` reads the `Transactions` metric of the documents storage account from chapter 12.

- File: [`platform_metrics.py`](./platform_metrics.py)
- Run: `python platform_metrics.py` (or `./run_all.sh 12` from the project root)
- You should see: `platform metrics returned: ['Transactions']`

## It works when

- spans readable with KQL
- log line readable
- custom metric readable
