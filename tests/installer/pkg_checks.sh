#!/usr/bin/env bash
# Install → check → uninstall one Vyomi package, the way a user would.
#
#   pkg_checks.sh deb  <file.deb>  <version> <outdir>     (Debian/Ubuntu host, sudo)
#   pkg_checks.sh rpm  <file.rpm>  <version> <outdir>     (Fedora/RHEL host, root)
#   pkg_checks.sh brew <formula>   <version> <outdir>     (macOS, Homebrew; formula
#                                                          from vyomi-cloud/tap)
# Prints PASS/FAIL per check, appends a section to <outdir>/summary.md and
# exits 1 if any check failed. Telemetry is off: test installs must not count.
set -uo pipefail
KIND="$1"; PKG="$2"; VER="$3"; OUT="$4"
mkdir -p "$OUT"
export VYOMI_NO_TELEMETRY=1 HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_INSTALL_CLEANUP=1 DEBIAN_FRONTEND=noninteractive
NAME=$(basename "$PKG")
pass=0; fail=0; ROWS=""
check() {  # check "<name>" <exit-code> "<detail>"
  local ok=$([ "$2" = "0" ] && echo PASS || echo FAIL)
  echo "$ok: $1${3:+ — $3}"
  [ "$ok" = PASS ] && pass=$((pass+1)) || fail=$((fail+1))
  ROWS+="| $([ "$ok" = PASS ] && echo ✅ || echo ❌) | $1 | ${3//|/\\|} |"$'\n'
}
SUDO=""; [ "$(id -u)" != 0 ] && SUDO="sudo -E"

# ── Install ───────────────────────────────────────────────────────────────
t0=$(date +%s)
case "$KIND" in
  deb)  out=$($SUDO apt-get install -y "$(realpath "$PKG")" 2>&1); rc=$? ;;
  rpm)  out=$(dnf install -y "$(realpath "$PKG")" 2>&1); rc=$? ;;
  brew) out=$(brew install "vyomi-cloud/tap/$PKG" 2>&1); rc=$? ;;
esac
echo "$out" > "$OUT/$NAME-install.log"
check "install $NAME" "$rc" "$(( $(date +%s) - t0 ))s$([ "$rc" != 0 ] && echo "; $(echo "$out" | tail -1)")"

# ── Installed version + files ─────────────────────────────────────────────
case "$KIND" in
  deb)  pname=$(dpkg-deb -f "$PKG" Package); iv=$(dpkg-query -W -f '${Version}' "$pname" 2>/dev/null)
        root=$(dpkg -L "$pname" 2>/dev/null | grep -E '/VERSION$' | sort -r -k1,1 | grep -m1 -E '/lib/cloud-learn/VERSION$|/VERSION$' | xargs -r dirname) ;;
  rpm)  pname=$(rpm -qp --qf '%{NAME}' "$PKG"); iv=$(rpm -q --qf '%{VERSION}' "$pname" 2>/dev/null)
        root=$(rpm -ql "$pname" 2>/dev/null | grep -E '/VERSION$' | grep -m1 -E '/lib/cloud-learn/VERSION$|/VERSION$' | xargs -r dirname) ;;
  brew) pname="$PKG"; iv=$(brew list --versions "$PKG" 2>/dev/null | awk '{print $2}')
        root="$(brew --prefix "$PKG" 2>/dev/null)/libexec" ;;
esac
[ "${iv%%-*}" = "$VER" ]; check "package manager reports version $VER" $? "found '${iv:-none}'"
if [[ "$NAME" == *vyomi-docker* ]]; then
  # Thin Docker-substrate package: launcher + the pull-only compose file only.
  case "$KIND" in
    deb)  cf=$(dpkg -L "$pname" 2>/dev/null | grep -E 'docker-compose\.cloudlite\.yml$' | head -1) ;;
    rpm)  cf=$(rpm -ql "$pname" 2>/dev/null | grep -E 'docker-compose\.cloudlite\.yml$' | head -1) ;;
    brew) cf="$(brew --prefix "$PKG" 2>/dev/null)/share/vyomi-docker/docker-compose.cloudlite.yml" ;;
  esac
  [ -n "${cf:-}" ] && [ -f "$cf" ]; check "ships docker-compose.cloudlite.yml" $? "${cf:-not found}"
elif [ -n "${root:-}" ] && [ -f "$root/VERSION" ]; then
  fv=$(tr -d '[:space:]' < "$root/VERSION"); [ "$fv" = "$VER" ]; check "bundled VERSION is $VER" $? "$root/VERSION = $fv"
else
  check "bundled VERSION file present" 1 "no VERSION under ${root:-?}"
fi

# ── Launcher on PATH ──────────────────────────────────────────────────────
v=$(command -v vyomi); [ -n "$v" ]; check "'vyomi' on PATH" $? "${v:-not found}"
if [ -n "$v" ]; then
  h=$(vyomi help 2>&1); rc=$?; echo "$h" > "$OUT/$NAME-help.txt"
  [ "$rc" = 0 ] && [ -n "$h" ]; check "vyomi help runs" $? "exit $rc; $(echo "$h" | head -1)"
  d=$(vyomi doctor 2>&1); rc=$?; echo "$d" > "$OUT/$NAME-doctor.txt"
  [ -n "$d" ]; check "vyomi doctor runs" $? "exit $rc; $(echo "$d" | head -1)"
fi
# ── vyomi commands ────────────────────────────────────────────────────────
# Every launcher command, run as a user would but against a stub `docker` (it
# records the compose calls), with a throwaway HOME. A real `vyomi up` is the
# Startup check's job. `update` hits the real GitHub release + SHA256SUMS.
if [ -n "$v" ]; then
  CT=$(mktemp -d); mkdir -p "$CT/bin" "$CT/home"
  printf '#!/bin/sh\necho "docker $*" >> "%s/docker.log"; exit 0\n' "$CT" > "$CT/bin/docker"; chmod +x "$CT/bin/docker"
  vy() { env HOME="$CT/home" PATH="$CT/bin:$PATH" VYOMI_SUBSTRATE=docker VYOMI_NO_BANNER=1 CI=1 \
           VYOMI_URL=http://127.0.0.1:9 VYOMI_NO_SELF_UPDATE=1 "$@"; }
  pin() { sed -nE 's#.*vyomi/appliance:([0-9]+\.[0-9]+\.[0-9]+).*#\1#p' "$1" 2>/dev/null | head -1; }
  LATEST=$(curl -fsSL --max-time 15 "https://api.github.com/repos/vyomi-cloud/appliance/releases/latest" 2>/dev/null \
    | sed -nE 's/.*"tag_name": *"v?([0-9]+\.[0-9]+\.[0-9]+)".*/\1/p' | head -1)

  for flag in --version version -V; do
    o=$(vy vyomi "$flag" 2>&1); rc=$?; echo "$o" > "$OUT/$NAME-version$flag.txt"
    [ "$rc" = 0 ] && echo "$o" | head -1 | grep -q "^vyomi $VER "; check "vyomi $flag reports $VER" $? "exit $rc; $(echo "$o" | head -1)"
  done
  o=$(vy vyomi --version 2>&1)
  echo "$o" | grep -q 'simulator : not running'; check "vyomi --version shows the simulator state" $? "$(echo "$o" | grep 'simulator' | head -1)"
  h=$(vy vyomi help 2>&1)
  echo "$h" | grep -q update && echo "$h" | grep -q version; check "vyomi help lists update + version" $? ""

  : > "$CT/docker.log"; o=$(vy vyomi status 2>&1); rc=$?
  [ "$rc" = 0 ] && grep -q 'compose .*cloudlite.yml.* ps' "$CT/docker.log"; check "vyomi status → docker compose ps" $? "exit $rc"
  : > "$CT/docker.log"; o=$(vy vyomi logs 2>&1); rc=$?
  [ "$rc" = 0 ] && grep -q 'compose .* logs' "$CT/docker.log"; check "vyomi logs → docker compose logs" $? "exit $rc"
  : > "$CT/docker.log"; o=$(vy vyomi down 2>&1); rc=$?
  [ "$rc" = 0 ] && grep -q 'compose .* down' "$CT/docker.log"; check "vyomi down → docker compose down" $? "exit $rc"

  # update: moves to the latest release (pulls its images) ...
  rm -rf "$CT/home/.vyomi"; : > "$CT/docker.log"
  o=$(vy vyomi update 2>&1); rc=$?; echo "$o" > "$OUT/$NAME-update.txt"
  got=$(pin "$CT/home/.vyomi/docker-compose.cloudlite.yml"); [ -n "$got" ] || got="$VER"
  [ "$rc" = 0 ] && [ -n "$LATEST" ] && [ "$got" = "$LATEST" ] && grep -q "pull" "$CT/docker.log"
  check "vyomi update → latest release v${LATEST:-?}" $? "exit $rc; compose v$got; $(grep -m1 -E 'Updating|latest release' <<<"$o")"
  # ... and from an older install it fetches the newer compose (checksum-verified).
  if [[ "$NAME" == *vyomi-docker* ]] && [ -n "${cf:-}" ] && [ -f "$cf" ]; then
    sed -E 's#vyomi/appliance:[0-9.]+#vyomi/appliance:3.0.0#g' "$cf" > "$CT/old.yml"
    rm -rf "$CT/home/.vyomi"; : > "$CT/docker.log"
    o=$(vy VYOMI_BUNDLED_COMPOSE="$CT/old.yml" vyomi update 2>&1); rc=$?; echo "$o" > "$OUT/$NAME-update-from-old.txt"
    got=$(pin "$CT/home/.vyomi/docker-compose.cloudlite.yml")
    [ "$rc" = 0 ] && [ -n "$LATEST" ] && [ "$got" = "$LATEST" ] && grep -q '\.vyomi/docker-compose.cloudlite.yml.* pull' "$CT/docker.log"
    check "vyomi update from v3.0.0 → v${LATEST:-?} (SHA256-checked)" $? "exit $rc; cached compose v${got:-none}"
    o=$(vy VYOMI_BUNDLED_COMPOSE="$CT/old.yml" vyomi --version 2>&1)
    echo "$o" | grep -q "compose   : v$LATEST"; check "after update, vyomi runs the cached v${LATEST:-?}" $? "$(echo "$o" | grep compose)"
  fi
  rm -rf "$CT"
fi
if [ "$KIND" = brew ]; then
  out=$(brew test "$PKG" 2>&1); rc=$?; echo "$out" > "$OUT/$NAME-brew-test.log"
  check "brew test $PKG" "$rc" "$(echo "$out" | tail -1)"
fi

# ── Uninstall ─────────────────────────────────────────────────────────────
case "$KIND" in
  deb)  out=$($SUDO apt-get remove -y --purge "$pname" 2>&1); rc=$? ;;
  rpm)  out=$(dnf remove -y "$pname" 2>&1); rc=$? ;;
  brew) out=$(brew uninstall "$PKG" 2>&1); rc=$? ;;
esac
echo "$out" > "$OUT/$NAME-uninstall.log"
check "uninstall $pname" "$rc" "$(echo "$out" | tail -1)"
case "$KIND" in
  deb) left=$(dpkg-query -W "$pname" 2>/dev/null | wc -l) ;;
  rpm) left=$(rpm -q "$pname" >/dev/null 2>&1 && echo 1 || echo 0) ;;
  brew) left=$(brew list --versions "$PKG" 2>/dev/null | wc -l) ;;
esac
left=$(echo "$left" | tr -d '[:space:]')   # macOS wc pads with spaces
[ "$left" = 0 ] && [ -z "$(command -v vyomi)" ]; check "uninstall leaves no package and no 'vyomi' on PATH" $? "package entries: $left; vyomi: $(command -v vyomi || echo none)"

{ echo "#### $KIND · \`$NAME\` — $pass/$((pass+fail)) passed"; echo
  echo "| | Check | Detail |"; echo "|---|---|---|"; printf '%s' "$ROWS"; echo; } >> "$OUT/summary.md"
echo "$KIND $NAME: $pass/$((pass+fail)) checks passed"
[ "$fail" = 0 ]
