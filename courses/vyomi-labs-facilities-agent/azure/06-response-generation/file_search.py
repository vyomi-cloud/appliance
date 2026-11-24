import time
from azlab import aoai, CHAT

oc = aoai("2025-03-01-preview")
store = oc.vector_stores.create(name="facilities-kb")
f = oc.files.create(file=("boiler-sop.md", open("boiler-sop.md", "rb").read()), purpose="assistants")
oc.vector_stores.files.create(store.id, file_id=f.id)
print("files in the vector store:", len(oc.vector_stores.files.list(store.id).data))

assistant = oc.beta.assistants.create(model=CHAT, instructions="Answer only from the files.", tools=[{"type": "file_search"}],
                                      tool_resources={"file_search": {"vector_store_ids": [store.id]}})
thread = oc.beta.threads.create(messages=[{"role": "user", "content": "What must I do when boiler pressure exceeds 30 psi?"}])
run = oc.beta.threads.runs.create(thread.id, assistant_id=assistant.id)
for _ in range(60):
    if run.status not in ("queued", "in_progress"):
        break
    time.sleep(0.5)
    run = oc.beta.threads.runs.retrieve(run.id, thread_id=thread.id)
msgs = oc.beta.threads.messages.list(thread.id).data
notes = [a for m in msgs if m.role == "assistant" for c in m.content for a in c.text.annotations]
print("run:", run.status, "| annotation types:", sorted({a.type for a in notes}))
