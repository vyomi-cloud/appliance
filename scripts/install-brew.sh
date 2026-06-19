#!/usr/bin/env bash
# ----------------------------------------------------------------------------
# One-shot Homebrew install of Vyomi on macOS.
# Handles Homebrew's third-party tap-trust security gate, installs the
# coreutils prereq (gives `gtimeout` so the launcher can't hang at
# "packaging source"), then installs vyomi.
#
# Run:   scripts/install-brew.sh           # tap + trust + install
#        scripts/install-brew.sh --up      # ...and then run `vyomi up`
# ----------------------------------------------------------------------------
set -euo pipefail

TAP="vyomi-cloud/tap"
FORMULA="vyomi-cloud/tap/vyomi"

say(){ printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
ok(){  printf '    \033[32m✓\033[0m %s\n' "$*"; }

command -v brew >/dev/null 2>&1 || {
  echo "Homebrew not found. Install it first: https://brew.sh"; exit 1; }

say "Tapping ${TAP}"
brew tap "$TAP" 2>/dev/null || true
ok "tapped"

# Newer Homebrew refuses to load formulae from third-party taps until the tap
# is explicitly trusted. `brew trust` only exists on those versions; on older
# Homebrew the commands no-op and we just move on.
say "Trusting ${TAP} (Homebrew tap-trust security gate)"
brew trust "$TAP" 2>/dev/null \
  || brew trust --formula "$FORMULA" 2>/dev/null \
  || echo "    (no 'brew trust' needed on this Homebrew version)"
ok "tap trusted"

say "Installing coreutils (gtimeout → launcher timeouts work, no 'packaging source' hang)"
brew install coreutils
ok "coreutils installed"

say "Installing vyomi"
brew install "$FORMULA"
ok "vyomi installed"

if [ "${1:-}" = "--up" ]; then
  say "Launching appliance"
  vyomi up
else
  cat <<'EOF'

Done. Next:

    vyomi up

EOF
fi
