"""Component 3 Runtime: Foundry/Azure OpenAI Assistants (agent + thread + run) and the app-host alternative (Container Apps via ARM)."""
import time
from _common import *

P = Probe(3, "runtime", "Runtime: Assistants agent/thread/run + Container Apps host")
B = endpoint(); ensure_rg(B); ensure_openai(B)
S = {}


def agent():
    oc = aoai(B, "2025-03-01-preview")
    a = oc.beta.assistants.create(model="chat", name="supervisor", instructions="Route facilities requests.",
                                  tools=[{"type": "function", "function": {"name": "create_work_order", "parameters": {"type": "object", "properties": {"site": {"type": "string"}}}}}])
    S["oc"], S["a"] = oc, a
    return a.id


def thread_run():
    oc, a = S["oc"], S["a"]
    th = oc.beta.threads.create(messages=[{"role": "user", "content": "The lobby has a water leak."}])
    r = oc.beta.threads.runs.create(th.id, assistant_id=a.id)
    S["th"], S["run"] = th, r
    return {"thread": th.id, "run": r.id, "status": r.status}


def run_completes():
    """Runs execute synchronously inside create(); the status comes back in the create response."""
    r = S["run"]
    assert r.status in ("completed", "requires_action"), f"run {r.status}: {getattr(r.last_error, 'message', '')[:150]}"
    return r.status


def get_paths():
    """Reading state back: GET thread, GET run, list messages (what every agent loop does after a run)."""
    oc = S["oc"]
    oc.beta.threads.retrieve(S["th"].id)
    oc.beta.threads.runs.retrieve(S["run"].id, thread_id=S["th"].id)
    return [m.role for m in oc.beta.threads.messages.list(S["th"].id).data]


def foundry_project_agents():
    """azure-ai-agents (the Foundry Agents SDK) at a project endpoint: <endpoint>/api/projects/<p>."""
    from azure.ai.agents import AgentsClient
    from azure.core.pipeline.policies import SansIOHTTPPolicy
    c = AgentsClient(endpoint=B + "/api/projects/p1", credential=Cred(), authentication_policy=SansIOHTTPPolicy())
    return c.create_agent(model="chat", name="foundry-sup", instructions="x").id


def capp():
    from azure.mgmt.appcontainers import ContainerAppsAPIClient
    c = arm(ContainerAppsAPIClient, B)
    c.managed_environments.begin_create_or_update(RG, "env1", {"location": LOC, "properties": {}}).result()
    env = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.App/managedEnvironments/env1"
    a = c.container_apps.begin_create_or_update(RG, "agent-app", {"location": LOC, "properties": {"managedEnvironmentId": env,
        "configuration": {"ingress": {"external": True, "targetPort": 8080}},
        "template": {"containers": [{"name": "agent", "image": "mcr.microsoft.com/k8se/quickstart:latest"}]}}}).result()
    S["capp"] = a
    return {"fqdn": a.latest_revision_fqdn, "state": str(a.provisioning_state)}


def capp_runs_code():
    """Does the app host actually run the image (the AgentCore Runtime analogue)? Look for a reachable ingress URL."""
    import requests
    a = S["capp"]
    assert a.latest_revision_fqdn, "no fqdn"
    base = f"http://{a.latest_revision_fqdn}" if not a.latest_revision_fqdn.startswith("http") else a.latest_revision_fqdn
    r = requests.get(base, timeout=5)
    return r.status_code


if P.step("Assistants: create agent with function tool (openai AzureOpenAI beta.assistants)", agent):
    P.step("Assistants: create thread + message + run", thread_run)
    P.step("run reaches completed / requires_action (needs a model; 503 from the LLM seam without one)", run_completes, blocked="no model")
    P.step("GET thread / GET run / list messages (read-back after the run)", get_paths)
P.step("Foundry Agents SDK (azure-ai-agents) at a project endpoint", foundry_project_agents)
if P.step("Container Apps: environment + container app via ARM (azure-mgmt-appcontainers)", capp):
    P.step("Container App ingress answers HTTP (does the host run the container?)", capp_runs_code)
P.finish()
