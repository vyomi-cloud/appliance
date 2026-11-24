import time
import uuid

import gcp
import memory
from agents import ask

client = gcp.vertex_client("v1beta1")
engine = memory.engine_name()
session = client.agent_engines.sessions.create(name=engine, user_id="maria").response.name
print("session:", session.rsplit("/", 1)[-1])

question = "Boiler B-12 is at 34 psi. What does the SOP say?"
answer = ask(question, "maria")["answer"]
for author, role, text in (("user", "user", question), ("agent", "model", answer)):
    client.agent_engines.sessions.events.append(name=session, author=author, invocation_id=uuid.uuid4().hex[:8], timestamp=time.time(),
                                                config={"content": {"role": role, "parts": [{"text": text}]}})

events = list(client.agent_engines.sessions.events.list(name=session))
print("events replayed:", len(events))
assert len(events) == 2
