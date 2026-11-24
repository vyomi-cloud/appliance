#!/bin/sh
# vyomi-endurance round trip: Terraform -> stack -> export as Terraform -> fresh stack.
#   run_roundtrip.sh <endpoint-A> <endpoint-B> [report.json]      (docker-side URLs, e.g. http://host.docker.internal:9101)
# 1 apply the reference app on simulator A with Terraform
# 2 export A as Terraform (GET /api/terraform/export/bundle) and measure coverage: exported resources / applied resources
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

curl -s -m 120 "$HA/api/terraform/export/bundle" -o "$OUT/export.zip" && python3 - "$OUT" "$EB" <<'PY' || exit 2
import json, os, sys, zipfile
out, ep = sys.argv[1], sys.argv[2]
zipfile.ZipFile(os.path.join(out, "export.zip")).extractall(out)
svc = "s3 ec2 iam sts rds apigateway lambda cloudwatchlogs secretsmanager kms dynamodb".split()
ends = "\n".join(f'    {s} = "{ep}"' for s in svc)
open(os.path.join(out, "override.tf"), "w").write(
 'provider "aws" {\n  access_key = "test"\n  secret_key = "test"\n  skip_credentials_validation = true\n'
 '  skip_requesting_account_id = true\n  skip_metadata_api_check = true\n  s3_use_path_style = true\n  endpoints {\n' + ends + '\n  }\n}\n')
PY
types() { awk -F. '$1=="data"{next} {t=$1; if ($1=="module") t=$3; print t}' | sort | uniq -c | awk '{print $2" "$1}'; }
# Rules written as separate resources are exported inline on their security group, and S3 objects are data, not configuration: both
# are the same stack in a different spelling, so they are not compared by type.
tf "$SRC" state list 2>/dev/null | types | grep -vE '^(aws_vpc_security_group_(in|e)gress_rule|aws_s3_object) ' >"$LOG/types-a.txt"
exported=$(python3 -c "import zipfile,re;z=zipfile.ZipFile('$OUT/export.zip');print(sum(len(re.findall(r'^resource ',z.read(n).decode(),re.M)) for n in z.namelist() if n.endswith('.tf')))")
applied_cmp=$(awk '{n+=$2} END{print n+0}' "$LOG/types-a.txt")
res "$([ "$exported" -ge "$applied_cmp" ] && echo PASS || echo FAIL)" "stack -> terraform: export holds $exported resources for $applied_cmp comparable applied resources"
tf "$OUT" init >"$LOG/b-init.log" 2>&1
tf "$OUT" apply -auto-approve -backup=- >"$LOG/b-apply.log" 2>&1; b_rc=$?
res "$([ $b_rc -eq 0 ] && echo PASS || echo FAIL)" "exported terraform -> fresh stack: apply on B"
tf "$OUT" state list 2>/dev/null | types | grep -vE '^(aws_vpc_security_group_(in|e)gress_rule|aws_s3_object) ' >"$LOG/types-b.txt"
missing=$(awk 'NR==FNR{b[$1]=$2;next}{ if (b[$1]+0 < $2) printf "%s(%d/%d) ", $1, b[$1]+0, $2 }' "$LOG/types-b.txt" "$LOG/types-a.txt")
res "$([ -z "$missing" ] && echo PASS || echo FAIL)" "same resources on B as on A${missing:+; missing: $missing}"
[ -z "$missing" ] || m_rc=1
tf "$OUT" plan -detailed-exitcode >"$LOG/b-replan.log" 2>&1; p_rc=$?
res "$([ $p_rc -eq 0 ] && echo PASS || echo FAIL)" "re-plan on B is a no-op (exit $p_rc; 2 = drift)"

# the rebuilt stack must export to the same Terraform as the original (generated ids aside)
mkdir -p "$OUT-b" && rm -rf "$OUT-b"/* && curl -s -m 120 "$HB/api/terraform/export/bundle" -o "$OUT-b/export.zip"
python3 - "$OUT/export.zip" "$OUT-b/export.zip" "$LOG/export-diff.txt" <<'PY'
import re, sys, zipfile, difflib
def load(p):
    z = zipfile.ZipFile(p); out = {}
    for n in sorted(z.namelist()):
        if n.endswith((".tf", ".tfvars")):
            t = z.read(n).decode()
            t = re.sub(r"\b(vpc|subnet|sg|igw|rtb|rtbassoc|eni|i)-[0-9a-f]{8,}\b", r"\1-ID", t)
            out[n] = re.sub(r"\b[0-9a-f]{10}\b", "APIID", t)
    return out
a, b = load(sys.argv[1]), load(sys.argv[2])
diff = []
for n in sorted(set(a) | set(b)):
    diff += list(difflib.unified_diff(a.get(n, "").splitlines(), b.get(n, "").splitlines(), f"A/{n}", f"B/{n}", lineterm="", n=1))
open(sys.argv[3], "w").write("\n".join(diff))
sys.exit(1 if diff else 0)
PY
e_rc=$?
res "$([ $e_rc -eq 0 ] && echo PASS || echo FAIL)" "export of B equals export of A (diff: $LOG/export-diff.txt)"

fail=0; [ $e_rc -ne 0 ] || [ "${m_rc:-0}" -ne 0 ] || [ $a_rc -ne 0 ] || [ "$exported" -lt "$applied_cmp" ] || [ $b_rc -ne 0 ] || [ $p_rc -ne 0 ] && fail=1
printf '{"endpoint_a":"%s","endpoint_b":"%s","applied":%s,"exported":%s,"apply_a_rc":%s,"apply_b_rc":%s,"replan_b_rc":%s,"passed":%s}\n' \
  "$EA" "$EB" "$applied" "$exported" "$a_rc" "$b_rc" "$p_rc" "$([ $fail -eq 0 ] && echo true || echo false)" >"$REPORT"
[ $fail -eq 0 ] && echo "ROUNDTRIP: PASS" || echo "ROUNDTRIP: GAPS (logs in $LOG)"
[ "${ROUNDTRIP_STRICT:-0}" = 1 ] && exit $fail; exit 0
