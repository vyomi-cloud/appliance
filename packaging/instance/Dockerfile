# Vyomi compute-instance image — the "AMI" for the Docker compute backend
# (CloudLite+). A VM-like Ubuntu base with SSH + docker-in-instance, supervised
# by tini (no full systemd). Built once; per-instance CPU/RAM are applied as
# cgroup limits at `docker run` time. SSH access is enabled out of the box —
# the launcher injects the user's public key via VYOMI_SSH_PUBKEY at launch.
#
#   docker build -t vyomi/instance:ubuntu-24.04 packaging/instance
#   docker run -d --name vyomi-i-<id> --privileged --cpus N --memory Mm \
#     -e VYOMI_SSH_PUBKEY="ssh-ed25519 AAAA..." \
#     -v vyomi-i-<id>-root:/var/lib/docker  vyomi/instance:ubuntu-24.04
FROM ubuntu:24.04

# Canonical's default archive/security/ports mirrors have recurring DNS/
# availability outages that specifically break Docker builds (hit this
# build repeatedly: "Could not resolve 'archive.ubuntu.com'" etc.). The
# Azure regional mirrors are Canonical-operated but on separate DNS/CDN
# infrastructure, so they stay up when the global ones don't — and
# GitHub-hosted Linux runners already run on Azure, so it's also the
# closest mirror.
RUN sed -i \
        -e 's|http://archive.ubuntu.com/ubuntu/|http://azure.archive.ubuntu.com/ubuntu/|g' \
        -e 's|http://security.ubuntu.com/ubuntu/|http://azure.archive.ubuntu.com/ubuntu/|g' \
        -e 's|http://ports.ubuntu.com/ubuntu-ports/|http://azure.ports.ubuntu.com/ubuntu-ports/|g' \
        /etc/apt/sources.list.d/ubuntu.sources

RUN apt-get update && apt-get install -y --no-install-recommends \
        openssh-server sudo ca-certificates curl iproute2 \
        docker.io docker-compose-v2 tini \
    && rm -rf /var/lib/apt/lists/* \
    # ubuntu:24.04 already ships a default 'ubuntu' user (UID 1000), so create
    # it only if absent (keeps the image buildable on older bases too).
    && (id ubuntu >/dev/null 2>&1 || useradd -m -s /bin/bash ubuntu) \
    && usermod -aG sudo ubuntu \
    && echo 'ubuntu ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/ubuntu \
    && chmod 0440 /etc/sudoers.d/ubuntu \
    && mkdir -p /run/sshd /etc/ssh/sshd_config.d \
    && printf 'PasswordAuthentication no\nPubkeyAuthentication yes\nPermitRootLogin no\n' \
         > /etc/ssh/sshd_config.d/vyomi.conf

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 22
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
