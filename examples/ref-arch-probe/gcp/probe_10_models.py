"""C10 Models: google-genai (vertexai=True) generateContent (with function calling) + embedContent against the simulator."""
from _common import *

s = Step()


def _no_model(e):
    t = str(e)
    return "503" in t or "not reachable" in t or "Local LLM" in t


def generate():
    from google.genai import types, errors
    c = genai_client()
    try:
        r = c.models.generate_content(model="gemini-2.0-flash", contents="Say OK", config=types.GenerateContentConfig(max_output_tokens=20))
    except errors.APIError as e:
        if _no_model(e):
            raise Blocked(f"needs a model: {str(e)[:200]}")
        raise
    assert r.text, r
    return r.text[:60]


def generate_tools():
    from google.genai import types, errors
    c = genai_client()
    fd = types.FunctionDeclaration(name="asset_status", description="status of an asset", parameters=types.Schema(type="OBJECT", properties={"asset_id": types.Schema(type="STRING")}, required=["asset_id"]))
    try:
        r = c.models.generate_content(model="gemini-2.0-flash", contents="What is the status of B-12?", config=types.GenerateContentConfig(
            tools=[types.Tool(function_declarations=[fd])], automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)))
    except errors.APIError as e:
        if _no_model(e):
            raise Blocked(f"needs a model (request with tools accepted up to the model call): {str(e)[:160]}")
        raise
    return str(r.function_calls)


def embed():
    c = genai_client()
    r = c.models.embed_content(model="text-embedding-005", contents=["boiler pressure limit", "elevator contract"])
    vs = [e.values for e in r.embeddings]
    assert len(vs) == 2 and len(vs[0]) > 8 and vs[0] != vs[1], vs
    return f"2 vectors, dim {len(vs[0])}"


def embed_semantic():
    """Embeddings must be semantic for RAG to be meaningful; the simulator's no-model fallback is a hash embedding."""
    c = genai_client()
    r = c.models.embed_content(model="text-embedding-005", contents=["boiler pressure limit", "boiler pressure maximum", "elevator contract renewal"])
    v = [e.values for e in r.embeddings]
    cos = lambda a, b: sum(x * y for x, y in zip(a, b)) / ((sum(x * x for x in a) ** .5) * (sum(y * y for y in b) ** .5))
    near, far = cos(v[0], v[1]), cos(v[0], v[2])
    if not near > far:
        raise AssertionError(f"embeddings are not semantic (near={near:.2f} far={far:.2f}): hash fallback in use")
    return f"near={near:.2f} far={far:.2f}"


s("generateContent (Vertex via google-genai)", generate)
s("generateContent with function declarations", generate_tools)
s("embedContent text-embedding-005", embed)
s("embedContent: paraphrase sharing words closer than unrelated text (lexical hash fallback without a model; cannot prove semantic)", embed_semantic)
s.finish()
