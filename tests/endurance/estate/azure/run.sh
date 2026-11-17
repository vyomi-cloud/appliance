#!/bin/sh
# usage: run.sh <tofu args...>  (OpenTofu in Linux; provider cache shared outside the repo).
# azurerm needs HTTPS: front.py (this dir) fronts the simulator; its cert is trusted via SSL_CERT_FILE.
CERT="${VYOMI_AZURE_CERT:-$HOME/.vyomi-endurance-azure/cert.pem}"
cd "$(dirname "$0")" && docker run --rm -v "$PWD":/w -w /w -v "${VYOMI_PLUGIN_CACHE:-$HOME/.vyomi-endurance/plugin-cache}":/cache -v "$CERT":/cert.pem:ro -e SSL_CERT_FILE=/cert.pem -e TF_PLUGIN_CACHE_DIR=/cache -e TF_IN_AUTOMATION=1 -e TF_LOG ghcr.io/opentofu/opentofu:latest "$@" -no-color
