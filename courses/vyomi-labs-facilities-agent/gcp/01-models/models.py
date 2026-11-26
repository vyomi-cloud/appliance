from google.genai import types

import gcp

def _pick():
    """The models are the ones this simulator hosts: in-browser models on Nano, the Mesh model pool on a Mesh. Ask its Model Garden, never hard-code a vendor id."""
    r = gcp.authed_session().get(gcp.ENDPOINT + "/v1beta1/publishers")
    r.raise_for_status()
    ids = [m["name"].split("/")[-1] for m in r.json()["publisherModels"]]
    emb = [i for i in ids if "embed" in i or "minilm" in i]
    return [i for i in ids if i not in emb][0], emb[0]


CHAT_MODEL, EMBED_MODEL = _pick()
_client = gcp.genai_client()


def chat(prompt, system=None, max_tokens=300):
    r = _client.models.generate_content(model=CHAT_MODEL, contents=prompt,
                                        config=types.GenerateContentConfig(system_instruction=system, max_output_tokens=max_tokens, temperature=0))
    return r.text


def chat_with_tools(prompt, declarations):
    """declarations: a list of types.FunctionDeclaration. Returns the function calls the model asked for (the model never runs them: your code does)."""
    r = _client.models.generate_content(model=CHAT_MODEL, contents=prompt, config=types.GenerateContentConfig(
        tools=[types.Tool(function_declarations=declarations)], automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)))
    return {"calls": [{"name": c.name, "args": dict(c.args)} for c in (r.function_calls or [])], "text": r.text if not r.function_calls else ""}


def embed(texts, dimensions=None):
    """dimensions: ask for a shorter vector when the model supports it (your RAG design sets this); None keeps the model's own size."""
    cfg = types.EmbedContentConfig(output_dimensionality=dimensions) if dimensions else None
    r = _client.models.embed_content(model=EMBED_MODEL, contents=texts, config=cfg)
    return [e.values for e in r.embeddings]
