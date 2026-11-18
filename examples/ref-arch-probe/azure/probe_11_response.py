"""Component 11 Response: grounded answer with citations (Assistants file_search / on-your-data) + output content filter."""
from _common import *

P = Probe(11, "response", "Response: grounded cited answer + output filter")
B = endpoint(); ensure_rg(B); ensure_openai(B)
S = {}


def vector_store():
    oc = aoai(B, "2025-03-01-preview"); S["oc"] = oc
    vs = oc.vector_stores.create(name="kb")
    f = oc.files.create(file=("policy.txt", b"Approvals above 500 dollars need a manager sign off. Water leaks are reported to facilities."), purpose="assistants")
    oc.vector_stores.files.create(vs.id, file_id=f.id)
    S["vs"] = vs
    return vs.id


def vs_list_files():
    fs = S["oc"].vector_stores.files.list(S["vs"].id).data
    assert fs, "no files"


def agent_file_search():
    oc = S["oc"]
    a = oc.beta.assistants.create(model="chat", instructions="Answer only from the files.", tools=[{"type": "file_search"}], tool_resources={"file_search": {"vector_store_ids": [S["vs"].id]}})
    th = oc.beta.threads.create(messages=[{"role": "user", "content": "Who must approve 900 dollars?"}])
    r = oc.beta.threads.runs.create(th.id, assistant_id=a.id)
    S["th"], S["run"] = th, r
    assert r.status == "completed", f"run {r.status}: {getattr(r.last_error, 'message', '')[:140]}"


def citations():
    ms = S["oc"].beta.threads.messages.list(S["th"].id).data
    ann = [x for m in ms if m.role == "assistant" for c in m.content for x in c.text.annotations]
    assert ann and ann[0].type == "file_citation", ann


def run_steps_retrieval():
    steps = S["oc"].beta.threads.runs.steps.list(S["run"].id, thread_id=S["th"].id).data
    assert steps


def on_your_data():
    """Chat completions 'On Your Data' with an Azure AI Search data source."""
    r = S["oc"].chat.completions.create(model="chat", messages=[{"role": "user", "content": "approval rule?"}], extra_body={"data_sources": [{"type": "azure_search", "parameters": {
        "endpoint": B, "index_name": "kb", "authentication": {"type": "api_key", "key": "k"}}}]})
    assert getattr(r.choices[0].message, "context", None) or r.choices[0].message.content


def output_filter():
    """Output-side filter: a deployment bound to a policy with Source=Completion blocks, and finish_reason=content_filter is surfaced."""
    from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient
    c = arm(CognitiveServicesManagementClient, B)
    p = c.rai_policies.create_or_update(RG, "aoai1", "outp", {"properties": {"mode": "Blocking", "basePolicyName": "Microsoft.Default",
        "contentFilters": [{"name": "Violence", "severityThreshold": "Low", "blocking": True, "enabled": True, "source": "Completion"}]}})
    assert p.name == "outp"
    d = c.deployments.get(RG, "aoai1", "chat")
    return "output-source policy accepted; enforcement on a completion needs a model"


P.step("vector store + file upload + file attach (openai SDK)", vector_store)
P.step("vector store file list", vs_list_files)
P.step("assistant with file_search runs against the vector store (needs a model)", agent_file_search, blocked="no model")
P.step("assistant message carries file_citation annotations (needs a model)", citations, blocked="no model")
P.step("run steps list shows retrieval step (needs a model)", run_steps_retrieval, blocked="no model")
P.step("chat completions On Your Data (azure_search data source) (needs a model)", on_your_data, blocked="no model")
P.step("output (Completion-source) content filter policy accepted by ARM", output_filter)
P.finish()
