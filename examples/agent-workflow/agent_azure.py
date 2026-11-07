"""Azure driver: openai.AzureOpenAI chat tools loop + embeddings. Native SDK, only azure_endpoint differs from production.
    VYOMI_ENDPOINT=http://127.0.0.1:8099 python agent_azure.py ["Where is my order A1001?"]
The deployment name ($AZURE_OPENAI_DEPLOYMENT, default 'chat') is whatever you created under your Azure OpenAI account.
"""
import json
import os
import time

from openai import AzureOpenAI

import triage_tools as tools

DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "chat")
EMBED_DEPLOYMENT = os.environ.get("AZURE_OPENAI_EMBED_DEPLOYMENT", "embed")


def client():
    return AzureOpenAI(azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT") or tools.endpoint(), api_key=os.environ.get("AZURE_OPENAI_API_KEY", "local-key"),
                       api_version="2024-10-21", max_retries=0, timeout=600)


def run_agent(question, trace):
    oc = client()
    tools.set_embedder(lambda texts: [d.embedding for d in oc.embeddings.create(model=EMBED_DEPLOYMENT, input=texts).data])
    spec = [{"type": "function", "function": t} for t in tools.TOOLS]
    messages = [{"role": "system", "content": tools.SYSTEM}, {"role": "user", "content": question}]
    for step in range(1, tools.MAX_STEPS + 1):
        t0 = time.time()
        r = oc.chat.completions.create(model=DEPLOYMENT, messages=messages, tools=spec, temperature=0, max_tokens=300)
        m = r.choices[0].message
        calls = m.tool_calls or []
        parsed = []
        for tc in calls:
            try:
                parsed.append(json.loads(tc.function.arguments or "{}"))
            except ValueError:
                parsed.append({})
        trace.append({"step": step, "seconds": time.time() - t0, "text": m.content or "",
                      "tool_calls": [{"name": tc.function.name, "args": a} for tc, a in zip(calls, parsed)]})
        if not calls:
            return m.content or ""
        messages.append(m)
        for tc, a in zip(calls, parsed):
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(tools.execute(tc.function.name, a))})
    return "(gave up: no final answer within MAX_STEPS)"


if __name__ == "__main__":
    raise SystemExit(tools.cli(run_agent, "azure/openai"))
