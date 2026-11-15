#!/bin/sh
# Vendor (pin) the llama.cpp converter used to turn a PEFT adapter into an f16 GGUF LoRA. ~3 MB sparse checkout, no build.
# Tag b8996 = c3c15053925746c74fc2aaf6b864bd66665393c4 (the version the numbers were measured with; keep it in step with the llama-server image tag).
set -e
DEST="${1:-$(dirname "$0")/llama.cpp}"
TAG="${LLAMACPP_TAG:-b8996}"
rm -rf "$DEST"
git clone -q --depth 1 --branch "$TAG" --filter=blob:none --sparse https://github.com/ggml-org/llama.cpp.git "$DEST"
git -C "$DEST" sparse-checkout set gguf-py conversion 2>/dev/null || git -C "$DEST" sparse-checkout set gguf-py
echo "llama.cpp $TAG at $(git -C "$DEST" rev-parse HEAD) -> $DEST"
