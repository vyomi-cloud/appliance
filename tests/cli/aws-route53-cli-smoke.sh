#!/usr/bin/env bash
# Real aws-cli Route 53 smoke against Vyomi — the unmodified binary with only
# --endpoint-url pointed at the appliance. One [PASS]/[FAIL] line per check.
#
#   ENDPOINT=http://127.0.0.1:9000 bash tests/cli/aws-route53-cli-smoke.sh
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_PAGER=""

if ! command -v aws >/dev/null 2>&1; then
    echo "[FAIL] aws-cli is not installed"
    exit 1
fi

pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: $3"; fail=$((fail+1)); fi; }
r53() { aws route53 --endpoint-url "$BASE" "$@" 2>&1; }
# q <expected-substring> <description> <aws args...>: run and look for a substring.
q() { local want="$1" what="$2"; shift 2; local out; out=$(r53 "$@"); local rc=$?
      if [ $rc -eq 0 ] && { [ -z "$want" ] || printf '%s' "$out" | grep -q -- "$want"; }; then chk 0 "$what"; else chk 1 "$what" "$(printf '%s' "$out" | head -c 300)"; fi; }
# v <description> <aws args...>: run, expect success, result text in $OUT.
v() { local what="$1"; shift; OUT=$(r53 "$@"); local rc=$?
      if [ $rc -eq 0 ]; then chk 0 "$what"; else chk 1 "$what" "$(printf '%s' "$OUT" | head -c 300)"; OUT=""; fi; }
# f <expected-error-substring> <description> <aws args...>: expect failure with a message.
f() { local want="$1" what="$2"; shift 2; local out; out=$(r53 "$@"); local rc=$?
      if [ $rc -ne 0 ] && printf '%s' "$out" | grep -q -- "$want"; then chk 0 "$what"; else chk 1 "$what" "$(printf '%s' "$out" | head -c 300)"; fi; }

SFX=$(date +%s | tail -c 6)
ZONE="cli-$SFX.example.com"
echo "== aws route53 against $BASE =="
aws --version 2>&1 | head -1

v "create-hosted-zone" create-hosted-zone --name "$ZONE" --caller-reference "cli-$SFX" \
  --hosted-zone-config Comment=cli-smoke --query 'HostedZone.Id' --output text
ZID="${OUT##*/}"
q "$ZONE." "get-hosted-zone returns the name" get-hosted-zone --id "$ZID"
q "awsdns" "zone has AWS-style name servers" get-hosted-zone --id "$ZID" --query 'DelegationSet.NameServers' --output text
q "$ZID" "list-hosted-zones contains it" list-hosted-zones
q "$ZID" "list-hosted-zones-by-name" list-hosted-zones-by-name --dns-name "$ZONE"
q "2" "new zone has SOA + NS (2 records)" get-hosted-zone --id "$ZID" --query 'HostedZone.ResourceRecordSetCount' --output text
f "HostedZoneAlreadyExists" "duplicate caller reference is rejected" create-hosted-zone --name "$ZONE" --caller-reference "cli-$SFX"
f "NoSuchHostedZone" "unknown zone is NoSuchHostedZone" get-hosted-zone --id ZDOESNOTEXIST

BATCH=$(cat <<JSON
{"Comment":"smoke","Changes":[
 {"Action":"CREATE","ResourceRecordSet":{"Name":"www.$ZONE","Type":"A","TTL":300,"ResourceRecords":[{"Value":"192.0.2.10"},{"Value":"192.0.2.11"}]}},
 {"Action":"CREATE","ResourceRecordSet":{"Name":"mail.$ZONE","Type":"MX","TTL":300,"ResourceRecords":[{"Value":"10 mx.$ZONE"}]}},
 {"Action":"CREATE","ResourceRecordSet":{"Name":"txt.$ZONE","Type":"TXT","TTL":60,"ResourceRecords":[{"Value":"\"v=spf1 -all\""}]}}]}
JSON
)
v "change-resource-record-sets (CREATE x3)" change-resource-record-sets --hosted-zone-id "$ZID" --change-batch "$BATCH" --query 'ChangeInfo.Id' --output text
CHG="${OUT##*/}"
q "INSYNC" "get-change reports INSYNC" get-change --id "$CHG" --query 'ChangeInfo.Status' --output text
q "192.0.2.10" "list-resource-record-sets shows the A record" list-resource-record-sets --hosted-zone-id "$ZID"
q "www.$ZONE." "list-resource-record-sets --start-record-name" list-resource-record-sets --hosted-zone-id "$ZID" --start-record-name "www.$ZONE" --start-record-type A --max-items 1
f "InvalidChangeBatch" "CREATE of an existing record is InvalidChangeBatch" change-resource-record-sets --hosted-zone-id "$ZID" --change-batch "$BATCH"
UPS='{"Changes":[{"Action":"UPSERT","ResourceRecordSet":{"Name":"www.'"$ZONE"'","Type":"A","TTL":120,"ResourceRecords":[{"Value":"192.0.2.99"}]}}]}'
v "UPSERT replaces the record" change-resource-record-sets --hosted-zone-id "$ZID" --change-batch "$UPS"
q "192.0.2.99" "upserted value is returned" test-dns-answer --hosted-zone-id "$ZID" --record-name "www.$ZONE" --record-type A
q "NXDOMAIN" "test-dns-answer for a missing name is NXDOMAIN" test-dns-answer --hosted-zone-id "$ZID" --record-name "nope.$ZONE" --record-type A --query ResponseCode --output text

v "change-tags-for-resource" change-tags-for-resource --resource-type hostedzone --resource-id "$ZID" --add-tags Key=env,Value=cli
q "cli" "list-tags-for-resource" list-tags-for-resource --resource-type hostedzone --resource-id "$ZID"
v "update-hosted-zone-comment" update-hosted-zone-comment --id "$ZID" --comment "updated"
q "updated" "comment is updated" get-hosted-zone --id "$ZID" --query 'HostedZone.Config.Comment' --output text
q "" "get-hosted-zone-count" get-hosted-zone-count

v "create-health-check" create-health-check --caller-reference "hc-$SFX" \
  --health-check-config "Type=HTTPS,FullyQualifiedDomainName=www.$ZONE,ResourcePath=/health,Port=443"
HC=$(printf '%s' "$OUT" | python3 -c 'import sys,json; print(json.load(sys.stdin)["HealthCheck"]["Id"])' 2>/dev/null)
q "/health" "get-health-check" get-health-check --health-check-id "$HC"
q "$HC" "list-health-checks" list-health-checks
q "Observations" "get-health-check-status" get-health-check-status --health-check-id "$HC"
v "update-health-check" update-health-check --health-check-id "$HC" --failure-threshold 5
q "5" "failure threshold updated" get-health-check --health-check-id "$HC" --query 'HealthCheck.HealthCheckConfig.FailureThreshold' --output text
v "delete-health-check" delete-health-check --health-check-id "$HC"
f "NoSuchHealthCheck" "deleted health check is gone" get-health-check --health-check-id "$HC"

f "HostedZoneNotEmpty" "non-empty zone cannot be deleted" delete-hosted-zone --id "$ZID"
DEL=$(cat <<JSON
{"Changes":[
 {"Action":"DELETE","ResourceRecordSet":{"Name":"www.$ZONE","Type":"A","TTL":120,"ResourceRecords":[{"Value":"192.0.2.99"}]}},
 {"Action":"DELETE","ResourceRecordSet":{"Name":"mail.$ZONE","Type":"MX","TTL":300,"ResourceRecords":[{"Value":"10 mx.$ZONE"}]}},
 {"Action":"DELETE","ResourceRecordSet":{"Name":"txt.$ZONE","Type":"TXT","TTL":60,"ResourceRecords":[{"Value":"\"v=spf1 -all\""}]}}]}
JSON
)
v "change-resource-record-sets (DELETE x3)" change-resource-record-sets --hosted-zone-id "$ZID" --change-batch "$DEL"
v "delete-hosted-zone" delete-hosted-zone --id "$ZID"
f "NoSuchHostedZone" "deleted zone is gone" get-hosted-zone --id "$ZID"

echo "== $pass passed, $fail failed =="
[ "$fail" -eq 0 ]
