"""OptimizePrompt must never show the local model's junk as an 'optimized prompt'.
Owner symptom: the result area showed '{{input}}{{output}}' over and over. A <1 GB model told to keep '{{variable}}' placeholders parrots ones it
was never given. Regression: internal/made-up placeholders and loops never reach the result; the user's own {{variables}} always survive.
Run: python3 -m pytest tests/test_bedrock_optimize_prompt.py -q   (or python3 tests/test_bedrock_optimize_prompt.py)"""
import json, os, re, sys
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from core import bedrock_build_core as bc, llm_core  # noqa: E402

MODEL = "amazon.nova-lite-v1:0"


def _run(reply, text):
    """Run _optimize with a fake local model that answers `reply`; return (optimized_text, analysis_note)."""
    seen = {}
    def fn(messages, system, max_tokens, temperature, stop, **kw):
        seen["meta"], seen["max_tokens"] = messages[-1]["content"], max_tokens
        return reply
    llm_core.set_backend(fn=fn, model="fake")
    try:
        r = bc._optimize({"input": {"textPrompt": {"text": text}}, "targetModelId": MODEL})
    finally:
        llm_core.set_backend(fn=None)
    body = r["body"].decode("utf-8", "replace")
    out = re.search(r'"optimizedPrompt":\s*\{"textPrompt":\s*\{"text":\s*("(?:[^"\\]|\\.)*")', body)
    note = re.search(r'"message":\s*("(?:[^"\\]|\\.)*")', body)
    return json.loads(out.group(1)), json.loads(note.group(1)), seen


def test_owner_symptom_placeholder_loop_is_replaced():
    out, note, _ = _run("{{input}}{{output}}" * 60, "summarize this {{doc}} for me")
    assert "{{input}}" not in out and "{{output}}" not in out
    assert "{{doc}}" in out and "summarize this" in out
    assert "rule-based" in note


def test_made_up_placeholders_with_words_are_rejected():
    out, note, _ = _run("You are an expert. Answer {{input}} and write {{output}} now please.", "tell me about cats")
    assert "{{" not in out and "rule-based" in note


def test_user_typed_input_placeholder_is_kept():
    good = "You are a precise assistant. Summarize the text in {{input}} as three bullet points."
    out, note, _ = _run(good, "summarize {{input}}")
    assert out == good and "rule-based" not in note


def test_good_model_reply_passes_through_unchanged():
    good = "You are a travel expert. Write a short, friendly itinerary for {{city}} as a bulleted list."
    out, note, _ = _run(good, "make an itinerary for {{city}}")
    assert out == good and "local model" in note and "rule-based" not in note


def test_dropped_user_variable_falls_back_and_variable_survives():
    out, note, _ = _run("You are a helpful assistant who writes clear summaries of documents.", "summarize {{doc}}")
    assert "{{doc}}" in out and "rule-based" in note


def test_repetition_loop_without_placeholders_is_rejected():
    out, note, _ = _run("sure sure sure sure sure sure sure sure sure sure sure sure sure sure sure sure", "explain tcp")
    assert out.startswith("You are a careful assistant") and "rule-based" in note


def test_empty_reply_falls_back():
    out, note, _ = _run("   ", "explain tcp")
    assert "explain tcp" in out and "rule-based" in note


def test_meta_prompt_never_contains_a_literal_variable_token_and_caps_tokens():
    _, _, seen = _run("You are an expert. Explain TCP slowly and clearly in plain words.", "explain tcp")
    assert "{{variable}}" not in seen["meta"] and "{{" not in seen["meta"].split("PROMPT:")[0]
    assert seen["max_tokens"] <= 400


def test_meta_prompt_lists_only_the_users_variables():
    _, _, seen = _run("You are an expert. Use {{a}} and {{b}} to write the full answer.", "use {{a}} and {{b}}")
    head = seen["meta"].split("PROMPT:")[0]
    assert "{{a}}" in head and "{{b}}" in head


def test_no_backend_is_an_honest_424():
    llm_core.set_backend(fn=None)
    r = bc._optimize({"input": {"textPrompt": {"text": "hello world"}}, "targetModelId": MODEL})
    assert r["status"] == 424 and b"DependencyFailedException" in json.dumps(r, default=lambda o: o.decode()).encode()


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
