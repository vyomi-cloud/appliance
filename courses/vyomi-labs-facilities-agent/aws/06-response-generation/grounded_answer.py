import boto3

from ask_agent import ask
from guardrail import ensure_guardrail

res = ask("facilities-session-" + "c" * 20)
print("route:", res["route"])
print("cited sources:", sorted({c["source"] for c in res["citations"]}))
print("answer:", res["answer"])
print("grounded in the boiler SOP:", any("boiler-sop" in c["source"] for c in res["citations"]))

check = boto3.client("bedrock-runtime").apply_guardrail(guardrailIdentifier=ensure_guardrail(), guardrailVersion="DRAFT", source="OUTPUT",
                                                        content=[{"text": {"text": res["answer"]}}])
print("agent answer passes the output guardrail:", check["action"] == "NONE")
