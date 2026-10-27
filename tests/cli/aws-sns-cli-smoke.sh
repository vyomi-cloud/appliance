#!/usr/bin/env bash
# Real aws-cli SNS smoke against Vyomi — the unmodified binary with only
# --endpoint-url pointed at the appliance. One [PASS]/[FAIL] line per check.
#
#   ENDPOINT=http://127.0.0.1:9000 bash tests/cli/aws-sns-cli-smoke.sh
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
sns() { aws sns --endpoint-url "$BASE" "$@" 2>&1; }
sqs() { aws sqs --endpoint-url "$BASE" "$@" 2>&1; }
# q <expected-substring> <description> <aws args...>: run and look for a substring.
q() { local want="$1" what="$2"; shift 2; local out; out=$(sns "$@"); local rc=$?
      if [ $rc -eq 0 ] && { [ -z "$want" ] || printf '%s' "$out" | grep -q -- "$want"; }; then chk 0 "$what"; else chk 1 "$what" "$(printf '%s' "$out" | head -c 300)"; fi; }
# v <description> <aws args...>: run, expect success, result text in $OUT.
v() { local what="$1"; shift; OUT=$(sns "$@"); local rc=$?
      if [ $rc -eq 0 ]; then chk 0 "$what"; else chk 1 "$what" "$(printf '%s' "$OUT" | head -c 300)"; OUT=""; fi; }
# f <expected-error-substring> <description> <aws args...>: expect failure with a message.
f() { local want="$1" what="$2"; shift 2; local out; out=$(sns "$@"); local rc=$?
      if [ $rc -ne 0 ] && printf '%s' "$out" | grep -q -- "$want"; then chk 0 "$what"; else chk 1 "$what" "$(printf '%s' "$out" | head -c 300)"; fi; }
# log <jq-free python expr over the delivery log item list `items`> -> prints result
logq() { curl -s "$BASE/api/aws/sns/deliveries" | python3 -c "import json,sys; items=json.load(sys.stdin)['items']; print($1)"; }

SFX=$(date +%s | tail -c 6)
TOPIC="cli-topic-$SFX"
FIFO="cli-fifo-$SFX.fifo"
QNAME="cli-q-$SFX"
echo "== aws sns against $BASE =="
aws --version 2>&1 | head -1

# topics
v "create-topic" create-topic --name "$TOPIC" --query TopicArn --output text
TARN="$OUT"
[ "${TARN##*:}" = "$TOPIC" ] && chk 0 "topic ARN ends with the topic name" || chk 1 "topic ARN ends with the topic name" "$TARN"
q "$TOPIC" "list-topics" list-topics
q "TopicArn" "get-topic-attributes" get-topic-attributes --topic-arn "$TARN"
q "" "set-topic-attributes DisplayName" set-topic-attributes --topic-arn "$TARN" --attribute-name DisplayName --attribute-value "CLI topic"
q "CLI topic" "DisplayName is stored" get-topic-attributes --topic-arn "$TARN"
q "" "tag-resource" tag-resource --resource-arn "$TARN" --tags Key=env,Value=dev
q "dev" "list-tags-for-resource" list-tags-for-resource --resource-arn "$TARN"
q "" "untag-resource" untag-resource --resource-arn "$TARN" --tag-keys env
q "" "add-permission" add-permission --topic-arn "$TARN" --label share --aws-account-id 111122223333 --action-name Publish
q "111122223333" "policy contains the new statement" get-topic-attributes --topic-arn "$TARN"
q "" "remove-permission" remove-permission --topic-arn "$TARN" --label share
f "NotFound" "get-topic-attributes on a missing topic" get-topic-attributes --topic-arn "${TARN}-missing"
f "InvalidParameter" "create-topic rejects a bad name" create-topic --name "bad name!"

# FIFO topic
v "create-topic (FIFO)" create-topic --name "$FIFO" --attributes FifoTopic=true,ContentBasedDeduplication=true --query TopicArn --output text
FARN="$OUT"
f "MessageGroupId" "FIFO publish needs a MessageGroupId" publish --topic-arn "$FARN" --message hi
q "MessageId" "FIFO publish with a group id" publish --topic-arn "$FARN" --message hi --message-group-id g1

# subscriptions + fan-out into a real SQS queue
OUT=$(sqs create-queue --queue-name "$QNAME" --query QueueUrl --output text); QURL="$OUT"
QARN=$(sqs get-queue-attributes --queue-url "$QURL" --attribute-names QueueArn --query Attributes.QueueArn --output text)
v "subscribe (sqs)" subscribe --topic-arn "$TARN" --protocol sqs --notification-endpoint "$QARN" --query SubscriptionArn --output text
SARN="$OUT"
case "$SARN" in "$TARN":*) chk 0 "sqs subscription is confirmed immediately";; *) chk 1 "sqs subscription is confirmed immediately" "$SARN";; esac
q "$QARN" "list-subscriptions-by-topic" list-subscriptions-by-topic --topic-arn "$TARN"
q "" "set-subscription-attributes FilterPolicy" set-subscription-attributes --subscription-arn "$SARN" --attribute-name FilterPolicy --attribute-value '{"color":["red"]}'
q "FilterPolicy" "get-subscription-attributes" get-subscription-attributes --subscription-arn "$SARN"
q "MessageId" "publish with a matching attribute" publish --topic-arn "$TARN" --message "to-sqs" --subject "cli" --message-attributes '{"color":{"DataType":"String","StringValue":"red"}}'
q "MessageId" "publish with a non-matching attribute" publish --topic-arn "$TARN" --message "filtered-out" --message-attributes '{"color":{"DataType":"String","StringValue":"blue"}}'
BODIES=$(sqs receive-message --queue-url "$QURL" --max-number-of-messages 10 --wait-time-seconds 0 --query 'Messages[].Body' --output text)
printf '%s' "$BODIES" | grep -q "to-sqs" && chk 0 "matching message fanned out to the SQS queue" || chk 1 "matching message fanned out to the SQS queue" "$BODIES"
printf '%s' "$BODIES" | grep -q "filtered-out" && chk 1 "filter policy dropped the non-matching message" "$BODIES" || chk 0 "filter policy dropped the non-matching message"

# email subscription needs confirmation (token comes from the message log)
v "subscribe (email, pending)" subscribe --topic-arn "$TARN" --protocol email --notification-endpoint "cli-$SFX@example.com" --query SubscriptionArn --output text
[ "$OUT" = "pending confirmation" ] && chk 0 "email subscription is pending confirmation" || chk 1 "email subscription is pending confirmation" "$OUT"
TOKEN=$(logq "[i['token'] for i in items if i['kind']=='SubscriptionConfirmation' and i['endpoint']=='cli-$SFX@example.com'][0]")
f "InvalidParameter" "confirm-subscription with a wrong token" confirm-subscription --topic-arn "$TARN" --token deadbeef
q "SubscriptionArn" "confirm-subscription with the logged token" confirm-subscription --topic-arn "$TARN" --token "$TOKEN"
q "" "publish after confirmation" publish --topic-arn "$TARN" --message "to-email" --subject "hello"
[ "$(logq "any(i['kind']=='Notification' and i['protocol']=='email' and i['message']=='to-email' for i in items)")" = "True" ] \
  && chk 0 "email delivery recorded in the message log" || chk 1 "email delivery recorded in the message log"

# publish-batch
v "publish-batch" publish-batch --topic-arn "$TARN" --publish-batch-request-entries '[{"Id":"a","Message":"m1"},{"Id":"b","Message":"m2"}]' --query 'length(Successful)' --output text
[ "$OUT" = "2" ] && chk 0 "publish-batch delivers both entries" || chk 1 "publish-batch delivers both entries" "$OUT"
f "BatchEntryIdsNotDistinct" "publish-batch rejects duplicate ids" publish-batch --topic-arn "$TARN" --publish-batch-request-entries '[{"Id":"a","Message":"m1"},{"Id":"a","Message":"m2"}]'

# mobile push
v "create-platform-application" create-platform-application --name "cli-app-$SFX" --platform GCM --attributes PlatformCredential=cli-key --query PlatformApplicationArn --output text
PAPP="$OUT"
v "create-platform-endpoint" create-platform-endpoint --platform-application-arn "$PAPP" --token "tok-$SFX" --query EndpointArn --output text
PEP="$OUT"
q "tok-$SFX" "get-endpoint-attributes" get-endpoint-attributes --endpoint-arn "$PEP"
q "$PEP" "list-endpoints-by-platform-application" list-endpoints-by-platform-application --platform-application-arn "$PAPP"
q "MessageId" "publish to the endpoint" publish --target-arn "$PEP" --message '{"GCM":"{\"data\":{\"m\":1}}"}' --message-structure json
q "" "disable the endpoint" set-endpoint-attributes --endpoint-arn "$PEP" --attributes Enabled=false
f "EndpointDisabled" "publish to a disabled endpoint fails" publish --target-arn "$PEP" --message hi
q "$PAPP" "list-platform-applications" list-platform-applications
q "" "delete-endpoint" delete-endpoint --endpoint-arn "$PEP"
q "" "delete-platform-application" delete-platform-application --platform-application-arn "$PAPP"

# SMS
q "" "set-sms-attributes" set-sms-attributes --attributes DefaultSMSType=Transactional
q "Transactional" "get-sms-attributes" get-sms-attributes
q "true" "get-sms-sandbox-account-status" get-sms-sandbox-account-status
PHONE="+1555555$(printf '%04d' $((SFX % 10000)))"
q "" "create-sms-sandbox-phone-number" create-sms-sandbox-phone-number --phone-number "$PHONE"
OTP=$(logq "[i['token'] for i in items if i['kind']=='SMSSandboxVerification' and i['endpoint']=='$PHONE'][0]")
q "" "verify-sms-sandbox-phone-number" verify-sms-sandbox-phone-number --phone-number "$PHONE" --one-time-password "$OTP"
q "Verified" "list-sms-sandbox-phone-numbers" list-sms-sandbox-phone-numbers
q "MessageId" "publish an SMS to the verified number" publish --phone-number "$PHONE" --message "hi"
q "" "delete-sms-sandbox-phone-number" delete-sms-sandbox-phone-number --phone-number "$PHONE"
q "false" "check-if-phone-number-is-opted-out" check-if-phone-number-is-opted-out --phone-number "$PHONE"

# clean up
q "" "unsubscribe" unsubscribe --subscription-arn "$SARN"
q "" "delete-topic" delete-topic --topic-arn "$TARN"
q "" "delete-topic (FIFO)" delete-topic --topic-arn "$FARN"
OUT=$(sns list-topics --query "Topics[?contains(TopicArn, '$TOPIC')]" --output text)
[ -z "$OUT" ] && chk 0 "deleted topic is gone from list-topics" || chk 1 "deleted topic is gone from list-topics" "$OUT"
sqs delete-queue --queue-url "$QURL" >/dev/null 2>&1

echo "aws sns cli: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
