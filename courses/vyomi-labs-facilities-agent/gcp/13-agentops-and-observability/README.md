# Layer 13: AgentOps and Observability

_Traces, metrics and logs you can read back_

**What you build:** See what the agent did: a trace per step, metrics for KPIs, and structured logs tied to the trace.

## Code, in order

### 1. Install the libraries

Chapter 8 makes the agent observable: a trace of what it did (Cloud Trace), structured logs tied to that trace (Cloud Logging) and KPI metrics (Cloud Monitoring). It relies on gcp.py (chapter 10) and the supervisor in agents.py (chapter 3), whose run records one span per agent and tool step. Cloud Monitoring has no REST transport in the Python library, so metrics and the gRPC logging example use the simulator's gRPC front door.

- File: [`install_8.sh`](./install_8.sh)

### 2. Export the agent's spans to Cloud Trace

Runs the supervisor, then sends its spans to Cloud Trace v2 with batch_write_spans: one root span for the whole run and one child span per agent or tool step, all under one trace id. The trace id is saved so the log and metric steps can point at it.

- File: [`export_trace.py`](./export_trace.py)
- Run: `python export_trace.py` (or `./run_all.sh 13` from the project root)
- You should see: `spans exported in trace`

### 3. Read the trace back

Cloud Trace v1 reads the trace by id and lists traces for the project: confirmation the spans landed and that each agent step is a span.

- File: [`read_trace.py`](./read_trace.py)
- Run: `python read_trace.py` (or `./run_all.sh 13` from the project root)
- You should see: `trace listed by list_traces: True`

### 4. Write a structured log tied to the trace

A structured log entry (log_struct) for the run, carrying the trace resource name so Logs Explorer can show the log and the trace together; then read it back with a filter on the log name. This uses the library's HTTP mode.

- File: [`log_run.py`](./log_run.py)
- Run: `python log_run.py` (or `./run_all.sh 13` from the project root)
- You should see: `trace field ends with the trace id: True`

### 5. Publish a KPI metric

A custom metric custom.googleapis.com/facilities/tool_calls: create the metric descriptor, write one data point (how many tools the agent called) and read it back. Monitoring has no REST transport in the Python library, so this is the default gRPC client pointed at the simulator's gRPC front door.

- File: [`metric.py`](./metric.py)
- Run: `python metric.py` (or `./run_all.sh 13` from the project root)
- You should see: `metric read back:`

### 6. Write logs over gRPC too

Cloud Logging's default transport is gRPC. The same structured log written and read back through the default client shows the application code is unchanged on real Google Cloud: only the endpoint option is simulator-specific.

- File: [`log_grpc.py`](./log_grpc.py)
- Run: `python log_grpc.py` (or `./run_all.sh 13` from the project root)
- You should see: `gRPC log entry written and read back`

### 7. Cost and budget limit per layer

A budget object counts notional model tokens per layer and refuses the call that would cross the limit, so a runaway loop stops itself before the bill. The block drives the real Gemini-compatible model from chapter 10 until the budget trips, then asserts the crossing call was refused and spend never exceeded the limit.

- File: [`cost_meter.py`](./cost_meter.py)
- Run: `python cost_meter.py` (or `./run_all.sh 13` from the project root)
- You should see: `cost limit verified`

## It works when

- trace readable
- structured log with trace id
- custom metric listed
