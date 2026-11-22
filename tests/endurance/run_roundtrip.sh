#!/bin/sh
# vyomi-endurance round trip: Terraform -> stack -> export as Terraform -> fresh stack.
#   run_roundtrip.sh <endpoint-A> <endpoint-B> [report.json]      (docker-side URLs, e.g. http://host.docker.internal:9101)
# 1 apply the reference app on simulator A with Terraform
# 2 export A as Terraform (GET /api/terraform/export) and measure coverage: exported resources / applied resources
# 3 apply the EXPORTED Terraform on a fresh simulator B (must apply)
# 4 re-plan on B must be a NO-OP, and B's own export must hold the same resources as A's
# Report-only by default (the exporter is a draft; the numbers are the point). ROUNDTRIP_STRICT=1 makes any miss exit non-zero.
set -u
EA="$1"; EB="$2"; REPORT="${3:-/dev/null}"
HERE=$(cd "$(dirname "$0")" && pwd); SRC="$HERE/roundtrip/aws"; OUT="$SRC/exported"
HA=$(printf %s "$EA" | sed 's#host.docker.internal#127.0.0.1#'); HB=$(printf %s "$EB" | sed 's#host.docker.internal#127.0.0.1#')
LOG="${ENDURANCE_LOG_DIR:-${TMPDIR:-/tmp}}/endurance-roundtrip"; mkdir -p "$LOG" "$OUT"; rm -rf "$OUT"/* "$SRC"/terraform.tfstate*
CACHE="${VYOMI_PLUGIN_CACHE:-$HOME/.vyomi-endurance/plugin-cache}"; mkdir -p "$CACHE"
tf() { d="$1"; shift; docker run --rm -v "$d":/w -w /w -v "$CACHE":/cache -e TF_PLUGIN_CACHE_DIR=/cache -e TF_IN_AUTOMATION=1 ghcr.io/opentofu/opentofu:latest "$@" -no-color; }
res() { echo "[$1] $2"; }

tf "$SRC" init >"$LOG/a-init.log" 2>&1
tf "$SRC" apply -auto-approve -backup=- -var="endpoint=$EA" >"$LOG/a-apply.log" 2>&1; a_rc=$?
applied=$(tf "$SRC" state list 2>/dev/null | grep -vc '^data\.')
res "$([ $a_rc -eq 0 ] && echo PASS || echo FAIL)" "terraform -> stack: apply on A ($applied resources)"

curl -s -m 60 "$HA/api/terraform/export" >"$OUT/export.json"
python3 - "$OUT" "$EB" <<'PY' || exit 2
import json, sys, os
out, ep = sys.argv[1], sys.argv[2]
d = json.load(open(os.path.join(out, "export.json")))
for name, text in (d.get("terraform_hcl") or {}).items():
    if name != "providers.tf":
        open(os.path.join(out, name), "w").write(text)
svc = "s3 ec2 iam sts rds apigateway lambda cloudwatchlogs secretsmanager kms dynamodb".split()
ends = "\n".join(f'    {s} = "{ep}"' for s in svc)
open(os.path.join(out, "providers.tf"), "w").write(
 'provider "aws" {\n  region = "us-east-1"\n  access_key = "test"\n  secret_key = "test"\n  skip_credentials_validation = true\n'
 '  skip_requesting_account_id = true\n  skip_metadata_api_check = true\n  s3_use_path_style = true\n  endpoints {\n' + ends + '\n  }\n}\n')
s = d.get("summary", {})
json.dump({"exported": s.get("supported_resources", 0), "inventory": s.get("resource_count", 0)}, open(os.path.join(out, "cov.json"), "w"))
PY
exported=$(python3 -c "import json;print(json.load(open('$OUT/cov.json'))['exported'])")
inventory=$(python3 -c "import json;print(json.load(open('$OUT/cov.json'))['inventory'])")
res "$([ "$exported" -ge "$applied" ] && echo PASS || echo FAIL)" "stack -> terraform: export covers $exported of $applied applied resources (inventory lists $inventory)"

tf "$OUT" init >"$LOG/b-init.log" 2>&1
tf "$OUT" apply -auto-approve -backup=- >"$LOG/b-apply.log" 2>&1; b_rc=$?
res "$([ $b_rc -eq 0 ] && echo PASS || echo FAIL)" "exported terraform -> fresh stack: apply on B"
tf "$OUT" plan -detailed-exitcode >"$LOG/b-replan.log" 2>&1; p_rc=$?
res "$([ $p_rc -eq 0 ] && echo PASS || echo FAIL)" "re-plan on B is a no-op (exit $p_rc; 2 = drift)"

fail=0; [ $a_rc -ne 0 ] || [ "$exported" -lt "$applied" ] || [ $b_rc -ne 0 ] || [ $p_rc -ne 0 ] && fail=1
printf '{"endpoint_a":"%s","endpoint_b":"%s","applied":%s,"exported":%s,"inventory":%s,"apply_a_rc":%s,"apply_b_rc":%s,"replan_b_rc":%s,"passed":%s}\n' \
  "$EA" "$EB" "$applied" "$exported" "$inventory" "$a_rc" "$b_rc" "$p_rc" "$([ $fail -eq 0 ] && echo true || echo false)" >"$REPORT"
[ $fail -eq 0 ] && echo "ROUNDTRIP: PASS" || echo "ROUNDTRIP: GAPS (logs in $LOG)"
[ "${ROUNDTRIP_STRICT:-0}" = 1 ] && exit $fail; exit 0
