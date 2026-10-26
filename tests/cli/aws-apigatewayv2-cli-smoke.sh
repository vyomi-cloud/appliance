#!/usr/bin/env bash
# Real `aws apigatewayv2` CLI smoke against Vyomi — only --endpoint-url is overridden.
#   ENDPOINT=http://127.0.0.1:9000 bash tests/cli/aws-apigatewayv2-cli-smoke.sh
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}" AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}" AWS_PAGER=""
if ! command -v aws >/dev/null 2>&1; then echo "[FAIL] aws-cli not installed"; exit 1; fi

pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: ${3:-}"; fail=$((fail+1)); fi; }
A() { aws --endpoint-url "$BASE" apigatewayv2 "$@"; }
SFX=$(date +%s)

API=$(A create-api --name "cli-$SFX" --protocol-type HTTP --description cli --query ApiId --output text 2>&1); rc=$?
chk $rc "create-api" "$API"
[ $rc -ne 0 ] && { echo "$pass passed, $((fail)) failed"; exit 1; }

out=$(A get-api --api-id "$API" --query Name --output text 2>&1); [ "$out" = "cli-$SFX" ]; chk $? "get-api returns the name" "$out"
out=$(A get-apis --query "Items[?ApiId=='$API'].ApiId" --output text 2>&1); [ "$out" = "$API" ]; chk $? "get-apis lists it" "$out"
out=$(A update-api --api-id "$API" --name "cli-renamed-$SFX" --query Name --output text 2>&1); [ "$out" = "cli-renamed-$SFX" ]; chk $? "update-api" "$out"
A get-api --api-id nosuchapi >/dev/null 2>/tmp/avg2.err; rc=$?; grep -q NotFoundException /tmp/avg2.err; chk $(( rc!=0 && $?==0 ? 0 : 1 )) "get-api unknown → NotFoundException" "$(cat /tmp/avg2.err)"

INT=$(A create-integration --api-id "$API" --integration-type HTTP_PROXY --integration-uri https://example.com --integration-method GET --payload-format-version 1.0 --query IntegrationId --output text 2>&1); chk $? "create-integration" "$INT"
RT=$(A create-route --api-id "$API" --route-key "GET /items" --target "integrations/$INT" --query RouteId --output text 2>&1); chk $? "create-route" "$RT"
out=$(A get-routes --api-id "$API" --query "Items[0].RouteKey" --output text 2>&1); [ "$out" = "GET /items" ]; chk $? "get-routes" "$out"
out=$(A update-route --api-id "$API" --route-id "$RT" --operation-name listItems --query OperationName --output text 2>&1); [ "$out" = "listItems" ]; chk $? "update-route" "$out"
A create-stage --api-id "$API" --stage-name prod >/dev/null 2>&1; chk $? "create-stage"
DEP=$(A create-deployment --api-id "$API" --stage-name prod --query DeploymentId --output text 2>&1); chk $? "create-deployment" "$DEP"
out=$(A get-stage --api-id "$API" --stage-name prod --query DeploymentId --output text 2>&1); [ "$out" = "$DEP" ]; chk $? "get-stage points at the deployment" "$out"
out=$(A get-deployments --api-id "$API" --query "length(Items)" --output text 2>&1); [ "$out" = "1" ]; chk $? "get-deployments" "$out"
A create-authorizer --api-id "$API" --name jwt --authorizer-type JWT --identity-source '$request.header.Authorization' \
  --jwt-configuration Audience=aud,Issuer=https://issuer.example.com >/dev/null 2>&1; chk $? "create-authorizer (JWT)"
A create-model --api-id "$API" --name Item --schema '{"type":"object"}' >/dev/null 2>&1; chk $? "create-model"

ARN="arn:aws:apigateway:us-east-1::/apis/$API"
A tag-resource --resource-arn "$ARN" --tags team=x >/dev/null 2>&1; chk $? "tag-resource"
out=$(A get-tags --resource-arn "$ARN" --query "Tags.team" --output text 2>&1); [ "$out" = "x" ]; chk $? "get-tags" "$out"
A untag-resource --resource-arn "$ARN" --tag-keys team >/dev/null 2>&1; chk $? "untag-resource"

DOM="cli-$SFX.example.com"
A create-domain-name --domain-name "$DOM" >/dev/null 2>&1; chk $? "create-domain-name"
A create-api-mapping --domain-name "$DOM" --api-id "$API" --stage prod >/dev/null 2>&1; chk $? "create-api-mapping"
A delete-domain-name --domain-name "$DOM" >/dev/null 2>&1; chk $? "delete-domain-name"
VL=$(A create-vpc-link --name "vl-$SFX" --subnet-ids subnet-12345 --query VpcLinkId --output text 2>&1); chk $? "create-vpc-link" "$VL"
A delete-vpc-link --vpc-link-id "$VL" >/dev/null 2>&1; chk $? "delete-vpc-link"

A delete-route --api-id "$API" --route-id "$RT" >/dev/null 2>&1; chk $? "delete-route"
A delete-integration --api-id "$API" --integration-id "$INT" >/dev/null 2>&1; chk $? "delete-integration"
A delete-stage --api-id "$API" --stage-name prod >/dev/null 2>&1; chk $? "delete-stage"
A delete-api --api-id "$API" >/dev/null 2>&1; chk $? "delete-api"
A get-api --api-id "$API" >/dev/null 2>&1; [ $? -ne 0 ]; chk $? "get-api after delete fails"

echo; echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
