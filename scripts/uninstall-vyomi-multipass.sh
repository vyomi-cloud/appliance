#!/usr/bin/env bash
# ----------------------------------------------------------------------------
# Clean uninstall of Vyomi + Multipass on macOS.
# DESTROYS all multipass VMs and removes all Vyomi state — for a clean slate.
#
# Run:   bash ~/uninstall-vyomi-multipass.sh          (asks to confirm)
#        bash ~/uninstall-vyomi-multipass.sh -y       (skip the prompt)
#
# Steps 5–6 use sudo and will prompt for your macOS password.
# ----------------------------------------------------------------------------
set -u

say(){ printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
ok(){  printf '    \033[32m✓\033[0m %s\n' "$*"; }
warn(){ printf '    \033[33m!\033[0m %s\n' "$*"; }

# ── confirmation ────────────────────────────────────────────────────────────
if [ "${1:-}" != "-y" ]; then
  echo "This will DESTROY all multipass VMs and completely remove Vyomi + Multipass."
  echo "Current VMs:"
  multipass list 2>/dev/null || echo "  (multipass not reachable)"
  printf "\nType 'yes' to continue: "
  read -r ans
  [ "$ans" = "yes" ] || { echo "Aborted."; exit 1; }
fi

# ── 1. host loopback bridge ─────────────────────────────────────────────────
say "1/6  Stopping host loopback bridge(s)"
pkill -f 'socat.*94' 2>/dev/null || true
ok "socat bridges stopped"

# ── 2. destroy all multipass VMs ────────────────────────────────────────────
say "2/6  Destroying all multipass VMs"
if command -v multipass >/dev/null 2>&1; then
  multipass delete --all --purge 2>/dev/null \
    || { multipass delete --all 2>/dev/null; multipass purge 2>/dev/null; }
  multipass list 2>/dev/null || true
  ok "VMs deleted + purged"
else
  warn "multipass not on PATH — skipping VM deletion"
fi

# ── 3. uninstall vyomi (brew) + untap ───────────────────────────────────────
say "3/6  Uninstalling vyomi + removing tap"
brew uninstall vyomi 2>/dev/null || true
brew uninstall cloud-learn 2>/dev/null || true
brew untap vyomi-cloud/tap 2>/dev/null || true
ok "vyomi uninstalled, tap removed"

# ── 4. remove vyomi state / keys / config ───────────────────────────────────
say "4/6  Removing vyomi state, SSH keys, config"
rm -rf "$HOME/.vyomi" "$HOME/.cloud-learn" "$HOME/.cloudlearn"
rm -f  "$HOME/.ssh/vyomi_ed25519" "$HOME/.ssh/vyomi_ed25519.pub"
rm -rf "$HOME/.config/vyomi"
ok "state, keys, config removed"

# ── 5. uninstall multipass (cask) ───────────────────────────────────────────
say "5/6  Uninstalling multipass (Homebrew cask)"
brew uninstall --cask multipass 2>/dev/null || true
ok "multipass cask uninstalled"

# ── 6. residue cleanup (sudo) ───────────────────────────────────────────────
say "6/6  Residue cleanup (sudo — may prompt for your password)"
sudo launchctl bootout system /Library/LaunchDaemons/com.canonical.multipassd.plist 2>/dev/null || true
sudo rm -f  /Library/LaunchDaemons/com.canonical.multipassd.plist
sudo rm -rf "/Library/Application Support/com.canonical.multipass" \
            "/var/root/Library/Application Support/multipassd" \
            "$HOME/Library/Application Support/multipass" \
            "$HOME/Library/Application Support/multipass-client" \
            "/Applications/Multipass.app" \
            /usr/local/bin/multipass /opt/homebrew/bin/multipass 2>/dev/null || true
for p in com.canonical.multipass.multipassd \
         com.canonical.multipass.multipass \
         com.canonical.multipass.multipass_gui; do
  sudo pkgutil --forget "$p" 2>/dev/null || true
done
ok "residue cleaned + pkg receipts forgotten"

# ── verification ────────────────────────────────────────────────────────────
say "Verification"
if which vyomi cloud-learn multipass 2>/dev/null; then
  warn "some binaries still on PATH (above) — open a new shell and re-check"
else
  ok "no vyomi/multipass binaries on PATH"
fi
if ls -d "$HOME/.vyomi" "$HOME/.cloud-learn" 2>/dev/null; then
  warn "some state dirs remain (above)"
else
  ok "all state dirs removed"
fi

cat <<'EOF'

Clean slate done. To reinstall (install coreutils FIRST so the launcher's
timeouts work and it can't hang at "packaging source"):

    brew install coreutils
    brew install vyomi-cloud/tap/vyomi
    vyomi up

EOF
