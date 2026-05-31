#!/usr/bin/env bash
# Real aws-cli smoke against the CloudLearn simulator. Proves the unmodified
# binary works when --endpoint-url points at the simulator.
#
# Run from the host (where aws-cli is installed) OR inside the simulator
# container (where boto3+awscli are already in requirements.txt):
#
#   ENDPOINT=http://192.168.252.7:9000 bash tests/conformance/aws-cli-smoke.sh
#
#   multipass exec cloudlearn-appliance -- bash -lc \
#     'docker exec cloud-learn-simulator-1 bash /app/tests/conformance/aws-cli-smoke.sh'
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
# Tell aws-cli to skip SSL warnings + not load any real config files.
export AWS_PAGER=""

# aws-cli may be missing on the host — bail with a skip status (not a failure).
if ! command -v aws >/dev/null 2>&1; then
    echo "SKIP aws-cli not installed; install via 'pip install awscli' or apt/brew"
    exit 0
fi

pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "PASS $2"; pass=$((pass+1)); else echo "FAIL $2 :: $3"; fail=$((fail+1)); fi; }

echo "== aws-cli against $BASE =="
aws --version 2>&1 | head -1

# Switch to an AWS space (the simulator gates S3/EC2 ops to AWS spaces).
# Use python urllib so this works in minimal containers without curl.
AWS_SP=$(python3 -c "
import json, urllib.request
try:
    d = json.load(urllib.request.urlopen('$BASE/api/spaces', timeout=5))
    print(next((s['space_id'] for s in d.get('spaces', []) if s.get('provider')=='aws'), ''))
except Exception:
    print('')
" 2>/dev/null)
if [ -n "$AWS_SP" ]; then
    python3 -c "
import urllib.request
req = urllib.request.Request('$BASE/api/spaces/$AWS_SP/switch', method='POST')
urllib.request.urlopen(req, timeout=5).read()
" >/dev/null 2>&1
    echo "switched to AWS space: $AWS_SP"
fi

BUCKET="cli-smoke-$(date +%s)"

# --- S3 ---
out=$(aws --endpoint-url "$BASE" s3 mb "s3://$BUCKET" 2>&1)
chk $? "s3 mb (create bucket)" "$out"

out=$(aws --endpoint-url "$BASE" s3 ls 2>&1)
echo "$out" | grep -q "$BUCKET"
chk $? "s3 ls (list buckets shows new one)" "$(echo "$out" | tail -2)"

echo "hello-from-aws-cli" > /tmp/aws-cli-obj.txt
out=$(aws --endpoint-url "$BASE" s3 cp /tmp/aws-cli-obj.txt "s3://$BUCKET/obj.txt" 2>&1)
chk $? "s3 cp (upload)" "$out"

out=$(aws --endpoint-url "$BASE" s3 cp "s3://$BUCKET/obj.txt" - 2>&1)
echo "$out" | grep -q "hello-from-aws-cli"
chk $? "s3 cp (download to stdout)" "$out"

out=$(aws --endpoint-url "$BASE" s3 rm "s3://$BUCKET/obj.txt" 2>&1); chk $? "s3 rm" "$out"
out=$(aws --endpoint-url "$BASE" s3 rb "s3://$BUCKET" 2>&1); chk $? "s3 rb (delete bucket)" "$out"

# --- IAM ---
USR="cli-smoke-user-$(date +%s)"
out=$(aws --endpoint-url "$BASE" iam create-user --user-name "$USR" 2>&1); chk $? "iam create-user" "$out"
out=$(aws --endpoint-url "$BASE" iam list-users 2>&1); echo "$out" | grep -q "$USR"
chk $? "iam list-users contains new user" "$(echo "$out" | tail -3)"
out=$(aws --endpoint-url "$BASE" iam delete-user --user-name "$USR" 2>&1); chk $? "iam delete-user" "$out"

# --- EC2 ---
out=$(aws --endpoint-url "$BASE" ec2 describe-instances 2>&1); chk $? "ec2 describe-instances" "$out"

# --- DynamoDB (proxied to DDB Local) ---
TBL="cli-smoke-tbl-$(date +%s)"
out=$(aws --endpoint-url "$BASE" dynamodb create-table \
    --table-name "$TBL" \
    --attribute-definitions AttributeName=id,AttributeType=S \
    --key-schema AttributeName=id,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST 2>&1)
chk $? "dynamodb create-table (via DDB Local proxy)" "$out"

out=$(aws --endpoint-url "$BASE" dynamodb put-item \
    --table-name "$TBL" \
    --item '{"id":{"S":"k1"},"v":{"S":"aws-cli-roundtrip"}}' 2>&1)
chk $? "dynamodb put-item" "$out"

out=$(aws --endpoint-url "$BASE" dynamodb get-item \
    --table-name "$TBL" --key '{"id":{"S":"k1"}}' 2>&1)
echo "$out" | grep -q "aws-cli-roundtrip"
chk $? "dynamodb get-item round-trip" "$out"

aws --endpoint-url "$BASE" dynamodb delete-table --table-name "$TBL" >/dev/null 2>&1

# --- SQS (legacy query → ElasticMQ) ---
QNAME="cli-smoke-q-$(date +%s)"
out=$(aws --endpoint-url "$BASE" sqs create-queue --queue-name "$QNAME" 2>&1)
chk $? "sqs create-queue" "$out"

out=$(aws --endpoint-url "$BASE" sqs list-queues 2>&1); chk $? "sqs list-queues" "$out"

echo "RESULT pass=$pass fail=$fail"
[ "$fail" = "0" ] || exit 1
