# Layer 12: AgentOps and Observability

_Traces, metrics and logs you can read back_

**What you build:** See what the agent did: a trace per step, metrics for KPIs, and structured logs tied to the trace.

## Code, in order

### 1. Trace an agent run

Runs the agent, then turns its spans into an X-Ray trace (one segment per sub-agent and tool call), publishes KPIs to CloudWatch, and writes a structured log line that carries the trace id so you can jump from a log to its trace. The spans come from the real agent run, so this needs the hosted agent from chapter 3.

- File: [`trace_agent.py`](./trace_agent.py)
- Run: `python trace_agent.py` (or `./run_all.sh 12` from the project root)
- You should see: `structured log carries the trace id: True`

### 2. List the evaluators

AgentCore Evaluations score agent behaviour (correctness, helpfulness, tool selection). ListEvaluators shows the evaluators you can attach to the runtime.

- File: [`evaluators.py`](./evaluators.py)
- Run: `python evaluators.py` (or `./run_all.sh 12` from the project root)
- You should see: `evaluators available:`

### 3. A cost meter and a budget limit per layer

Cost is a feature of an enterprise agent, not an invoice surprise. Every layer gets a meter and a ceiling: tokens in and out are converted to a notional dollar figure (the simulator's models are free, the arithmetic is the lesson), published to CloudWatch with a Layer dimension, and checked against that layer's budget before the next call. The block asserts the metrics are readable per layer, an alarm exists on the budget, and a layer over budget is refused while the others keep working.

- File: [`cost_meter.py`](./cost_meter.py)
- Run: `python cost_meter.py` (or `./run_all.sh 12` from the project root)
- You should see: `cost control verified`

## It works when

- trace can be read back
- metrics listed
- logs round-trip with trace id
