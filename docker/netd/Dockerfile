# vyomi netd — the netsim enforcer sidecar. Runs in the Docker HOST network namespace and owns
# exactly one nftables table per Vyomi space (`table inet vyomi_<space>`) plus a few
# DOCKER-USER accepts tagged `vyomi_<space>`. It holds no logic: core/netsim/enforce.py compiles
# the ruleset and pipes it in with `docker exec -i <netd> nft -f -` (atomic, idempotent).
#
#   docker build -t vyomi/netd:1 docker/netd
#   docker run -d --name vyomi-netd --network host --cap-add NET_ADMIN --restart unless-stopped vyomi/netd:1
FROM alpine:3.20
RUN apk add --no-cache nftables iptables \
 && nft --version && iptables -V
LABEL org.opencontainers.image.title="vyomi-netd" \
      org.opencontainers.image.description="Vyomi netsim enforcer sidecar (nftables in the host netns)"
HEALTHCHECK --interval=60s --timeout=5s CMD nft list tables >/dev/null || exit 1
CMD ["sleep", "infinity"]
