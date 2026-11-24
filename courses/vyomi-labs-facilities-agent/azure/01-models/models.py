import json
from azlab import aoai, CHAT, EMBED


def chat(prompt, system=None):
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    r = aoai().chat.completions.create(model=CHAT, messages=msgs, max_tokens=200, temperature=0)
    return r.choices[0].message.content


def chat_with_tools(prompt, tools):
    r = aoai().chat.completions.create(model=CHAT, messages=[{"role": "user", "content": prompt}], tools=tools, tool_choice="auto")
    m = r.choices[0].message
    call = m.tool_calls[0] if m.tool_calls else None
    return {"finish_reason": r.choices[0].finish_reason,
            "tool_use": {"name": call.function.name, "input": json.loads(call.function.arguments)} if call else None,
            "text": m.content or ""}


def embed(text):
    return aoai().embeddings.create(model=EMBED, input=[text]).data[0].embedding
