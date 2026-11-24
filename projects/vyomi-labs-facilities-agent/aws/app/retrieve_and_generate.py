import boto3

from guardrail import ensure_guardrail
from models import CHAT_MODEL

ag = boto3.client("bedrock-agent")
kb = next(k for k in ag.list_knowledge_bases()["knowledgeBaseSummaries"] if k["name"] == "facilities-kb")["knowledgeBaseId"]
r = boto3.client("bedrock-agent-runtime").retrieve_and_generate(
    input={"text": "What should I do when boiler pressure exceeds 30 psi?"},
    retrieveAndGenerateConfiguration={"type": "KNOWLEDGE_BASE", "knowledgeBaseConfiguration": {
        "knowledgeBaseId": kb, "modelArn": "arn:aws:bedrock:us-east-1::foundation-model/" + CHAT_MODEL,
        "generationConfiguration": {"guardrailConfiguration": {"guardrailId": ensure_guardrail(), "guardrailVersion": "DRAFT"}}}})
print("answer:", r["output"]["text"][:140].replace("\n", " "))
print("citation blocks:", len(r["citations"]))
