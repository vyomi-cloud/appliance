"""CI smoke for examples/agent-workflow: the three drivers (boto3 Converse, google-genai Vertex, openai AzureOpenAI) import and run their
tool loops end to end through core.wire_ingress.

THE MODEL HERE IS A SCRIPTED FAKE (tests/conformance/llm_fakes.py), NOT A REAL LLM: it proves the example code + wire plumbing, not
agent quality. The real-model runs are recorded in examples/agent-workflow/SAMPLE-RUN.md (run_demo.py --run).
Skips when boto3 / google-genai / openai are missing.   Run: PYTHONPATH=. python tests/conformance/test_example_agent_workflow.py
"""
import importlib
import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
EX = os.path.abspath(os.path.join(HERE, "..", "..", "examples", "agent-workflow"))
sys.path.insert(0, HERE)
sys.path.insert(0, EX)


def scripted(body):
    msgs = body["messages"]
    if any(m["role"] == "tool" for m in msgs):
        return {"content": "Order A1001 has shipped via UPS; for a reset use Forgot password in Settings; ticket T-1 opened."}
    q = [m for m in msgs if m["role"] == "user"][-1]["content"].lower()
    if "reset" in q:
        return {"tool_calls": [{"name": "search_kb", "arguments": {"query": "reset password"}}]}
    if "damaged" in q:
        return {"tool_calls": [{"name": "create_ticket", "arguments": {"summary": "damaged", "priority": "high", "order_id": "A1002"}}]}
    return {"tool_calls": [{"name": "get_order_status", "arguments": {"order_id": "A1001"}}]}


def main():
    missing = [m for m in ("boto3", "google.genai", "openai") if importlib.util.find_spec(m.split(".")[0]) is None]
    if missing:
        print("skipping, not installed:", missing)
        return 0
    from llm_fakes import FakeLLM
    import run_demo
    from core import llm_core as llm
    fake = FakeLLM(handler=scripted)
    os.environ["TRIAGE_DB_FILE"] = os.path.join(tempfile.mkdtemp(), "db.json")
    srv, url = run_demo.start_server(fake.url, "fake-qwen", "fake-embed", embed_fn=lambda ts: [llm.hash_embed(t) for t in ts])
    os.environ["VYOMI_ENDPOINT"] = url
    bad = 0
    for name in ("aws", "gcp", "azure"):
        mod = importlib.import_module(f"agent_{name}")
        rc = mod.tools.cli(mod.run_agent, name, [])
        print(f"{'ok  ' if rc == 0 else 'FAIL'} agent_{name} (fake model)")
        bad += rc != 0
    import triage_tools as tools
    db = tools.load_db()
    print("ok   tickets written to the JSON db" if db["tickets"] else "FAIL no ticket persisted")
    bad += not db["tickets"]
    fake.close()
    srv.should_exit = True
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())


def test_example_agent_workflow():
    assert main() == 0
