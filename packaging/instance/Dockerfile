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

RUN apt-get update && apt-get install -y --no-install-recommends \
        openssh-server sudo ca-certificates curl iproute2 \
        docker.io docker-compose-v2 tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -s /bin/bash ubuntu \
    && adduser ubuntu sudo \
    && echo 'ubuntu ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/ubuntu \
    && chmod 0440 /etc/sudoers.d/ubuntu \
    && mkdir -p /run/sshd /etc/ssh/sshd_config.d \
    && printf 'PasswordAuthentication no\nPubkeyAuthentication yes\nPermitRootLogin no\n' \
         > /etc/ssh/sshd_config.d/vyomi.conf

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 22
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
