#!/usr/bin/env bash
# Real `aws ssm` CLI smoke against Vyomi — only --endpoint-url is overridden.
#   ENDPOINT=http://127.0.0.1:9000 bash tests/cli/aws-ssm-cli-smoke.sh
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}" AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}" AWS_PAGER=""
if ! command -v aws >/dev/null 2>&1; then echo "[FAIL] aws-cli not installed"; exit 1; fi

pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: ${3:-}"; fail=$((fail+1)); fi; }
A() { aws --endpoint-url "$BASE" ssm "$@"; }
SFX=$(date +%s)
P="/cli-$SFX/app"

out=$(A put-parameter --name "$P/db/host" --value db.local --type String --description cli --query Version --output text 2>&1); [ "$out" = "1" ]; chk $? "put-parameter → version 1" "$out"
A put-parameter --name "$P/db/host" --value x --type String >/tmp/ssm-dup.err 2>&1; rc=$?; grep -q ParameterAlreadyExists /tmp/ssm-dup.err; chk $(( rc!=0 && $?==0 ? 0 : 1 )) "put-parameter without --overwrite → ParameterAlreadyExists" "$(cat /tmp/ssm-dup.err)"
out=$(A put-parameter --name "$P/db/host" --value db2.local --type String --overwrite --query Version --output text 2>&1); [ "$out" = "2" ]; chk $? "put-parameter --overwrite → version 2" "$out"
out=$(A get-parameter --name "$P/db/host" --query Parameter.Value --output text 2>&1); [ "$out" = "db2.local" ]; chk $? "get-parameter" "$out"
out=$(A get-parameter --name "$P/db/host:1" --query Parameter.Value --output text 2>&1); [ "$out" = "db.local" ]; chk $? "get-parameter by version selector" "$out"
A put-parameter --name "$P/secret" --value s3cr3t --type SecureString >/dev/null 2>&1; chk $? "put-parameter SecureString"
out=$(A get-parameter --name "$P/secret" --with-decryption --query Parameter.Value --output text 2>&1); [ "$out" = "s3cr3t" ]; chk $? "get-parameter --with-decryption" "$out"
out=$(A get-parameter --name "$P/secret" --query Parameter.Value --output text 2>&1); [ "$out" != "s3cr3t" ]; chk $? "SecureString is not returned in clear without decryption" "$out"
out=$(A get-parameters-by-path --path "$P" --recursive --query "length(Parameters)" --output text 2>&1); [ "$out" = "2" ]; chk $? "get-parameters-by-path --recursive" "$out"
out=$(A get-parameters --names "$P/db/host" "/missing-$SFX" --query "InvalidParameters[0]" --output text 2>&1); [ "$out" = "/missing-$SFX" ]; chk $? "get-parameters reports InvalidParameters" "$out"
out=$(A describe-parameters --parameter-filters "Key=Name,Option=BeginsWith,Values=$P" --query "length(Parameters)" --output text 2>&1); [ "$out" = "2" ]; chk $? "describe-parameters with a Name filter" "$out"
A label-parameter-version --name "$P/db/host" --parameter-version 1 --labels stable >/dev/null 2>&1; chk $? "label-parameter-version"
out=$(A get-parameter --name "$P/db/host:stable" --query Parameter.Version --output text 2>&1); [ "$out" = "1" ]; chk $? "get-parameter by label" "$out"
out=$(A get-parameter-history --name "$P/db/host" --query "length(Parameters)" --output text 2>&1); [ "$out" = "2" ]; chk $? "get-parameter-history" "$out"
A add-tags-to-resource --resource-type Parameter --resource-id "$P/db/host" --tags Key=team,Value=x >/dev/null 2>&1; chk $? "add-tags-to-resource"
out=$(A list-tags-for-resource --resource-type Parameter --resource-id "$P/db/host" --query "TagList[0].Value" --output text 2>&1); [ "$out" = "x" ]; chk $? "list-tags-for-resource" "$out"
A remove-tags-from-resource --resource-type Parameter --resource-id "$P/db/host" --tag-keys team >/dev/null 2>&1; chk $? "remove-tags-from-resource"
A get-parameter --name "/nope-$SFX" >/tmp/ssm-nf.err 2>&1; rc=$?; grep -q ParameterNotFound /tmp/ssm-nf.err; chk $(( rc!=0 && $?==0 ? 0 : 1 )) "get-parameter unknown → ParameterNotFound" "$(cat /tmp/ssm-nf.err)"

DOC="cli-doc-$SFX"
A create-document --name "$DOC" --document-type Command --content '{"schemaVersion":"2.2","description":"cli","mainSteps":[]}' >/dev/null 2>&1; chk $? "create-document"
out=$(A describe-document --name "$DOC" --query Document.Status --output text 2>&1); [ "$out" = "Active" ]; chk $? "describe-document" "$out"
out=$(A get-document --name "$DOC" --query DocumentType --output text 2>&1); [ "$out" = "Command" ]; chk $? "get-document" "$out"
out=$(A list-documents --filters Key=Owner,Values=Self --query "DocumentIdentifiers[?Name=='$DOC'].Name" --output text 2>&1); [ "$out" = "$DOC" ]; chk $? "list-documents --filters Owner=Self" "$out"
CMD=$(A send-command --document-name AWS-RunShellScript --instance-ids i-0123456789abcdef0 --parameters 'commands=["echo hi"]' --query Command.CommandId --output text 2>&1); chk $? "send-command" "$CMD"
out=$(A get-command-invocation --command-id "$CMD" --instance-id i-0123456789abcdef0 --query Status --output text 2>&1); [ "$out" = "Success" ]; chk $? "get-command-invocation" "$out"
out=$(A list-commands --command-id "$CMD" --query "Commands[0].DocumentName" --output text 2>&1); [ "$out" = "AWS-RunShellScript" ]; chk $? "list-commands" "$out"

WIN=$(A create-maintenance-window --name "cli-win-$SFX" --schedule 'cron(0 2 * * ? *)' --duration 4 --cutoff 1 --no-allow-unassociated-targets --query WindowId --output text 2>&1); chk $? "create-maintenance-window" "$WIN"
out=$(A describe-maintenance-windows --filters Key=Name,Values="cli-win-$SFX" --query "WindowIdentities[0].WindowId" --output text 2>&1); [ "$out" = "$WIN" ]; chk $? "describe-maintenance-windows" "$out"
A delete-maintenance-window --window-id "$WIN" >/dev/null 2>&1; chk $? "delete-maintenance-window"
PB=$(A create-patch-baseline --name "cli-pb-$SFX" --operating-system AMAZON_LINUX_2 --query BaselineId --output text 2>&1); chk $? "create-patch-baseline" "$PB"
A delete-patch-baseline --baseline-id "$PB" >/dev/null 2>&1; chk $? "delete-patch-baseline"

A delete-document --name "$DOC" >/dev/null 2>&1; chk $? "delete-document"
A delete-parameter --name "$P/db/host" >/dev/null 2>&1; chk $? "delete-parameter"
out=$(A delete-parameters --names "$P/secret" "$P/gone" --query "DeletedParameters[0]" --output text 2>&1); [ "$out" = "$P/secret" ]; chk $? "delete-parameters" "$out"
A get-parameter --name "$P/db/host" >/dev/null 2>&1; [ $? -ne 0 ]; chk $? "get-parameter after delete fails"

echo; echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
