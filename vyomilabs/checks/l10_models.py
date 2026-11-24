"""Layer 10: Foundation Models via Bedrock. CODE layer: imports the learner's layers/l10_models.py and calls chat(), chat_with_tools(), embed().
The checker creates nothing in the simulator; the learner's code talks to the model through the standard AWS SDK settings."""
import os

from . import register
from .. import workspace
from facilities.runtime import Blocked

TOOL = {"toolSpec": {"name": "asset_status", "description": "status of an asset by id",
                     "inputSchema": {"json": {"type": "object", "properties": {"asset_id": {"type": "string"}}, "required": ["asset_id"]}}}}


@register(10)
def verify(ctx):
    os.environ["AWS_ENDPOINT_URL"] = ctx.endpoint
    os.environ.setdefault("AWS_DEFAULT_REGION", ctx.region)
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
    box = {}

    def load():
        box["m"] = workspace.load_layer("l10_models.py", ctx_workspace(ctx))
        for fn in ("chat", "chat_with_tools", "embed"):
            assert callable(getattr(box["m"], fn, None)), f"layers/l10_models.py has no function {fn}()"
        return "layers/l10_models.py loaded"
    ctx.step("your layers/l10_models.py loads and defines chat, chat_with_tools, embed", load)
    m = box.get("m")
    if not m:
        return

    def guard(fn):
        try:
            return fn()
        except NotImplementedError as e:
            raise AssertionError(f"not written yet: {e}")

    def chat():
        t = guard(lambda: m.chat("Reply with the single word OK."))
        assert isinstance(t, str) and t.strip(), "chat() must return the reply text as a non-empty string"
        return f"model replied {t[:40]!r}"
    ctx.step("chat() returns the model's reply text", chat, lane="local model")

    def tools():
        r = guard(lambda: m.chat_with_tools("What is the status of asset B-12?", [TOOL]))
        assert isinstance(r, dict) and {"stop_reason", "tool_use", "text"} <= set(r), "chat_with_tools() must return a dict with stop_reason, tool_use and text"
        assert r["stop_reason"] in ("tool_use", "end_turn"), f"unexpected stop_reason {r['stop_reason']!r}"
        if r["stop_reason"] == "tool_use":
            assert r["tool_use"] and r["tool_use"].get("name") == "asset_status", "tool_use must carry the toolUse block with the tool name"
        return f"stop_reason={r['stop_reason']}"
    ctx.step("chat_with_tools() returns stop_reason, tool_use and text", tools, lane="local model")

    def embed():
        v = guard(lambda: m.embed("boiler pressure"))
        assert isinstance(v, list) and v and all(isinstance(x, (int, float)) for x in v), "embed() must return a non-empty list of numbers"
        if not any(abs(x) > 1e-9 for x in v):
            raise Blocked("local model", "embedding endpoint returned an all-zero vector (no embedding model reachable)")
        return f"embedding of {len(v)} numbers"
    ctx.step("embed() returns an embedding vector", embed, lane="local model")


def ctx_workspace(ctx):
    return getattr(ctx, "workspace", None)
