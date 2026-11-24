import os

import agents


def handler(payload, context):
    payload = payload if isinstance(payload, dict) else {"prompt": str(payload)}
    st = agents.ask(payload.get("prompt") or payload.get("question", ""), payload.get("user", "anonymous"))
    res = {k: st.get(k) for k in ("answer", "route", "citations", "analytics", "approval", "llm_used", "tools", "spans")}
    res.update(response=st.get("answer"), sessionId=getattr(context, "session_id", None), pid=os.getpid())
    return res
