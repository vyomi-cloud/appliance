#!/bin/sh
# Vyomi compute-instance entrypoint (CloudLite+ — Docker compute backend).
# tini is PID 1; this supervises sshd (the instance's front door) and, when the
# container is privileged, dockerd (docker-in-instance). The user's SSH public
# key is injected at launch via the VYOMI_SSH_PUBKEY env var so `ssh ubuntu@<ip>`
# works immediately — the EC2/VM "ssh in" UX on a plain Docker container.
set -e

# ── SSH public-key injection (passed at `docker run -e VYOMI_SSH_PUBKEY=...`) ──
if [ -n "${VYOMI_SSH_PUBKEY:-}" ]; then
  install -d -m 700 -o ubuntu -g ubuntu /home/ubuntu/.ssh
  printf '%s\n' "$VYOMI_SSH_PUBKEY" > /home/ubuntu/.ssh/authorized_keys
  chmod 600 /home/ubuntu/.ssh/authorized_keys
  chown ubuntu:ubuntu /home/ubuntu/.ssh/authorized_keys
fi

# ── docker-in-instance (best effort; only works when --privileged) ────────────
if command -v dockerd >/dev/null 2>&1; then
  ( dockerd >/var/log/dockerd.log 2>&1 & ) 2>/dev/null || true
fi

# ── sshd in the foreground (tini reaps the backgrounded dockerd) ──────────────
install -d -m 0755 /run/sshd
exec /usr/sbin/sshd -D -e
