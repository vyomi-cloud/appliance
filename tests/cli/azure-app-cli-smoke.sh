#!/usr/bin/env bash
# Real `az` CLI against Vyomi's Azure Container Apps (Microsoft.App) ARM API — endpoint override only.
# `az rest` is the Azure CLI's documented client for any ARM resource provider, so every call goes
# through the unmodified binary. ENDPOINT (default http://127.0.0.1:9000), SUB. One [PASS]/[FAIL] per check.
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
SUB="${AZURE_SUBSCRIPTION_ID:-00000000-0000-0000-0000-cloudlearn01}"
RG="rg-cli-app-$(date +%s)"
ENVN="cae-cli"; APP="web-cli"; JOB="job-cli"
API="api-version=2024-03-01"
P="$BASE/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.App"
pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: $3"; fail=$((fail+1)); fi; }

if ! command -v az >/dev/null 2>&1; then echo "[FAIL] az CLI not installed"; exit 1; fi
echo "== az rest against $BASE sub=$SUB rg=$RG =="
az --version 2>&1 | head -1
export AZURE_CORE_COLLECT_TELEMETRY=false AZURE_CORE_NO_COLOR=true
rest() { az rest --skip-authorization-header --only-show-errors "$@" 2>&1; }

out=$(rest --method put --url "$P/managedEnvironments/$ENVN?$API" --body '{"location":"eastus","properties":{"zoneRedundant":false}}')
chk $? "az rest PUT managedEnvironments" "$out"
echo "$out" | grep -q '"defaultDomain"' && echo "$out" | grep -q '"staticIp"'
chk $? "environment has defaultDomain + staticIp" "$(echo "$out" | head -5)"
ENV_ID=$(echo "$out" | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])' 2>/dev/null)

BODY='{"location":"eastus","properties":{"managedEnvironmentId":"'"$ENV_ID"'","configuration":{"activeRevisionsMode":"Multiple","ingress":{"external":true,"targetPort":80},"secrets":[{"name":"db-pass","value":"s3cret"}]},"template":{"containers":[{"name":"web","image":"mcr.microsoft.com/k8se/quickstart:latest","resources":{"cpu":0.5,"memory":"1Gi"},"env":[{"name":"MODE","value":"cli"},{"name":"PASS","secretRef":"db-pass"}]}],"scale":{"minReplicas":1,"maxReplicas":4}}}}'
out=$(rest --method put --url "$P/containerApps/$APP?$API" --body "$BODY"); chk $? "az rest PUT containerApps" "$out"
echo "$out" | grep -q '"latestRevisionName"' && echo "$out" | grep -q '"fqdn"' && echo "$out" | grep -q '"provisioningState": "Succeeded"'
chk $? "app has latestRevisionName, ingress fqdn, Succeeded" "$(echo "$out" | head -5)"
REV=$(echo "$out" | python3 -c 'import sys,json; print(json.load(sys.stdin)["properties"]["latestRevisionName"])' 2>/dev/null)

out=$(rest --method get --url "$P/containerApps/$APP?$API"); echo "$out" | grep -q '"db-pass"' && ! echo "$out" | grep -q 's3cret'
chk $? "GET hides secret values" "$(echo "$out" | head -3)"
out=$(rest --method post --url "$P/containerApps/$APP/listSecrets?$API"); echo "$out" | grep -q 's3cret'
chk $? "POST listSecrets returns values" "$out"
out=$(rest --method get --url "$P/containerApps?$API"); echo "$out" | grep -q "\"$APP\""
chk $? "list containerApps in the resource group" "$out"
out=$(rest --method get --url "$BASE/subscriptions/$SUB/providers/Microsoft.App/containerApps?$API"); echo "$out" | grep -q "\"$APP\""
chk $? "list containerApps in the subscription" "$out"
out=$(rest --method get --url "$P/containerApps/$APP/revisions?$API"); echo "$out" | grep -q "$REV"
chk $? "list revisions includes $REV" "$out"
out=$(rest --method get --url "$P/containerApps/$APP/revisions/$REV/replicas?$API"); echo "$out" | grep -q '"runningState": "Running"'
chk $? "list replicas of the revision" "$out"
out=$(rest --method post --url "$P/containerApps/$APP/revisions/$REV/restart?$API"); chk $? "restart revision" "$out"
out=$(rest --method post --url "$P/containerApps/$APP/stop?$API"); chk $? "stop app" "$out"
out=$(rest --method get --url "$P/containerApps/$APP?$API"); echo "$out" | grep -q '"runningStatus": "Stopped"'
chk $? "runningStatus is Stopped" "$(echo "$out" | head -3)"
out=$(rest --method post --url "$P/containerApps/$APP/start?$API"); chk $? "start app" "$out"

out=$(rest --method put --url "$P/jobs/$JOB?$API" --body '{"location":"eastus","properties":{"environmentId":"'"$ENV_ID"'","configuration":{"triggerType":"Manual","replicaTimeout":300,"manualTriggerConfig":{"parallelism":1,"replicaCompletionCount":1}},"template":{"containers":[{"name":"job","image":"busybox:1.36","resources":{"cpu":0.25,"memory":"0.5Gi"}}]}}}')
chk $? "az rest PUT jobs" "$out"
out=$(rest --method post --url "$P/jobs/$JOB/start?$API" --body '{}'); chk $? "start job execution" "$out"
out=$(rest --method get --url "$P/jobs/$JOB/executions?$API"); echo "$out" | grep -q '"status": "Succeeded"'
chk $? "job executions list shows the run" "$out"

out=$(rest --method put --url "$P/containerApps/bad_name?$API" --body '{"location":"eastus"}'); echo "$out" | grep -q 'ContainerAppInvalidName'
chk $? "invalid app name → ContainerAppInvalidName" "$out"
out=$(rest --method delete --url "$P/managedEnvironments/$ENVN?$API"); echo "$out" | grep -q 'ManagedEnvironmentHasContainerApps'
chk $? "delete environment with apps is refused" "$out"
out=$(rest --method delete --url "$P/jobs/$JOB?$API"); chk $? "delete job" "$out"
out=$(rest --method delete --url "$P/containerApps/$APP?$API"); chk $? "delete app" "$out"
out=$(rest --method get --url "$P/containerApps/$APP?$API"); echo "$out" | grep -q 'ResourceNotFound'
chk $? "deleted app → ResourceNotFound" "$out"
out=$(rest --method delete --url "$P/managedEnvironments/$ENVN?$API"); chk $? "delete environment" "$out"

echo "== $pass passed, $fail failed =="
[ "$fail" = "0" ]
