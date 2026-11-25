import boto3

bedrock = boto3.client("bedrock")


def ensure_guardrail():
    for g in bedrock.list_guardrails()["guardrails"]:
        if g["name"] == "facilities-guardrail":
            return g["id"]
    r = bedrock.create_guardrail(
        name="facilities-guardrail", description="Facilities agent guardrail",
        blockedInputMessaging="Sorry, I cannot help with that request.", blockedOutputsMessaging="Sorry, that answer was withheld.",
        contentPolicyConfig={"filtersConfig": [{"type": "PROMPT_ATTACK", "inputStrength": "HIGH", "outputStrength": "NONE"}]},
        wordPolicyConfig={"wordsConfig": [{"text": "master-key-code"}]},
        sensitiveInformationPolicyConfig={"piiEntitiesConfig": [{"type": "EMAIL", "action": "ANONYMIZE"},
                                                                {"type": "US_SOCIAL_SECURITY_NUMBER", "action": "BLOCK"}]})
    bedrock.create_guardrail_version(guardrailIdentifier=r["guardrailId"])
    return r["guardrailId"]


if __name__ == "__main__":
    print("guardrail", ensure_guardrail())
