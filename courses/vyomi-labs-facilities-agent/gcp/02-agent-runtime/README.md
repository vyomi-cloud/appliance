# Layer 2: Agent Runtime

_A supervisor agent and three sub-agents answering in isolated sessions_

**What you build:** Host a supervisor agent that routes work to Facilities, Maintenance and Analytics sub-agents, one isolated session at a time.

## Code, in order

### 1. Install the libraries

Chapter 3 hosts the agent on Vertex AI Agent Engine and builds the graph with LangGraph. It relies on the gcp.py and vymodels.py files from chapter 10.

- File: [`install_3.sh`](./install_3.sh)

### 2. Write the starter tools

The sub-agents need something to look things up in. Until chapters 7 (tools), 12 (pipeline) and 5 (approval) exist, they use this small in-package data set (the same four SOP documents, three assets and three work orders you will load into Cloud Storage and Firestore later). Those chapters replace each function with a real backend; the agents code below does not change shape.

- File: [`starter_tools.py`](./starter_tools.py)

### 3. Write the supervisor and the three sub-agents

A LangGraph graph: the supervisor asks the model which specialists are needed (Facilities for procedures, Maintenance for a specific asset, Analytics for counts), the chosen sub-agents run in order, and the supervisor writes the final answer from what they found. Every step records a span so chapter 8 can export a trace. If the model's routing reply cannot be parsed, keyword rules take over, and the result says which was used (llm_used).

- File: [`agents.py`](./agents.py)

### 4. Try the agent in your own process

Before hosting it, run the graph locally. The question needs all three sub-agents: the SOP (Facilities), asset B-12 (Maintenance) and a count (Analytics). The answer text comes from the deterministic test stub in this verification (it repeats the first retrieved passage); a larger model would write a sentence.

- File: [`try_agent.py`](./try_agent.py)
- Run: `python try_agent.py` (or `./run_all.sh 2` from the project root)
- You should see: `route: ['facilities', 'maintenance', 'analytics']`

### 5. Write the Agent Engine entry point

Agent Engine hosts a class with a set_up() method (runs once when the engine starts) and the query method you register at deploy time. It reads where the model is from environment variables set at deploy.

- File: [`agent_engine_app.py`](./agent_engine_app.py)

### 6. Deploy the agent to Agent Engine

Packages the five files as a source package, stages it in Cloud Storage and creates the engine facilities_supervisor with class method query. The environment variables tell the hosted agent where the model is (on real Google Cloud you would leave the endpoint out).

- File: [`deploy_agent.py`](./deploy_agent.py)
- Run: `python deploy_agent.py` (or `./run_all.sh 2` from the project root)
- You should see: `deployed projects/`

### 7. Query the hosted agent

Looks the engine up by its display name and sends one question. The check that matters is the process id: the agent runs in the engine's own process, not in yours.

- File: [`query_agent.py`](./query_agent.py)
- Run: `python query_agent.py` (or `./run_all.sh 2` from the project root)
- You should see: `hosted in a separate process: True`

## It works when

- engine facilities_supervisor exists
- query returns an answer
- sessions isolated
