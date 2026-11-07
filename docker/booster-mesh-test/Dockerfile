# LOCAL TEST image only (names: vyomi-mesh-*). Base = the runner-pool spike image (llama.cpp + node + ws); adds WireGuard + net tools.
FROM vyomi-runllm-runner:spike
USER root
RUN apt-get update && apt-get install -y --no-install-recommends wireguard-tools wireguard-go iproute2 iputils-ping iperf3 netcat-openbsd python3 iptables \
    && rm -rf /var/lib/apt/lists/*
