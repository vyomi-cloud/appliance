#!/bin/sh
# Run after the .deb is installed. Best-effort — never fail the install.
set -e

if ! command -v multipass >/dev/null 2>&1; then
  echo
  echo "==> Note: Multipass not detected."
  echo "    Vyomi appliance mode requires Multipass for VM provisioning."
  echo "    Install via:  sudo snap install multipass"
  echo "    Or:           https://multipass.run/install"
  echo
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "==> Note: docker not detected on host. The appliance VM will install"
  echo "    its own docker engine on first 'cloud-learn up'."
fi

echo "==> CloudLearn installed. Run 'cloud-learn up' to start the simulator."
echo "==> Docs: https://github.com/vyomi-cloud/appliance"

# ── Install-funnel phone-home (anonymous, opt-out via VYOMI_NO_TELEMETRY) ──
# Marks this install as DOWNLOADED with channel=deb at https://vyomi.cloud/.
# Fail-soft: a missing curl, a 5xx, a DNS failure — all swallowed. We
# background it via `&` + disown so a slow network can't extend the apt
# install. The 3s curl timeout inside the script bounds total work.
PHONE_HOME="/usr/share/vyomi/packaging/common/phone-home.sh"
[ -x "$PHONE_HOME" ] || PHONE_HOME="/opt/vyomi/packaging/common/phone-home.sh"
if [ -x "$PHONE_HOME" ]; then
  ( sh "$PHONE_HOME" deb >/dev/null 2>&1 & ) || true
fi

exit 0
