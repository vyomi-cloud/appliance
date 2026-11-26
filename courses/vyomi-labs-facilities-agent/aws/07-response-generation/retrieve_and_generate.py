import boto3

from guardrail import ensure_guardrail
from vymodels import CHAT_MODEL

ag = boto3.client("bedrock-agent")
kb = next(k for k in ag.list_knowledge_bases()["knowledgeBaseSummaries"] if k["name"] == "facilities-kb")["knowledgeBaseId"]
r = boto3.client("bedrock-agent-runtime").retrieve_and_generate(
    input={"text": "What should I do when boiler pressure exceeds 30 psi?"},
    retrieveAndGenerateConfiguration={"type": "KNOWLEDGE_BASE", "knowledgeBaseConfiguration": {
        "knowledgeBaseId": kb, "modelArn": "arn:aws:bedrock:us-east-1::foundation-model/" + CHAT_MODEL,
        "generationConfiguration": {"guardrailConfiguration": {"guardrailId": ensure_guardrail(), "guardrailVersion": "DRAFT"}}}})
print("answer:", r["output"]["text"][:140].replace("\n", " "))
refs = [ref for c in r["citations"] for ref in c.get("retrievedReferences", [])]
print("citation blocks:", len(r["citations"]), "| source documents cited:", sorted({x["location"]["s3Location"]["uri"] for x in refs}))
# A grounded answer cites its sources: no citation means the model answered from memory, which is the failure this chapter exists to prevent.
assert r["output"]["text"].strip(), "empty answer"
assert r["citations"] and refs, "RetrieveAndGenerate returned an answer with no citations"
assert any("boiler-sop" in x["location"]["s3Location"]["uri"] for x in refs), "the boiler question must cite the boiler SOP"
