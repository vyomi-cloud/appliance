"""Hands-on lab blocks for the Microsoft Azure course. Every block is complete, copy-paste code: the learner saves `file`, runs `run`, and sees `expect`.
vyomilabs/labrun.py executes these blocks in order against a clean local Azure simulator (vyomilabs/labenv_azure.py), so what the guide shows is what has actually run.
The model is the repo's deterministic test stub (tools/llm_stub), not a large hosted model: calls and shapes are identical, replies are fixed and short."""


BOTH = ["nano", "mesh"]
MESH = ["mesh"]


def b(title, text, file, code, run=None, expect=None, lang="python", needs_runtime=False, edition=None, nano_note=None, kind="build", needs_appliance=False):
    """needs_runtime: the block needs real function execution (appliance or Mesh); the local in-process simulator only runs a restricted sandbox.
    needs_appliance: needs the full appliance (labrun only runs it with --endpoint). edition: ["nano","mesh"] (default) or ["mesh"] for the paid Mesh course only.
    nano_note: why a block is not on Nano or what a Nano learner should expect. kind: build | harden | iam | failure | ship."""
    return dict(title=title, text=text, file=file, lang=lang, code=code.strip("\n") + "\n", run=run, expect=expect, needs_runtime=needs_runtime,
                edition=list(edition or BOTH), nano_note=nano_note, kind=kind, needs_appliance=needs_appliance)


from .rag_design_src import design_blocks

LAB = {}

PIP1 = "pip install azure-core azure-identity azure-mgmt-apimanagement azure-mgmt-frontdoor azure-mgmt-network PyJWT cryptography requests"

LAB[1] = [
 b("Install the libraries", "Chapter 1 sign users in and protects the front door: Microsoft Entra ID issues the tokens (`azure-identity`), the API Management gateway from chapter 4 verifies them with a `validate-jwt` policy, and Web Application Firewall policies sit at the edge (`azure-mgmt-frontdoor`, `azure-mgmt-network`). It needs the gateway from chapter 4. The simulator serves Entra on the same https address as everything else, which is why `azure-identity` is given it as its `authority`.",
   "install1.sh", PIP1, lang="bash"),
 b("Register the app and a user in Entra", "Two things to sign in: an application registration (the agent) with a client secret, and a user. This is Microsoft Graph v1.0 REST, the same calls `az ad app create`, `az ad app credential reset` and `az ad user create` make. The ids and secret are saved to `entra.json` for the next blocks (a real secret would go in Key Vault, chapter 13).",
   "entra.py", '''
import json
import requests
from azlab import ENDPOINT

API_URI = "api://facilities-api"
USER, PASSWORD = "maria.ops@facilities.example.com", "Fac!lities-2026"


def graph(method, path, body=None):
    r = requests.request(method, f"{ENDPOINT}/v1.0{path}", json=body, headers={"Authorization": "Bearer vyomi-local"}, timeout=30)
    if r.status_code >= 300 and "already exists" not in r.text.lower():
        raise RuntimeError(f"Graph {method} {path} HTTP {r.status_code}: {r.text[:200]}")
    return r.json() if r.text else {}


if __name__ == "__main__":
    app = graph("POST", "/applications", {"displayName": "facilities-users", "identifierUris": [API_URI]})
    secret = graph("POST", f"/applications/{app['id']}/addPassword", {"passwordCredential": {"displayName": "facilities-agent"}})
    graph("POST", "/users", {"displayName": "Maria Ops", "userPrincipalName": USER, "mailNickname": "maria.ops", "accountEnabled": True,
                             "passwordProfile": {"password": PASSWORD, "forceChangePasswordNextSignIn": False}})
    json.dump({"client_id": app["appId"], "client_secret": secret["secretText"]}, open("entra.json", "w"))
    print("app registration facilities-users client_id:", app["appId"], "| user:", USER)
''', run="python entra.py", expect="app registration facilities-users client_id:"),
 b("Sign in and verify the token", "Two sign-ins. The application signs in with its client secret through `azure-identity`'s `ClientSecretCredential` (the client-credentials flow) and gets a JWT. The user signs in with the OAuth2 password grant on the tenant's token endpoint (what `UsernamePasswordCredential` does; this script calls the endpoint directly because the MSAL library behind that credential drops the port from the user-realm lookup URL on a local address). Then the part the backend must always do: verify the token's RS256 signature against the tenant's published signing keys (JWKS) with PyJWT and check the audience. The user's token is saved in `token.txt` (the gateway helper picks it up) and the application token in `app_token.txt`.",
   "sign_in.py", '''
import json
import jwt
import requests
from azure.identity import ClientSecretCredential
from azlab import ENDPOINT, TENANT
from entra import API_URI, USER, PASSWORD

cfg = json.load(open("entra.json"))
cred = ClientSecretCredential(TENANT, cfg["client_id"], cfg["client_secret"], authority=ENDPOINT, disable_instance_discovery=True)
app_token = cred.get_token(API_URI + "/.default").token
open("app_token.txt", "w").write(app_token)
print("application token is a JWT:", app_token.count(".") == 2)

r = requests.post(f"{ENDPOINT}/{TENANT}/oauth2/v2.0/token", data={"grant_type": "password", "client_id": cfg["client_id"], "username": USER, "password": PASSWORD,
                                                                  "scope": API_URI + "/.default"}, timeout=30)
r.raise_for_status()
user_token = r.json()["access_token"]
open("token.txt", "w").write(user_token)

key = jwt.PyJWKClient(f"{ENDPOINT}/{TENANT}/discovery/v2.0/keys").get_signing_key_from_jwt(user_token).key
claims = jwt.decode(user_token, key, algorithms=["RS256"], audience=[API_URI, cfg["client_id"]], options={"verify_iss": False})
print("signature verified against the tenant keys | signed in as:", claims.get("preferred_username") or claims.get("upn"))
''', run="python sign_in.py", expect="signed in as: maria.ops@facilities.example.com"),
 b("Turn on validate-jwt at the gateway", "Replace the API policy from chapter 4 with one that also runs `validate-jwt` first: the gateway fetches the tenant's OpenID configuration, checks the signature and that the audience is your API, and answers 401 itself otherwise. It keeps the function key and the rate limit, and adds an `x-vyomi-caller` header carrying the caller's application id (the `azp` claim of a v2.0 token), so a tool can audit who called it. Then four calls prove the edge: no key, key but no token, a forged `alg=none` token, and the real token.",
   "protect_gateway.py", '''
import base64
import json
import requests
from azlab import ENDPOINT, TENANT, RG
from azdata import function_key
from entra import API_URI
from gw import apim, SERVICE, url, subscription_key

cfg = json.load(open("entra.json"))
POLICY = ('<policies><inbound><base/>'
          '<validate-jwt header-name="Authorization" failed-validation-httpcode="401" failed-validation-error-message="Unauthorized. Access token is missing or invalid.">'
          f'<openid-config url="{ENDPOINT}/{TENANT}/v2.0/.well-known/openid-configuration"/>'
          f'<audiences><audience>{API_URI}</audience><audience>{cfg["client_id"]}</audience></audiences></validate-jwt>'
          f'<set-header name="x-functions-key" exists-action="override"><value>{function_key()}</value></set-header>'
          '<rate-limit-by-key calls="60" renewal-period="60" counter-key="@(context.Subscription.Id)"/>'
          '<set-header name="x-vyomi-caller" exists-action="override"><value>@(context.Request.Headers.GetValueOrDefault("Authorization","").AsJwt()?.Claims["azp"].FirstOrDefault())</value></set-header>'
          '</inbound><backend><base/></backend><outbound><base/></outbound><on-error><base/></on-error></policies>')
apim().api_policy.create_or_update(RG, SERVICE, "tools", "policy", {"value": POLICY, "format": "xml"})


def call(key=True, token=None):
    h = {"Content-Type": "application/json"}
    if key:
        h["Ocp-Apim-Subscription-Key"] = subscription_key()
    if token:
        h["Authorization"] = "Bearer " + token
    return requests.post(url("tools/kb-search"), json={"query": "boiler pressure limit"}, headers=h, timeout=60)


b64 = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
forged = f"{b64({'alg': 'none'})}.{b64({'aud': API_URI, 'appid': 'evil'})}."
print("no subscription key:", call(key=False, token=open("token.txt").read()).status_code)
print("key but no token:", call().status_code)
print("forged alg=none token:", call(token=forged).status_code)
good = call(token=open("token.txt").read())
print("real Entra user token:", good.status_code, "| results:", len(good.json()["results"]))
app_call = call(token=open("app_token.txt").read()).json()
print("application token -> caller seen by the tool is the app id:", app_call["caller"] == cfg["client_id"])
''', run="python protect_gateway.py", expect="application token -> caller seen by the tool is the app id: True"),
 b("Create the WAF policies", "A Web Application Firewall inspects requests at the edge for injection and similar attacks. Two real policy types, each created and read back: an Azure Front Door policy (Premium, default rule set, Prevention mode) with `azure-mgmt-frontdoor`, and an Application Gateway policy (OWASP 3.2) with `azure-mgmt-network`. The simulator stores and returns these policies; it has no layer-7 firewall engine, so it does not block attack traffic itself.",
   "waf.py", '''
from azure.mgmt.frontdoor import FrontDoorManagementClient
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.network.models import ManagedRuleSet, ManagedRulesDefinition, PolicySettings, WebApplicationFirewallPolicy
from azlab import arm, ensure_rg, RG, LOC

ensure_rg()
fd = arm(FrontDoorManagementClient)
fd.policies.begin_create_or_update(RG, "facilitieswaf", {
    "location": "global", "sku": {"name": "Premium_AzureFrontDoor"}, "policy_settings": {"enabled_state": "Enabled", "mode": "Prevention"},
    "managed_rules": {"managed_rule_sets": [{"rule_set_type": "Microsoft_DefaultRuleSet", "rule_set_version": "2.1"}]}}).result()
got = fd.policies.get(RG, "facilitieswaf")
print("Front Door WAF policy", got.name, "mode:", getattr(got.policy_settings.mode, "value", got.policy_settings.mode))

net = arm(NetworkManagementClient)
net.web_application_firewall_policies.create_or_update(RG, "facilitieswafgw", WebApplicationFirewallPolicy(
    location=LOC, policy_settings=PolicySettings(state="Enabled", mode="Prevention"),
    managed_rules=ManagedRulesDefinition(managed_rule_sets=[ManagedRuleSet(rule_set_type="OWASP", rule_set_version="3.2")])))
gw = net.web_application_firewall_policies.get(RG, "facilitieswafgw")
print("Application Gateway WAF policy", gw.name, "mode:", getattr(gw.policy_settings.mode, "value", gw.policy_settings.mode))
''', run="python waf.py", expect="Application Gateway WAF policy facilitieswafgw mode: Prevention"),
]
PIP2 = "pip install azure-core azure-ai-contentsafety azure-mgmt-cognitiveservices azure-mgmt-servicebus azure-servicebus openai"

LAB[2] = [
 b("Install the libraries", "Chapter 2 guards what comes in and tells approvers what is waiting. Input guardrails: Azure AI Content Safety (`azure-ai-contentsafety`, you call it) and the Azure OpenAI content filter (a policy bound to a deployment that filters every prompt and completion for you). The approver inbox is the Service Bus subscription you created in chapter 5. It uses `azlab.py` (chapter 10) and `approval.py` (chapter 5). Scope note: the simulator's filters are a deterministic rule set, not Microsoft's trained classifiers.",
   "install2.sh", PIP2, lang="bash"),
 b("Screen an input with Content Safety", "`analyze_text` returns a severity per harm category (Hate, SelfHarm, Sexual, Violence). A normal facilities question scores 0 everywhere; a threat is flagged. Your channel code calls this before the text reaches the agent, and refuses at or above a threshold you choose.",
   "screen_input.py", '''
from azure.ai.contentsafety import ContentSafetyClient
from azure.ai.contentsafety.models import AnalyzeTextOptions
from azure.core.credentials import AzureKeyCredential
from azlab import ENDPOINT

client = ContentSafetyClient(ENDPOINT, AzureKeyCredential("vyomi-local"))


def screen(text):
    return {x.category: x.severity for x in client.analyze_text(AnalyzeTextOptions(text=text)).categories_analysis}


ok = screen("What is the SOP when boiler pressure exceeds 30 psi?")
bad = screen("I am going to kill and torture you")
print("benign question flagged:", any(v for v in ok.values()))
print("threat flagged:", any(v and v > 0 for v in bad.values()), "| categories:", {k: v for k, v in bad.items() if v})
''', run="python screen_input.py", expect="benign question flagged: False"),
 b("Bind a content-filter policy to a model deployment", "The second guardrail needs no code in your app: a Responsible AI (RAI) policy, `facilities-guardrail`, filters Violence, Hate, SelfHarm and Sexual content on both the Prompt and the Completion, and is attached to a deployment (`chat-guarded`, same model as `chat`). A harmful prompt is refused with HTTP 400 `content_filter` before any model runs; a benign one reaches the model. Uses `azure-mgmt-cognitiveservices`.",
   "content_filter.py", '''
from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient
from openai import BadRequestError
from azlab import arm, aoai, pick_models, RG, OPENAI_ACCOUNT

cs = arm(CognitiveServicesManagementClient)
filters = [{"name": n, "severityThreshold": "Low", "blocking": True, "enabled": True, "source": s}
           for n in ("Violence", "Hate", "SelfHarm", "Sexual") for s in ("Prompt", "Completion")]
cs.rai_policies.create_or_update(RG, OPENAI_ACCOUNT, "facilities-guardrail", {"properties": {"mode": "Blocking", "basePolicyName": "Microsoft.Default", "contentFilters": filters}})
cs.deployments.begin_create_or_update(RG, OPENAI_ACCOUNT, "chat-guarded", {"sku": {"name": "Standard", "capacity": 1}, "properties": {
    "model": pick_models()[0], "raiPolicyName": "facilities-guardrail"}}).result()
print("policy facilities-guardrail bound to deployment chat-guarded")

try:
    aoai().chat.completions.create(model="chat-guarded", messages=[{"role": "user", "content": "I am going to kill and torture you"}])
    print("violent prompt: ANSWERED")
except BadRequestError as e:
    print("violent prompt refused:", e.status_code, getattr(e, "code", None))
r = aoai().chat.completions.create(model="chat-guarded", max_tokens=10, messages=[{"role": "user", "content": "What is the boiler pressure limit?"}])
print("benign prompt reaches the model:", bool(r.choices[0].message.content))
''', run="python content_filter.py", expect="violent prompt refused: 400 content_filter"),
 b("Use the approver inbox", "The inbox is a Service Bus topic with a subscription behind it. This block makes sure the resources exist (creating them again is a no-op after chapter 5), sends a notification to the topic, and reads it from `approver-inbox` over AMQP 1.0 with peek-lock: *receive* leaves the message locked, *complete* removes it, so it is never delivered twice. It also reads the subscription's message count through Azure Resource Manager, the number an operations dashboard shows.",
   "inbox.py", '''
import json
from azure.mgmt.servicebus import ServiceBusManagementClient
from azure.servicebus import ServiceBusClient, ServiceBusMessage
from azlab import arm, RG, LOC
from approval import conn, TOPIC, INBOX

sb = arm(ServiceBusManagementClient)
sb.namespaces.begin_create_or_update(RG, "facilities-bus", {"location": LOC, "sku": {"name": "Standard", "tier": "Standard"}}).result()
sb.topics.create_or_update(RG, "facilities-bus", TOPIC, {})
sb.subscriptions.create_or_update(RG, "facilities-bus", TOPIC, INBOX, {})

with ServiceBusClient.from_connection_string(conn()) as c:
    with c.get_topic_sender(TOPIC) as s:
        s.send_messages(ServiceBusMessage(json.dumps({"request_id": "smoke", "summary": "inbox smoke test"}), subject="smoke", application_properties={"requester": "duty"}))
    print("messages waiting in the inbox (ARM):", sb.subscriptions.get(RG, "facilities-bus", TOPIC, INBOX).message_count)
    with c.get_subscription_receiver(TOPIC, INBOX, max_wait_time=10) as r:
        got = r.receive_messages(max_message_count=5, max_wait_time=10)
        print("received:", json.loads(b"".join(got[0].body))["summary"], "| requester property:", got[0].application_properties.get(b"requester"))
        for m in got:
            r.complete_message(m)
    with c.get_subscription_receiver(TOPIC, INBOX, max_wait_time=2) as r:
        print("redelivered after complete:", len(r.receive_messages(max_message_count=1, max_wait_time=2)))
''', run="python inbox.py", expect="redelivered after complete: 0"),
]
PIP3 = "pip install azure-ai-agents azure-core azure-mgmt-appcontainers azure-mgmt-resource openai langgraph fastapi uvicorn requests"

LAB[3] = [
 b("Install the libraries", "Chapter 3 builds the agent runtime. Azure has no single hosted-agent service like AgentCore Runtime or Vertex AI Agent Engine, so this layer is ASSEMBLED from two real services and says so plainly: Azure AI Foundry Agents (`azure-ai-agents`) holds the agent definitions and runs them on threads, and Azure Container Apps (`azure-mgmt-appcontainers`) hosts your own agent code, a LangGraph supervisor, behind an HTTPS ingress. It relies on the chat deployment from chapter 10 and `azlab.py`.",
   "install3.sh", PIP3, lang="bash"),
 b("Create the supervisor and the three sub-agents in Foundry", "Four agent definitions in the Foundry project `facilities-project`, created with the real `azure-ai-agents` client: a supervisor that routes, and Facilities, Maintenance and Analytics sub-agents. The tool definitions are declared now (the model can ask for them); chapter 7 builds the tools themselves and chapter 4 puts a gateway in front of them. Then the supervisor runs on a thread: create thread, add a user message, create a run, poll it. The model is the repo's deterministic test stub: it answers a question that mentions tools by asking for one, so the run stops in `requires_action` (the model asked your code to call a tool and is waiting). That is the correct, expected state here: chapter 7 builds the tools and chapter 4 the gateway they sit behind.",
   "foundry_agents.py", '''
import time
from azure.ai.agents import AgentsClient
from azlab import ENDPOINT, DevToken, CHAT

client = AgentsClient(endpoint=f"{ENDPOINT}/api/projects/facilities-project", credential=DevToken())

TOOLS = [
    {"type": "function", "function": {"name": "kb_search", "description": "Search the facilities knowledge base (read-only).",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "asset_status", "description": "Look up an asset and its work orders (read-only).",
        "parameters": {"type": "object", "properties": {"asset_id": {"type": "string"}}, "required": ["asset_id"]}}},
    {"type": "function", "function": {"name": "create_work_order", "description": "Request a work order (needs human approval).",
        "parameters": {"type": "object", "properties": {"asset_id": {"type": "string"}, "summary": {"type": "string"}}, "required": ["asset_id", "summary"]}}},
]
AGENTS = (("facilities_supervisor", "You route facilities requests to the Facilities, Maintenance and Analytics agents and combine their answers.", TOOLS),
          ("facilities_facilities", "Answer from the knowledge base only, with citations.", TOOLS[:1]),
          ("facilities_maintenance", "Look up assets and raise work orders (approval required).", TOOLS[1:]),
          ("facilities_analytics", "Count and summarise work orders.", []))
ids = {}
for name, instructions, tools in AGENTS:
    ids[name] = client.create_agent(model=CHAT, name=name, instructions=instructions, tools=tools).id
print("agents:", sorted(a.name for a in client.list_agents() if a.name in ids))

thread = client.threads.create()
client.messages.create(thread_id=thread.id, role="user", content="Boiler B-12 is at 34 psi. What does the SOP say?")
run = client.runs.create(thread_id=thread.id, agent_id=ids["facilities_supervisor"])
for _ in range(60):
    run = client.runs.get(thread_id=thread.id, run_id=run.id)
    if str(run.status).lower().split(".")[-1] not in ("queued", "in_progress"):
        break
    time.sleep(0.5)
print("supervisor run:", str(run.status).lower().split(".")[-1], "| messages on the thread:", len(list(client.messages.list(thread_id=thread.id))))
''', run="python foundry_agents.py", expect="agents: ['facilities_analytics', 'facilities_facilities', 'facilities_maintenance', 'facilities_supervisor']"),
 b("Write the supervisor graph", "The agent code itself, a LangGraph `StateGraph`: the supervisor asks the model which sub-agents are needed (a JSON list), runs them in order, and synthesises one answer. Each sub-agent is a node with its own role prompt. Every span (a timed step) is recorded in the state, because chapter 8 turns them into traces. At this point the sub-agents have no tools (those arrive in chapters 7 and 4), so each answers from the model alone: that is stated in the code, not hidden. The cloud is injected as a `converse(system, text)` function, so this file has no Azure code in it and is reused unchanged in later chapters.",
   "agent_graph.py", '''
import json
import re
import time
from typing import TypedDict
from langgraph.graph import StateGraph, END

ROUTER_PROMPT = (
    "You route facilities requests to specialist agents. The agents are:\\n"
    "- facilities: searches the knowledge base (SOPs, safety rules, policies, maintenance procedures, how-to guidance).\\n"
    "- maintenance: looks up a specific asset (ids like B-12 or AHU-7) and its work orders, and can raise a work order.\\n"
    "- analytics: counts and statistics over work orders (how many, trends, summaries).\\n"
    "Pick every agent needed. Reply with only a JSON list such as [\\"facilities\\",\\"maintenance\\"], drawn from [\\"facilities\\",\\"maintenance\\",\\"analytics\\"]."
)
ROLES = {"facilities": "You are the Facilities agent. Answer procedure and safety questions.",
         "maintenance": "You are the Maintenance agent. Answer questions about assets and work orders.",
         "analytics": "You are the Analytics agent. Answer questions that need counts or summaries."}


class State(TypedDict, total=False):
    question: str
    user: str
    route: list
    notes: dict
    citations: list
    approval: str
    answer: str
    llm_used: bool
    spans: list


def build(converse, tools=None):
    """converse(system, text) -> str. tools: optional {name: callable}; sub-agents use a tool when one is supplied (chapters 7 and 4 supply them)."""
    tools = tools or {}

    def span(st, name, t0):
        st.setdefault("spans", []).append({"name": name, "kind": "agent", "start": t0, "end": time.time()})

    def supervisor(st):
        t0 = time.time()
        plan = None
        text = converse(ROUTER_PROMPT, st["question"])
        try:
            plan = [p for p in json.loads(re.search(r"\\[.*\\]", text, re.S).group(0)) if p in ROLES]
        except Exception:
            plan = None
        st["llm_used"] = bool(plan)
        st["route"] = plan or ["facilities"]
        st["notes"] = {}
        span(st, "supervisor.plan", t0)
        return st

    def sub_agent(name):
        def node(st):
            t0 = time.time()
            if name in tools:
                st["notes"][name] = tools[name](st)
            else:
                st["notes"][name] = converse(ROLES[name], st["question"])
            span(st, f"agent:{name}", t0)
            return st
        return node

    def synthesize(st):
        t0 = time.time()
        context = "\\n".join(f"[{i + 1}] {n}" for i, n in enumerate(st["notes"].values()))
        st["answer"] = converse("Answer using only the context. Cite sources like [1].", f"Context:\\n{context}\\n\\nQuestion: {st['question']}")
        span(st, "supervisor.synthesize", t0)
        return st

    g = StateGraph(State)
    g.add_node("supervisor", supervisor)
    for n in ROLES:
        g.add_node(n, sub_agent(n))
    g.add_node("synth", synthesize)
    g.set_entry_point("supervisor")
    order = list(ROLES)

    def next_after(after):
        def pick(st):
            rest = [a for a in (order[order.index(after) + 1:] if after else order) if a in st["route"]]
            return rest[0] if rest else "synth"
        return pick
    targets = {**{n: n for n in order}, "synth": "synth"}
    for src in ["supervisor"] + order:
        g.add_conditional_edges(src, next_after(None if src == "supervisor" else src), targets)
    g.add_edge("synth", END)
    return g.compile()
'''),
 b("Write the HTTP app with isolated sessions", "The Container Apps entrypoint: a small FastAPI app. `POST /query` takes a prompt, a user and a session id and runs the graph. Conversation history is kept per session id in its own list, so one session never sees another's turns: that is the isolation the runtime layer owes you. The model client is the real `openai` `AzureOpenAI` client on your `chat` deployment, pointed at the simulator through environment variables the container receives.",
   "app.py", '''
import os
from fastapi import FastAPI
from openai import AzureOpenAI
import agent_graph

client = AzureOpenAI(azure_endpoint=os.environ["VYOMI_ENDPOINT"], api_key="vyomi-local", api_version="2024-10-21", max_retries=0, timeout=120)


def converse(system, text, max_tokens=300):
    r = client.chat.completions.create(model="chat", max_tokens=max_tokens, temperature=0,
                                       messages=[{"role": "system", "content": system}, {"role": "user", "content": text}])
    return r.choices[0].message.content


graph = agent_graph.build(converse)
SESSIONS = {}           # session id -> list of turns; nothing is shared between sessions
app = FastAPI(title="facilities-supervisor")


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/query")
def query(body: dict):
    session = body.get("session", "default")
    history = SESSIONS.setdefault(session, [])
    st = graph.invoke({"question": body["prompt"], "user": body.get("user", "anonymous"), "spans": []})
    history.append({"q": body["prompt"], "a": st["answer"]})
    return {"answer": st["answer"], "route": st["route"], "llm_used": st["llm_used"], "session": session, "turns": len(history),
            "spans": st["spans"], "pid": os.getpid()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8080")))
'''),
 b("Run the graph locally first", "Before hosting, prove the graph on your machine: route, run the sub-agents, answer. The router sends this question to the Facilities agent (procedures) and the Maintenance agent (an asset id). The answer text comes from the deterministic test stub.",
   "try_graph.py", '''
import os
os.environ.setdefault("VYOMI_ENDPOINT", os.environ["VYOMI_AZURE_HTTP_ENDPOINT"])
from app import graph

st = graph.invoke({"question": "Boiler B-12 is at 34 psi. What does the SOP say, and what is its status?", "user": "maria", "spans": []})
print("route:", st["route"], "| model routed:", st["llm_used"])
print("spans:", [s["name"] for s in st["spans"]])
print("answer:", st["answer"][:80])
''', run="python try_graph.py", expect="route: ['facilities', 'maintenance'] | model routed: True"),
 b("Create the Container Apps environment and the app", "Two ARM calls with `azure-mgmt-appcontainers`: a managed environment, then the container app `facilities-supervisor` with external ingress on port 8080. The simulator's Python app image `vyomi/python-app:latest` starts `app.py` from the zip you pass in `VYOMI_APP_SOURCE_B64`; on real Azure you would instead build a container image from the same two files, push it to Azure Container Registry and put its name in `image`. The environment variables are the endpoint the container calls the model on, the same way you would set them on real Container Apps.",
   "deploy_container_app.py", '''
import base64
import io
import os
import zipfile
from azure.mgmt.appcontainers import ContainerAppsAPIClient
from azlab import arm, rid, RG, LOC, HTTP_ENDPOINT

APP, ENV = "facilities-supervisor", "facilities-env"

buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
    z.write("app.py", "app.py")
    z.write("agent_graph.py", "agent_graph.py")
    z.writestr("requirements.txt", "fastapi\\nuvicorn\\nopenai\\nlanggraph\\n")
bundle = base64.b64encode(buf.getvalue()).decode()

c = arm(ContainerAppsAPIClient)
c.managed_environments.begin_create_or_update(RG, ENV, {"location": LOC, "properties": {}}).result()
app = c.container_apps.begin_create_or_update(RG, APP, {"location": LOC, "properties": {
    "managedEnvironmentId": rid("Microsoft.App", "managedEnvironments", ENV),
    "configuration": {"ingress": {"external": True, "targetPort": 8080}},
    "template": {"containers": [{"name": "supervisor", "image": "vyomi/python-app:latest", "env": [
        {"name": "VYOMI_APP_SOURCE_B64", "value": bundle}, {"name": "VYOMI_ENDPOINT", "value": HTTP_ENDPOINT}]}]}}}).result()
print("container app", app.name, "state:", getattr(app.provisioning_state, "value", app.provisioning_state))
''', run="python deploy_container_app.py", expect="container app facilities-supervisor state: Succeeded"),
 b("Call the hosted supervisor in two sessions", "Read the ingress address from the container app (the simulator reports it as `vyomiIngressUrl`; on real Azure it is `properties.configuration.ingress.fqdn`) and `POST /query`. Session `s1` asks twice and session `s2` once: the turn counters prove the two sessions do not share history. The hosted app runs the LangGraph supervisor and sub-agents inside the container process (see the `pid`).",
   "call_container_app.py", '''
import requests
from azure.mgmt.appcontainers import ContainerAppsAPIClient
from azlab import arm, RG

raw = arm(ContainerAppsAPIClient).container_apps.get(RG, "facilities-supervisor", cls=lambda resp, des, hdr: resp.http_response.json())
base = raw["properties"]["vyomiIngressUrl"].rstrip("/")


def ask(session, prompt):
    r = requests.post(base + "/query", json={"prompt": prompt, "user": "maria", "session": session}, timeout=60)
    r.raise_for_status()
    return r.json()


a1 = ask("s1", "Boiler B-12 is at 34 psi. What does the SOP say?")
a2 = ask("s1", "And what about AHU-7?")
b1 = ask("s2", "How many work orders are open?")
print("s1 turns:", a1["turns"], "->", a2["turns"], "| s2 turns:", b1["turns"])
print("route for s2:", b1["route"], "| spans:", [s["name"] for s in b1["spans"]])
''', run="python call_container_app.py", expect="s1 turns: 1 -> 2 | s2 turns: 1", needs_runtime=True),
]
PIP4 = "pip install azure-core azure-mgmt-apimanagement requests"

LAB[4] = [
 b("Install the libraries", "Chapter 4 puts one governed door in front of the tools: Azure API Management (APIM). The tool catalogue is an API with one operation per tool; policies add a rate limit and a rule that keeps the write tool behind an approval; an MCP server API exposes the same tools as `tools/list` and `tools/call`. It fronts the Function App from chapter 7. Honest scope note: Azure has no Cedar-style agent policy engine (AWS AgentCore Gateway and Vertex AI have one), so the policy here is APIM policy expressions (`choose`/`when`), which is what Azure teams actually use.",
   "install4.sh", PIP4, lang="bash"),
 b("Write the gateway helpers", "The APIM data plane is served at `https://<service>.azure-api.net/<api path>` on Azure; the simulator serves it at `/azure-data/apim/<service>/<api path>`. `headers()` carries the subscription key (read from APIM through ARM, as `az apim` does) and, from chapter 1 on, the bearer token. `mcp()` sends a JSON-RPC 2.0 message to the MCP API.",
   "gw.py", '''
import os
import requests
from azure.mgmt.apimanagement import ApiManagementClient
from azlab import arm, ENDPOINT, RG

SERVICE = "facilities-apim"
SUBSCRIPTION = "agent-sub"


def apim():
    return arm(ApiManagementClient)


def url(path=""):
    return f"{ENDPOINT}/azure-data/apim/{SERVICE}/{path.lstrip('/')}"


def subscription_key():
    return apim().subscription.list_secrets(RG, SERVICE, SUBSCRIPTION).primary_key


def headers(extra=None):
    h = {"Ocp-Apim-Subscription-Key": subscription_key(), "Content-Type": "application/json"}
    token = os.environ.get("VYOMI_BEARER_TOKEN")           # set from chapter 1 on
    if not token and os.path.exists("token.txt"):          # chapter 1 saves the access token here
        token = open("token.txt").read().strip()
    if token:
        h["Authorization"] = "Bearer " + token
    h.update(extra or {})
    return h


def mcp(method, params=None):
    r = requests.post(url("mcp"), json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}, headers=headers(), timeout=60)
    r.raise_for_status()
    out = r.json()
    if "error" in out:
        raise RuntimeError(f"MCP error: {out['error']}")
    return out["result"]
'''),
 b("Create the gateway, the tool catalogue and the subscription", "In order: the APIM service `facilities-apim`; an API `tools` whose backend is your Function App; three operations (`kb-search`, `asset-status`, `create-work-order`, the write tool); an API-level policy that adds the function's host key to every backend call (so callers never see it) and rate-limits each subscription to 60 calls a minute; and a subscription `agent-sub` that covers every API. Callers now need a subscription key, never the function key.",
   "create_gateway.py", '''
from azure.mgmt.apimanagement.models import SubscriptionCreateParameters
from azlab import rid, ensure_rg, RG, LOC, HTTP_ENDPOINT
from azdata import function_key, FUNCTION_APP
from gw import apim, SERVICE, SUBSCRIPTION, subscription_key

ensure_rg()
a = apim()
a.api_management_service.begin_create_or_update(RG, SERVICE, {"location": LOC, "sku": {"name": "Developer", "capacity": 1},
                                                              "publisher_email": "ops@facilities.example.com", "publisher_name": "facilities"}).result()
backend = f"{HTTP_ENDPOINT}/azure-data/functions/{FUNCTION_APP}/api"       # the gateway reaches the Function App over the simulator's plain-http address
a.api.begin_create_or_update(RG, SERVICE, "tools", {"display_name": "facilities-tools", "path": "tools", "protocols": ["https"],
                                                    "subscription_required": True, "service_url": backend}).result()
for op in ("kb-search", "asset-status", "create-work-order"):
    a.api_operation.create_or_update(RG, SERVICE, "tools", op, {"display_name": op, "method": "POST", "url_template": "/" + op})

POLICY = (f'<policies><inbound><base/>'
          f'<set-header name="x-functions-key" exists-action="override"><value>{function_key()}</value></set-header>'
          '<rate-limit-by-key calls="60" renewal-period="60" counter-key="@(context.Subscription.Id)"/>'
          '</inbound><backend><base/></backend><outbound><base/></outbound><on-error><base/></on-error></policies>')
a.api_policy.create_or_update(RG, SERVICE, "tools", "policy", {"value": POLICY, "format": "xml"})
a.subscription.create_or_update(RG, SERVICE, SUBSCRIPTION, SubscriptionCreateParameters(
    display_name="facilities agent", scope=rid("Microsoft.ApiManagement", "service", SERVICE) + "/apis"))
print("gateway", SERVICE, "| catalogue:", sorted(o.name for o in a.api_operation.list_by_api(RG, SERVICE, "tools")), "| subscription key issued:", bool(subscription_key()))
''', run="python create_gateway.py", expect="catalogue: ['asset-status', 'create-work-order', 'kb-search']"),
 b("Call a read-only tool through the gateway", "The same asset-status call as chapter 7, but now through the front door: the gateway checks the subscription key, rate-limits, adds the function key and forwards. Without the key it answers 401.",
   "call_gateway.py", '''
import requests
from gw import url, headers

ok = requests.post(url("tools/asset-status"), json={"asset_id": "B-12"}, headers=headers(), timeout=60)
print("with the subscription key:", ok.status_code, "| B-12 status:", ok.json()["asset"]["status"])
no = requests.post(url("tools/asset-status"), json={"asset_id": "B-12"}, headers={"Content-Type": "application/json"}, timeout=30)
print("without a key:", no.status_code)
''', run="python call_gateway.py", expect="with the subscription key: 200 | B-12 status: RUNNING"),
 b("Add an operation policy and the approval rule", "Two operation-level policies. The first, a `rate-limit` of 1000 calls a minute on `asset-status`, shows the usual per-operation throttle. The second is the Azure substitute for an agent policy engine: a `choose`/`when` *policy expression* on the write tool that returns 403 unless the request carries an `x-approval-id` header. The check shows both sides: without the header the call never reaches the function; with it, it does (and the function, which has no approved ledger row for that id, still refuses: defence in depth, you will build the ledger in chapter 5).",
   "policies.py", '''
import requests
from azlab import RG
from gw import apim, SERVICE, url, headers

BASE = "<backend><base/></backend><outbound><base/></outbound><on-error><base/></on-error></policies>"
apim().api_operation_policy.create_or_update(RG, SERVICE, "tools", "asset-status", "policy", {
    "value": '<policies><inbound><base/><rate-limit calls="1000" renewal-period="60"/></inbound>' + BASE, "format": "xml"})

DENY_WRITE = ('<policies><inbound><base/><choose><when condition="@(string.IsNullOrEmpty(context.Request.Headers.GetValueOrDefault(&quot;x-approval-id&quot;,&quot;&quot;)))">'
              '<return-response><set-status code="403" reason="Forbidden"/><set-header name="Content-Type" exists-action="override"><value>application/json</value></set-header>'
              '<set-body>{"error":"write tools need an approved request (x-approval-id)"}</set-body></return-response></when></choose></inbound>' + BASE)
apim().api_operation_policy.create_or_update(RG, SERVICE, "tools", "create-work-order", "policy", {"value": DENY_WRITE, "format": "xml"})

no = requests.post(url("tools/create-work-order"), json={"request_id": "x"}, headers=headers(), timeout=30)
yes = requests.post(url("tools/create-work-order"), json={"request_id": "nonexistent"}, headers=headers({"x-approval-id": "req-none"}), timeout=60)
print("write tool without x-approval-id:", no.status_code, no.json()["error"])
print("write tool with x-approval-id: reaches the function ->", yes.status_code, yes.json())
''', run="python policies.py", expect="write tool without x-approval-id: 403"),
 b("Expose the tools as an MCP server", "MCP (Model Context Protocol) is how agent frameworks discover tools. APIM can publish an existing REST API as an MCP server: create a second API of type `mcp` whose source is `tools`, and its operations become MCP tools. Then speak plain JSON-RPC 2.0 to it: `tools/list` to discover, `tools/call` to run one.",
   "mcp_server.py", '''
import json
from azure.mgmt.apimanagement.models import ApiCreateOrUpdateParameter
from azlab import rid, RG
from gw import apim, SERVICE, mcp

apim().api.begin_create_or_update(RG, SERVICE, "tools-mcp", ApiCreateOrUpdateParameter(
    display_name="facilities-tools-mcp", path="mcp", protocols=["https"], subscription_required=True, api_type="mcp",
    source_api_id=rid("Microsoft.ApiManagement", "service", SERVICE) + "/apis/tools")).result()
names = sorted(t["name"] for t in mcp("tools/list")["tools"])
print("MCP tools/list:", names)
tool = next((n for n in names if n.replace("-", "_").endswith("asset_status")), None)
if tool is None:
    raise SystemExit("the 'asset_status' tool was not found. Deploy the chapter 'Agent Gateway' first (its Deploy this chapter button), then run this step again.")
res = mcp("tools/call", {"name": tool, "arguments": {"asset_id": "B-12"}})
print("MCP tools/call", tool, "-> isError:", bool(res.get("isError")), "| status:", json.loads(res["content"][0]["text"])["asset"]["status"])
''', run="python mcp_server.py", expect="| status: RUNNING"),
]
PIP5 = "pip install azure-core azure-data-tables azure-servicebus azure-mgmt-servicebus requests"

LAB[5] = [
 b("Install the libraries", "Chapter 5 makes write actions safe: the agent never writes a work order directly. It parks a request for a human, the human decides, and only an APPROVED request can be executed. Honest scope note: Azure has no single managed service for this, so the flow is ASSEMBLED from three real parts, and the code says so: an Azure Table ledger is the system of record (`approvalledger`), an Azure Service Bus topic with an `approver-inbox` subscription delivers the request to the approver (AMQP 1.0), and the two functions from chapter 7 (`approval-decision`, `create-work-order`) enforce the rules. Logic Apps and Durable Functions are the managed orchestrators Azure also offers; they are not used here. Needs chapter 7 (functions, tables).",
   "install5.sh", PIP5, lang="bash"),
 b("Create the Service Bus namespace, topic and approver inbox", "Through `azure-mgmt-servicebus`: a Standard namespace `facilities-bus`, a topic `work-order-approval` (every request is published here) and a subscription `approver-inbox` (the approver reads from it). Chapter 2 later uses the same inbox for notifications.",
   "create_bus.py", '''
from azure.mgmt.servicebus import ServiceBusManagementClient
from azlab import arm, ensure_rg, RG, LOC

ensure_rg()
sb = arm(ServiceBusManagementClient)
sb.namespaces.begin_create_or_update(RG, "facilities-bus", {"location": LOC, "sku": {"name": "Standard", "tier": "Standard"}}).result()
sb.topics.create_or_update(RG, "facilities-bus", "work-order-approval", {})
sb.subscriptions.create_or_update(RG, "facilities-bus", "work-order-approval", "approver-inbox", {})
print("namespace facilities-bus | topic work-order-approval | subscription", [s.name for s in sb.subscriptions.list_by_topic(RG, "facilities-bus", "work-order-approval")][0])
''', run="python create_bus.py", expect="subscription approver-inbox"),
 b("Write the approval helpers", "The three halves of the flow in one module. `request_approval` is what the agent calls: ledger row `PENDING` first, then the message on the topic, and nothing else (no work order). `pull_request` is the approver's side: read the inbox over AMQP with peek-lock, complete the message that belongs to this request and put the others back. `wait_decision` is the parked caller: it polls the ledger until the status leaves `PENDING`. The Service Bus connection string is the vendor emulator form (`UseDevelopmentEmulator=true`); on real Azure it is the same string without that flag.",
   "approval.py", '''
import json
import time
from azure.servicebus import ServiceBusClient, ServiceBusMessage
from azlab import HOST, AMQP_PORT
from azdata import table

TOPIC, INBOX, LEDGER = "work-order-approval", "approver-inbox", "approvalledger"


def conn():
    return f"Endpoint=sb://{HOST}:{AMQP_PORT};SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=vyomi;UseDevelopmentEmulator=true"


def request_approval(request_id, asset_id, summary, priority, requester):
    payload = {"request_id": request_id, "asset_id": asset_id, "summary": summary, "priority": priority, "requester": requester}
    table(LEDGER).upsert_entity(dict(PartitionKey="req", RowKey=request_id, status="PENDING", ts=int(time.time()), **payload))
    with ServiceBusClient.from_connection_string(conn()) as c, c.get_topic_sender(TOPIC) as s:
        s.send_messages(ServiceBusMessage(json.dumps(payload), subject="work-order", application_properties={"requester": requester, "kind": "work-order"}))
    return {"request_id": request_id, "status": "PENDING_APPROVAL"}


def pull_request(request_id, tries=15):
    """The approver reads the inbox: complete our message, abandon (put back) anyone else's."""
    with ServiceBusClient.from_connection_string(conn()) as c:
        for _ in range(tries):
            with c.get_subscription_receiver(TOPIC, INBOX, max_wait_time=2) as r:
                for m in r.receive_messages(max_message_count=10, max_wait_time=2):
                    body = json.loads(b"".join(m.body).decode())
                    if body.get("request_id") == request_id:
                        r.complete_message(m)
                        return body
                    r.abandon_message(m)
    return None


def ledger_row(request_id):
    return dict(table(LEDGER).get_entity("req", request_id))


def wait_decision(request_id, out, tries=80):
    for _ in range(tries):
        row = ledger_row(request_id)
        if row.get("status") not in (None, "PENDING"):
            out["row"] = row
            return
        time.sleep(0.25)


def work_orders():
    return [dict(e) for e in table("workorders").list_entities()]
'''),
 b("Park a request: nothing is written yet", "The agent asks for a work order on boiler B-12. Check the four guarantees of the parking step: the ledger row is `PENDING`; no work order exists; `create-work-order` refuses the request even if someone calls it directly; and an approver who is not on the allow-list cannot decide it (the ledger stays `PENDING`).",
   "park_request.py", '''
from approval import request_approval, ledger_row, work_orders
from azdata import call_function, FUNCTION_APP

request_approval("req-demo0001", "B-12", "Work order for B-12: boiler pressure is 34 psi, above the 30 psi limit", "P1", "maria")
print("ledger status:", ledger_row("req-demo0001")["status"])
print("work orders requested by maria:", len([w for w in work_orders() if w.get("requester") == "maria"]))
premature = call_function(FUNCTION_APP, "create-work-order", {"request_id": "req-demo0001"})
print("create-work-order before approval:", premature["error"])
stranger = call_function(FUNCTION_APP, "approval-decision", {"request_id": "req-demo0001", "decision": "APPROVE", "approver": "mallory@evil.test"})
print("unauthorised approver:", stranger["error"], "| ledger still", ledger_row("req-demo0001")["status"])
''', run="python park_request.py", expect="ledger status: PENDING\nwork orders requested by maria: 0"),
 b("Approve: the parked caller proceeds and the work order is created", "The approver pulls the request from the inbox, then calls `approval-decision`. A background thread plays the parked agent: it polls the ledger and wakes the moment the status changes. Only then does `create-work-order` run, and it writes the work order and closes the ledger row (`EXECUTED`, with the approver recorded). A second call is idempotent: still one work order.",
   "approve_request.py", '''
import threading
from approval import pull_request, wait_decision, ledger_row, work_orders
from azdata import call_function, FUNCTION_APP

msg = pull_request("req-demo0001")
print("inbox delivered:", msg["summary"][:50])

seen = {}
waiting = threading.Thread(target=wait_decision, args=("req-demo0001", seen))
waiting.start()
d = call_function(FUNCTION_APP, "approval-decision", {"request_id": "req-demo0001", "decision": "APPROVE", "approver": "duty.manager@example.com"})
waiting.join(timeout=30)
print("decision:", d["status"], "| the waiting caller saw:", seen["row"]["status"])

wo = call_function(FUNCTION_APP, "create-work-order", {"request_id": "req-demo0001"})
row = ledger_row("req-demo0001")
print("work order:", wo["work_order_id"], "| ledger:", row["status"], "approved by", row["approver"])
again = call_function(FUNCTION_APP, "create-work-order", {"request_id": "req-demo0001"})
print("second call idempotent:", again.get("idempotent"), "| work orders for B-12 from this request:", len([w for w in work_orders() if w["work_order_id"] == wo["work_order_id"]]))
''', run="python approve_request.py", expect="second call idempotent: True | work orders for B-12 from this request: 1"),
 b("Reject, and refuse a late decision", "A second request is rejected: the ledger says `REJECTED`, `create-work-order` refuses, and no work order is written. Last, optimistic concurrency: a decision written with a stale ETag is refused with HTTP 412, so two approvers can never both decide the same request.",
   "reject_request.py", '''
from azure.core import MatchConditions
from azure.core.exceptions import HttpResponseError
from azure.data.tables import UpdateMode
from approval import request_approval, pull_request, ledger_row, work_orders
from azdata import call_function, table, FUNCTION_APP

request_approval("req-demo0002", "EL-3", "Replace elevator 3 (this one is rejected)", "P3", "maria")
pull_request("req-demo0002")
d = call_function(FUNCTION_APP, "approval-decision", {"request_id": "req-demo0002", "decision": "REJECT", "approver": "duty.manager@example.com"})
refused = call_function(FUNCTION_APP, "create-work-order", {"request_id": "req-demo0002"})
print("decision:", d["status"], "| create-work-order:", refused["error"][:40])
print("work orders written for the rejected request:", len([w for w in work_orders() if w.get("requester") == "maria" and w["asset_id"] == "EL-3"]))

ledger = table("approvalledger")
stale = ledger.get_entity("req", "req-demo0001").metadata["etag"]
ledger.update_entity({"PartitionKey": "req", "RowKey": "req-demo0001", "note": "touched"}, mode=UpdateMode.MERGE)
try:
    ledger.update_entity({"PartitionKey": "req", "RowKey": "req-demo0001", "status": "REJECTED"}, mode=UpdateMode.MERGE, etag=stale, match_condition=MatchConditions.IfNotModified)
except HttpResponseError as e:
    print("decision with a stale ETag refused:", e.status_code)
''', run="python reject_request.py", expect="decision with a stale ETag refused: 412"),
]
PIP6 = "pip install azure-core azure-search-documents openai"

LAB[6] = [
 b("Install the libraries", "Chapter 6 queries the `facilities-kb` index that chapter 12 filled: full-text (BM25), vector, hybrid and semantic queries with `azure-search-documents`, and embeddings from your `embed` deployment (chapter 10). It uses `azlab.py`, `azdata.py` and `kb_index.py`.",
   "install6.sh", PIP6, lang="bash"),
 b("Look at the index you built", "Read the index back: the fields, the vector field dimensions and the semantic configuration. This is what decides which kinds of query the index can answer.",
   "inspect_index.py", '''
from kb_index import index_client
from azdata import INDEX

ix = index_client().get_index(INDEX)
print("fields:", [(f.name, "vector" if f.name == "content_vector" else "text/key") for f in ix.fields])
print("vector dimensions:", next(f.vector_search_dimensions for f in ix.fields if f.name == "content_vector"))
print("semantic configurations:", [c.name for c in ix.semantic_search.configurations])
''', run="python inspect_index.py", expect="vector dimensions:"),
 b("Embed the documents and store the vectors", "Chapter 12's indexer loaded the text (the four SOPs plus the water-leak SOP you uploaded in its last block, five documents in all). Vector search needs one embedding per document: ask your `embed` deployment for the vectors, then `merge_documents` writes them into `content_vector` without touching the rest of the document. Embeddings come from the repo's deterministic test stub, so similarity is crude: real `text-embedding-3` vectors rank far better.",
   "embed_docs.py", '''
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azlab import aoai, EMBED
from azdata import search_endpoint, search_key, INDEX
import rag_design

sc = SearchClient(search_endpoint(), INDEX, AzureKeyCredential(search_key()))
rows = list(sc.search(search_text="*", select=["id", "source", "content"], top=50))
dims = {"dimensions": rag_design.dimensions()} if rag_design.dimensions() else {}        # your design: vector size
vectors = [d.embedding for d in aoai().embeddings.create(model=EMBED, input=[r["content"] for r in rows], **dims).data]
results = sc.merge_documents([{"id": r["id"], "content_vector": v} for r, v in zip(rows, vectors)])
print("embedded and merged", sum(1 for r in results if r.succeeded), "documents")
''', run="python embed_docs.py", expect="embedded and merged 5 documents"),
 b("Write the retrieval helper", "One function every later layer imports: `kb_search(query, mode)` returns ranked passages, each with its `source` so an answer can cite it. `mode` is `text`, `vector`, `hybrid` or `semantic`. A vector query sends the embedding of the question; a hybrid query sends both text and vector and the service fuses the two rankings (reciprocal rank fusion); a semantic query asks the semantic ranker to re-rank and returns a reranker score.",
   "kb.py", '''
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery
from azlab import aoai, EMBED
from azdata import search_endpoint, search_key, INDEX
import rag_design

_sc = SearchClient(search_endpoint(), INDEX, AzureKeyCredential(search_key()))


def kb_search(query, mode="text", top=None):
    top = top or rag_design.top_k()                      # your design: how many passages
    vector = None
    if mode in ("vector", "hybrid"):
        dims = {"dimensions": rag_design.dimensions()} if rag_design.dimensions() else {}     # your design: vector size
        emb = aoai().embeddings.create(model=EMBED, input=[query], **dims).data[0].embedding
        vector = [VectorizedQuery(vector=emb, k_nearest_neighbors=top, fields="content_vector")]
    kw = {"query_type": "semantic", "semantic_configuration_name": "sem"} if mode == "semantic" else {}
    rows = _sc.search(search_text=None if mode == "vector" else query, vector_queries=vector, select=["id", "source", "title", "content"], top=top, **kw)
    return [{"source": r["source"], "text": r["content"], "score": r["@search.score"], "reranker": r.get("@search.reranker_score")} for r in rows]
'''),
 b("Run the four kinds of query", "BM25 text search ranks the boiler SOP first for a boiler question and the HVAC manual first for an air-handler question. A vector query finds the boiler SOP from a differently worded question. Hybrid combines both. The semantic ranker adds a reranker score. Every hit carries its `source`, which is what makes citations possible.",
   "try_search.py", '''
from kb import kb_search

for mode, q in (("text", "boiler pressure exceeds 30 psi"), ("text", "AHU-7 supply air temperature drift chilled water valve"),
                ("vector", "what to do when boiler pressure is too high"), ("hybrid", "fire alarm evacuation procedure"),
                ("semantic", "who signs off on boiler work")):
    hits = kb_search(q, mode)
    extra = f" reranker={hits[0]['reranker']}" if mode == "semantic" else ""
    print(f"{mode:8} {q[:44]:44} -> {hits[0]['source']}{extra}")
print("every hit has a source:", all(h["source"] for h in kb_search("fire alarm evacuation")))
''', run="python try_search.py", expect="vector   what to do when boiler pressure is too high  -> boiler-sop.md\nhybrid   fire alarm evacuation procedure              -> fire-safety-sop.md"),
 b("Apply your design to the kb-search tool", "The `kb-search` function from chapter 7 returns three passages unless told otherwise. It reads `RAG_TOP_K` from its application settings, so this script copies the top K from your RAG design (chapter 14) into the Function App's settings, keeping every other setting. Run it again after you change the design.",
   "apply_design.py", '''
from azure.mgmt.web import WebSiteManagementClient
from azure.mgmt.web.models import StringDictionary
from azlab import arm, RG
from azdata import FUNCTION_APP
import rag_design

web = arm(WebSiteManagementClient)
settings = dict(web.web_apps.list_application_settings(RG, FUNCTION_APP).properties or {})
settings["RAG_TOP_K"] = str(rag_design.top_k())
web.web_apps.update_application_settings(RG, FUNCTION_APP, StringDictionary(properties=settings))
print("kb-search now returns", web.web_apps.list_application_settings(RG, FUNCTION_APP).properties["RAG_TOP_K"], "passages")
''', run="python apply_design.py", expect="kb-search now returns 3 passages"),
]
PIP7 = "pip install azure-core azure-data-tables azure-mgmt-resource azure-mgmt-web azure-mgmt-search requests"

LAB[7] = [
 b("Install the libraries", "Chapter 7 reads and writes Azure Table storage (`azure-data-tables`), creates the Function App and the AI Search service through Azure Resource Manager, and calls the functions over HTTPS. It uses `azlab.py` from chapter 10.",
   "install7.sh", PIP7, lang="bash"),
 b("Write the data helpers", "Small helpers shared by chapters 7, 5, 9 and 6: the Storage connection string in the Azurite form with an explicit `TableEndpoint` (that is how the Azure SDKs are pointed at an emulator), the AI Search address and admin key as ARM reports them, and an HTTPS call to a function with its host key.",
   "azdata.py", '''
import requests
from urllib.parse import urlparse
from azure.data.tables import TableServiceClient
from azlab import arm, ENDPOINT, HTTP_ENDPOINT, STORAGE, ACCOUNT_KEY, RG, HOST

SEARCH_SERVICE = "facilities-search"
INDEX = "facilities-kb"
FUNCTION_APP = "facilities-tools"


def storage_cs(service, endpoint=ENDPOINT, proto="https"):
    return f"DefaultEndpointsProtocol={proto};AccountName={STORAGE};AccountKey={ACCOUNT_KEY};{service}Endpoint={endpoint}/{STORAGE};"


def tables():
    return TableServiceClient.from_connection_string(storage_cs("Table"))


def table(name):
    return tables().create_table_if_not_exists(name)


def search_endpoint():
    """The data-plane address of the AI Search service. A real service advertises https://<name>.search.windows.net; the simulator serves the same wire under its own path."""
    from azure.mgmt.search import SearchManagementClient
    advertised = arm(SearchManagementClient).services.get(RG, SEARCH_SERVICE).endpoint or ""
    if advertised and (urlparse(advertised).hostname or "") in (HOST, "localhost", "127.0.0.1"):
        return advertised.rstrip("/")
    return f"{ENDPOINT}/azure-data/search/{SEARCH_SERVICE}"


def search_key():
    from azure.mgmt.search import SearchManagementClient
    return arm(SearchManagementClient).admin_keys.get(RG, SEARCH_SERVICE).primary_key


def function_key(app=FUNCTION_APP):
    from azure.mgmt.web import WebSiteManagementClient
    keys = arm(WebSiteManagementClient).web_apps.list_host_keys(RG, app)
    return (keys.function_keys or {}).get("default") or keys.master_key


def call_function(app, name, payload, timeout=120):
    r = requests.post(f"{ENDPOINT}/azure-data/functions/{app}/api/{name}", json=payload, headers={"x-functions-key": function_key(app)}, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"function {app}/{name} HTTP {r.status_code}: {r.text[-300:]}")
    return r.json()
'''),
 b("Create the AI Search service", "The knowledge-search tool needs the address and key of an Azure AI Search service as application settings, so create the service now (chapters 12 and 6 fill and query it). Basic SKU, one ARM call with the real `azure-mgmt-search` client.",
   "create_search.py", '''
from azure.mgmt.search import SearchManagementClient
from azlab import arm, ensure_rg, RG, LOC
from azdata import SEARCH_SERVICE, search_endpoint

ensure_rg()
arm(SearchManagementClient).services.begin_create_or_update(RG, SEARCH_SERVICE, {"location": LOC, "sku": {"name": "basic"}}).result()
print("search service", SEARCH_SERVICE, "ready; data-plane address:", search_endpoint())
''', run="python create_search.py", expect="search service facilities-search ready"),
 b("Create the Table storage tables and seed the data", "Table storage holds the operational data. Three tables: `assets`, `workorders`, and `approvalledger` (the approval system of record, used from chapter 5). Rows are addressed by PartitionKey plus RowKey. Boiler B-12 runs at 34 psi, the example problem used in later chapters.",
   "seed.py", '''
from azdata import table

ASSETS = [
    {"asset_id": "B-12", "name": "Boiler B-12", "site": "HQ-1", "type": "boiler", "status": "RUNNING", "pressure_psi": 34, "last_inspection": "2026-08-02"},
    {"asset_id": "AHU-7", "name": "Air handling unit 7", "site": "HQ-1", "type": "hvac", "status": "DEGRADED", "supply_temp_drift_c": 3.8, "last_inspection": "2026-09-12"},
    {"asset_id": "EL-3", "name": "Elevator 3", "site": "HQ-2", "type": "elevator", "status": "RUNNING", "last_inspection": "2026-10-01"},
]
WORK_ORDERS = [
    {"work_order_id": "WO-000101", "asset_id": "AHU-7", "title": "Replace AHU-7 filter", "priority": "P3", "status": "CLOSED", "requester": "seed"},
    {"work_order_id": "WO-000102", "asset_id": "B-12", "title": "Quarterly PRV inspection", "priority": "P2", "status": "OPEN", "requester": "seed"},
    {"work_order_id": "WO-000103", "asset_id": "EL-3", "title": "Door-zone sensor check", "priority": "P2", "status": "OPEN", "requester": "seed"},
]
for name, rows, pk, key in (("assets", ASSETS, "asset", "asset_id"), ("workorders", WORK_ORDERS, "wo", "work_order_id")):
    t = table(name)
    for row in rows:
        t.upsert_entity(dict(row, PartitionKey=pk, RowKey=row[key]))
    print("seeded", name, len(list(t.list_entities())))
table("approvalledger")
print("created approvalledger (empty)")
''', run="python seed.py", expect="created approvalledger (empty)"),
 b("Write the knowledge-search tool", "Read-only. It calls Azure AI Search with the real `azure-search-documents` client, using the address and key from the function's application settings. It returns passages with their source name so answers can cite them. It runs after chapter 12 has filled the index.",
   "fn_kb_search.py", '''
import json
import os
import azure.functions as func


def main(req: func.HttpRequest) -> func.HttpResponse:
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient
    body = req.get_json() if req.get_body() else {}
    sc = SearchClient(os.environ["SEARCH_ENDPOINT"], os.environ.get("SEARCH_INDEX", "facilities-kb"), AzureKeyCredential(os.environ["SEARCH_KEY"]))
    rows = sc.search(search_text=body.get("query", ""), top=int(body.get("top_k", os.environ.get("RAG_TOP_K", 3))))      # your design (chapter 14), set as the RAG_TOP_K app setting
    results = [{"text": r["content"], "score": r.get("@search.score"), "source": r.get("source") or r.get("title") or r["id"]} for r in rows]
    caller = req.headers.get("x-vyomi-caller") or "anonymous"      # set by the API Management gateway in chapter 1 after it validated the token
    return func.HttpResponse(json.dumps({"results": results, "caller": caller}), mimetype="application/json")
'''),
 b("Write the asset-status tool", "Read-only. It returns one asset and its work orders from Table storage. It never writes.",
   "fn_asset_status.py", '''
import json
import os
import azure.functions as func


def _table(name):
    from azure.data.tables import TableClient
    return TableClient.from_connection_string(os.environ["TABLE_CONNECTION_STRING"], name)


def _clean(d):
    return {k: v for k, v in d.items() if k not in ("PartitionKey", "RowKey", "Timestamp") and not hasattr(v, "isoformat")}


def main(req: func.HttpRequest) -> func.HttpResponse:
    from azure.core.exceptions import ResourceNotFoundError
    body = req.get_json() if req.get_body() else {}
    aid = body["asset_id"]
    try:
        asset = dict(_table(os.environ.get("ASSETS_TABLE", "assets")).get_entity("asset", aid))
    except ResourceNotFoundError:
        return func.HttpResponse(json.dumps({"found": False}), mimetype="application/json")
    wos = [dict(e) for e in _table(os.environ.get("WORK_ORDERS_TABLE", "workorders")).query_entities("asset_id eq @a", parameters={"a": aid})]
    return func.HttpResponse(json.dumps({"found": True, "asset": _clean(asset), "work_orders": [_clean(w) for w in wos]}), mimetype="application/json")
'''),
 b("Write the approval-decision tool", "The decision half of the approval flow (used in chapter 5). It records APPROVED or REJECTED in the ledger only if the request is still PENDING and the approver is on the allow-list, using an ETag-conditional update so two approvers cannot both decide. It never creates the work order.",
   "fn_approval_decision.py", '''
import json
import os
import time
import azure.functions as func

APPROVERS = ("@example.com",)


def _table(name):
    from azure.data.tables import TableClient
    return TableClient.from_connection_string(os.environ["TABLE_CONNECTION_STRING"], name)


def main(req: func.HttpRequest) -> func.HttpResponse:
    from azure.core import MatchConditions
    from azure.core.exceptions import ResourceModifiedError, ResourceNotFoundError
    from azure.data.tables import UpdateMode
    b = req.get_json() if req.get_body() else {}
    rid, decision, approver = b.get("request_id"), (b.get("decision") or "").upper(), b.get("approver", "")
    ledger = _table(os.environ.get("LEDGER_TABLE", "approvalledger"))
    out = lambda d: func.HttpResponse(json.dumps(d), mimetype="application/json")
    try:
        row = ledger.get_entity("req", rid)
    except ResourceNotFoundError:
        return out({"ok": False, "error": "unknown request"})
    if row.get("status") != "PENDING":
        return out({"ok": False, "error": f"request is {row.get('status')}, not PENDING"})
    if decision not in ("APPROVE", "REJECT") or not approver.endswith(APPROVERS):
        return out({"ok": False, "error": "decision must be APPROVE or REJECT from an authorised approver"})
    status = "APPROVED" if decision == "APPROVE" else "REJECTED"
    try:
        ledger.update_entity({"PartitionKey": "req", "RowKey": rid, "status": status, "approver": approver, "decided_at": int(time.time())},
                             mode=UpdateMode.MERGE, etag=row.metadata["etag"], match_condition=MatchConditions.IfNotModified)
    except ResourceModifiedError:
        return out({"ok": False, "error": "request was decided concurrently"})
    return out({"ok": True, "request_id": rid, "status": status, "approver": approver})
'''),
 b("Write the work-order tool", "The write tool. It refuses unless the ledger says APPROVED, creates the work order, then marks the ledger row EXECUTED. Calling it twice creates one work order (idempotent).",
   "fn_create_work_order.py", '''
import json
import os
import azure.functions as func


def _table(name):
    from azure.data.tables import TableClient
    return TableClient.from_connection_string(os.environ["TABLE_CONNECTION_STRING"], name)


def main(req: func.HttpRequest) -> func.HttpResponse:
    from azure.core import MatchConditions
    from azure.core.exceptions import ResourceNotFoundError
    from azure.data.tables import UpdateMode
    b = req.get_json() if req.get_body() else {}
    rid = b.get("request_id", "")
    ledger = _table(os.environ.get("LEDGER_TABLE", "approvalledger"))
    out = lambda d: func.HttpResponse(json.dumps(d), mimetype="application/json")
    try:
        row = ledger.get_entity("req", rid)
    except ResourceNotFoundError:
        return out({"ok": False, "error": "refused: unknown request"})
    if row.get("status") == "EXECUTED":
        return out({"ok": True, "work_order_id": row["work_order_id"], "idempotent": True})
    if row.get("status") != "APPROVED":
        return out({"ok": False, "error": f"refused: ledger status is {row.get('status')}, a work order needs APPROVED"})
    wo_id = "WO-" + rid[-6:].upper()
    _table(os.environ.get("WORK_ORDERS_TABLE", "workorders")).upsert_entity({
        "PartitionKey": "wo", "RowKey": wo_id, "work_order_id": wo_id, "asset_id": row["asset_id"], "title": row["summary"],
        "priority": row.get("priority", "P3"), "status": "OPEN", "requester": row.get("requester", "")})
    ledger.update_entity({"PartitionKey": "req", "RowKey": rid, "status": "EXECUTED", "work_order_id": wo_id}, mode=UpdateMode.MERGE,
                         etag=row.metadata["etag"], match_condition=MatchConditions.IfNotModified)
    return out({"ok": True, "work_order_id": wo_id})
'''),
 b("Deploy the Function App", "Four steps, the same ones `az functionapp create`, `az functionapp config appsettings set` and `az functionapp deployment source config-zip` perform: an App Service plan (consumption), the site, its application settings (the Table connection string, the search address and key, the table names) and a zip deploy of the four functions in the Python v1 layout (`<name>/__init__.py` plus `function.json`). On real Azure the settings would be Key Vault references or a managed identity.",
   "deploy_tools.py", '''
import io
import json
import zipfile
import requests
from azure.mgmt.web import WebSiteManagementClient
from azure.mgmt.web.models import StringDictionary
from azlab import arm, rid, RG, LOC, ENDPOINT, HTTP_ENDPOINT
from azdata import storage_cs, search_endpoint, search_key, function_key, FUNCTION_APP, INDEX

FUNCTIONS = {"kb-search": "fn_kb_search.py", "asset-status": "fn_asset_status.py",
             "approval-decision": "fn_approval_decision.py", "create-work-order": "fn_create_work_order.py"}

web = arm(WebSiteManagementClient)
web.app_service_plans.begin_create_or_update(RG, FUNCTION_APP + "-plan", {"location": LOC, "sku": {"name": "Y1", "tier": "Dynamic"}, "kind": "functionapp"}).result()
web.web_apps.begin_create_or_update(RG, FUNCTION_APP, {"location": LOC, "kind": "functionapp,linux",
                                                       "server_farm_id": rid("Microsoft.Web", "serverfarms", FUNCTION_APP + "-plan")}).result()
web.web_apps.update_application_settings(RG, FUNCTION_APP, StringDictionary(properties={
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "TABLE_CONNECTION_STRING": storage_cs("Table", HTTP_ENDPOINT, "http"),     # the function sandbox reaches the simulator over plain http
    "SEARCH_ENDPOINT": search_endpoint().replace(ENDPOINT, HTTP_ENDPOINT, 1), "SEARCH_KEY": search_key(), "SEARCH_INDEX": INDEX,
    "ASSETS_TABLE": "assets", "WORK_ORDERS_TABLE": "workorders", "LEDGER_TABLE": "approvalledger", "INDEXER_NAME": "docs-indexer"}))

buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("host.json", json.dumps({"version": "2.0"}))
    z.writestr("requirements.txt", "azure-functions\\nazure-data-tables\\nazure-search-documents\\n")
    for name, path in FUNCTIONS.items():
        z.writestr(f"{name}/__init__.py", open(path).read())
        z.writestr(f"{name}/function.json", json.dumps({"scriptFile": "__init__.py", "bindings": [
            {"authLevel": "function", "type": "httpTrigger", "direction": "in", "name": "req", "methods": ["get", "post"]},
            {"type": "http", "direction": "out", "name": "$return"}]}))
r = requests.post(f"{ENDPOINT}/azure-data/functions/{FUNCTION_APP}/api/zipdeploy", data=buf.getvalue(), timeout=60)
r.raise_for_status()
listed = sorted(f.name.split("/")[-1] for f in web.web_apps.list_functions(RG, FUNCTION_APP))
print("deployed", FUNCTION_APP, listed)
print("host key listed through ARM:", bool(function_key()))
''', run="python deploy_tools.py", expect="deployed facilities-tools ['approval-decision', 'asset-status', 'create-work-order', 'kb-search']"),
 b("Call the read-only tool", "Call asset-status for boiler B-12 over HTTPS with the host key (`x-functions-key`), the way an agent or the API Management gateway will. The table read happens inside the function.",
   "call_tools.py", '''
from azdata import call_function, FUNCTION_APP

out = call_function(FUNCTION_APP, "asset-status", {"asset_id": "B-12"})
print("found:", out["found"], "| status:", out["asset"]["status"], "| work orders:", len(out["work_orders"]))
''', run="python call_tools.py", expect="found: True | status: RUNNING | work orders: 1"),
]
PIP8 = ("pip install azure-core azure-mgmt-loganalytics azure-mgmt-applicationinsights azure-mgmt-monitor azure-monitor-opentelemetry-exporter "
        "azure-monitor-query opentelemetry-sdk requests langgraph fastapi openai")

LAB[8] = [
 b("Install the libraries", "Chapter 8 lets you see what the agent did: one trace span per agent and tool step, a structured log line and a custom metric, all exported to Application Insights with the official OpenTelemetry exporter (`azure-monitor-opentelemetry-exporter`), then read back with KQL (Kusto) from the linked Log Analytics workspace (`azure-monitor-query`). It runs the supervisor graph from chapter 3, so it needs `agent_graph.py`, `app.py`, chapter 7 (tools), chapter 5 (approval) and chapter 6 (search).",
   "install8.sh", PIP8, lang="bash"),
 b("Create the workspace and the Application Insights component", "Azure's observability is two resources: a Log Analytics workspace (the store you query with KQL) and a *workspace-based* Application Insights component (the ingestion endpoint for traces, logs and metrics, which writes into that workspace). Created through Azure Resource Manager; the connection string and the workspace id are saved to `obs.json`.",
   "create_observability.py", '''
import json
from azure.mgmt.applicationinsights import ApplicationInsightsManagementClient
from azure.mgmt.loganalytics import LogAnalyticsManagementClient
from azlab import arm, rid, ensure_rg, RG, LOC, ENDPOINT

ensure_rg()
ws = arm(LogAnalyticsManagementClient).workspaces.begin_create_or_update(RG, "facilities-law", {"location": LOC}).result()
ai = arm(ApplicationInsightsManagementClient).components.create_or_update(RG, "facilities-ai", {
    "location": LOC, "kind": "web", "application_type": "web", "workspace_resource_id": rid("Microsoft.OperationalInsights", "workspaces", "facilities-law")})
ikey = ai.connection_string.split("InstrumentationKey=")[1].split(";")[0]
json.dump({"workspace_id": ws.customer_id, "ingest": f"InstrumentationKey={ikey};IngestionEndpoint={ENDPOINT}/"}, open("obs.json", "w"))
print("workspace facilities-law customerId:", ws.customer_id, "| application insights facilities-ai ready")
''', run="python create_observability.py", expect="application insights facilities-ai ready"),
 b("Write the full agent: the graph plus its tools", "The chapter 3 graph, now with real tools plugged into its `tools` hook. Facilities calls the `kb-search` function, Maintenance calls `asset-status` and, when the question asks for a work order, parks an approval request (chapter 5), and Analytics counts work orders in Table storage. Each tool call is recorded as a span of kind `tool` next to the agent spans. The model is the repo's deterministic test stub, so its answers are short and fixed; the routing, the tool calls and the spans are real.",
   "full_agent.py", '''
import os
import re
import time
import uuid
os.environ.setdefault("VYOMI_ENDPOINT", os.environ["VYOMI_AZURE_HTTP_ENDPOINT"])
import agent_graph
from app import converse
from approval import request_approval, work_orders
from azdata import call_function, FUNCTION_APP


def _tool_span(st, name, t0):
    st["spans"].append({"name": f"tool:{name}", "kind": "tool", "start": t0, "end": time.time()})


def facilities(st):
    t0 = time.time()
    out = call_function(FUNCTION_APP, "kb-search", {"query": st["question"]})      # how many passages comes from your design, inside the tool
    _tool_span(st, "kb_search", t0)
    st["citations"] = [{"n": i + 1, "source": r["source"], "text": r["text"]} for i, r in enumerate(out["results"])]
    return "\\n".join(f"[{c['n']}] {c['text']}" for c in st["citations"])


def maintenance(st):
    t0 = time.time()
    m = re.search(r"\\b([A-Z]{1,3}-\\d+)\\b", st["question"])
    if not m:
        return "No asset id in the question."
    out = call_function(FUNCTION_APP, "asset-status", {"asset_id": m.group(1)})
    _tool_span(st, "asset_status", t0)
    note = f"Asset {m.group(1)} status {out['asset']['status']}; open work orders: {[w['work_order_id'] for w in out['work_orders'] if w['status'] == 'OPEN']}."
    if re.search(r"work order|raise|create", st["question"], re.I):
        rid = "req-" + uuid.uuid4().hex[:10]
        t1 = time.time()
        request_approval(rid, m.group(1), f"Work order for {m.group(1)}: " + st["question"][:100], "P1" if re.search(r"exceed|pressure|fire", st["question"], re.I) else "P2", st.get("user", ""))
        _tool_span(st, "create_work_order", t1)
        st["approval"] = rid
        note += f" A work order request ({rid}) was submitted and is waiting for approval."
    return note


def analytics(st):
    t0 = time.time()
    rows = work_orders()
    _tool_span(st, "work_order_stats", t0)
    return f"Work orders: {len(rows)} total, {len([r for r in rows if r.get('status') == 'OPEN'])} open."


graph = agent_graph.build(converse, tools={"facilities": facilities, "maintenance": maintenance, "analytics": analytics})


def ask(question, user="maria"):
    return graph.invoke({"question": question, "user": user, "spans": []})


if __name__ == "__main__":
    st = ask("Boiler B-12 is at 34 psi. What does the SOP say, and please raise a work order for it. How many work orders are open?")
    print("route:", st["route"])
    print("spans:", [s["name"] for s in st["spans"]])
    print("approval request:", st.get("approval", "none")[:8], "| answer:", st["answer"][:70])
'''),
 b("Run the agent once", "One real run through every layer built so far: the supervisor routes to all three sub-agents, the tools run (search, asset lookup, an approval request, the statistics), and the spans come back in the state.",
   "run_agent.py", '''
import json
import full_agent

st = full_agent.ask("Boiler B-12 is at 34 psi. What does the SOP say, and please raise a work order for it. How many work orders are open?")
json.dump({"spans": st["spans"], "route": st["route"], "user": st["user"], "approval": st.get("approval")}, open("run.json", "w"))
tools = [s["name"] for s in st["spans"] if s["kind"] == "tool"]
print("route:", st["route"])
print("tool calls:", tools)
print("approval request parked:", bool(st.get("approval")), "| spans recorded:", len(st["spans"]))
''', run="python run_agent.py", expect="approval request parked: True"),
 b("Export the spans, a log line and a metric", "With the OpenTelemetry SDK and the Azure Monitor exporters: the run becomes one root span `facilities-supervisor` with a child span per agent and tool step (their start and end times are the ones the graph measured); a structured JSON log line records the route and tools; and a counter `facilities.tool_calls` records how many tools ran. Every record carries the trace id, which is how you find them again.",
   "export_telemetry.py", '''
import json
import logging
import time
import uuid
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import SimpleLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.trace import SpanKind, set_span_in_context
from azure.monitor.opentelemetry.exporter import AzureMonitorLogExporter, AzureMonitorMetricExporter, AzureMonitorTraceExporter

obs = json.load(open("obs.json"))
run = json.load(open("run.json"))
cs = obs["ingest"]
ns = lambda t: int(t * 1e9)
tag = uuid.uuid4().hex
spans = run["spans"]

tp = TracerProvider()
tp.add_span_processor(SimpleSpanProcessor(AzureMonitorTraceExporter(connection_string=cs, disable_offline_storage=True)))
tracer = tp.get_tracer("facilities-supervisor")
root = tracer.start_span("facilities-supervisor", start_time=ns(spans[0]["start"]), kind=SpanKind.SERVER, attributes={"facilities.trace": tag, "user": run["user"]})
ctx = set_span_in_context(root)
for s in spans:
    tracer.start_span(s["name"], context=ctx, start_time=ns(s["start"]), attributes={"kind": s["kind"], "facilities.trace": tag}).end(end_time=ns(s["end"]))
root.end(end_time=ns(spans[-1]["end"]))
tp.shutdown()
trace_id = format(root.get_span_context().trace_id, "032x")

lp = LoggerProvider()
lp.add_log_record_processor(SimpleLogRecordProcessor(AzureMonitorLogExporter(connection_string=cs, disable_offline_storage=True)))
log = logging.getLogger("facilities-agent-" + tag[:6])
log.setLevel(logging.INFO)
log.addHandler(LoggingHandler(level=logging.INFO, logger_provider=lp))
log.info("agent_run %s", json.dumps({"event": "agent_run", "trace": tag, "route": run["route"], "tools": [s["name"] for s in spans if s["kind"] == "tool"]}))
lp.shutdown()

n_tools = len([s for s in spans if s["kind"] == "tool"])
reader = PeriodicExportingMetricReader(AzureMonitorMetricExporter(connection_string=cs, disable_offline_storage=True), export_interval_millis=3600_000)
mp = MeterProvider(metric_readers=[reader])
mp.get_meter("facilities").create_counter("facilities.tool_calls").add(n_tools, {"agent": "facilities-supervisor"})
mp.force_flush()
mp.shutdown()

json.dump({"trace_id": trace_id, "tag": tag, "tool_calls": n_tools}, open("trace.json", "w"))
print("exported", len(spans) + 1, "spans, 1 log line and the metric facilities.tool_calls =", n_tools, "| trace id", trace_id)
''', run="python export_telemetry.py", expect="the metric facilities.tool_calls = 4"),
 b("Read it back with KQL", "`LogsQueryClient.query_workspace` runs Kusto queries against the workspace. Spans land in `AppDependencies`, log lines in `AppTraces`, the metric in `AppMetrics`; the trace id is `OperationId`. Telemetry takes a moment to be queryable, so the script retries for up to 20 seconds. Alert rules and workbooks are not simulated; the KQL subset covers these queries.",
   "query_telemetry.py", '''
import json
import time
from datetime import timedelta
from azure.monitor.query import LogsQueryClient
from azlab import DevToken, ENDPOINT

obs, tr = json.load(open("obs.json")), json.load(open("trace.json"))
client = LogsQueryClient(DevToken(), endpoint=ENDPOINT + "/azure-data/loganalytics")


def q(text):
    r = client.query_workspace(obs["workspace_id"], text, timespan=timedelta(hours=2))
    return r.tables[0].rows if r.tables else []


rows = []
for _ in range(20):
    rows = q(f"AppDependencies | where OperationId == '{tr['trace_id']}' | project Name | order by Name asc")
    if rows:
        break
    time.sleep(1)
names = sorted({r[0] for r in rows})
print("spans read back:", names)
print("log lines:", len(q(f"AppTraces | where Message has '{tr['tag']}' | project Message")))
total = q("AppMetrics | where Name == 'facilities.tool_calls' | summarize total=sum(Sum)")[0][0]
print("facilities.tool_calls total:", total)
''', run="python query_telemetry.py", expect="facilities.tool_calls total: 4"),
 b("Ingest into a custom table and summarise", "For data that is not a trace, the Log Analytics HTTP Data Collector API writes rows straight into a custom table (`AgentRun_CL`; the suffixes `_s` mark string columns). Then KQL `summarize` counts calls per tool.",
   "custom_table.py", '''
import json
import uuid
from datetime import timedelta
import requests
from azure.monitor.query import LogsQueryClient
from azlab import DevToken, ENDPOINT, rid

obs = json.load(open("obs.json"))
run_id = uuid.uuid4().hex
rows = [{"run": run_id, "tool": t, "via": "function"} for t in ("kb_search", "asset_status", "asset_status", "work_order_stats")]
r = requests.post(f"{ENDPOINT}{rid('Microsoft.OperationalInsights', 'workspaces', 'facilities-law')}/api/logs", headers={"Log-Type": "AgentRun"}, json=rows, timeout=20)
print("ingest HTTP", r.status_code)
client = LogsQueryClient(DevToken(), endpoint=ENDPOINT + "/azure-data/loganalytics")
res = client.query_workspace(obs["workspace_id"], f"AgentRun_CL | where run_s == '{run_id}' | summarize n=count() by tool_s | order by tool_s asc", timespan=timedelta(hours=2))
print("calls per tool:", {r[0]: r[1] for r in res.tables[0].rows})
''', run="python custom_table.py", expect="calls per tool: {'asset_status': 2, 'kb_search': 1, 'work_order_stats': 1}"),
 b("Read platform metrics from Azure Monitor", "Azure resources publish their own metrics. `MonitorManagementClient.metrics.list` reads the `Transactions` metric of the documents storage account from chapter 12.",
   "platform_metrics.py", '''
from azure.mgmt.monitor import MonitorManagementClient
from azlab import arm, rid

m = arm(MonitorManagementClient).metrics.list(rid("Microsoft.Storage", "storageAccounts", "facilitiesdocs"), metricnames="Transactions", aggregation="Total",
                                              timespan="2026-11-17T00:00:00Z/2026-11-30T00:00:00Z", interval="PT1H")
print("platform metrics returned:", [x.name.value for x in m.value])
''', run="python platform_metrics.py", expect="platform metrics returned: ['Transactions']"),
]
PIP9 = "pip install azure-core azure-data-tables openai requests"

LAB[9] = [
 b("Install the libraries", "Chapter 9 gives the agent memory. Azure splits it honestly in two. SHORT-TERM memory (the events of one session) is a managed feature: an Assistants / Foundry *thread* stores the messages and their metadata. LONG-TERM memory (facts that outlive a session) is NOT a managed Azure service: Azure has no counterpart to AgentCore Memory or Vertex AI Memory Bank, so you build it yourself as an application pattern on Azure Table storage, and this chapter says so in the code. It uses `azlab.py` and `azdata.py` (chapters 10 and 7).",
   "install9.sh", PIP9, lang="bash"),
 b("Short-term memory: a thread", "Create a thread with metadata (who and which session), add two user messages, read them back in order, update the metadata, then run an assistant on the thread: the run reads the whole thread and appends its reply to it. The thread is the session's memory: the service keeps the messages for you. Be clear about what this block proves: the model here is the repo's deterministic test stub, which only echoes the last user message, so it verifies the mechanics (history in order, metadata, a run that completes and appends to the same thread), not that a model recalls the badge number. A larger model would answer '4412' to a question about the badge.",
   "short_term.py", '''
import time
from azlab import aoai, CHAT

oc = aoai("2025-03-01-preview")
thread = oc.beta.threads.create(metadata={"session": "s1", "user": "maria"})
for text in ("my badge is 4412", "which floor am I on"):
    oc.beta.threads.messages.create(thread.id, role="user", content=text)
history = oc.beta.threads.messages.list(thread.id, order="asc").data
print("history in order:", [m.content[0].text.value for m in history])

oc.beta.threads.update(thread.id, metadata={"session": "s1", "user": "maria", "topic": "badge"})
print("metadata:", oc.beta.threads.retrieve(thread.id).metadata)

assistant = oc.beta.assistants.create(model=CHAT, instructions="Answer from the conversation so far.")
run = oc.beta.threads.runs.create(thread.id, assistant_id=assistant.id)
for _ in range(60):
    if run.status not in ("queued", "in_progress"):
        break
    time.sleep(0.5)
    run = oc.beta.threads.runs.retrieve(run.id, thread_id=thread.id)
reply = " ".join(c.text.value for m in oc.beta.threads.messages.list(thread.id).data if m.role == "assistant" for c in m.content)
print("run:", run.status, "| thread now holds", len(oc.beta.threads.messages.list(thread.id).data), "messages (2 user + 1 assistant)")
oc.beta.threads.delete(thread.id)
''', run="python short_term.py", expect="thread now holds 3 messages (2 user + 1 assistant)"),
 b("Long-term memory: write the helper", "Facts are rows in a Table called `longtermmemory`. `PartitionKey` is `tenant|user`, so one user can only ever read their own rows and a tenant boundary is part of every key: that is the scoping rule for memory (never trust a fact from another user, and never let one user's text become another's context). Each row keeps its source and a timestamp so you can expire or audit it. `remember` upserts, `recall` reads, `forget` deletes (retention and right to erasure).",
   "memory.py", '''
import time
from azdata import table

TABLE = "longtermmemory"


def _pk(tenant, user):
    return f"{tenant}|{user}".replace("/", "_").replace("#", "_").replace("?", "_")[:60]


def remember(tenant, user, key, fact, source="session"):
    table(TABLE).upsert_entity({"PartitionKey": _pk(tenant, user), "RowKey": key, "fact": fact, "source": source, "ts": int(time.time())})


def recall(tenant, user):
    return [dict(e) for e in table(TABLE).query_entities("PartitionKey eq @u", parameters={"u": _pk(tenant, user)})]


def forget(tenant, user, key):
    table(TABLE).delete_entity(_pk(tenant, user), key)
'''),
 b("Try it: a new session recalls a fact, another user cannot", "Session one stores a preference. A completely new process (a new session, a new thread) reads it back. A second user sees nothing. Then `forget` removes it.",
   "try_memory.py", '''
from memory import remember, recall, forget

remember("facilities", "maria", "pref-floor", "prefers floor 3 east wing for inspections", source="session s1")
print("new session recalls:", recall("facilities", "maria")[0]["fact"])
print("another user sees:", recall("facilities", "tom"))
forget("facilities", "maria", "pref-floor")
print("after forget:", recall("facilities", "maria"))
''', run="python try_memory.py", expect="new session recalls: prefers floor 3 east wing for inspections"),
 b("Confirm there is no managed long-term memory API", "A check, not a feature: the Azure OpenAI / Foundry surface has no memory-store route. Both probes must answer 404 or 405. This is why the previous two blocks are your own code and not an Azure service.",
   "no_managed_memory.py", '''
import requests
from azlab import ENDPOINT

codes = [requests.get(ENDPOINT + p, params={"api-version": "2025-03-01-preview"}, timeout=10).status_code for p in ("/openai/memory_stores", "/openai/memories")]
print("memory routes answer:", codes, "-> no managed long-term memory API")
''', run="python no_managed_memory.py", expect="no managed long-term memory API"),
]
PIP10 = "pip install azure-core azure-identity azure-mgmt-resource azure-mgmt-cognitiveservices openai"

LAB[10] = [
 b("Install the libraries", "Chapter 10 uses the official Azure management library for the Azure OpenAI account and the official `openai` library (its `AzureOpenAI` client) for the model calls. Nothing is modified or wrapped.",
   "install10.sh", PIP10, lang="bash"),
 b("Write the shared Azure settings", "Every chapter imports this one file, so keep the name `azlab.py` and keep it next to your other files. It reads the simulator address from environment variables and builds the real Azure clients. The management clients (`azure-mgmt-*`) are pointed at the simulator with `base_url`, which is exactly how you point them at a sovereign cloud. The simulator accepts any bearer token on its control plane, so a small fixed-token credential is enough here (on real Azure you would pass `DefaultAzureCredential()`). Later chapters add to the helpers at the bottom, never change the top.",
   "azlab.py", '''
import os
import time
from urllib.parse import urlparse

ENDPOINT = os.environ["VYOMI_AZURE_ENDPOINT"]                          # https://localhost:<port>  (the simulator, TLS with a local CA)
HTTP_ENDPOINT = os.environ.get("VYOMI_AZURE_HTTP_ENDPOINT", ENDPOINT)   # the same simulator on plain http, used by functions and containers
AMQP_PORT = int(os.environ.get("VYOMI_AZURE_AMQP_PORT", "5672"))        # Service Bus AMQP 1.0 listener
SUB = os.environ.get("AZURE_SUBSCRIPTION_ID", "00000000-0000-0000-0000-cloudlearn01")
RG = "rg-facilities"
LOC = "eastus"
TENANT = "facilities-tenant"
HOST = urlparse(ENDPOINT).hostname or "localhost"
STORAGE = "devstoreaccount1"
ACCOUNT_KEY = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="   # the public Azurite development key
CHAT, EMBED = "chat", "embed"                                            # your deployment names
OPENAI_ACCOUNT = "facilities-openai"

_cache = {}


class DevToken:
    """A TokenCredential that always returns the same development token (the simulator does not check it)."""
    def get_token(self, *scopes, **kwargs):
        from azure.core.credentials import AccessToken
        return AccessToken(os.environ.get("VYOMI_ACCESS_TOKEN", "vyomi-local"), int(time.time()) + 3600)


def arm(cls, **kw):
    """Any azure-mgmt-* client, pointed at the simulator."""
    if cls not in _cache:
        _cache[cls] = cls(DevToken(), SUB, base_url=ENDPOINT, polling_interval=0, **kw)
    return _cache[cls]


def rid(provider, kind, name):
    return f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/{provider}/{kind}/{name}"


def ensure_rg():
    from azure.mgmt.resource.resources import ResourceManagementClient
    arm(ResourceManagementClient).resource_groups.create_or_update(RG, {"location": LOC})


def pick_models():
    """The models are the ones this simulator hosts: in-browser models on Nano, the Mesh model pool on a Mesh. Returns (chat, embedding) as
    the {format, name, version} a deployment needs. Never hard-code a vendor model."""
    from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient
    ms = [{"format": m.model.format, "name": m.model.name, "version": m.model.version} for m in arm(CognitiveServicesManagementClient).models.list(LOC) if m.kind == "OpenAI"]
    emb = [m for m in ms if "embed" in m["name"] or "minilm" in m["name"]]
    return [m for m in ms if m not in emb][0], emb[0]


def aoai(api_version="2024-10-21"):
    from openai import AzureOpenAI
    key = ("aoai", api_version)
    if key not in _cache:
        _cache[key] = AzureOpenAI(azure_endpoint=ENDPOINT, api_key="vyomi-local", api_version=api_version, max_retries=0, timeout=120)
    return _cache[key]
'''),
 b("Create the Azure OpenAI account and the two deployments", "Azure OpenAI is a resource: an account of kind `OpenAI`, and inside it one *deployment* per model. Your code never names the model, it names the deployment (`chat`, `embed`). Resource group first, then the account, then the deployments, all through the real `azure-mgmt-cognitiveservices` client.",
   "create_openai.py", '''
from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient
from azlab import arm, ensure_rg, pick_models, RG, LOC, OPENAI_ACCOUNT, CHAT, EMBED

ensure_rg()
cs = arm(CognitiveServicesManagementClient)
cs.accounts.begin_create(RG, OPENAI_ACCOUNT, {"location": LOC, "kind": "OpenAI", "sku": {"name": "S0"},
                                              "properties": {"customSubDomainName": OPENAI_ACCOUNT}}).result()
chat_model, embed_model = pick_models()
for name, model in ((CHAT, chat_model), (EMBED, embed_model)):
    cs.deployments.begin_create_or_update(RG, OPENAI_ACCOUNT, name, {"sku": {"name": "Standard", "capacity": 1},
        "properties": {"model": model}}).result()
print("deployments:", sorted(d.name for d in cs.deployments.list(RG, OPENAI_ACCOUNT)))
''', run="python create_openai.py", expect="deployments: ['chat', 'embed']"),
 b("Write the model client", "Every other chapter imports these three functions, so keep the names. The model behind your deployments is one the simulator hosts (a small open model on Nano, the Mesh model pool on a Mesh), so replies are those of a small open model; the calls are identical to what you would send to a larger hosted model.",
   "vymodels.py", '''
import json
from azlab import aoai, CHAT, EMBED


def chat(prompt, system=None):
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    r = aoai().chat.completions.create(model=CHAT, messages=msgs, max_tokens=200, temperature=0)
    return r.choices[0].message.content


def chat_with_tools(prompt, tools):
    r = aoai().chat.completions.create(model=CHAT, messages=[{"role": "user", "content": prompt}], tools=tools, tool_choice="auto")
    m = r.choices[0].message
    call = m.tool_calls[0] if m.tool_calls else None
    return {"finish_reason": r.choices[0].finish_reason,
            "tool_use": {"name": call.function.name, "input": json.loads(call.function.arguments)} if call else None,
            "text": m.content or ""}


def embed(text, dimensions=None):
    """dimensions: ask for a shorter vector (your RAG design sets this); None keeps the model's own size."""
    kw = {"dimensions": dimensions} if dimensions else {}
    return aoai().embeddings.create(model=EMBED, input=[text], **kw).data[0].embedding
'''),
 b("Try chat, a tool call and an embedding", "A chat turn, a tool-calling turn (the model asks for `asset_status`, your code would run it) and an embedding (a list of numbers: its length depends on the embedding model your simulator hosts). The tool definition is the one the agents use later.",
   "try_models.py", '''
from vymodels import chat, chat_with_tools, embed

print("chat:", chat("Reply with the single word OK."))

TOOL = {"type": "function", "function": {"name": "asset_status", "description": "Look up an asset by id",
        "parameters": {"type": "object", "properties": {"asset_id": {"type": "string"}}, "required": ["asset_id"]}}}
r = chat_with_tools("What is the status of asset B-12?", [TOOL])
print("tools: finish_reason =", r["finish_reason"], "| tool =", r["tool_use"])

print("embed: vector of", len(embed("boiler pressure limit")), "numbers")
''', run="python try_models.py", expect="embed: vector of"),
 b("Streaming, smaller embeddings and an unknown deployment", "`stream=True` returns chunks as they are produced. `dimensions=256` shrinks an embedding (ask for a shorter vector). Calling a deployment that does not exist is a 404 `DeploymentNotFound`: the most common first mistake, so see it once.",
   "try_more.py", '''
from openai import NotFoundError
from azlab import aoai, CHAT, EMBED

chunks = [c for c in aoai().chat.completions.create(model=CHAT, messages=[{"role": "user", "content": "hi"}], stream=True)]
print("stream:", len(chunks), "chunks")

small = aoai().embeddings.create(model=EMBED, input="a", dimensions=256)
print("embedding with dimensions=256:", len(small.data[0].embedding), "numbers")

try:
    aoai().chat.completions.create(model="no-such-deployment", messages=[{"role": "user", "content": "x"}])
except NotFoundError as e:
    print("unknown deployment ->", e.status_code, getattr(e, "code", ""))
''', run="python try_more.py", expect="unknown deployment -> 404"),
]
PIP11 = "pip install azure-core azure-ai-contentsafety azure-search-documents openai"

LAB[11] = [
 b("Install the libraries", "Chapter 11 generates answers that are grounded in what chapter 6 retrieved and checks them before the user sees them. It uses the `openai` library (chat, Assistants file search, and Azure OpenAI On Your Data), `azure-ai-contentsafety` for the output filter and the retrieval helper `kb.py` from chapter 6. Scope note: Azure AI Content Safety flags harmful text (hate, sexual, violence, self-harm). Masking personal data is a different Azure service (Azure AI Language PII detection) that the simulator does not offer, so this chapter does not claim to do it.",
   "install11.sh", PIP11, lang="bash"),
 b("Write the grounded answer function", "Retrieve, number the passages, and instruct the model to answer only from them and cite like [1]. The function returns the answer together with the numbered citations (source file plus the passage), so a user interface can show where each claim came from. The reply here is the repo's deterministic test stub, which simply quotes the first passage; a larger model writes a fuller answer.",
   "respond.py", '''
from azlab import aoai, CHAT
from kb import kb_search
import rag_design

SYSTEM = "Answer using only the context. Cite sources like [1]. If the context does not contain the answer, say you do not know."


def answer(question, mode=None, top=None):
    hits = kb_search(question, mode or rag_design.search_type(), top)      # your design: search type and how many passages
    best = max([h.get("score") or 0 for h in hits] or [0])
    if rag_design.grounding_threshold() > 0 and best < rag_design.grounding_threshold():       # your design: refuse when nothing retrieved is relevant enough
        return {"answer": "I do not know: nothing in the approved documents is relevant enough.", "citations": []}
    citations = [{"n": i + 1, "source": h["source"], "text": h["text"][:160]} for i, h in enumerate(hits)]
    context = "\\n".join(f"[{c['n']}] {h['text']}" for c, h in zip(citations, hits))
    r = aoai().chat.completions.create(model=CHAT, max_tokens=300, temperature=0, messages=[
        {"role": "system", "content": SYSTEM}, {"role": "user", "content": f"Context:\\n{context}\\n\\nQuestion: {question}"}])
    return {"answer": r.choices[0].message.content, "citations": citations}
'''),
 b("Try it: a cited answer", "Ask the boiler question. The answer must carry a citation marker, and the first citation must be the boiler SOP.",
   "try_respond.py", '''
from respond import answer

r = answer("What must I do when boiler pressure exceeds 30 psi?")
print("answer:", r["answer"][:110])
for c in r["citations"]:
    print(f"citation [{c['n']}]:", c["source"])
print("grounded:", "[1]" in r["answer"] and r["citations"][0]["source"] == "boiler-sop.md")
''', run="python try_respond.py", expect="grounded: True"),
 b("Filter the output with Azure AI Content Safety", "`ContentSafetyClient.analyze_text` returns a severity (0 to 7) for each harm category. `check_output` blocks an answer if any category reaches the threshold. The clean agent answer passes; an invented harmful completion is flagged. The simulator's Content Safety is a deterministic filter set, not Microsoft's trained classifiers.",
   "guard.py", '''
from azure.ai.contentsafety import ContentSafetyClient
from azure.ai.contentsafety.models import AnalyzeTextOptions
from azure.core.credentials import AzureKeyCredential
from azlab import ENDPOINT

_client = ContentSafetyClient(ENDPOINT, AzureKeyCredential("vyomi-local"))
THRESHOLD = 2


def severities(text):
    return {x.category: x.severity for x in _client.analyze_text(AnalyzeTextOptions(text=text)).categories_analysis}


def check_output(text):
    sev = severities(text)
    return {"allowed": all((v or 0) < THRESHOLD for v in sev.values()), "severities": sev}


if __name__ == "__main__":
    from respond import answer
    good = check_output(answer("What must I do when boiler pressure exceeds 30 psi?")["answer"])
    bad = check_output("You should torture and kill the technician who reports to you.")
    print("agent answer allowed:", good["allowed"])
    print("harmful completion allowed:", bad["allowed"], "| flagged categories:", [k for k, v in bad["severities"].items() if v and v >= 2])
''', run="python guard.py", expect="harmful completion allowed: False"),
 b("Ground with Assistants file search", "The managed alternative to doing retrieval yourself: upload a file to a *vector store*, give an assistant the `file_search` tool, run it on a thread, and read the `file_citation` annotations on its reply. Same `openai` library, same calls as on Azure OpenAI.",
   "file_search.py", '''
import time
from azlab import aoai, CHAT

oc = aoai("2025-03-01-preview")
store = oc.vector_stores.create(name="facilities-kb")
f = oc.files.create(file=("boiler-sop.md", open("boiler-sop.md", "rb").read()), purpose="assistants")
oc.vector_stores.files.create(store.id, file_id=f.id)
print("files in the vector store:", len(oc.vector_stores.files.list(store.id).data))

assistant = oc.beta.assistants.create(model=CHAT, instructions="Answer only from the files.", tools=[{"type": "file_search"}],
                                      tool_resources={"file_search": {"vector_store_ids": [store.id]}})
thread = oc.beta.threads.create(messages=[{"role": "user", "content": "What must I do when boiler pressure exceeds 30 psi?"}])
run = oc.beta.threads.runs.create(thread.id, assistant_id=assistant.id)
for _ in range(60):
    if run.status not in ("queued", "in_progress"):
        break
    time.sleep(0.5)
    run = oc.beta.threads.runs.retrieve(run.id, thread_id=thread.id)
msgs = oc.beta.threads.messages.list(thread.id).data
notes = [a for m in msgs if m.role == "assistant" for c in m.content for a in c.text.annotations]
print("run:", run.status, "| annotation types:", sorted({a.type for a in notes}))
''', run="python file_search.py", expect="annotation types: ['file_citation']"),
 b("Ground with Azure OpenAI On Your Data", "The one-call version: add a `data_sources` entry of type `azure_search` to a normal chat request and the service retrieves from your AI Search index itself and returns the citations in the message `context`. It reuses the index and key from chapter 7 and 12.",
   "on_your_data.py", '''
from azlab import aoai, CHAT
from azdata import search_endpoint, search_key, INDEX

r = aoai("2025-03-01-preview").chat.completions.create(model=CHAT, messages=[{"role": "user", "content": "What is the boiler pressure rule?"}], extra_body={
    "data_sources": [{"type": "azure_search", "parameters": {"endpoint": search_endpoint(), "index_name": INDEX,
                                                            "authentication": {"type": "api_key", "key": search_key()}}}]})
context = getattr(r.choices[0].message, "context", None) or {}
print("On Your Data citations:", len(context.get("citations", [])))
''', run="python on_your_data.py", expect="On Your Data citations:"),
]
PIP12 = "pip install azure-core azure-storage-blob azure-search-documents azure-mgmt-storage azure-mgmt-search azure-mgmt-eventgrid azure-mgmt-web requests"

# ───────────────────────── chapter 14: design the RAG ─────────────────────────
LAB[14] = design_blocks(b, "azure")

# ───────────────────────── chapter 12: knowledge pipeline ─────────────────────────
LAB[12] = [
 b("Install the libraries", "Chapter 12 turns documents into searchable knowledge: Blob Storage holds the files, an Azure AI Search indexer reads them into the `facilities-kb` index, and an Event Grid subscription plus a Function re-runs the indexer whenever a new blob lands. It relies on the search service and `azdata.py` from chapter 7.",
   "install12.sh", PIP12, lang="bash"),
 b("Save the four documents", "The corpus: three SOPs and one maintenance manual, each a short Markdown file. Save each one exactly as shown, with the file name given (the file name becomes the citation source later). First, the boiler SOP.",
   "boiler-sop.md", '''
# SOP-101 Boiler plant operation (Site HQ-1, Building A)

If boiler pressure exceeds 30 psi, close the main steam valve, notify the duty engineer and raise a P1 work order.
The pressure relief valve (PRV) must be inspected every 90 days. Record the inspection in the maintenance log.
Never bypass the low-water cutoff. Boiler B-12 serves floors 1 to 6.
''', lang="markdown"),
 b("Save the elevator SOP", "Elevator faults.", "elevator-sop.md", '''
# SOP-215 Elevator faults

An elevator reporting door-zone faults must be taken out of service and tagged. Raise a P2 work order with the vendor.
Passengers trapped in a car: call the vendor emergency line and keep security on the floor until released.
''', lang="markdown"),
 b("Save the fire-safety SOP", "Fire alarms and evacuation.", "fire-safety-sop.md", '''
# SOP-310 Fire safety and evacuation

Fire alarm panels are tested monthly. When an alarm sounds, security must verify within 2 minutes and start evacuation of the affected zone.
Fire extinguishers are inspected annually. Sprinkler valve closures require a P1 work order and a fire watch until restored.
''', lang="markdown"),
 b("Save the HVAC manual", "Air handling unit maintenance.", "hvac-maintenance-manual.md", '''
# MM-220 HVAC air handling unit maintenance manual (AHU-7)

Replace the AHU-7 filter every 60 days or when differential pressure exceeds 250 Pa.
Inspect belts and bearings quarterly. A supply air temperature drift greater than 3 degrees C indicates a failing chilled water valve.
Raise a P2 work order for chilled water valve replacement. Spare valves are stocked in store room S-2.
''', lang="markdown"),
 b("Create the storage account and upload the documents", "A StorageV2 account `facilitiesdocs` through `azure-mgmt-storage`, then (with `azure-storage-blob`) a container `docs` and the four files. The blob data plane uses the same Azurite-style connection string as Table storage in chapter 7. The last line reads one blob back to prove the upload.",
   "upload_docs.py", '''
import os
from azure.mgmt.storage import StorageManagementClient
from azure.storage.blob import BlobServiceClient
from azlab import arm, ensure_rg, RG, LOC
from azdata import storage_cs

ensure_rg()
arm(StorageManagementClient).storage_accounts.begin_create(RG, "facilitiesdocs", {"location": LOC, "sku": {"name": "Standard_LRS"}, "kind": "StorageV2"}).result()
blobs = BlobServiceClient.from_connection_string(storage_cs("Blob"))
try:
    blobs.create_container("docs")
except Exception as e:
    if "ContainerAlreadyExists" not in str(e):
        raise
for name in ("boiler-sop.md", "elevator-sop.md", "fire-safety-sop.md", "hvac-maintenance-manual.md"):
    blobs.get_blob_client("docs", name).upload_blob(open(name, "rb").read(), overwrite=True)
names = sorted(b.name for b in blobs.get_container_client("docs").list_blobs())
print("container docs:", names)
print("read back:", blobs.get_blob_client("docs", "boiler-sop.md").download_blob().readall().decode().splitlines()[0])
''', run="python upload_docs.py", expect="read back: # SOP-101 Boiler plant operation"),
 b("Define and create the search index", "The index `facilities-kb` is the schema of what is searchable: an `id` key, `source` (the blob name, for citations), `title` and `content` as full-text fields, and `content_vector`, a 1536-number vector field with an HNSW algorithm. A semantic configuration `sem` tells the semantic ranker which fields matter. Chapter 6 queries this index with text, vectors and the ranker. `kb_index()` is reused there.",
   "kb_index.py", '''
from azure.core.credentials import AzureKeyCredential
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (HnswAlgorithmConfiguration, SearchField, SearchFieldDataType, SearchIndex, SearchableField,
                                                   SemanticConfiguration, SemanticField, SemanticPrioritizedFields, SemanticSearch, SimpleField,
                                                   VectorSearch, VectorSearchProfile)
from azdata import search_endpoint, search_key, INDEX
from vymodels import embed
import rag_design

# the vector size: your design when it sets one, otherwise that of the embedding model this simulator hosts (it differs between Nano and a Mesh)
DIMS = rag_design.dimensions() or len(embed("dimension probe"))


def kb_index():
    fields = [SimpleField(name="id", type=SearchFieldDataType.String, key=True, filterable=True),
              SimpleField(name="source", type=SearchFieldDataType.String, filterable=True),
              SearchableField(name="title", type=SearchFieldDataType.String),
              SearchableField(name="content", type=SearchFieldDataType.String),
              SearchField(name="content_vector", type=SearchFieldDataType.Collection(SearchFieldDataType.Single), searchable=True,
                          vector_search_dimensions=DIMS, vector_search_profile_name="vp")]
    return SearchIndex(name=INDEX, fields=fields,
                       vector_search=VectorSearch(algorithms=[HnswAlgorithmConfiguration(name="h")],
                                                  profiles=[VectorSearchProfile(name="vp", algorithm_configuration_name="h")]),
                       semantic_search=SemanticSearch(configurations=[SemanticConfiguration(name="sem", prioritized_fields=SemanticPrioritizedFields(
                           title_field=SemanticField(field_name="title"), content_fields=[SemanticField(field_name="content")]))]))


def index_client():
    return SearchIndexClient(search_endpoint(), AzureKeyCredential(search_key()))


if __name__ == "__main__":
    ic = index_client()
    ic.create_or_update_index(kb_index())
    print("index", INDEX, "fields:", [f.name for f in ic.get_index(INDEX).fields])
''', run="python kb_index.py", expect="index facilities-kb fields: ['id', 'source', 'title', 'content', 'content_vector']"),
 b("Create the blob data source and the indexer", "An indexer is a scheduled job that reads a data source and writes documents into an index. The data source points at the `docs` container; field mappings turn the blob path into the key (`base64Encode`) and the blob name into `source` and `title`. Run it and wait for `success`. This is the initial load.",
   "indexer.py", '''
import time
from azure.core.credentials import AzureKeyCredential
from azure.search.documents.indexes import SearchIndexerClient
from azure.search.documents.indexes.models import FieldMapping, SearchIndexer, SearchIndexerDataContainer, SearchIndexerDataSourceConnection
from azlab import HTTP_ENDPOINT
from azdata import search_endpoint, search_key, storage_cs, INDEX

ic = SearchIndexerClient(search_endpoint(), AzureKeyCredential(search_key()))
ic.create_or_update_data_source_connection(SearchIndexerDataSourceConnection(
    name="docs-blob", type="azureblob", connection_string=storage_cs("Blob", HTTP_ENDPOINT, "http"), container=SearchIndexerDataContainer(name="docs")))
ic.create_or_update_indexer(SearchIndexer(name="docs-indexer", data_source_name="docs-blob", target_index_name=INDEX, field_mappings=[
    FieldMapping(source_field_name="metadata_storage_path", target_field_name="id", mapping_function={"name": "base64Encode"}),
    FieldMapping(source_field_name="metadata_storage_name", target_field_name="source"),
    FieldMapping(source_field_name="metadata_storage_name", target_field_name="title")]))
ic.run_indexer("docs-indexer")
for _ in range(40):
    last = ic.get_indexer_status("docs-indexer").last_result
    if last and str(last.status).lower().endswith("success"):
        break
    time.sleep(1)
print("indexer last run:", str(last.status).split(".")[-1].lower(), "| documents:", last.item_count)
''', run="python indexer.py", expect="indexer last run: success | documents: 4"),
 b("Check the documents are searchable", "A first full-text query. The boiler SOP must rank first for a boiler question, and the index must hold exactly four documents.",
   "check_search.py", '''
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azdata import search_endpoint, search_key, INDEX

sc = SearchClient(search_endpoint(), INDEX, AzureKeyCredential(search_key()))
rows = list(sc.search(search_text="boiler pressure", select=["id", "source", "content"], top=3))
print("documents in the index:", len(list(sc.search(search_text="*", top=50))))
print("'boiler pressure' ->", rows[0]["source"])
''', run="python check_search.py", expect="'boiler pressure' -> boiler-sop.md"),
 b("Write the ingest function", "The pipeline's trigger. Event Grid posts `Microsoft.Storage.BlobCreated` events here. The function answers the subscription validation handshake (Event Grid sends a code and expects it echoed back), and for every new blob it runs the indexer so the document becomes searchable.",
   "fn_ingest_docs.py", '''
import json
import os
import azure.functions as func


def main(req: func.HttpRequest) -> func.HttpResponse:
    events = req.get_json() if req.get_body() else []
    events = events if isinstance(events, list) else [events]
    out = lambda d: func.HttpResponse(json.dumps(d), mimetype="application/json")
    for ev in events:
        if ev.get("eventType") == "Microsoft.EventGrid.SubscriptionValidationEvent":
            return out({"validationResponse": ev["data"]["validationCode"]})
    ran = []
    for ev in events:
        if ev.get("eventType") != "Microsoft.Storage.BlobCreated":
            continue
        from azure.core.credentials import AzureKeyCredential
        from azure.search.documents.indexes import SearchIndexerClient
        SearchIndexerClient(os.environ["SEARCH_ENDPOINT"], AzureKeyCredential(os.environ["SEARCH_KEY"])).run_indexer(os.environ.get("INDEXER_NAME", "docs-indexer"))
        ran.append(ev.get("subject", ""))
    return out({"received": len(events), "indexer_runs": ran})
'''),
 b("Deploy the function and subscribe it to blob events", "Deploy it as its own Function App `facilities-ingest` (same four ARM steps as chapter 7), then wire the event path with `azure-mgmt-eventgrid`: a *system topic* on the storage account (Azure publishes storage events there) and an event subscription that delivers `BlobCreated` events to the function.",
   "deploy_ingest.py", '''
import io
import json
import zipfile
import requests
from azure.mgmt.eventgrid import EventGridManagementClient
from azure.mgmt.eventgrid.models import AzureFunctionEventSubscriptionDestination, EventSubscription, EventSubscriptionFilter, SystemTopic
from azure.mgmt.web import WebSiteManagementClient
from azure.mgmt.web.models import StringDictionary
from azlab import arm, rid, RG, LOC, ENDPOINT, HTTP_ENDPOINT
from azdata import search_endpoint, search_key

APP = "facilities-ingest"
web = arm(WebSiteManagementClient)
web.app_service_plans.begin_create_or_update(RG, APP + "-plan", {"location": LOC, "sku": {"name": "Y1", "tier": "Dynamic"}, "kind": "functionapp"}).result()
web.web_apps.begin_create_or_update(RG, APP, {"location": LOC, "kind": "functionapp,linux", "server_farm_id": rid("Microsoft.Web", "serverfarms", APP + "-plan")}).result()
web.web_apps.update_application_settings(RG, APP, StringDictionary(properties={
    "FUNCTIONS_WORKER_RUNTIME": "python", "SEARCH_ENDPOINT": search_endpoint().replace(ENDPOINT, HTTP_ENDPOINT, 1), "SEARCH_KEY": search_key(), "INDEXER_NAME": "docs-indexer"}))
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("host.json", json.dumps({"version": "2.0"}))
    z.writestr("on-blob/__init__.py", open("fn_ingest_docs.py").read())
    z.writestr("on-blob/function.json", json.dumps({"scriptFile": "__init__.py", "bindings": [
        {"authLevel": "function", "type": "httpTrigger", "direction": "in", "name": "req", "methods": ["get", "post"]}, {"type": "http", "direction": "out", "name": "$return"}]}))
requests.post(f"{ENDPOINT}/azure-data/functions/{APP}/api/zipdeploy", data=buf.getvalue(), timeout=60).raise_for_status()

eg = arm(EventGridManagementClient)
eg.system_topics.begin_create_or_update(RG, "facilitiesdocs-topic", SystemTopic(
    location=LOC, source=rid("Microsoft.Storage", "storageAccounts", "facilitiesdocs"), topic_type="Microsoft.Storage.StorageAccounts")).result()
sub = eg.system_topic_event_subscriptions.begin_create_or_update(RG, "facilitiesdocs-topic", "blob-created", EventSubscription(
    destination=AzureFunctionEventSubscriptionDestination(resource_id=rid("Microsoft.Web", "sites", APP) + "/functions/on-blob"),
    filter=EventSubscriptionFilter(included_event_types=["Microsoft.Storage.BlobCreated"]))).result()
print("function app", APP, "deployed; event subscription blob-created:", getattr(sub.provisioning_state, "value", sub.provisioning_state))
''', run="python deploy_ingest.py", expect="event subscription blob-created: Succeeded"),
 b("Upload a new document and watch it become searchable", "The whole pipeline end to end: upload a new SOP; Azure Storage raises `BlobCreated`; Event Grid calls the function; the function runs the indexer; the new text becomes searchable without you doing anything else. The script polls the search index for a random word that exists only in the new file.",
   "new_doc.py", '''
import time
import uuid
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.storage.blob import BlobServiceClient
from azdata import search_endpoint, search_key, storage_cs, INDEX

word = "zebrafish" + uuid.uuid4().hex[:6]
BlobServiceClient.from_connection_string(storage_cs("Blob")).get_blob_client("docs", "water-leak-sop.md").upload_blob(
    f"# SOP-205 Water leak\\nReport a {word} water leak in the lobby to facilities immediately.".encode(), overwrite=True)
sc = SearchClient(search_endpoint(), INDEX, AzureKeyCredential(search_key()))
found = []
for _ in range(45):
    found = [r["source"] for r in sc.search(search_text=word, select=["source"], top=3)]
    if found:
        break
    time.sleep(1)
print("new upload became searchable as:", found[0] if found else "NOT FOUND")
''', run="python new_doc.py", expect="new upload became searchable as: water-leak-sop.md"),
]
PIP13 = "pip install azure-core azure-mgmt-keyvault azure-keyvault-keys azure-mgmt-monitor cryptography azure-data-tables"

LAB[13] = [
 b("Install the libraries", "Chapter 13 protects and audits the app. Azure Key Vault holds a key (`azure-mgmt-keyvault` creates the vault, `azure-keyvault-keys` uses the key); you encrypt the sensitive approval record with envelope encryption; and the Azure Activity Log (`azure-mgmt-monitor`) is the audit trail of the control-plane operations the whole course performed. It needs the approval record from chapter 5 and uses `approval.py` and `azlab.py`.",
   "install13.sh", PIP13, lang="bash"),
 b("Create the Key Vault", "The vault `facilities-kv` through Azure Resource Manager, standard SKU, no access policies (the simulator does not enforce them: RBAC evaluation is simplified).",
   "create_vault.py", '''
from azure.mgmt.keyvault import KeyVaultManagementClient
from azure.mgmt.keyvault.models import Sku, SkuFamily, SkuName, VaultCreateOrUpdateParameters, VaultProperties
from azlab import arm, ensure_rg, RG, LOC

ensure_rg()
v = arm(KeyVaultManagementClient).vaults.begin_create_or_update(RG, "facilities-kv", VaultCreateOrUpdateParameters(location=LOC, properties=VaultProperties(
    tenant_id="00000000-0000-0000-0000-000000000000", sku=Sku(family=SkuFamily.A, name=SkuName.STANDARD), access_policies=[]))).result()
print("vault", v.name, "created; uri advertised by ARM:", v.properties.vault_uri)
''', run="python create_vault.py", expect="vault facilities-kv created"),
 b("Create the key", "`KeyClient.create_rsa_key` makes the 2048-bit RSA key `ledger-key`. On real Azure the vault address is `https://facilities-kv.vault.azure.net`. The simulator serves its vault API on its own https host, so the client is given that address and `verify_challenge_resource=False`, the documented option for vault hosts that are not `*.vault.azure.net` (private endpoints, sovereign clouds).",
   "make_key.py", '''
from azure.keyvault.keys import KeyClient
from azlab import DevToken, ENDPOINT

client = KeyClient(vault_url=ENDPOINT, credential=DevToken(), verify_challenge_resource=False)
key = client.create_rsa_key("ledger-key", size=2048)
print("key", key.name, "type", key.key.kty, "| listed:", [k.name for k in client.list_properties_of_keys()])
''', run="python make_key.py", expect="listed: ['ledger-key']"),
 b("Encrypt the approval record with envelope encryption", "Never encrypt data directly with a vault key: generate a random 256-bit data key (DEK), encrypt the record locally with AES-GCM (the approval ledger row from chapter 5 as the associated data is the table name), and ask Key Vault only to *wrap* the DEK. Store the wrapped DEK next to the ciphertext. To read it back, unwrap the DEK in the vault and decrypt locally. Rotating the vault key then never means re-encrypting the data. The last lines check a plain encrypt/decrypt round trip with the same key.",
   "envelope.py", '''
import os
from azure.keyvault.keys import KeyClient
from azure.keyvault.keys.crypto import CryptographyClient, EncryptionAlgorithm, KeyWrapAlgorithm
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from azlab import DevToken, ENDPOINT
from approval import ledger_row

row = ledger_row("req-demo0001")
record = f"ledger record: work order {row['work_order_id']} approved by {row['approver']}".encode()

kc = KeyClient(vault_url=ENDPOINT, credential=DevToken(), verify_challenge_resource=False)
crypto = CryptographyClient(kc.get_key("ledger-key").id, DevToken(), verify_challenge_resource=False)

dek = AESGCM.generate_key(bit_length=256)
nonce = os.urandom(12)
ciphertext = AESGCM(dek).encrypt(nonce, record, b"approvalledger")
wrapped = crypto.wrap_key(KeyWrapAlgorithm.rsa_oaep_256, dek).encrypted_key
print("the data key is wrapped by ledger-key; wrapped differs from the key:", wrapped != dek)

unwrapped = crypto.unwrap_key(KeyWrapAlgorithm.rsa_oaep_256, wrapped).key
print("unwrap + decrypt restores the record:", AESGCM(unwrapped).decrypt(nonce, ciphertext, b"approvalledger") == record)

sealed = crypto.encrypt(EncryptionAlgorithm.rsa_oaep_256, b"hello")
print("direct encrypt/decrypt round trip:", crypto.decrypt(EncryptionAlgorithm.rsa_oaep_256, sealed.ciphertext).plaintext == b"hello")
''', run="python envelope.py", expect="unwrap + decrypt restores the record: True"),
 b("Read the audit trail from the Activity Log", "Every create you ran in this course was a control-plane operation, and Azure records each one in the Activity Log. `activity_logs.list` takes an OData filter on time and resource group. The check looks for the vault and the function app you created.",
   "audit.py", '''
import time
from azure.mgmt.monitor import MonitorManagementClient
from azlab import arm, RG

since = time.strftime("%Y-%m-%dT00:00:00Z", time.gmtime(time.time() - 86400))
log = arm(MonitorManagementClient).activity_logs
events = list(log.list(filter=f"eventTimestamp ge '{since}'"))
ops = {e.operation_name.value for e in events if e.operation_name}
print("control-plane events:", len(events) > 0, "| vault create recorded:", "Microsoft.KeyVault/vaults/write" in ops, "| function app create recorded:", "Microsoft.Web/sites/write" in ops)
print("events for resource group", RG + ":", len(list(log.list(filter=f"eventTimestamp ge '{since}' and resourceGroupName eq '{RG}'"))) > 0)
''', run="python audit.py", expect="vault create recorded: True | function app create recorded: True"),
]


# Enterprise additions (hardening, failure labs, key rotation, tamper evidence, the ship-it capstone) live in labs_azure_ent.py and are appended here.
from .labs_azure_ent import extend  # noqa: E402

extend(LAB, b)
