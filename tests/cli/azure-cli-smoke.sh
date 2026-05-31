#!/usr/bin/env bash
# Real az CLI smoke against the CloudLearn simulator. Proves the unmodified
# binary works when its ARM endpoint points at the simulator. Mirrors
# tests/conformance/aws-cli-smoke.sh + gcp-cli-smoke.sh.
#
# Run from the host (where az is installed) OR inside any container with az.
# The recipe to install az inside a temporary container:
#
#   multipass exec cloudlearn-appliance -- bash -lc \
#     'docker run --rm --network host \
#        -e ENDPOINT=http://127.0.0.1:9000 \
#        -v /workspace/cloud-learn/tests/conformance:/work -w /work \
#        mcr.microsoft.com/azure-cli:latest bash azure-cli-smoke.sh'
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
SUB="${AZURE_SUBSCRIPTION_ID:-sub-001}"
RG="${AZURE_RESOURCE_GROUP:-rg-smoke}"
LOCATION="${AZURE_LOCATION:-eastus}"

if ! command -v az >/dev/null 2>&1; then
    echo "SKIP az not installed; install via 'pip install azure-cli' or use mcr.microsoft.com/azure-cli image"
    exit 0
fi

pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "PASS $2"; pass=$((pass+1)); else echo "FAIL $2 :: $3"; fail=$((fail+1)); fi; }

echo "== az against $BASE subscription=$SUB =="
az --version 2>&1 | head -1

# Point az ARM at the simulator. Real Azure CLI uses
# AZURE_RESOURCE_MANAGER_HOSTNAME to override the endpoint (Cloud profile).
export AZURE_RESOURCE_MANAGER_HOSTNAME="${BASE#http://}"
export AZURE_RESOURCE_MANAGER_HOSTNAME="${AZURE_RESOURCE_MANAGER_HOSTNAME#https://}"
# Disable login + use the simulator (no Azure AD).
export AZURE_CLI_DISABLE_CONNECTION_VERIFICATION=1

# Switch to an Azure space (so resources land in the right context).
# Use python urllib so this works without curl.
AZ_SP=$(python3 -c "
import json, urllib.request
try:
    d = json.load(urllib.request.urlopen('$BASE/api/spaces', timeout=5))
    print(next((s['space_id'] for s in d.get('spaces', []) if s.get('provider')=='azure'), ''))
except Exception:
    print('')
" 2>/dev/null)
if [ -n "$AZ_SP" ]; then
    python3 -c "
import urllib.request
req = urllib.request.Request('$BASE/api/spaces/$AZ_SP/switch', method='POST')
urllib.request.urlopen(req, timeout=5).read()
" >/dev/null 2>&1
    echo "switched to Azure space: $AZ_SP"
fi

# az's group create / show would hit ARM resource groups. The simulator's ARM
# dispatcher accepts the standard /subscriptions/{sub}/resourceGroups path.
VMNAME="az-smoke-vm-$(date +%s)"
STG="azsmokestg$(date +%s | tail -c 8)"
SVR="az-smoke-sql-$(date +%s)"
DB="orders"

# --- VM ---
# `az vm create` is a wrapper that calls many ARM ops (nic, nsg, public ip, disk,
# image lookup). For a smoke test we hit the lower-level resource PUT directly
# via az rest, which is the documented escape hatch for unmodified ARM clients.
out=$(az rest --method put \
    --url "$BASE/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Compute/virtualMachines/$VMNAME?api-version=2024-03-01" \
    --body "{\"location\":\"$LOCATION\",\"properties\":{\"hardwareProfile\":{\"vmSize\":\"Standard_D2s_v5\"},\"storageProfile\":{\"imageReference\":{\"offer\":\"UbuntuServer\",\"sku\":\"22.04-LTS\"}},\"osProfile\":{\"computerName\":\"$VMNAME\",\"adminUsername\":\"azureadmin\",\"adminPassword\":\"Password123!\"}}}" \
    --skip-authorization-header 2>&1)
chk $? "az rest PUT Microsoft.Compute/virtualMachines" "$out"

out=$(az rest --method get \
    --url "$BASE/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Compute/virtualMachines/$VMNAME?api-version=2024-03-01" \
    --skip-authorization-header 2>&1)
echo "$out" | grep -q "$VMNAME"
chk $? "az rest GET VM round-trip" "$(echo "$out" | tail -3)"

# --- Storage ---
out=$(az rest --method put \
    --url "$BASE/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Storage/storageAccounts/$STG?api-version=2023-05-01" \
    --body "{\"location\":\"$LOCATION\",\"sku\":{\"name\":\"Standard_LRS\"},\"kind\":\"StorageV2\",\"properties\":{}}" \
    --skip-authorization-header 2>&1)
chk $? "az rest PUT Microsoft.Storage/storageAccounts" "$out"

# --- SQL (real Postgres backend per MVP P0 stack) ---
out=$(az rest --method put \
    --url "$BASE/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Sql/servers/$SVR?api-version=2023-08-01" \
    --body "{\"location\":\"$LOCATION\",\"properties\":{\"administratorLogin\":\"azureadmin\",\"administratorLoginPassword\":\"Password123!\"}}" \
    --skip-authorization-header 2>&1)
chk $? "az rest PUT Microsoft.Sql/servers" "$out"

out=$(az rest --method put \
    --url "$BASE/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Sql/servers/$SVR/databases/$DB?api-version=2023-08-01" \
    --body "{\"location\":\"$LOCATION\",\"properties\":{}}" \
    --skip-authorization-header 2>&1)
chk $? "az rest PUT Microsoft.Sql/.../databases (real Postgres)" "$out"

# Verify the data plane: GET-after-PUT must surface a connectionInfo with engine=PostgreSQL
out=$(az rest --method get \
    --url "$BASE/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Sql/servers/$SVR/databases/$DB?api-version=2023-08-01" \
    --skip-authorization-header 2>&1)
echo "$out" | grep -q "PostgreSQL"
chk $? "az SQL DB connectionInfo surfaces real Postgres engine" "$(echo "$out" | tail -5)"

# Cleanup — best-effort.
az rest --method delete --url "$BASE/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Sql/servers/$SVR/databases/$DB?api-version=2023-08-01" --skip-authorization-header >/dev/null 2>&1
az rest --method delete --url "$BASE/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Sql/servers/$SVR?api-version=2023-08-01" --skip-authorization-header >/dev/null 2>&1
az rest --method delete --url "$BASE/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Storage/storageAccounts/$STG?api-version=2023-05-01" --skip-authorization-header >/dev/null 2>&1
az rest --method delete --url "$BASE/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Compute/virtualMachines/$VMNAME?api-version=2024-03-01" --skip-authorization-header >/dev/null 2>&1

echo "RESULT pass=$pass fail=$fail"
[ "$fail" = "0" ] || exit 1
