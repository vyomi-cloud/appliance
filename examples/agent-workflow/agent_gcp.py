"""GCP driver: google-genai with vertexai=True, function calling (manual loop) + text-embedding. Native SDK, endpoint overridden.
    VYOMI_ENDPOINT=http://127.0.0.1:8099 python agent_gcp.py ["Where is my order A1001?"]
"""
import os
import time

from google import genai
from google.auth.credentials import Credentials
from google.genai import types

import triage_tools as tools

MODEL = os.environ.get("VERTEX_MODEL", "gemini-2.0-flash")


class DummyCreds(Credentials):
    """google-genai insists on ADC for Vertex; the simulator ignores the bearer token, so any credentials object will do."""
    def refresh(self, request):
        self.token = "vyomi-local"


def client():
    return genai.Client(vertexai=True, project=os.environ.get("GOOGLE_CLOUD_PROJECT", "demo-project"), location="us-central1", credentials=DummyCreds(),
                        http_options=types.HttpOptions(base_url=tools.endpoint(), api_version="v1"))


def _schema(s):
    """JSON schema -> genai Schema (upper-case types, as the real Vertex API wants)."""
    return types.Schema(type=s["type"].upper(), description=s.get("description"), enum=s.get("enum"),
                        properties={k: _schema(v) for k, v in s.get("properties", {}).items()} or None, required=s.get("required"))


def run_agent(question, trace):
    c = client()
    tools.set_embedder(lambda texts: [e.values for e in c.models.embed_content(model="text-embedding-005", contents=texts).embeddings])
    cfg = types.GenerateContentConfig(
        system_instruction=tools.SYSTEM, temperature=0, max_output_tokens=300,
        tools=[types.Tool(function_declarations=[types.FunctionDeclaration(name=t["name"], description=t["description"], parameters=_schema(t["parameters"]))
                                                 for t in tools.TOOLS])],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))      # we run the loop ourselves
    contents = [types.Content(role="user", parts=[types.Part(text=question)])]
    for step in range(1, tools.MAX_STEPS + 1):
        t0 = time.time()
        r = c.models.generate_content(model=MODEL, contents=contents, config=cfg)
        calls = r.function_calls or []
        text = "".join(p.text or "" for p in (r.candidates[0].content.parts if r.candidates and r.candidates[0].content else []) if not p.function_call)
        trace.append({"step": step, "seconds": time.time() - t0, "text": text, "tool_calls": [{"name": f.name, "args": dict(f.args or {})} for f in calls]})
        if not calls:
            return text
        contents.append(r.candidates[0].content)
        contents.append(types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
            name=f.name, response=tools.execute(f.name, dict(f.args or {})))) for f in calls]))
    return "(gave up: no final answer within MAX_STEPS)"


if __name__ == "__main__":
    raise SystemExit(tools.cli(run_agent, "gcp/vertex"))
