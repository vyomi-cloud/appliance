"""Nano (no Mesh) lists ONLY in-browser web LLMs (>=3); the ten-model pool is Mesh-only.
Run: VYOMI_CATALOG=web PYTHONPATH=. python3 tests/conformance/test_ai_model_catalog_web.py"""
import os
os.environ["VYOMI_CATALOG"] = "web"
from core import ai_model_catalog as C, ai_models_core as A


def run():
    assert C.WEB and len(C.IDS) >= 3, C.IDS
    assert all(m["tag"].endswith("-MLC") for m in C.MODELS)
    assert [m[0] for m in A.BEDROCK_MODELS] == ["vyomi." + i for i in C.IDS]
    assert not set(C.IDS) & {"qwen2.5-7b", "llama3.1-8b", "qwen3-30b"}
    assert all(C.availability(i)["available"] for i in C.IDS)
    assert C.resolve("aws", "anthropic.claude-3-sonnet") in C.BY_ID
    print("WEB CATALOG OK", C.IDS)


if __name__ == "__main__":
    run()
