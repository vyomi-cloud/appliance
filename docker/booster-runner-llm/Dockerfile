# LOCAL TEST image only (mimics a GitHub-hosted ubuntu runner: llama-server + node + curl). The real runner uses the
# workflow in .github/booster/llm-runner.yml. Build/run names: vyomi-runllm-*.
FROM ghcr.io/ggml-org/llama.cpp:server
USER root
ENTRYPOINT []
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/runner && cd /opt/runner && npm i --no-audit --no-fund --silent ws@8.18.0
COPY entrypoint.sh runner-llm-dial.mjs /opt/runner/
ENV WS_PKG=/opt/runner/node_modules/ws LLAMA_BIN=/app/llama-server MODEL_DIR=/models
CMD ["bash", "/opt/runner/entrypoint.sh"]
