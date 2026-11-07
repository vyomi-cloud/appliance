#!/usr/bin/env python3
"""Regenerate consoles/src/common/ai-model-catalog.json from core/ai_model_catalog.py (the single catalogue source).
Run after editing the catalogue; tests/conformance/test_ai_model_catalog.py fails if the JSON is stale."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core import ai_model_catalog as C  # noqa: E402


def doc():
    return {"_comment": "GENERATED from core/ai_model_catalog.py by scripts/gen_ai_model_catalog_json.py - do not edit.",
            "default_chat": C.DEFAULT_CHAT, "default_embed": C.DEFAULT_EMBED, "local_id": C.LOCAL_ID, "needs_booster": C.NEEDS_BOOSTER,
            "models": [{k: m[k] for k in ("id", "name", "vendor", "publisher", "kind", "size", "role", "blurb", "tag", "pooled")} for m in C.MODELS]}


if __name__ == "__main__":
    out = os.path.join(ROOT, "consoles", "src", "common", "ai-model-catalog.json")
    with open(out, "w") as f:
        json.dump(doc(), f, indent=1)
        f.write("\n")
    print("wrote", out)
