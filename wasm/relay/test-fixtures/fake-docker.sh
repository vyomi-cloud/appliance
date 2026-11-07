#!/bin/sh
# Test double for the docker CLI used by core/booster_shell.py. Records argv; `exec` runs a local sh on the PTY we were given.
[ -n "$VYOMI_FAKE_DOCKER" ] && echo "$*" >> "$VYOMI_FAKE_DOCKER"
eval "last=\${$#}"
case "$1" in
  inspect)
    for a in "$@"; do last="$a"; done
    case "$last" in
      vyomi-i-good|vyomi-i-good2|vyomi-i-gcp1|vyomi-i-az1) echo 'true|1|vyomi-net ' ;;
      vyomi-i-vpc1) echo 'true|1|vyomi-net-sp1-vpc ' ;;
      vyomi-i-lookalike) echo 'true|1|vyomi-netx ' ;;
      vyomi-i-stopped) echo 'false|1|vyomi-net ' ;;
      vyomi-i-othernet) echo 'true|1|bridge ' ;;
      vyomi-i-nolabel) echo 'true||vyomi-net ' ;;
      *) echo "no such container" >&2; exit 1 ;;
    esac ;;
  exec)
    name=""
    for a in "$@"; do case "$a" in vyomi-i-*) name="$a" ;; esac; done
    echo "FAKE-VM:$name"
    exec sh ;;
  *) exit 2 ;;
esac
