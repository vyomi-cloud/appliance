# Chapter 2: Agent Runtime

_A supervisor agent and three sub-agents answering in isolated sessions_

**What you build:** Host a supervisor agent that routes work to Facilities, Maintenance and Analytics sub-agents, one isolated session at a time.

## Code, in order

### 1. Install the libraries

Chapter 3 builds the agent runtime. Azure has no single hosted-agent service like AgentCore Runtime or Vertex AI Agent Engine, so this layer is ASSEMBLED from two real services and says so plainly: Azure AI Foundry Agents (`azure-ai-agents`) holds the agent definitions and runs them on threads, and Azure Container Apps (`azure-mgmt-appcontainers`) hosts your own agent code, a LangGraph supervisor, behind an HTTPS ingress. It relies on the chat deployment from chapter 10 and `azlab.py`.

- File: [`app/install3.sh`](../app/install3.sh)

### 2. Create the supervisor and the three sub-agents in Foundry

Four agent definitions in the Foundry project `facilities-project`, created with the real `azure-ai-agents` client: a supervisor that routes, and Facilities, Maintenance and Analytics sub-agents. The tool definitions are declared now (the model can ask for them); chapter 7 builds the tools themselves and chapter 4 puts a gateway in front of them. Then the supervisor runs on a thread: create thread, add a user message, create a run, poll it. The model is the repo's deterministic test stub: it answers a question that mentions tools by asking for one, so the run stops in `requires_action` (the model asked your code to call a tool and is waiting). That is the correct, expected state here: chapter 7 builds the tools and chapter 4 the gateway they sit behind.

- File: [`app/foundry_agents.py`](../app/foundry_agents.py)
- Run: `cd app && python foundry_agents.py`
- You should see: `agents: ['facilities_analytics', 'facilities_facilities', 'facilities_maintenance', 'facilities_supervisor']`

### 3. Write the supervisor graph

The agent code itself, a LangGraph `StateGraph`: the supervisor asks the model which sub-agents are needed (a JSON list), runs them in order, and synthesises one answer. Each sub-agent is a node with its own role prompt. Every span (a timed step) is recorded in the state, because chapter 8 turns them into traces. At this point the sub-agents have no tools (those arrive in chapters 7 and 4), so each answers from the model alone: that is stated in the code, not hidden. The cloud is injected as a `converse(system, text)` function, so this file has no Azure code in it and is reused unchanged in later chapters.

- File: [`app/agent_graph.py`](../app/agent_graph.py)

### 4. Write the HTTP app with isolated sessions

The Container Apps entrypoint: a small FastAPI app. `POST /query` takes a prompt, a user and a session id and runs the graph. Conversation history is kept per session id in its own list, so one session never sees another's turns: that is the isolation the runtime layer owes you. The model client is the real `openai` `AzureOpenAI` client on your `chat` deployment, pointed at the simulator through environment variables the container receives.

- File: [`app/app.py`](../app/app.py)

### 5. Run the graph locally first

Before hosting, prove the graph on your machine: route, run the sub-agents, answer. The router sends this question to the Facilities agent (procedures) and the Maintenance agent (an asset id). The answer text comes from the deterministic test stub.

- File: [`app/try_graph.py`](../app/try_graph.py)
- Run: `cd app && python try_graph.py`
- You should see: `route: ['facilities', 'maintenance'] | model routed: True`

### 6. Create the Container Apps environment and the app

Two ARM calls with `azure-mgmt-appcontainers`: a managed environment, then the container app `facilities-supervisor` with external ingress on port 8080. The simulator's Python app image `vyomi/python-app:latest` starts `app.py` from the zip you pass in `VYOMI_APP_SOURCE_B64`; on real Azure you would instead build a container image from the same two files, push it to Azure Container Registry and put its name in `image`. The environment variables are the endpoint the container calls the model on, the same way you would set them on real Container Apps.

- File: [`app/deploy_container_app.py`](../app/deploy_container_app.py)
- Run: `cd app && python deploy_container_app.py`
- You should see: `container app facilities-supervisor state: Succeeded`

### 7. Call the hosted supervisor in two sessions

Read the ingress address from the container app (the simulator reports it as `vyomiIngressUrl`; on real Azure it is `properties.configuration.ingress.fqdn`) and `POST /query`. Session `s1` asks twice and session `s2` once: the turn counters prove the two sessions do not share history. The hosted app runs the LangGraph supervisor and sub-agents inside the container process (see the `pid`).

- File: [`app/call_container_app.py`](../app/call_container_app.py)
- Run: `cd app && python call_container_app.py`
- You should see: `s1 turns: 1 -> 2 | s2 turns: 1`

## It works when

- agents exist
- a run completes
- container app answers /query
