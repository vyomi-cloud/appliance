import guardrail
from google.cloud import modelarmor_v1 as ma

print("template:", guardrail.ensure_template())
client = guardrail.client()


def screen(text):
    return client.sanitize_model_response(request={"name": guardrail.TEMPLATE, "model_response_data": {"text": text}, "user_prompt": "who should I call?"})


dirty = screen("Call the duty engineer. Her record: ssn 123-45-6789, email jane.doe@example.com.")
clean = screen("Close the main steam valve and notify the duty engineer [1].")
print("answer with sensitive data flagged:", guardrail.match(dirty))
print("clean answer passes:", not guardrail.match(clean))
assert guardrail.match(dirty) and not guardrail.match(clean)
