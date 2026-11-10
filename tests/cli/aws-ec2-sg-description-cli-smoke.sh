#!/usr/bin/env bash
# aws-cli: EC2 security groups carry GroupDescription (the XML element is <groupDescription>).
#   ENDPOINT=http://127.0.0.1:9000 bash tests/cli/aws-ec2-sg-description-cli-smoke.sh
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}" AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}" AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}" AWS_PAGER=""
fail=0
chk() { if [ "$1" = 0 ]; then echo "[PASS] $2"; else echo "[FAIL] $2 :: ${3:-}"; fail=1; fi; }
ec2() { aws ec2 --endpoint-url "$BASE" "$@" 2>&1; }
SFX=$(date +%s | tail -c 6)
VPC=$(ec2 create-vpc --cidr-block 10.77.0.0/16 --query Vpc.VpcId --output text)
GID=$(ec2 create-security-group --vpc-id "$VPC" --group-name "cli-sg-$SFX" --description "cli sg desc $SFX" --query GroupId --output text)
D=$(ec2 describe-security-groups --group-ids "$GID" --query 'SecurityGroups[0].Description' --output text)
[ "$D" = "cli sg desc $SFX" ] && chk 0 "describe-security-groups returns the Description given at creation" || chk 1 "describe-security-groups returns the Description given at creation" "$D"
DD=$(ec2 describe-security-groups --filters Name=group-name,Values=default --query 'SecurityGroups[0].Description' --output text)
[ "$DD" = "default VPC security group" ] && chk 0 "the default group is 'default VPC security group'" || chk 1 "the default group is 'default VPC security group'" "$DD"
ec2 delete-security-group --group-id "$GID" >/dev/null; ec2 delete-vpc --vpc-id "$VPC" >/dev/null
exit $fail
