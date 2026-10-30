#!/usr/bin/env bash
# Real aws-cli SNS smoke against Vyomi — the unmodified binary with only
# --endpoint-url pointed at the appliance. One [PASS]/[FAIL] line per check.
#
#   ENDPOINT=http://127.0.0.1:9000 bash tests/cli/aws-sns-cli-smoke.sh
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
CONSOLE="${CONSOLE:-$BASE}"   # the console's own API: the same server offline, the Nano tab on Nano
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
logq() { curl -s "$CONSOLE/api/aws/sns/deliveries" | python3 -c "import json,sys; items=json.load(sys.stdin)['items']; print($1)"; }

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


# ── push delivery through NATS JetStream: HTTP confirm/notify/retry/DLQ, FIFO dedup ──────────
RDIR=$(mktemp -d)
cat > "$RDIR/recv.py" <<'PY'
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
port, out = int(sys.argv[1]), sys.argv[2]
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
        with open(out + "/log.jsonl", "a") as f:
            f.write(json.dumps({"path": self.path, "type": self.headers.get("x-amz-sns-message-type"), "body": body}) + "\n")
        self.send_response(500 if self.path.startswith("/fail") else 200); self.end_headers()
HTTPServer(("0.0.0.0", port), H).serve_forever()
PY
cat > "$RDIR/verify.py" <<'PY'
import base64, json, sys, urllib.request
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
env = json.loads(sys.argv[1])
fields = {"Notification": ["Message", "MessageId", "Subject", "Timestamp", "TopicArn", "Type"],
          "SubscriptionConfirmation": ["Message", "MessageId", "SubscribeURL", "Timestamp", "Token", "TopicArn", "Type"]}[env["Type"]]
text = "".join(f"{k}\n{env[k]}\n" for k in fields if k in env)
cert = x509.load_pem_x509_certificate(urllib.request.urlopen(env["SigningCertURL"], timeout=10).read())
cert.public_key().verify(base64.b64decode(env["Signature"]), text.encode(), padding.PKCS1v15(),
                         hashes.SHA256() if env["SignatureVersion"] == "2" else hashes.SHA1())
print("verified")
PY
RPORT=$((20000 + SFX % 20000))
RHOST="${SNS_RECEIVER_HOST:-$(hostname -I 2>/dev/null | awk '{print $1}')}"; RHOST="${RHOST:-172.17.0.1}"
python3 "$RDIR/recv.py" "$RPORT" "$RDIR" & RPID=$!
sleep 1
rlog() { python3 -c "
import json, os
rows=[json.loads(l) for l in open('$RDIR/log.jsonl')] if os.path.exists('$RDIR/log.jsonl') else []
print($1)"; }
waitfor() { local i; for i in $(seq 1 "${2:-30}"); do [ "$(rlog "$1")" = "True" ] && return 0; sleep 1; done; return 1; }

HT="cli-http-$SFX"
v "create-topic (HTTP delivery)" create-topic --name "$HT" --query TopicArn --output text; HTARN="$OUT"
v "subscribe an HTTP endpoint" subscribe --topic-arn "$HTARN" --protocol http --notification-endpoint "http://$RHOST:$RPORT/ok" --return-subscription-arn --query SubscriptionArn --output text
if waitfor "any(r['type']=='SubscriptionConfirmation' for r in rows)"; then chk 0 "endpoint receives a SubscriptionConfirmation POST"; else chk 1 "endpoint receives a SubscriptionConfirmation POST" "none within 30s (receiver http://$RHOST:$RPORT)"; fi
CONF=$(rlog "[r['body'] for r in rows if r['type']=='SubscriptionConfirmation'][0] if rows else '{}'")
TOKEN=$(printf '%s' "$CONF" | python3 -c "import json,sys; print(json.load(sys.stdin).get('Token',''))")
VOUT=$(python3 "$RDIR/verify.py" "$CONF" 2>&1 | tail -1); [ "$VOUT" = "verified" ] && chk 0 "the confirmation message is signed (certificate served by the appliance)" || chk 1 "the confirmation message is signed" "$VOUT"
q "$HTARN" "confirm-subscription with the delivered token" confirm-subscription --topic-arn "$HTARN" --token "$TOKEN"
q "MessageId" "publish to the HTTP topic" publish --topic-arn "$HTARN" --message "hello-http-$SFX" --subject "subj"
if waitfor "any(r['type']=='Notification' and 'hello-http-$SFX' in r['body'] for r in rows)"; then chk 0 "confirmed endpoint receives the Notification POST"; else chk 1 "confirmed endpoint receives the Notification POST" "none within 30s"; fi
NOTE=$(rlog "[r['body'] for r in rows if r['type']=='Notification' and 'hello-http-$SFX' in r['body']][0]")
VOUT=$(python3 "$RDIR/verify.py" "$NOTE" 2>&1 | tail -1); [ "$VOUT" = "verified" ] && chk 0 "the notification signature verifies against SigningCertURL" || chk 1 "the notification signature verifies" "$VOUT"

DLQ="cli-dlq-$SFX"
DLQURL=$(sqs create-queue --queue-name "$DLQ" --query QueueUrl --output text)
DLQARN=$(sqs get-queue-attributes --queue-url "$DLQURL" --attribute-names QueueArn --query Attributes.QueueArn --output text)
FT="cli-fail-$SFX"
v "create-topic (failing endpoint)" create-topic --name "$FT" --query TopicArn --output text; FTARN="$OUT"
POLICY='{"healthyRetryPolicy":{"numRetries":2,"minDelayTarget":1,"maxDelayTarget":1,"numNoDelayRetries":0,"numMinDelayRetries":0,"numMaxDelayRetries":0,"backoffFunction":"linear"}}'
FATTRS=$(python3 -c "import json,sys; print(json.dumps({'DeliveryPolicy': sys.argv[1], 'RedrivePolicy': json.dumps({'deadLetterTargetArn': sys.argv[2]})}))" "$POLICY" "$DLQARN")
v "subscribe a 500-returning endpoint with a DeliveryPolicy + RedrivePolicy" subscribe --topic-arn "$FTARN" --protocol http --notification-endpoint "http://$RHOST:$RPORT/fail-$SFX" --return-subscription-arn --query SubscriptionArn --output text \
  --attributes "$FATTRS"
FSARN="$OUT"
sleep 1
FTOKEN=$(logq "[i['token'] for i in items if i['kind']=='SubscriptionConfirmation' and i['endpoint'].endswith('/fail-$SFX')][0]")
q "$FTARN" "confirm the failing subscription" confirm-subscription --topic-arn "$FTARN" --token "$FTOKEN"
sleep 4
q "MessageId" "publish to the failing topic" publish --topic-arn "$FTARN" --message "will-fail-$SFX"
if waitfor "sum(1 for r in rows if r['type']=='Notification' and 'will-fail-$SFX' in r['body'])==3" 40; then chk 0 "a 500-returning endpoint is retried per the delivery policy (1 attempt + 2 retries)"; else chk 1 "a 500-returning endpoint is retried per the delivery policy" "attempts: $(rlog "sum(1 for r in rows if r['type']=='Notification' and 'will-fail-$SFX' in r['body'])")"; fi
DL=""
for i in $(seq 1 20); do DL=$(sqs receive-message --queue-url "$DLQURL" --max-number-of-messages 10 --wait-time-seconds 1 --query 'Messages[].Body' --output text); printf '%s' "$DL" | grep -q "will-fail-$SFX" && break; done
printf '%s' "$DL" | grep -q "will-fail-$SFX" && chk 0 "after the retries the message lands in the RedrivePolicy dead-letter queue" || chk 1 "after the retries the message lands in the dead-letter queue" "$(printf '%s' "$DL" | head -c 200)"
q "" "unsubscribe the HTTP subscription" unsubscribe --subscription-arn "$FSARN"
q "" "delete the HTTP topic" delete-topic --topic-arn "$HTARN"
sns delete-topic --topic-arn "$FTARN" >/dev/null 2>&1
sqs delete-queue --queue-url "$DLQURL" >/dev/null 2>&1

DT="cli-dedup-$SFX.fifo"
v "create-topic (FIFO, dedup)" create-topic --name "$DT" --attributes FifoTopic=true --query TopicArn --output text; DTARN="$OUT"
M1=$(sns publish --topic-arn "$DTARN" --message dup --message-group-id g --message-deduplication-id d1 --query MessageId --output text)
M2=$(sns publish --topic-arn "$DTARN" --message dup --message-group-id g --message-deduplication-id d1 --query MessageId --output text)
[ -n "$M1" ] && [ "$M1" = "$M2" ] && chk 0 "a FIFO duplicate within the 5-minute window is dropped (same MessageId, delivered once)" || chk 1 "a FIFO duplicate within the 5-minute window is dropped" "$M1 vs $M2"
sns delete-topic --topic-arn "$DTARN" >/dev/null 2>&1
kill "$RPID" 2>/dev/null; rm -rf "$RDIR"

# clean up
q "" "unsubscribe" unsubscribe --subscription-arn "$SARN"
q "" "delete-topic" delete-topic --topic-arn "$TARN"
q "" "delete-topic (FIFO)" delete-topic --topic-arn "$FARN"
OUT=$(sns list-topics --query "Topics[?contains(TopicArn, '$TOPIC')]" --output text)
[ -z "$OUT" ] && chk 0 "deleted topic is gone from list-topics" || chk 1 "deleted topic is gone from list-topics" "$OUT"
sqs delete-queue --queue-url "$QURL" >/dev/null 2>&1

echo "aws sns cli: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
