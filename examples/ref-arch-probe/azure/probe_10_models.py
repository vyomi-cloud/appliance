"""Component 10 Models: Azure OpenAI chat completions + embeddings through deployments."""
from _common import *

P = Probe(10, "models", "Models: Azure OpenAI chat + embeddings")
B = endpoint(); ensure_rg(B); ensure_openai(B)
oc = aoai(B)


def deployments():
    from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient
    names = [d.name for d in arm(CognitiveServicesManagementClient, B).deployments.list(RG, "aoai1")]
    assert {"chat", "embed"} <= set(names), names
    return names


def embeddings():
    e = oc.embeddings.create(model="embed", input=["a", "b"])
    assert len(e.data) == 2 and len(e.data[0].embedding) == 1536
    return "2 x 1536"


def embeddings_dimensions():
    e = oc.embeddings.create(model="embed", input="a", dimensions=256)
    assert len(e.data[0].embedding) == 256, len(e.data[0].embedding)


def chat():
    r = oc.chat.completions.create(model="chat", messages=[{"role": "user", "content": "say hi"}], max_tokens=20)
    assert r.choices[0].message.content


def chat_tools_shape():
    r = oc.chat.completions.create(model="chat", messages=[{"role": "user", "content": "weather in Paris"}],
        tools=[{"type": "function", "function": {"name": "w", "parameters": {"type": "object", "properties": {"c": {"type": "string"}}}}}])
    assert r.choices[0].message.tool_calls or r.choices[0].message.content


def stream():
    n = 0
    for ch in oc.chat.completions.create(model="chat", messages=[{"role": "user", "content": "hi"}], stream=True):
        n += 1
    assert n


def missing_deployment():
    from openai import NotFoundError
    try:
        oc.chat.completions.create(model="nope", messages=[{"role": "user", "content": "x"}])
    except NotFoundError as e:
        return f"404 {getattr(e, 'code', '')}"
    raise AssertionError("no 404")


def responses_api():
    r = oc.responses.create(model="chat", input="hi")
    assert r.output_text


P.step("ARM deployments (chat gpt-4o, embed text-embedding-3-small) list", deployments)
P.step("embeddings.create: 2 inputs, 1536 dims", embeddings)
P.step("embeddings with dimensions=256 (text-embedding-3 feature)", embeddings_dimensions)
P.step("chat.completions (needs a model)", chat, blocked="no model")
P.step("chat.completions with tools (needs a model)", chat_tools_shape, blocked="no model")
P.step("chat.completions stream=True (needs a model)", stream, blocked="no model")
P.step("responses.create (needs a model)", responses_api, blocked="no model")
P.step("unknown deployment -> 404 DeploymentNotFound", missing_deployment)
P.finish()
