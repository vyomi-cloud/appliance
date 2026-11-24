# Chapter 12: AgentOps and Observability

_Traces, metrics and logs you can read back_

**What you build:** See what the agent did: a trace per step, metrics for KPIs, and structured logs tied to the trace.

## Code, in order

### 1. Trace an agent run

Runs the agent, then turns its spans into an X-Ray trace (one segment per sub-agent and tool call), publishes KPIs to CloudWatch, and writes a structured log line that carries the trace id so you can jump from a log to its trace. The spans come from the real agent run, so this needs the hosted agent from chapter 3.

- File: [`app/trace_agent.py`](../app/trace_agent.py)
- Run: `cd app && python trace_agent.py`
- You should see: `structured log carries the trace id: True`

### 2. List the evaluators

AgentCore Evaluations score agent behaviour (correctness, helpfulness, tool selection). ListEvaluators shows the evaluators you can attach to the runtime.

- File: [`app/evaluators.py`](../app/evaluators.py)
- Run: `cd app && python evaluators.py`
- You should see: `evaluators available:`

## It works when

- trace can be read back
- metrics listed
- logs round-trip with trace id
