#!/usr/bin/env bash
# Real aws-cli STS smoke against the Vyomi appliance — only --endpoint-url changed.
#   ENDPOINT=http://127.0.0.1:9000 bash tests/cli/aws-sts-cli-smoke.sh
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}" AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}" AWS_PAGER=""
unset AWS_SESSION_TOKEN

if ! command -v aws >/dev/null 2>&1; then
    echo "[FAIL] aws-cli not installed"; exit 1
fi
fails=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; else echo "[FAIL] $2 :: $3"; fails=$((fails+1)); fi; }
sts() { aws --endpoint-url "$BASE" sts "$@" 2>&1; }

OUT=$(sts get-caller-identity --query Account --output text)
[ "$OUT" = "123456789012" ]; chk $? "aws sts get-caller-identity returns the account" "$OUT"

ROLE=arn:aws:iam::123456789012:role/cli-sts-role
OUT=$(sts assume-role --role-arn "$ROLE" --role-session-name cli-session --duration-seconds 1800 --output json)
AK=$(echo "$OUT" | python3 -c 'import json,sys;print(json.load(sys.stdin)["Credentials"]["AccessKeyId"])' 2>/dev/null)
SK=$(echo "$OUT" | python3 -c 'import json,sys;print(json.load(sys.stdin)["Credentials"]["SecretAccessKey"])' 2>/dev/null)
ST=$(echo "$OUT" | python3 -c 'import json,sys;print(json.load(sys.stdin)["Credentials"]["SessionToken"])' 2>/dev/null)
case "$AK" in ASIA*) chk 0 "aws sts assume-role returns temporary credentials";; *) chk 1 "aws sts assume-role returns temporary credentials" "$OUT";; esac

ARN=$(AWS_ACCESS_KEY_ID=$AK AWS_SECRET_ACCESS_KEY=$SK AWS_SESSION_TOKEN=$ST sts get-caller-identity --query Arn --output text)
[ "$ARN" = "arn:aws:sts::123456789012:assumed-role/cli-sts-role/cli-session" ]; chk $? "get-caller-identity with the temporary credentials is the assumed role" "$ARN"

OUT=$(sts get-access-key-info --access-key-id "$AK" --query Account --output text)
[ "$OUT" = "123456789012" ]; chk $? "aws sts get-access-key-info" "$OUT"

OUT=$(sts get-session-token --duration-seconds 3600 --query Credentials.AccessKeyId --output text)
case "$OUT" in ASIA*) chk 0 "aws sts get-session-token";; *) chk 1 "aws sts get-session-token" "$OUT";; esac

OUT=$(sts get-federation-token --name cli-fed --query FederatedUser.Arn --output text)
[ "$OUT" = "arn:aws:sts::123456789012:federated-user/cli-fed" ]; chk $? "aws sts get-federation-token" "$OUT"

MSG=$(printf '{"allowed":false}' | base64 -w0)
OUT=$(sts decode-authorization-message --encoded-message "$MSG" --query DecodedMessage --output text)
echo "$OUT" | grep -q allowed; chk $? "aws sts decode-authorization-message" "$OUT"

OUT=$(sts assume-role --role-arn "$ROLE" --role-session-name "bad name!")
echo "$OUT" | grep -q "ValidationError"; chk $? "assume-role rejects an invalid session name with ValidationError" "$OUT"

echo "== done, failures: $fails =="
[ "$fails" = "0" ]
