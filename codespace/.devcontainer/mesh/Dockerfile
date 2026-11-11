# Mesh devcontainer image. Builds run as-is; an apt-get that fails on DNS falls back to IPv4 (see apt-get-fallback.sh) and continues.
FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04
COPY apt-get-fallback.sh /usr/local/bin/apt-get
RUN chmod +x /usr/local/bin/apt-get \
 && printf 'retry = 5\nretry-connrefused\n' > /root/.curlrc \
 && printf 'tries = 5\n' >> /etc/wgetrc
