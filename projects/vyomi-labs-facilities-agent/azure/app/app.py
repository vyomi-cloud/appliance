import os
from fastapi import FastAPI
from openai import AzureOpenAI
import agent_graph

client = AzureOpenAI(azure_endpoint=os.environ["VYOMI_ENDPOINT"], api_key="vyomi-local", api_version="2024-10-21", max_retries=0, timeout=120)


def converse(system, text, max_tokens=300):
    r = client.chat.completions.create(model="chat", max_tokens=max_tokens, temperature=0,
                                       messages=[{"role": "system", "content": system}, {"role": "user", "content": text}])
    return r.choices[0].message.content


graph = agent_graph.build(converse)
SESSIONS = {}           # session id -> list of turns; nothing is shared between sessions
app = FastAPI(title="facilities-supervisor")


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/query")
def query(body: dict):
    session = body.get("session", "default")
    history = SESSIONS.setdefault(session, [])
    st = graph.invoke({"question": body["prompt"], "user": body.get("user", "anonymous"), "spans": []})
    history.append({"q": body["prompt"], "a": st["answer"]})
    return {"answer": st["answer"], "route": st["route"], "llm_used": st["llm_used"], "session": session, "turns": len(history),
            "spans": st["spans"], "pid": os.getpid()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8080")))
