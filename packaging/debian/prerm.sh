#!/bin/sh
# Run before .deb removal. Stop the appliance VM cleanly if running.
set -e

if command -v cloud-learn >/dev/null 2>&1; then
  cloud-learn down >/dev/null 2>&1 || true
fi

exit 0
