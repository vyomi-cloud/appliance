from openai import NotFoundError
from azlab import aoai, CHAT, EMBED

chunks = [c for c in aoai().chat.completions.create(model=CHAT, messages=[{"role": "user", "content": "hi"}], stream=True)]
print("stream:", len(chunks), "chunks")

small = aoai().embeddings.create(model=EMBED, input="a", dimensions=256)
print("embedding with dimensions=256:", len(small.data[0].embedding), "numbers")

try:
    aoai().chat.completions.create(model="no-such-deployment", messages=[{"role": "user", "content": "x"}])
except NotFoundError as e:
    print("unknown deployment ->", e.status_code, getattr(e, "code", ""))
