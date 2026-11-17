#!/bin/sh
# usage: run.sh <tofu args...>  (OpenTofu in Linux; provider cache shared outside the repo).
# azurerm needs HTTPS: front.py (this dir) fronts the simulator; its cert is trusted via SSL_CERT_FILE.
# Storage data plane is host-style ({acct}.blob.core.windows.net:<front-port>): every account the estate creates is mapped to the host.
CERT="${VYOMI_AZURE_CERT:-$HOME/.vyomi-endurance-azure/cert.pem}"
HOSTS=""
for a in ${VYOMI_AZURE_STORAGE_ACCOUNTS:-stendurancedata stendurancelogs stendurancefunc}; do
  for s in blob queue table file dfs web; do HOSTS="$HOSTS --add-host $a.$s.core.windows.net:host-gateway"; done
done
cd "$(dirname "$0")" && docker run --rm $HOSTS -v "$PWD":/w -w /w -v "${VYOMI_PLUGIN_CACHE:-$HOME/.vyomi-endurance/plugin-cache}":/cache -v "$CERT":/cert.pem:ro -e SSL_CERT_FILE=/cert.pem -e TF_PLUGIN_CACHE_DIR=/cache -e TF_IN_AUTOMATION=1 -e TF_LOG ghcr.io/opentofu/opentofu:latest "$@" -no-color
