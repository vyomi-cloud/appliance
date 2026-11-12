"""Bedrock Agents + Knowledge Bases (S3 docs, embed seam) + AgentCore control plane / gateway MCP, via AwsWireRouter.

Run: PYTHONPATH=. ../appliance/.venv/bin/python tests/conformance/test_bedrock_agents_core.py
"""
import base64
import json

from core import llm_core as llm
from core import s3_object_core as s3c
from core.aws_wire_router import AwsWireRouter

BR = "AWS4-HMAC-SHA256 Credential=T/20261104/us-east-1/bedrock/aws4_request, SignedHeaders=host, Signature=0"
AC = "AWS4-HMAC-SHA256 Credential=T/20261104/us-east-1/bedrock-agentcore/aws4_request, SignedHeaders=host, Signature=0"
LAM = "AWS4-HMAC-SHA256 Credential=T/20261104/us-east-1/lambda/aws4_request, SignedHeaders=host, Signature=0"
ROLE = "arn:aws:iam::123456789012:role/r"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def call(r, auth, method, path, payload=None, query=None):
    out = r.handle(method, path, query or {}, {"authorization": auth, "content-type": "application/json"}, json.dumps(payload).encode() if payload is not None else b"")
    b = out["body"]
    try:
        doc = json.loads(b) if b else {}
    except ValueError:
        doc = {}
    return out["status"], doc, out


def main():
    llm.set_backend(lambda msgs, system, mt, temp, stop: {"text": "ANSWER based on: " + (msgs[-1]["content"][:60] if msgs else "")})
    r = AwsWireRouter()
    # ---- S3 docs
    s3c.dispatch(r.s3, "PUT", "/kbdocs", {}, {}, b"")
    for k, v in {"docs/refunds.txt": "Refunds are processed within fourteen days of the return request. Contact billing for refund status.",
                 "docs/shipping.md": "Shipping to Europe takes five business days with tracked courier delivery and customs paperwork.",
                 "docs/manual.pdf": "%PDF-1.4 binary"}.items():
        s3c.dispatch(r.s3, "PUT", f"/kbdocs/{k}", {}, {}, v.encode())

    # ---- knowledge base
    emb = "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0"
    kbp = {"name": "support-kb", "roleArn": ROLE, "knowledgeBaseConfiguration": {"type": "VECTOR", "vectorKnowledgeBaseConfiguration": {"embeddingModelArn": emb}},
           "storageConfiguration": {"type": "OPENSEARCH_SERVERLESS"}}
    s, o, _ = call(r, BR, "PUT", "/knowledgebases/", kbp)
    kid = o["knowledgeBase"]["knowledgeBaseId"]
    _check("create KB", s == 202 and o["knowledgeBase"]["knowledgeBaseArn"].endswith(f":knowledge-base/{kid}") and len(kid) == 10)
    _check("dup KB 409", call(r, BR, "PUT", "/knowledgebases/", kbp)[0] == 409)
    _check("bad embedding model 400", call(r, BR, "PUT", "/knowledgebases/", {**kbp, "name": "k2", "knowledgeBaseConfiguration": {"type": "VECTOR", "vectorKnowledgeBaseConfiguration": {"embeddingModelArn": "arn:x/foo"}}})[0] == 400)
    _check("list KBs", call(r, BR, "POST", "/knowledgebases/", {})[1]["knowledgeBaseSummaries"][0]["name"] == "support-kb")
    _check("get missing KB 404", call(r, BR, "GET", "/knowledgebases/NOPE000000")[0] == 404)
    s, o, _ = call(r, BR, "PUT", f"/knowledgebases/{kid}/datasources/", {"name": "s3src", "dataSourceConfiguration": {"type": "S3", "s3Configuration": {"bucketArn": "arn:aws:s3:::kbdocs", "inclusionPrefixes": ["docs/"]}},
                                                                         "vectorIngestionConfiguration": {"chunkingConfiguration": {"chunkingStrategy": "FIXED_SIZE", "fixedSizeChunkingConfiguration": {"maxTokens": 12, "overlapPercentage": 20}}}})
    did = o["dataSource"]["dataSourceId"]
    _check("create data source", s == 202)
    _check("non-S3 data source 400", call(r, BR, "PUT", f"/knowledgebases/{kid}/datasources/", {"name": "w", "dataSourceConfiguration": {"type": "WEB"}})[0] == 400)
    s, o, _ = call(r, BR, "PUT", f"/knowledgebases/{kid}/datasources/{did}/ingestionjobs/", {})
    st_ = o["ingestionJob"]["statistics"]
    _check("ingestion scanned 3, indexed 2, failed 1 (pdf)", st_["numberOfDocumentsScanned"] == 3 and st_["numberOfNewDocumentsIndexed"] == 2 and st_["numberOfDocumentsFailed"] == 1)
    _check("failure reason names pdf", "manual.pdf" in o["ingestionJob"]["failureReasons"][0])
    jid = o["ingestionJob"]["ingestionJobId"]
    _check("get ingestion job", call(r, BR, "GET", f"/knowledgebases/{kid}/datasources/{did}/ingestionjobs/{jid}")[1]["ingestionJob"]["status"] == "COMPLETE")

    s, o, _ = call(r, BR, "POST", f"/knowledgebases/{kid}/retrieve", {"retrievalQuery": {"text": "how long do refunds take"}, "retrievalConfiguration": {"vectorSearchConfiguration": {"numberOfResults": 2}}})
    top = o["retrievalResults"][0]
    _check("retrieve top hit is the refunds doc", s == 200 and top["location"]["s3Location"]["uri"] == "s3://kbdocs/docs/refunds.txt" and top["score"] > 0 and len(o["retrievalResults"]) == 2)
    s, o, _ = call(r, BR, "POST", f"/knowledgebases/{kid}/retrieve", {"retrievalQuery": {"text": "courier delivery to europe"}, "retrievalConfiguration": {"vectorSearchConfiguration": {"numberOfResults": 1}}})
    _check("retrieve routes to shipping doc", o["retrievalResults"][0]["location"]["s3Location"]["uri"].endswith("shipping.md"))
    _check("retrieve empty query 400", call(r, BR, "POST", f"/knowledgebases/{kid}/retrieve", {"retrievalQuery": {"text": ""}})[0] == 400)
    s, o, _ = call(r, BR, "POST", "/retrieveAndGenerate", {"input": {"text": "refund time?"}, "retrieveAndGenerateConfiguration": {"type": "KNOWLEDGE_BASE", "knowledgeBaseConfiguration": {"knowledgeBaseId": kid, "modelArn": "amazon.nova-lite-v1:0"}}})
    _check("retrieveAndGenerate answer + citations", s == 200 and o["output"]["text"].startswith("ANSWER") and o["citations"][0]["retrievedReferences"])

    # ---- agent
    ap = {"agentName": "support-agent", "foundationModel": "amazon.nova-lite-v1:0", "agentResourceRoleArn": ROLE, "instruction": "You are a helpful support agent for an online store. Be concise."}
    s, o, _ = call(r, BR, "PUT", "/agents/", ap)
    aid = o["agent"]["agentId"]
    _check("create agent NOT_PREPARED", s == 202 and o["agent"]["agentStatus"] == "NOT_PREPARED" and o["agent"]["agentVersion"] == "DRAFT")
    _check("short instruction 400", call(r, BR, "PUT", "/agents/", {**ap, "agentName": "a2", "instruction": "short"})[0] == 400)
    _check("bad model 400", call(r, BR, "PUT", "/agents/", {**ap, "agentName": "a3", "foundationModel": "nope.model"})[0] == 400)
    _check("alias before prepare 409", call(r, BR, "PUT", f"/agents/{aid}/agentaliases/", {"agentAliasName": "live"})[0] == 409)
    s, o, _ = call(r, BR, "PUT", f"/agents/{aid}/agentversions/DRAFT/knowledgebases/", {"knowledgeBaseId": kid, "description": "store policies"})
    _check("associate KB", s == 200 and o["agentKnowledgeBase"]["knowledgeBaseState"] == "ENABLED")
    s, o, _ = call(r, BR, "PUT", f"/agents/{aid}/agentversions/DRAFT/agentactiongroups/", {"actionGroupName": "orders"})
    _check("action group stored", s == 200)
    s, o, _ = call(r, BR, "POST", f"/agents/{aid}/")
    _check("prepare", s == 202 and call(r, BR, "GET", f"/agents/{aid}/")[1]["agent"]["agentStatus"] == "PREPARED")
    s, o, _ = call(r, BR, "PUT", f"/agents/{aid}/agentaliases/", {"agentAliasName": "live"})
    alias = o["agentAlias"]["agentAliasId"]
    _check("create alias -> version 1", s == 202 and o["agentAlias"]["routingConfiguration"][0]["agentVersion"] == "1")
    s, o, raw = call(r, BR, "POST", f"/agents/{aid}/agentAliases/{alias}/sessions/sess-1/text", {"inputText": "How long do refunds take?"})
    body = raw["body"]
    payload = json.loads(body[body.index(b"{"):body.rindex(b"}") + 1])
    _check("InvokeAgent returns eventstream chunk with answer", s == 200 and base64.b64decode(payload["bytes"]).startswith(b"ANSWER") and payload.get("attribution"))
    _check("TSTALIASID invokes draft", call(r, BR, "POST", f"/agents/{aid}/agentAliases/TSTALIASID/sessions/s2/text", {"inputText": "hi"})[0] == 200)
    _check("unknown alias 404", call(r, BR, "POST", f"/agents/{aid}/agentAliases/ZZZZZZZZZZ/sessions/s/text", {"inputText": "hi"})[0] == 404)
    _check("delete agent with alias 409", call(r, BR, "DELETE", f"/agents/{aid}/")[0] == 409)
    _check("list agents", call(r, BR, "GET", "/agents/")[1]["agentSummaries"][0]["agentName"] == "support-agent")
    llm.set_backend()
    import os
    os.environ["VYOMI_LLM_DISABLE"] = "1"
    s, o, _ = call(r, BR, "POST", f"/agents/{aid}/agentAliases/TSTALIASID/sessions/s3/text", {"inputText": "hi"})
    _check("no model -> 424 DependencyFailed (no canned answer)", s == 424)
    del os.environ["VYOMI_LLM_DISABLE"]
    llm.set_backend(lambda *a: "ok")
    _check("delete alias + agent", call(r, BR, "DELETE", f"/agents/{aid}/agentaliases/{alias}/")[0] == 202 and call(r, BR, "DELETE", f"/agents/{aid}/")[0] == 202)
    _check("delete KB", call(r, BR, "DELETE", f"/knowledgebases/{kid}")[0] == 202)
    _check("existing model catalogue still routed", call(r, BR, "GET", "/foundation-models")[0] == 200)

    # ---- AgentCore
    s, o, _ = call(r, AC, "POST", "/runtimes/", {"agentRuntimeName": "my_agent", "agentRuntimeArtifact": {"containerConfiguration": {"containerUri": "123456789012.dkr.ecr.us-east-1.amazonaws.com/a:1"}}, "roleArn": ROLE, "networkConfiguration": {"networkMode": "PUBLIC"}})
    rid = o["agentRuntimeId"]
    _check("create runtime CREATING", s == 202 and o["status"] == "CREATING" and o["agentRuntimeArn"].endswith(f":runtime/{rid}"))
    _check("bad runtime name 400", call(r, AC, "POST", "/runtimes/", {"agentRuntimeName": "1bad", "agentRuntimeArtifact": {}, "roleArn": ROLE})[0] == 400)
    _check("dup runtime 409", call(r, AC, "POST", "/runtimes/", {"agentRuntimeName": "my_agent", "agentRuntimeArtifact": {"containerConfiguration": {"containerUri": "x"}}, "roleArn": ROLE, "networkConfiguration": {"networkMode": "PUBLIC"}})[0] == 409)
    import time
    time.sleep(1.1)
    _check("runtime READY after a moment", call(r, AC, "GET", f"/runtimes/{rid}/")[1]["status"] == "READY")
    _check("list runtimes", call(r, AC, "GET", "/runtimes/")[1]["agentRuntimes"][0]["agentRuntimeName"] == "my_agent")
    s, o, _ = call(r, AC, "POST", f"/runtimes/{rid}/invocations", {"prompt": "hi"})
    _check("invoke runtime honest 424", s == 424)

    s, o, _ = call(r, AC, "POST", "/gateways/", {"name": "tools-gw", "roleArn": ROLE, "protocolType": "MCP", "authorizerType": "NONE"})
    gid = o["gatewayId"]
    _check("create gateway", s == 202 and o["gatewayUrl"].endswith("/mcp") and gid.startswith("tools-gw-"))
    _check("jwt gateway needs discovery url 400", call(r, AC, "POST", "/gateways/", {"name": "g2", "roleArn": ROLE, "authorizerType": "CUSTOM_JWT"})[0] == 400)
    # a lambda to expose as a tool
    code = "def handler(event, context):\n    return {'sum': event['a'] + event['b']}\n"
    import io, zipfile
    zb = io.BytesIO()
    with zipfile.ZipFile(zb, "w") as z:
        z.writestr("index.py", code)
    s, o, _ = call(r, LAM, "POST", "/2015-03-31/functions", {"FunctionName": "adder", "Runtime": "python3.12", "Role": ROLE, "Handler": "index.handler", "Code": {"ZipFile": base64.b64encode(zb.getvalue()).decode()}})
    larn = o.get("FunctionArn") or "arn:aws:lambda:us-east-1:123456789012:function:adder"
    tcfg = {"mcp": {"lambda": {"lambdaArn": larn, "toolSchema": {"inlinePayload": [{"name": "add", "description": "Add two numbers", "inputSchema": {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}}}]}}}}
    s, o, _ = call(r, AC, "POST", f"/gateways/{gid}/targets/", {"name": "calc", "targetConfiguration": tcfg})
    tid = o["targetId"]
    _check("create lambda target", s == 202 and o["status"] == "CREATING")
    _check("target without tool schema 400", call(r, AC, "POST", f"/gateways/{gid}/targets/", {"name": "t2", "targetConfiguration": {"mcp": {"lambda": {"lambdaArn": larn}}}})[0] == 400)
    _check("openapi target needs credentials 400", call(r, AC, "POST", f"/gateways/{gid}/targets/", {"name": "t3", "targetConfiguration": {"mcp": {"openApiSchema": {}}}})[0] == 400)
    time.sleep(1.1)
    _check("target READY", call(r, AC, "GET", f"/gateways/{gid}/targets/{tid}/")[1]["status"] == "READY")
    _check("list targets", len(call(r, AC, "GET", f"/gateways/{gid}/targets/")[1]["items"]) == 1)
    _check("gateway READY", call(r, AC, "GET", f"/gateways/{gid}/")[1]["status"] == "READY")
    s, o, _ = call(r, AC, "POST", f"/gateways/{gid}/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    _check("MCP tools/list shows target___tool", o["result"]["tools"][0]["name"] == "calc___add")
    s, o, _ = call(r, AC, "POST", f"/gateways/{gid}/mcp", {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "calc___add", "arguments": {"a": 2, "b": 5}}})
    _check("MCP tools/call really invokes the Lambda", o["result"]["isError"] is False and json.loads(o["result"]["content"][0]["text"]) == {"sum": 7})
    _check("MCP unknown tool -> JSON-RPC error", call(r, AC, "POST", f"/gateways/{gid}/mcp", {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "nope"}})[1]["error"]["code"] == -32602)
    _check("delete gateway with target 400", call(r, AC, "DELETE", f"/gateways/{gid}/")[0] == 400)
    _check("delete target + gateway", call(r, AC, "DELETE", f"/gateways/{gid}/targets/{tid}/")[0] == 202 and call(r, AC, "DELETE", f"/gateways/{gid}/")[0] == 202)
    _check("delete runtime", call(r, AC, "DELETE", f"/runtimes/{rid}/")[0] == 202)
    llm.set_backend()
    print("OK")


if __name__ == "__main__":
    main()
