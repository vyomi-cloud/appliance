import boto3

from guardrail import ensure_guardrail

rt = boto3.client("bedrock-runtime")
gid = ensure_guardrail()


def check(text):
    return rt.apply_guardrail(guardrailIdentifier=gid, guardrailVersion="DRAFT", source="OUTPUT", content=[{"text": {"text": text}}])


clean = check("Close the main steam valve and notify the duty engineer [1].")
print("clean answer:", clean["action"])
leaky = check("Close the main steam valve. Contact the duty engineer at jane.doe@example.com.")
print("leaky answer:", leaky["action"], "->", leaky["outputs"][0]["text"])
print("email removed:", "jane.doe@example.com" not in leaky["outputs"][0]["text"])
