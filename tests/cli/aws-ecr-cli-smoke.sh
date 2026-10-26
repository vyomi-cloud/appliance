#!/usr/bin/env bash
# Real `aws ecr` CLI smoke against the Vyomi appliance: the unmodified aws-cli with
# only --endpoint-url changed — repository lifecycle, layer upload, put-image,
# list/describe/batch-get/batch-delete, policies, tags, scan, auth token.
#
#   ENDPOINT=http://localhost:9000 bash tests/cli/aws-ecr-cli-smoke.sh
#
# One [PASS]/[FAIL] line per check; exit 1 on any failure.
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_PAGER=""

if ! command -v aws >/dev/null 2>&1; then
  echo "[FAIL] aws-cli is not installed"; exit 1
fi
ecr() { aws --endpoint-url "$BASE" ecr "$@"; }
fails=0
ok()  { echo "[PASS] $1"; }
bad() { echo "[FAIL] $1 :: $2"; fails=$((fails+1)); }
# run NAME CMD... — pass when the command exits 0; output kept in $OUT.
run() { local n="$1"; shift; if OUT=$("$@" 2>&1); then ok "$n"; else bad "$n" "$(echo "$OUT" | tail -2 | tr '\n' ' ')"; fi; }
# expect_err NAME CODE CMD... — pass when the command fails with the AWS error code CODE.
expect_err() { local n="$1" code="$2"; shift 2; if OUT=$("$@" 2>&1); then bad "$n" "expected $code but the call succeeded"; elif echo "$OUT" | grep -q "$code"; then ok "$n"; else bad "$n" "$(echo "$OUT" | tail -1)"; fi; }
q() { aws --endpoint-url "$BASE" ecr "$@" --output text; }

REPO="cli-conf/app-$(date +%s)"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

run "create-repository" ecr create-repository --repository-name "$REPO" --image-scanning-configuration scanOnPush=false --tags Key=team,Value=platform
URI=$(q create-repository --repository-name "cli-conf/uri-$$" --query repository.repositoryUri 2>/dev/null)
case "$URI" in */cli-conf/uri-$$) ok "create-repository returns a repositoryUri ending in the name";; *) bad "create-repository returns a repositoryUri ending in the name" "$URI";; esac
ecr delete-repository --repository-name "cli-conf/uri-$$" >/dev/null 2>&1
expect_err "create-repository twice → RepositoryAlreadyExistsException" RepositoryAlreadyExistsException ecr create-repository --repository-name "$REPO"
expect_err "create-repository with a bad name → InvalidParameterException" InvalidParameterException ecr create-repository --repository-name "Bad_Name"
N=$(q describe-repositories --repository-names "$REPO" --query 'repositories[0].repositoryName')
[ "$N" = "$REPO" ] && ok "describe-repositories shows the repository" || bad "describe-repositories shows the repository" "$N"
expect_err "describe-repositories of a missing repo → RepositoryNotFoundException" RepositoryNotFoundException ecr describe-repositories --repository-names nope/missing

# layer upload: blob → sha256 → initiate / upload-part / complete
printf 'vyomi-cli-layer' > "$TMP/layer.bin"
DIGEST="sha256:$(sha256sum "$TMP/layer.bin" | cut -d' ' -f1)"
SIZE=$(wc -c < "$TMP/layer.bin" | tr -d ' ')
UP=$(q initiate-layer-upload --repository-name "$REPO" --query uploadId)
[ -n "$UP" ] && ok "initiate-layer-upload" || bad "initiate-layer-upload" "no uploadId"
run "upload-layer-part" ecr upload-layer-part --repository-name "$REPO" --upload-id "$UP" --part-first-byte 0 --part-last-byte $((SIZE-1)) --layer-part-blob "fileb://$TMP/layer.bin"
D=$(q complete-layer-upload --repository-name "$REPO" --upload-id "$UP" --layer-digests "$DIGEST" --query layerDigest)
[ "$D" = "$DIGEST" ] && ok "complete-layer-upload returns the digest" || bad "complete-layer-upload returns the digest" "$D"
A=$(q batch-check-layer-availability --repository-name "$REPO" --layer-digests "$DIGEST" --query 'layers[0].layerAvailability')
[ "$A" = "AVAILABLE" ] && ok "batch-check-layer-availability → AVAILABLE" || bad "batch-check-layer-availability → AVAILABLE" "$A"

# image
MANIFEST="{\"schemaVersion\":2,\"mediaType\":\"application/vnd.docker.distribution.manifest.v2+json\",\"config\":{\"mediaType\":\"application/vnd.docker.container.image.v1+json\",\"size\":$SIZE,\"digest\":\"$DIGEST\"},\"layers\":[{\"mediaType\":\"application/vnd.docker.image.rootfs.diff.tar.gzip\",\"size\":$SIZE,\"digest\":\"$DIGEST\"}]}"
run "put-image v1" ecr put-image --repository-name "$REPO" --image-manifest "$MANIFEST" --image-tag v1
run "put-image latest (same digest)" ecr put-image --repository-name "$REPO" --image-manifest "$MANIFEST" --image-tag latest
C=$(q list-images --repository-name "$REPO" --query 'length(imageIds)')
[ "$C" = "2" ] && ok "list-images lists both tags" || bad "list-images lists both tags" "$C"
S=$(q describe-images --repository-name "$REPO" --query 'imageDetails[0].imageSizeInBytes')
[ "$S" = "$((SIZE*2))" ] && ok "describe-images reports the image size" || bad "describe-images reports the image size" "$S"
G=$(q batch-get-image --repository-name "$REPO" --image-ids imageTag=v1 --query 'images[0].imageId.imageTag')
[ "$G" = "v1" ] && ok "batch-get-image returns the image" || bad "batch-get-image returns the image" "$G"
expect_err "delete-repository with images → RepositoryNotEmptyException" RepositoryNotEmptyException ecr delete-repository --repository-name "$REPO"

# immutability, scanning, policies, tags, auth
run "put-image-tag-mutability IMMUTABLE" ecr put-image-tag-mutability --repository-name "$REPO" --image-tag-mutability IMMUTABLE
expect_err "re-tag in an IMMUTABLE repo → ImageTagAlreadyExistsException" ImageTagAlreadyExistsException ecr put-image --repository-name "$REPO" --image-manifest "${MANIFEST/schemaVersion\":2/schemaVersion\": 2}" --image-tag v1
run "put-image-tag-mutability MUTABLE" ecr put-image-tag-mutability --repository-name "$REPO" --image-tag-mutability MUTABLE
run "start-image-scan" ecr start-image-scan --repository-name "$REPO" --image-id imageTag=v1
ST=$(q describe-image-scan-findings --repository-name "$REPO" --image-id imageTag=v1 --query 'imageScanStatus.status')
[ "$ST" = "COMPLETE" ] && ok "describe-image-scan-findings → COMPLETE" || bad "describe-image-scan-findings → COMPLETE" "$ST"
POLICY='{"Version":"2012-10-17","Statement":[{"Sid":"pull","Effect":"Allow","Principal":"*","Action":["ecr:BatchGetImage"]}]}'
run "set-repository-policy" ecr set-repository-policy --repository-name "$REPO" --policy-text "$POLICY"
GP=$(q get-repository-policy --repository-name "$REPO" --query policyText)
[ "$GP" = "$POLICY" ] && ok "get-repository-policy round-trips" || bad "get-repository-policy round-trips" "$GP"
run "delete-repository-policy" ecr delete-repository-policy --repository-name "$REPO"
LIFE='{"rules":[{"rulePriority":1,"description":"keep 10","selection":{"tagStatus":"any","countType":"imageCountMoreThan","countNumber":10},"action":{"type":"expire"}}]}'
run "put-lifecycle-policy" ecr put-lifecycle-policy --repository-name "$REPO" --lifecycle-policy-text "$LIFE"
GL=$(q get-lifecycle-policy --repository-name "$REPO" --query lifecyclePolicyText)
[ "$GL" = "$LIFE" ] && ok "get-lifecycle-policy round-trips" || bad "get-lifecycle-policy round-trips" "$GL"
ARN=$(q describe-repositories --repository-names "$REPO" --query 'repositories[0].repositoryArn')
run "tag-resource" ecr tag-resource --resource-arn "$ARN" --tags Key=env,Value=dev
T=$(q list-tags-for-resource --resource-arn "$ARN" --query 'length(tags)')
[ "$T" = "2" ] && ok "list-tags-for-resource shows both tags" || bad "list-tags-for-resource shows both tags" "$T"
TOK=$(q get-authorization-token --query 'authorizationData[0].authorizationToken')
case "$(echo "$TOK" | base64 -d 2>/dev/null)" in AWS:*) ok "get-authorization-token decodes to AWS:<password>";; *) bad "get-authorization-token decodes to AWS:<password>" "$TOK";; esac
PE=$(q get-authorization-token --query 'authorizationData[0].proxyEndpoint')
case "$PE" in http*) ok "get-authorization-token has a proxy endpoint";; *) bad "get-authorization-token has a proxy endpoint" "$PE";; esac

# delete
R=$(q batch-delete-image --repository-name "$REPO" --image-ids imageTag=v1 --query 'length(imageIds)')
[ "$R" = "1" ] && ok "batch-delete-image removes the tag" || bad "batch-delete-image removes the tag" "$R"
run "delete-repository --force" ecr delete-repository --repository-name "$REPO" --force
expect_err "the repository is gone" RepositoryNotFoundException ecr describe-repositories --repository-names "$REPO"

if [ "$fails" -gt 0 ]; then echo "$fails check(s) failed"; exit 1; fi
echo "all checks passed"
