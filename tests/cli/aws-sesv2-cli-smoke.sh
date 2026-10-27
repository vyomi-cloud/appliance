#!/usr/bin/env bash
# Real aws-cli SES v2 smoke against Vyomi — the unmodified binary with only
# --endpoint-url pointed at the appliance. One [PASS]/[FAIL] line per check.
#
#   ENDPOINT=http://127.0.0.1:9000 bash tests/cli/aws-sesv2-cli-smoke.sh
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
ses() { aws sesv2 --endpoint-url "$BASE" "$@" 2>&1; }
# q <expected-substring> <description> <aws args...>: run and look for a substring.
q() { local want="$1" what="$2"; shift 2; local out; out=$(ses "$@"); local rc=$?
      if [ $rc -eq 0 ] && { [ -z "$want" ] || printf '%s' "$out" | grep -q -- "$want"; }; then chk 0 "$what"; else chk 1 "$what" "$(printf '%s' "$out" | head -c 300)"; fi; }
# v <description> <aws args...>: run, expect success, result text in $OUT.
v() { local what="$1"; shift; OUT=$(ses "$@"); local rc=$?
      if [ $rc -eq 0 ]; then chk 0 "$what"; else chk 1 "$what" "$(printf '%s' "$OUT" | head -c 300)"; OUT=""; fi; }
# f <expected-error-substring> <description> <aws args...>: expect failure with a message.
f() { local want="$1" what="$2"; shift 2; local out; out=$(ses "$@"); local rc=$?
      if [ $rc -ne 0 ] && printf '%s' "$out" | grep -q -- "$want"; then chk 0 "$what"; else chk 1 "$what" "$(printf '%s' "$out" | head -c 300)"; fi; }

SFX=$(date +%s | tail -c 6)
EMAIL="cli-$SFX@example.com"
DOMAIN="cli-$SFX.example.org"
CS="cli-cs-$SFX"
TPL="cli-tpl-$SFX"
LIST="cli-list-$SFX"
echo "== aws sesv2 against $BASE =="
aws --version 2>&1 | head -1

# identities
q "EMAIL_ADDRESS" "create-email-identity (address)" create-email-identity --email-identity "$EMAIL"
q "DOMAIN" "create-email-identity (domain)" create-email-identity --email-identity "$DOMAIN"
q "EMAIL_ADDRESS" "get-email-identity" get-email-identity --email-identity "$EMAIL"
v "domain DKIM tokens" get-email-identity --email-identity "$DOMAIN" --query 'length(DkimAttributes.Tokens)' --output text
[ "$OUT" = "3" ] && chk 0 "domain has 3 DKIM tokens" || chk 1 "domain has 3 DKIM tokens" "$OUT"
q "$DOMAIN" "list-email-identities" list-email-identities
f "AlreadyExistsException" "duplicate identity is rejected" create-email-identity --email-identity "$EMAIL"
f "NotFoundException" "unknown identity is NotFound" get-email-identity --email-identity "nobody-$SFX@example.com"
q "" "put-email-identity-mail-from-attributes" put-email-identity-mail-from-attributes --email-identity "$DOMAIN" --mail-from-domain "mail.$DOMAIN"
q "mail.$DOMAIN" "mail-from persisted" get-email-identity --email-identity "$DOMAIN"

# configuration set + event destination
q "" "create-configuration-set" create-configuration-set --configuration-set-name "$CS"
q "$CS" "list-configuration-sets" list-configuration-sets
q "" "put-configuration-set-sending-options" put-configuration-set-sending-options --configuration-set-name "$CS" --sending-enabled
q "" "create-configuration-set-event-destination" create-configuration-set-event-destination \
  --configuration-set-name "$CS" --event-destination-name ev1 \
  --event-destination "Enabled=true,MatchingEventTypes=SEND,SnsDestination={TopicArn=arn:aws:sns:us-east-1:123456789012:t}"
q "ev1" "get-configuration-set-event-destinations" get-configuration-set-event-destinations --configuration-set-name "$CS"

# templates
q "" "create-email-template" create-email-template --template-name "$TPL" \
  --template-content '{"Subject":"Hi {{name}}","Text":"Hello {{name}}","Html":"<b>{{name}}</b>"}'
q "Hi {{name}}" "get-email-template" get-email-template --template-name "$TPL"
q "Hi Ada" "test-render-email-template" test-render-email-template --template-name "$TPL" --template-data '{"name":"Ada"}'
q "$TPL" "list-email-templates" list-email-templates

# sending
v "send-email" send-email --from-email-address "$EMAIL" --destination "ToAddresses=to@example.net" \
  --content "Simple={Subject={Data=hello},Body={Text={Data=world}}}" --configuration-set-name "$CS" --query MessageId --output text
[ -n "$OUT" ] && chk 0 "send-email returns a MessageId" || chk 1 "send-email returns a MessageId" "$OUT"
f "MessageRejected" "unverified sender is rejected" send-email --from-email-address "x@unverified-$SFX.com" \
  --destination "ToAddresses=to@example.net" --content "Simple={Subject={Data=a},Body={Text={Data=b}}}"
q "" "send-bulk-email" send-bulk-email --from-email-address "$EMAIL" \
  --default-content "{\"Template\":{\"TemplateName\":\"$TPL\",\"TemplateData\":\"{}\"}}" --bulk-email-entries "Destination={ToAddresses=a@example.net}"

# contact list
q "" "create-contact-list" create-contact-list --contact-list-name "$LIST" --topics "TopicName=news,DisplayName=News,Description=d,DefaultSubscriptionStatus=OPT_IN"
q "" "create-contact" create-contact --contact-list-name "$LIST" --email-address "sub@example.net"
q "sub@example.net" "list-contacts" list-contacts --contact-list-name "$LIST"
q "OPT_IN" "contact inherits the topic default" get-contact --contact-list-name "$LIST" --email-address "sub@example.net"

# suppression + tags + account
q "" "put-suppressed-destination" put-suppressed-destination --email-address "bounce-$SFX@example.net" --reason BOUNCE
q "BOUNCE" "get-suppressed-destination" get-suppressed-destination --email-address "bounce-$SFX@example.net"
q "" "delete-suppressed-destination" delete-suppressed-destination --email-address "bounce-$SFX@example.net"
ARN="arn:aws:ses:us-east-1:123456789012:identity/$EMAIL"
q "" "tag-resource" tag-resource --resource-arn "$ARN" --tags Key=team,Value=mail
q "mail" "list-tags-for-resource" list-tags-for-resource --resource-arn "$ARN"
q "" "untag-resource" untag-resource --resource-arn "$ARN" --tag-keys team
q "SendQuota" "get-account" get-account

# cleanup
q "" "delete-contact" delete-contact --contact-list-name "$LIST" --email-address "sub@example.net"
q "" "delete-contact-list" delete-contact-list --contact-list-name "$LIST"
q "" "delete-email-template" delete-email-template --template-name "$TPL"
q "" "delete-configuration-set" delete-configuration-set --configuration-set-name "$CS"
q "" "delete-email-identity (address)" delete-email-identity --email-identity "$EMAIL"
q "" "delete-email-identity (domain)" delete-email-identity --email-identity "$DOMAIN"
f "NotFoundException" "deleted identity is gone" get-email-identity --email-identity "$EMAIL"

echo "== $pass passed, $fail failed =="
[ "$fail" -eq 0 ]
