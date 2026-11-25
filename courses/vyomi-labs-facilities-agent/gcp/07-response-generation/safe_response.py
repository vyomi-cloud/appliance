import guardrail
from respond import grounded_answer

guardrail.ensure_template()


def safe_answer(question):
    r = grounded_answer(question)
    verdict = guardrail.client().sanitize_model_response(request={"name": guardrail.TEMPLATE, "model_response_data": {"text": r["answer"]}, "user_prompt": question})
    if guardrail.match(verdict):
        return {"answer": "The answer was withheld because it may contain sensitive data.", "citations": [], "withheld": True}
    return dict(r, withheld=False)


if __name__ == "__main__":
    out = safe_answer("What should I do when boiler pressure exceeds 30 psi?")
    print("withheld:", out["withheld"], "| citations:", len(out["citations"]))
    assert not out["withheld"] and out["citations"]
    print("safe response delivered with its citations")
