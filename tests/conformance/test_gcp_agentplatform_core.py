"""Agent Platform extras (core/gcp_agentplatform_core) through the shared wire router: RAG Engine, Vertex AI Search, memories, sessions,
evaluation, monitoring jobs.

Run: PYTHONPATH=. python3 tests/conformance/test_gcp_agentplatform_core.py
"""
import json, sys, base64
from core.aws_wire_router import AwsWireRouter
AwsWireRouter.STRICT_GCP_PROJECT=False
r=AwsWireRouter()
P="/v1/projects/demo/locations/us-central1"
def call(m,p,b=None,q=None):
    o=r.handle(m,p,q or {},{"content-type":"application/json"},json.dumps(b).encode() if b is not None else b"")
    try: return o["status"],json.loads(o["body"] or b"{}")
    except Exception: return o["status"],o["body"]
n=0
def ck(name,c,x=""):
    global n
    print(("ok  " if c else "FAIL"),name,"" if c else str(x)[:300]); n+= (not c)
s,o=call("POST",P+"/ragCorpora",{"displayName":"facilities"}); ck("corpus",s==200 and o["done"],o); cn=o["response"]["name"]
s,o=call("POST","/upload/v1/"+cn+"/ragFiles:upload",{"ragFile":{"displayName":"hvac.txt"},"text":"The chiller plant on level 3 is serviced every quarter. Boiler inspection happens in October. Elevator maintenance contract renews in March."}); ck("upload",s==200,o)
s,o=call("POST",P+":retrieveContexts",{"query":{"text":"when is the boiler inspected","ragRetrievalConfig":{"topK":2}},"vertexRagStore":{"ragResources":[{"ragCorpus":cn}]}}); ck("retrieve",s==200 and "Boiler" in json.dumps(o),o)
s,o=call("GET","/v1/"+cn+"/ragFiles"); ck("files",len(o.get("ragFiles",[]))==1,o)
s,o=call("POST",P+":evaluateInstances",{"exactMatchInput":{"instances":[{"prediction":"a","reference":"a"},{"prediction":"a","reference":"b"}]}}); ck("exact",o["exactMatchResults"]["exactMatchMetricValues"][0]["score"]==1.0,o)
s,o=call("POST",P+":evaluateInstances",{"rougeInput":{"metricSpec":{"rougeType":"rougeL"},"instances":[{"prediction":"the cat sat","reference":"the cat sat down"}]}}); ck("rouge",s==200 and 0.5<o["rougeResults"]["rougeMetricValues"][0]["score"]<1,o)
s,o=call("POST",P+"/evaluationRuns",{"displayName":"e1","metrics":["bleu","rouge"],"dataset":{"rows":[{"prompt":"x","response":"hello world","reference":"hello world"}]}}); ck("evalrun",s==200 and o["summary"]["bleu"]>0.9,o)
s,o=call("GET",P+"/evaluationRuns"); ck("evallist",len(o["evaluationRuns"])==1,o)
D="/v1/projects/demo/locations/global/collections/default_collection"
s,o=call("POST",D+"/dataStores",{"displayName":"docs","industryVertical":"GENERIC","contentConfig":"CONTENT_REQUIRED"},{"dataStoreId":"docs"}); ck("ds",s==200,o)
s,o=call("POST",D+"/dataStores/docs/branches/default_branch/documents:import",{"inlineSource":{"documents":[{"id":"1","structData":{"title":"Boiler manual","body":"inspect the boiler yearly"}},{"id":"2","structData":{"title":"Lift","body":"elevator service"}}]}}); ck("import",s==200,o)
s,o=call("POST",D+"/dataStores/docs/servingConfigs/default_search:search",{"query":"boiler"}); ck("search",o["totalSize"]==1 and o["results"][0]["id"]=="1",o)
s,o=call("POST",D+"/engines",{"displayName":"app","dataStoreIds":["docs"],"solutionType":"SOLUTION_TYPE_SEARCH"},{"engineId":"app"}); ck("engine",s==200,o)
s,o=call("POST",D+"/engines/app/servingConfigs/default_search:search",{"query":"elevator"}); ck("engsearch",o["totalSize"]==1,o)
# agent engine child
s,o=call("POST",P+"/reasoningEngines",{"displayName":"ae"}); en=o["response"]["name"]
s,o=call("POST","/v1beta1/"+en+"/sessions",{"userId":"u1"}); ck("sess",s==200 and o["done"],o)
s,o=call("GET","/v1beta1/"+en+"/sessions"); ck("sesslist",len(o["sessions"])==1,o)
s,o=call("POST","/v1beta1/"+en+"/memories",{"fact":"User prefers level 3 chiller reports","scope":{"user_id":"u1"}}); ck("mem",s==200,o)
s,o=call("POST","/v1beta1/"+en+"/memories:retrieve",{"scope":{"user_id":"u1"},"similaritySearchParams":{"searchQuery":"chiller","topK":1}}); ck("memret",len(o["retrievedMemories"])==1,o)
s,o=call("GET","/v1beta1/"+en+"/memories"); ck("memlist",len(o["memories"])==1,o)
# monitoring
s,o=call("POST",P+"/endpoints",{"displayName":"e"}); epn=o["response"]["name"]
s,o=call("POST",P+"/modelDeploymentMonitoringJobs",{"displayName":"m","endpoint":epn}); ck("mon",s==200,o); mn=o["name"]
import time; time.sleep(2.2)
s,o=call("GET","/v1/"+mn); ck("monrun",o["state"]=="JOB_STATE_RUNNING",o)
s,o=call("POST","/v1/"+mn+":pause",{}); ck("pause",s==200,o)
s,o=call("GET","/v1/"+mn); ck("paused",o["state"]=="JOB_STATE_PAUSED",o)
s,o=call("POST","/v1/"+mn+":resume",{}); s,o=call("GET","/v1/"+mn); ck("resumed",o["state"]=="JOB_STATE_RUNNING",o)
s,o=call("DELETE","/v1/"+cn); ck("delcorp",s==200,o)
print("FAILS", n)
sys.exit(1 if n else 0)
