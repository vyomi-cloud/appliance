#!/bin/sh
# Installed as /usr/local/bin/apt-get (ahead of /usr/bin on PATH) in the Mesh devcontainer image, so the devcontainer features
# (docker-in-docker, sshd) that call `apt-get` pick it up. Builds run apt as-is first. Only if that FAILS with a name-resolution
# error (GitHub's build network sometimes returns IPv6-only DNS answers with no IPv6 route: "Could not resolve archive.ubuntu.com")
# does it retry with IPv4 forced, with retries, and then carry on. A failure of any other kind is returned untouched.
REAL="${VYOMI_REAL_APT_GET:-/usr/bin/apt-get}"
OUT="$(mktemp 2>/dev/null || echo /tmp/apt-get-fallback.$$)"
"$REAL" "$@" >"$OUT" 2>&1; rc=$?
cat "$OUT"
if [ "$rc" -ne 0 ] && grep -Eq "Could not resolve|Temporary failure resolving|Failed to fetch.*(resolve|connect)|Network is unreachable" "$OUT"; then
  echo "[vyomi-mesh] apt-get failed on name resolution; retrying with IPv4 forced" >&2
  rm -f "$OUT"
  { printf 'precedence ::ffff:0:0/96 100\n' >> /etc/gai.conf; } 2>/dev/null || true
  exec "$REAL" -o Acquire::ForceIPv4=true -o Acquire::Retries=5 "$@"
fi
rm -f "$OUT"
exit "$rc"
