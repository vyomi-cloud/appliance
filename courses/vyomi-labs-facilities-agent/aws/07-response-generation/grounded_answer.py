import boto3

import rag_design
from ask_agent import ask
from guardrail import ensure_guardrail

res = ask("facilities-session-" + "c" * 20)
best = max([c.get("score") or 0 for c in res["citations"]] or [0])
if rag_design.grounding_threshold() > 0 and best < rag_design.grounding_threshold():       # your design: refuse when nothing retrieved is relevant enough
    res = dict(res, answer="I can't answer that from the approved documents.", citations=[])
print("route:", res["route"])
print("cited sources:", sorted({c["source"] for c in res["citations"]}))
print("answer:", res["answer"])
print("grounded in the boiler SOP:", any("boiler-sop" in c["source"] for c in res["citations"]))

check = boto3.client("bedrock-runtime").apply_guardrail(guardrailIdentifier=ensure_guardrail(), guardrailVersion="DRAFT", source="OUTPUT",
                                                        content=[{"text": {"text": res["answer"]}}])
assert res["citations"], "an answer with no citations is not grounded"
assert all(c["source"].startswith("s3://") for c in res["citations"]), "every citation must point at a source document"
assert res["answer"].strip(), "the agent returned an empty answer"
print("agent answer passes the output guardrail:", check["action"] == "NONE")
assert check["action"] == "NONE", "the answer was intervened by the output guardrail"
