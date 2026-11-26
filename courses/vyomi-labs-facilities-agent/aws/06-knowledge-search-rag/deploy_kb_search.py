import io
import json
import os
import zipfile

import boto3

import rag_design

lam, ag = boto3.client("lambda"), boto3.client("bedrock-agent")
kb = next(k for k in ag.list_knowledge_bases()["knowledgeBaseSummaries"] if k["name"] == "facilities-kb")["knowledgeBaseId"]
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
    z.write("kb_search.py")
rr = rag_design.rerank()
DESIGN = {"RAG_TOP_K": str(rag_design.top_k()), "RAG_SEARCH_TYPE": rag_design.search_type(),        # your design becomes the tool's configuration
          "RAG_RERANK_TOP_N": str(rr["topN"] if rr["enabled"] else 0)}
lam.create_function(FunctionName="facilities-kb-search", Runtime="python3.12", Role="arn:aws:iam::123456789012:role/facilities-role",
                    Handler="kb_search.handler", Code={"ZipFile": buf.getvalue()}, Timeout=30,
                    Environment={"Variables": dict(DESIGN, KB_ID=kb, AWS_ENDPOINT_URL=os.environ["AWS_ENDPOINT_URL"],
                                                   AWS_DEFAULT_REGION=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))})
print("deployed facilities-kb-search")

r = lam.invoke(FunctionName="facilities-kb-search", Payload=json.dumps({"query": "boiler pressure limit"}).encode())
out = json.loads(r["Payload"].read())
print("tool returned", len(out["results"]), "cited results; first source:", out["results"][0]["source"])
