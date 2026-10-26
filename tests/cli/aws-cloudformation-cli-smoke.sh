#!/usr/bin/env bash
# Real aws-cli CloudFormation smoke against Vyomi: only --endpoint-url is changed.
#   ENDPOINT=http://127.0.0.1:9000 bash tests/cli/aws-cloudformation-cli-smoke.sh
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}" AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}" AWS_PAGER=""
if ! command -v aws >/dev/null 2>&1; then echo "SKIP aws-cli not installed"; exit 0; fi

pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: $3"; fail=$((fail+1)); fi; }
cf() { aws --endpoint-url "$BASE" cloudformation "$@"; }

N="cli-cfn-$$"
T="$(mktemp -d)"
cat > "$T/t.yaml" <<'YAML'
AWSTemplateFormatVersion: "2010-09-09"
Description: aws-cli smoke stack
Parameters:
  Env:
    Type: String
    Default: dev
Resources:
  Bucket:
    Type: AWS::S3::Bucket
  Topic:
    Type: AWS::SNS::Topic
    Properties:
      TopicName: !Sub "${AWS::StackName}-${Env}"
Outputs:
  TopicArn:
    Value: !Ref Topic
    Export:
      Name: !Sub "${AWS::StackName}-topic"
YAML

echo "== aws-cli cloudformation against $BASE =="
out=$(cf validate-template --template-body "file://$T/t.yaml" --query 'Parameters[0].ParameterKey' --output text 2>&1); chk $([ "$out" = "Env" ]; echo $?) "validate-template" "$out"
out=$(cf create-stack --stack-name "$N" --template-body "file://$T/t.yaml" --query StackId --output text 2>&1); chk $([[ "$out" == arn:aws:cloudformation:*:stack/$N/* ]]; echo $?) "create-stack" "$out"
out=$(cf describe-stacks --stack-name "$N" --query 'Stacks[0].StackStatus' --output text 2>&1); chk $([ "$out" = "CREATE_COMPLETE" ]; echo $?) "describe-stacks → CREATE_COMPLETE" "$out"
out=$(cf describe-stacks --stack-name "$N" --query 'Stacks[0].Outputs[0].OutputValue' --output text 2>&1); chk $([[ "$out" == arn:aws:sns:*:$N-dev ]]; echo $?) "stack output resolves !Ref/!Sub" "$out"
out=$(cf list-stack-resources --stack-name "$N" --query 'length(StackResourceSummaries)' --output text 2>&1); chk $([ "$out" = "2" ]; echo $?) "list-stack-resources" "$out"
out=$(cf describe-stack-events --stack-name "$N" --query 'length(StackEvents)' --output text 2>&1); chk $([ "${out:-0}" -ge 5 ] 2>/dev/null; echo $?) "describe-stack-events" "$out"
out=$(cf get-template --stack-name "$N" --query 'TemplateBody' --output text 2>&1); chk $([[ "$out" == *"aws-cli smoke stack"* ]]; echo $?) "get-template" "$out"
out=$(cf list-exports --query "Exports[?Name=='$N-topic'].Name" --output text 2>&1); chk $([ "$out" = "$N-topic" ]; echo $?) "list-exports" "$out"
out=$(cf update-stack --stack-name "$N" --template-body "file://$T/t.yaml" 2>&1); chk $([[ "$out" == *"No updates are to be performed"* ]]; echo $?) "update-stack no-op is rejected like AWS" "$out"
out=$(cf update-stack --stack-name "$N" --template-body "file://$T/t.yaml" --parameters ParameterKey=Env,ParameterValue=prod 2>&1); chk $([[ "$out" == *StackId* ]]; echo $?) "update-stack Env=prod" "$out"
out=$(cf describe-stacks --stack-name "$N" --query 'Stacks[0].StackStatus' --output text 2>&1); chk $([ "$out" = "UPDATE_COMPLETE" ]; echo $?) "stack UPDATE_COMPLETE" "$out"
out=$(cf create-change-set --stack-name "$N" --change-set-name cs1 --template-body "file://$T/t.yaml" --parameters ParameterKey=Env,ParameterValue=qa --query Id --output text 2>&1); chk $([[ "$out" == arn:aws:cloudformation:*:changeSet/cs1/* ]]; echo $?) "create-change-set" "$out"
out=$(cf describe-change-set --stack-name "$N" --change-set-name cs1 --query 'Changes[0].ResourceChange.Action' --output text 2>&1); chk $([ "$out" = "Modify" ]; echo $?) "describe-change-set → Modify" "$out"
out=$(cf execute-change-set --stack-name "$N" --change-set-name cs1 2>&1); chk $? "execute-change-set" "$out"
out=$(cf describe-stacks --stack-name "$N" --query 'Stacks[0].Parameters[0].ParameterValue' --output text 2>&1); chk $([ "$out" = "qa" ]; echo $?) "change set applied (Env=qa)" "$out"
out=$(cf deploy --stack-name "$N-dep" --template-file "$T/t.yaml" 2>&1); chk $([[ "$out" == *"Successfully created/updated stack"* ]]; echo $?) "aws cloudformation deploy" "$out"
cf delete-stack --stack-name "$N-dep" >/dev/null 2>&1
out=$(cf delete-stack --stack-name "$N" 2>&1); chk $? "delete-stack" "$out"
out=$(cf describe-stacks --stack-name "$N" 2>&1); chk $([[ "$out" == *"does not exist"* ]]; echo $?) "describe-stacks after delete → does not exist" "$out"
out=$(cf list-stacks --stack-status-filter DELETE_COMPLETE --query "StackSummaries[?StackName=='$N'].StackStatus" --output text 2>&1); chk $([ "$out" = "DELETE_COMPLETE" ]; echo $?) "list-stacks DELETE_COMPLETE" "$out"

rm -rf "$T"
echo; echo "$pass passed, $fail failed"
[ "$fail" = "0" ]
