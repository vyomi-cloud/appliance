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
            "default_chat": C.DEFAULT_CHAT, "default_embed": C.DEFAULT_EMBED, "local_id": C.LOCAL_ID, "needs_mesh": C.NEEDS_MESH,
            "models": [{k: m[k] for k in ("id", "name", "vendor", "publisher", "kind", "size", "role", "blurb", "tag", "pooled") + C.LICENSE_FIELDS} for m in C.MODELS],
            # role models (Mesh only): in the JSON for the pickers but shown ONLY while the cloud's own list API reports them served (aiModels.markServed)
            "special": [] if C.WEB else [{k: m[k] for k in ("id", "name", "vendor", "publisher", "kind", "size", "role", "blurb", "tag", "pooled", "licence", "caps", "serve") + C.LICENSE_FIELDS} for m in C.SPECIAL]}


if __name__ == "__main__":
    # `--web` writes the Nano (browser WebLLM) variant: run with VYOMI_CATALOG=web
    out = os.path.join(ROOT, "consoles", "src", "common", "ai-model-catalog-web.json" if "--web" in sys.argv else "ai-model-catalog.json")
    with open(out, "w") as f:
        json.dump(doc(), f, indent=1)
        f.write("\n")
    print("wrote", out)
