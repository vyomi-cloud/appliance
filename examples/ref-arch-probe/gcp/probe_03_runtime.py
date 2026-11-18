"""C3 Runtime: Vertex Agent Engine reasoningEngines create/get/list/query with the google-cloud-aiplatform gapic client (REST transport)."""
from _common import *
import json

s = Step()
P = PROJECT
parent = f"projects/{P}/locations/{LOC}"
SPEC = {"instructions": "You are a facilities agent.", "max_steps": 4, "tools": []}


def clients():
    from google.cloud import aiplatform_v1 as av
    return av, rest_client(av.ReasoningEngineServiceClient), rest_client(av.ReasoningEngineExecutionServiceClient)


def create_vyomi_spec():
    av, svc, ex = clients()
    eng = av.ReasoningEngine(display_name="facilities-agent", spec=av.ReasoningEngineSpec(
        deployment_spec=av.ReasoningEngineSpec.DeploymentSpec(env=[av.EnvVar(name="VYOMI_AGENT_SPEC", value=json.dumps(SPEC))])))
    res = svc.create_reasoning_engine(parent=parent, reasoning_engine=eng).result(timeout=60)
    s.name = res.name
    got = svc.get_reasoning_engine(name=res.name)
    assert got.display_name == "facilities-agent"
    return res.name


def create_real_shape():
    """What a real LangGraph/ADK app deploys: a packaged (pickled) class from GCS + class_methods. The simulator documents that this flow is unsupported."""
    av, svc, ex = clients()
    eng = av.ReasoningEngine(display_name="facilities-langgraph", spec=av.ReasoningEngineSpec(
        package_spec=av.ReasoningEngineSpec.PackageSpec(pickle_object_gcs_uri=f"gs://stage-{TAG}/agent.pkl", python_version="3.11",
                                                        requirements_gcs_uri=f"gs://stage-{TAG}/requirements.txt")))
    res = svc.create_reasoning_engine(parent=parent, reasoning_engine=eng).result(timeout=60)
    got = svc.get_reasoning_engine(name=res.name)
    # accepted as a control-plane record; can it execute?
    r = http().post(endpoint() + f"/v1/{res.name}:query", json={"classMethod": "query", "input": {"message": "hi"}})
    assert r.status_code == 200, f"package_spec engine cannot be queried: HTTP {r.status_code} {r.text[:200]}"
    return "executed"


def query():
    av, svc, ex = clients()
    r = http().post(endpoint() + f"/v1/{s.name}:query", json={"classMethod": "query", "input": {"message": "hello"}})
    if r.status_code in (502, 503) or "no model" in r.text.lower() or "backend" in r.text.lower() and r.status_code >= 500:
        raise Blocked(f"needs a model (HTTP {r.status_code}: {r.text[:200]}); request shape accepted up to model call")
    assert r.status_code == 200, f"HTTP {r.status_code} {r.text[:300]}"
    assert "output" in r.json(), r.text[:200]
    return r.text[:120]


s("create_reasoning_engine (Vyomi agent-spec in deploymentSpec.env) + get", create_vyomi_spec)
s("create_reasoning_engine with real-shaped package_spec (pickle from GCS) and query it", create_real_shape)
if hasattr(s, "name"):
    s("reasoningEngines:query on the spec engine (needs a model)", query)
s.finish()
