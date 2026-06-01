#!/bin/sh
# Run after the .deb is installed. Best-effort — never fail the install.
set -e

if ! command -v multipass >/dev/null 2>&1; then
  echo
  echo "==> Note: Multipass not detected."
  echo "    CloudLearn appliance mode requires Multipass for VM provisioning."
  echo "    Install via:  sudo snap install multipass"
  echo "    Or:           https://multipass.run/install"
  echo
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "==> Note: docker not detected on host. The appliance VM will install"
  echo "    its own docker engine on first 'cloud-learn up'."
fi

echo "==> CloudLearn installed. Run 'cloud-learn up' to start the simulator."
echo "==> Docs: https://github.com/cloudlearn/cloud-learn"

exit 0
