#!/usr/bin/env bash
# Real aws-cli (cognito-idp) against Vyomi: unmodified binary, only --endpoint-url changed.
#   ENDPOINT=http://localhost:9000 bash tests/cli/aws-cognito-idp-cli-smoke.sh
# Prints one [PASS]/[FAIL] line per check; exits non-zero on any failure.
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}" AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}" AWS_PAGER=""
command -v aws >/dev/null 2>&1 || { echo "[FAIL] aws-cli not installed"; exit 1; }
pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: $3"; fail=$((fail+1)); fi; }
cg() { aws --endpoint-url "$BASE" cognito-idp "$@" 2>&1; }
jq_() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)"; }
SFX="$(date +%s)"

out=$(cg create-user-pool --pool-name "cli-pool-$SFX" --auto-verified-attributes email --output json)
PID=$(echo "$out" | jq_ "d['UserPool']['Id']" 2>/dev/null)
[ -n "$PID" ]; chk $? "create-user-pool" "$out"

out=$(cg describe-user-pool --user-pool-id "$PID" --output json)
echo "$out" | grep -q "cli-pool-$SFX"; chk $? "describe-user-pool" "$out"

out=$(cg list-user-pools --max-results 60 --output json)
echo "$out" | grep -q "$PID"; chk $? "list-user-pools contains the pool" "$out"

out=$(cg create-user-pool-client --user-pool-id "$PID" --client-name cli-client \
      --explicit-auth-flows ALLOW_USER_PASSWORD_AUTH ALLOW_ADMIN_USER_PASSWORD_AUTH ALLOW_REFRESH_TOKEN_AUTH --output json)
CID=$(echo "$out" | jq_ "d['UserPoolClient']['ClientId']" 2>/dev/null)
[ -n "$CID" ]; chk $? "create-user-pool-client" "$out"

out=$(cg sign-up --client-id "$CID" --username carol --password 'Passw0rd!x' --user-attributes Name=email,Value=carol@example.com --output json)
echo "$out" | grep -q '"UserConfirmed": false'; chk $? "sign-up (unconfirmed)" "$out"

out=$(cg admin-confirm-sign-up --user-pool-id "$PID" --username carol)
chk $? "admin-confirm-sign-up" "$out"

out=$(cg initiate-auth --client-id "$CID" --auth-flow USER_PASSWORD_AUTH --auth-parameters USERNAME=carol,PASSWORD='Passw0rd!x' --output json)
AT=$(echo "$out" | jq_ "d['AuthenticationResult']['AccessToken']" 2>/dev/null)
[ -n "$AT" ]; chk $? "initiate-auth USER_PASSWORD_AUTH returns tokens" "$out"

out=$(cg get-user --access-token "$AT" --output json)
echo "$out" | grep -q carol@example.com; chk $? "get-user" "$out"

out=$(cg initiate-auth --client-id "$CID" --auth-flow USER_PASSWORD_AUTH --auth-parameters USERNAME=carol,PASSWORD=wrong 2>&1)
echo "$out" | grep -q NotAuthorizedException; chk $? "wrong password -> NotAuthorizedException" "$out"

out=$(cg admin-create-user --user-pool-id "$PID" --username dan --temporary-password 'Temp#Pass1' --user-attributes Name=email,Value=dan@example.com --output json)
echo "$out" | grep -q FORCE_CHANGE_PASSWORD; chk $? "admin-create-user" "$out"

out=$(cg list-users --user-pool-id "$PID" --filter 'email = "dan@example.com"' --output json)
echo "$out" | grep -q '"Username": "dan"'; chk $? "list-users --filter" "$out"

out=$(cg create-group --user-pool-id "$PID" --group-name admins --description Administrators)
chk $? "create-group" "$out"
out=$(cg admin-add-user-to-group --user-pool-id "$PID" --username dan --group-name admins)
chk $? "admin-add-user-to-group" "$out"
out=$(cg list-users-in-group --user-pool-id "$PID" --group-name admins --output json)
echo "$out" | grep -q '"Username": "dan"'; chk $? "list-users-in-group" "$out"

out=$(cg create-user-pool-domain --user-pool-id "$PID" --domain "cli-auth-$SFX")
chk $? "create-user-pool-domain" "$out"
out=$(cg describe-user-pool-domain --domain "cli-auth-$SFX" --output json)
echo "$out" | grep -q "$PID"; chk $? "describe-user-pool-domain" "$out"
cg delete-user-pool-domain --user-pool-id "$PID" --domain "cli-auth-$SFX" >/dev/null; chk $? "delete-user-pool-domain" ""

out=$(cg admin-delete-user --user-pool-id "$PID" --username dan); chk $? "admin-delete-user" "$out"
out=$(cg delete-user-pool-client --user-pool-id "$PID" --client-id "$CID"); chk $? "delete-user-pool-client" "$out"
out=$(cg delete-user-pool --user-pool-id "$PID"); chk $? "delete-user-pool" "$out"
out=$(cg describe-user-pool --user-pool-id "$PID" 2>&1)
echo "$out" | grep -q ResourceNotFoundException; chk $? "describe deleted pool -> ResourceNotFoundException" "$out"

echo "$pass passed, $fail failed"
[ "$fail" = "0" ]
