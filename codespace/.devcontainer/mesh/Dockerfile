# Mesh devcontainer image. Builds run as-is; an apt-get that fails on DNS falls back to IPv4 (see apt-get-fallback.sh) and continues.
FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04
COPY apt-get-fallback.sh /usr/local/bin/apt-get
RUN chmod +x /usr/local/bin/apt-get \
 && printf 'retry = 5\nretry-connrefused\n' > /root/.curlrc \
 && printf 'tries = 5\n' >> /etc/wgetrc
# The gate: the only privileged door to Docker for the Codespace user (docs/architecture/v4.0/MESH-SOFTWARE-PROTECTION.md).
# Installed root-owned now; vyomi-lockdown (which removes the user's own docker/sudo) is enabled separately after a real-Codespace test.
COPY vyomi-gate /usr/local/sbin/vyomi-gate
COPY vyomi-lockdown /usr/local/sbin/vyomi-lockdown
RUN chown root:root /usr/local/sbin/vyomi-gate /usr/local/sbin/vyomi-lockdown \
 && chmod 0755 /usr/local/sbin/vyomi-gate /usr/local/sbin/vyomi-lockdown \
 && printf 'vscode ALL=(root) NOPASSWD: /usr/local/sbin/vyomi-gate\n' > /etc/sudoers.d/vyomi-gate && chmod 0440 /etc/sudoers.d/vyomi-gate
