import json

from google.cloud import aiplatform_v1 as av

import gcp

NAME = "facilities_memory"


def engine_name():
    service = gcp.rest(av.ReasoningEngineServiceClient)
    for e in service.list_reasoning_engines(request={"parent": gcp.PARENT}):
        if e.display_name == NAME:
            return e.name
    spec = {"instructions": "Facilities memory host.", "max_steps": 2, "tools": []}
    engine = av.ReasoningEngine(display_name=NAME, spec=av.ReasoningEngineSpec(
        deployment_spec=av.ReasoningEngineSpec.DeploymentSpec(env=[av.EnvVar(name="VYOMI_AGENT_SPEC", value=json.dumps(spec))])))
    return service.create_reasoning_engine(parent=gcp.PARENT, reasoning_engine=engine).result(timeout=60).name


if __name__ == "__main__":
    print("memory host:", engine_name())
