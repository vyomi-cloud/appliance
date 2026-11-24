import time
from azlab import aoai, CHAT

oc = aoai("2025-03-01-preview")
thread = oc.beta.threads.create(metadata={"session": "s1", "user": "maria"})
for text in ("my badge is 4412", "which floor am I on"):
    oc.beta.threads.messages.create(thread.id, role="user", content=text)
history = oc.beta.threads.messages.list(thread.id, order="asc").data
print("history in order:", [m.content[0].text.value for m in history])

oc.beta.threads.update(thread.id, metadata={"session": "s1", "user": "maria", "topic": "badge"})
print("metadata:", oc.beta.threads.retrieve(thread.id).metadata)

assistant = oc.beta.assistants.create(model=CHAT, instructions="Answer from the conversation so far.")
run = oc.beta.threads.runs.create(thread.id, assistant_id=assistant.id)
for _ in range(60):
    if run.status not in ("queued", "in_progress"):
        break
    time.sleep(0.5)
    run = oc.beta.threads.runs.retrieve(run.id, thread_id=thread.id)
reply = " ".join(c.text.value for m in oc.beta.threads.messages.list(thread.id).data if m.role == "assistant" for c in m.content)
print("run:", run.status, "| thread now holds", len(oc.beta.threads.messages.list(thread.id).data), "messages (2 user + 1 assistant)")
oc.beta.threads.delete(thread.id)
