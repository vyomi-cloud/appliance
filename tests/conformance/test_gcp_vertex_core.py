"""Vertex AI control plane (core/gcp_vertex_core) through the shared wire router (= Nano / offline ingress).

Run: PYTHONPATH=. python3 tests/conformance/test_gcp_vertex_core.py
"""
import json
import sys
import time

from core import ai_model_catalog as CAT
from core.aws_wire_router import AwsWireRouter

AwsWireRouter.STRICT_GCP_PROJECT = False   # engine test: ad-hoc project ids
r = AwsWireRouter()
PASS = FAIL = 0
P = "/v1/projects/demo/locations/us-central1"


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {str(extra)[:300]}")


def call(method, path, body=None, query=None):
    o = r.handle(method, path, query or {}, {"content-type": "application/json"}, json.dumps(body).encode() if body is not None else b"")
    try:
        return o["status"], json.loads(o["body"] or b"{}")
    except Exception:
        return o["status"], {"raw": o["body"]}


def resp(op):
    return op.get("response", {})


# Model Garden
st, b = call("GET", "/v1/publishers/-/models")
check("Model Garden lists exactly the ten pool models", st == 200 and sorted(m["name"].split("/")[-1] for m in b["publisherModels"]) == sorted(CAT.IDS), b)
check("Model Garden availability: only the local small model without a booster", {m["name"].split("/")[-1] for m in b["publisherModels"] if m["vyomiAvailability"]["available"]} == {"qwen2.5-3b"})
st, b = call("GET", "/v1/publishers/qwen/models/qwen2.5-7b")
check("Model Garden get", st == 200 and b["launchStage"] == "GA" and b["vyomiAvailability"]["label"] == "Needs Booster (Pro/Max)", b)
check("Model Garden has no gemini/claude entries", call("GET", "/v1/publishers/google/models/gemini-2.5-pro")[0] == 404 and call("GET", "/v1/publishers/anthropic/models")[1]["publisherModels"] == [])
check("Model Garden unknown -> 404", call("GET", "/v1/publishers/google/models/nope")[0] == 404)

# Models, endpoints, deploy
st, op = call("POST", f"{P}/models:upload", {"model": {"displayName": "m1", "artifactUri": "gs://b/m"}})
check("models:upload -> done LRO", st == 200 and op["done"] and resp(op)["name"].startswith("projects/demo/locations/us-central1/models/"), op)
mname = resp(op)["name"]
st, _ = call("POST", f"{P}/models:upload", {"model": {}})
check("model without displayName -> INVALID_ARGUMENT", st == 400)
st, op = call("POST", f"{P}/endpoints", {"displayName": "ep1"}, {"endpointId": "ep1"})
check("endpoint create", st == 200 and resp(op)["name"].endswith("/endpoints/ep1"), op)
check("duplicate endpoint -> 409", call("POST", f"{P}/endpoints", {"displayName": "x"}, {"endpointId": "ep1"})[0] == 409)
st, op = call("POST", f"{P}/endpoints/ep1:deployModel", {"deployedModel": {"model": mname}})
check("deployModel", st == 200 and resp(op)["deployedModel"]["id"], op)
did = resp(op)["deployedModel"]["id"]
st, ep = call("GET", f"{P}/endpoints/ep1")
check("endpoint lists deployedModels + traffic 100", ep["deployedModels"][0]["id"] == did and ep["trafficSplit"] == {did: 100}, ep)
check("model knows its endpoint", call("GET", mname_path := "/v1/" + mname)[1]["deployedModels"][0]["endpoint"].endswith("/endpoints/ep1"))
check("custom predict is honestly 501", call("POST", f"{P}/endpoints/ep1:predict", {"instances": [1]})[0] == 501)
check("deploy unknown model -> 404", call("POST", f"{P}/endpoints/ep1:deployModel", {"deployedModel": {"model": P[1:] + "/models/zz"}})[0] == 404)
check("undeployModel", call("POST", f"{P}/endpoints/ep1:undeployModel", {"deployedModelId": did})[0] == 200
      and call("GET", f"{P}/endpoints/ep1")[1]["deployedModels"] == [])
st, b = call("GET", f"{P}/endpoints")
check("endpoints list", st == 200 and len(b["endpoints"]) == 1)
check("delete endpoint -> LRO then 404", call("DELETE", f"{P}/endpoints/ep1")[1]["done"] and call("GET", f"{P}/endpoints/ep1")[0] == 404)
check("delete model", call("DELETE", "/v1/" + mname)[0] == 200 and call("GET", "/v1/" + mname)[0] == 404)

call("POST", "/v1/projects/demo/locations/europe-west4/endpoints", {"displayName": "eu"}, {"endpointId": "eu1"})
check("list across all locations with '-'", {e["name"].split("/")[3] for e in call("GET", "/v1/projects/demo/locations/-/endpoints")[1]["endpoints"]} == {"europe-west4"}, call("GET", "/v1/projects/demo/locations/-/endpoints"))

# Datasets
st, op = call("POST", f"{P}/datasets", {"displayName": "ds", "metadataSchemaUri": "gs://x/tables.yaml"})
check("dataset create+list+delete", st == 200 and len(call("GET", f"{P}/datasets")[1]["datasets"]) == 1)
call("DELETE", "/v1/" + resp(op)["name"])
check("dataset deleted", call("GET", f"{P}/datasets")[1].get("datasets", []) == [])

# Jobs lifecycle
st, tp = call("POST", f"{P}/trainingPipelines", {"displayName": "tp", "modelToUpload": {"displayName": "trained"}, "trainingTaskDefinition": "x"})
check("trainingPipeline create PENDING", st == 200 and tp["state"] == "PIPELINE_STATE_PENDING", tp)
st, cj = call("POST", f"{P}/customJobs", {"displayName": "cj", "jobSpec": {"workerPoolSpecs": [{"machineSpec": {"machineType": "n1-standard-4"}, "replicaCount": "1"}]}})
check("customJob create", st == 200 and cj["state"] == "JOB_STATE_PENDING")
check("customJob without workerPoolSpecs -> 400", call("POST", f"{P}/customJobs", {"displayName": "x", "jobSpec": {}})[0] == 400)
st, bj = call("POST", f"{P}/batchPredictionJobs", {"displayName": "bp", "model": "m", "outputConfig": {"gcsDestination": {"outputUriPrefix": "gs://o/out"}}})
check("batch job cancel", call("POST", "/v1/" + bj["name"] + ":cancel", {})[0] == 200 and call("GET", "/v1/" + bj["name"])[1]["state"] == "JOB_STATE_CANCELLED")
check("cancel terminal job -> 400", call("POST", "/v1/" + bj["name"] + ":cancel", {})[0] == 400)
store = r.gcp_vertex
for rec in store.res.values():   # age the jobs instead of sleeping
    if "_t0" in rec:
        rec["_t0"] -= 10
st, tp2 = call("GET", "/v1/" + tp["name"])
check("pipeline SUCCEEDED and registered its model", tp2["state"] == "PIPELINE_STATE_SUCCEEDED" and "/models/" in tp2["modelToUpload"]["name"], tp2)
check("trained model exists in registry", call("GET", "/v1/" + tp2["modelToUpload"]["name"])[0] == 200)
check("customJob SUCCEEDED", call("GET", "/v1/" + cj["name"])[1]["state"] == "JOB_STATE_SUCCEEDED")
check("jobs list", len(call("GET", f"{P}/customJobs")[1]["customJobs"]) == 1)
check("delete job", call("DELETE", "/v1/" + cj["name"])[0] == 200)

# Vector Search
st, op = call("POST", f"{P}/indexes", {"displayName": "ix", "metadata": {"config": {"dimensions": 2, "distanceMeasureType": "DOT_PRODUCT_DISTANCE"}}})
iname = resp(op)["name"]
check("index create", st == 200 and iname)
check("index without dimensions -> 400", call("POST", f"{P}/indexes", {"displayName": "bad", "metadata": {}})[0] == 400)
check("upsert datapoints", call("POST", "/v1/" + iname + ":upsertDatapoints", {"datapoints": [
    {"datapointId": "a", "featureVector": [1, 0]}, {"datapointId": "b", "featureVector": [0, 1]}, {"datapointId": "c", "featureVector": [0.9, 0.1]}]})[0] == 200)
check("wrong-dim datapoint -> 400", call("POST", "/v1/" + iname + ":upsertDatapoints", {"datapoints": [{"datapointId": "z", "featureVector": [1]}]})[0] == 400)
check("index stats", call("GET", "/v1/" + iname)[1]["indexStats"]["vectorsCount"] == "3")
st, op = call("POST", f"{P}/indexEndpoints", {"displayName": "ie"})
ie = resp(op)["name"]
check("deployIndex", call("POST", "/v1/" + ie + ":deployIndex", {"deployedIndex": {"id": "dep1", "index": iname}})[0] == 200)
st, nn = call("POST", "/v1/" + ie + ":findNeighbors", {"deployedIndexId": "dep1", "queries": [{"datapoint": {"featureVector": [1, 0]}, "neighborCount": 2}]})
check("findNeighbors ranks by dot product", st == 200 and [n["datapoint"]["datapointId"] for n in nn["nearestNeighbors"][0]["neighbors"]] == ["a", "c"], nn)
call("POST", "/v1/" + iname + ":removeDatapoints", {"datapointIds": ["a"]})
st, nn = call("POST", "/v1/" + ie + ":findNeighbors", {"deployedIndexId": "dep1", "queries": [{"datapoint": {"featureVector": [1, 0]}, "neighborCount": 1}]})
check("removeDatapoints takes effect", nn["nearestNeighbors"][0]["neighbors"][0]["datapoint"]["datapointId"] == "c")

# Feature store
st, op = call("POST", f"{P}/featureGroups", {"bigQuery": {"bigQuerySource": {"inputUri": "bq://p.d.t"}}}, {"featureGroupId": "fg1"})
check("featureGroup create", st == 200)
check("feature under group", call("POST", f"{P}/featureGroups/fg1/features", {"description": "d"}, {"featureId": "f1"})[0] == 200
      and len(call("GET", f"{P}/featureGroups/fg1/features")[1]["features"]) == 1)
check("feature under missing group -> 404", call("POST", f"{P}/featureGroups/nope/features", {}, {"featureId": "f"})[0] == 404)
check("featureOnlineStore + view", call("POST", f"{P}/featureOnlineStores", {"optimized": {}}, {"featureOnlineStoreId": "fos"})[0] == 200
      and call("POST", f"{P}/featureOnlineStores/fos/featureViews", {}, {"featureViewId": "fv"})[0] == 200)

# Experiments / metadata / tensorboard
check("default metadata store listed", len(call("GET", f"{P}/metadataStores")[1]["metadataStores"]) >= 1)
st, c = call("POST", f"{P}/metadataStores/default/contexts", {"displayName": "exp1", "schemaTitle": "system.Experiment"}, {"contextId": "exp1"})
check("experiment (context) create", st == 200 and c["name"].endswith("/metadataStores/default/contexts/exp1"), c)
check("experiment list filter", len(call("GET", f"{P}/metadataStores/default/contexts", query={"filter": 'schema_title="system.Experiment"'})[1]["contexts"]) == 1)
st, op = call("POST", f"{P}/tensorboards", {"displayName": "tb"})
tb = resp(op)["name"]
check("tensorboard experiment + run", call("POST", "/v1/" + tb + "/experiments", {"displayName": "e"}, {"tensorboardExperimentId": "e1"})[0] == 200
      and call("POST", "/v1/" + tb + "/experiments/e1/runs", {"displayName": "r"}, {"tensorboardRunId": "r1"})[0] == 200)

# Notebooks
st, op = call("POST", "/v1/projects/demo/locations/us-central1/notebookRuntimeTemplates", {"displayName": "t", "machineSpec": {"machineType": "e2-standard-4"}})
check("colab runtime template", st == 200)
W = "/v2/projects/demo/locations/us-central1-a/instances"
st, op = call("POST", W, {"gceSetup": {"machineType": "n1-standard-4"}}, {"instanceId": "wb1"})
check("workbench instance create (v2)", st == 200 and resp(op)["state"] == "ACTIVE", op)
check("workbench stop/start", call("POST", W + "/wb1:stop", {})[0] == 200 and call("GET", W + "/wb1")[1]["state"] == "STOPPED"
      and call("POST", W + "/wb1:start", {})[0] == 200 and call("GET", W + "/wb1")[1]["state"] == "ACTIVE")
check("workbench list+delete", len(call("GET", W)[1]["instances"]) == 1 and call("DELETE", W + "/wb1")[0] == 200 and call("GET", W + "/wb1")[0] == 404)
check("operation get", call("GET", "/v1/" + op["name"])[0] == 200)

# Publisher model path still reaches the Gemini adapter
st, b = call("POST", f"{P}/publishers/google/models/gemini-2.0-flash:countTokens", {"contents": [{"role": "user", "parts": [{"text": "12345678"}]}]})
check("publisher countTokens still routes to ai_models_core", st == 200 and b["totalTokens"] == 2, b)

print(f"{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
