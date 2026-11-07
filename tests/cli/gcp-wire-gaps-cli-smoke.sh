#!/usr/bin/env bash
# Real `gcloud functions|dns|scc|logging ...` against Vyomi's GCP wire (endpoint override only).
# ENDPOINT (default http://127.0.0.1:9000), PROJECT. One [PASS]/[FAIL] line per check.
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
PROJECT="${PROJECT:-vyomi-project}"
R=us-central1
S="cli$(date +%s)"
pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: ${3:-}"; fail=$((fail+1)); fi; }
export CLOUDSDK_CORE_DISABLE_PROMPTS=1 CLOUDSDK_CORE_PROJECT="$PROJECT" CLOUDSDK_AUTH_DISABLE_CREDENTIALS=true
for api in CLOUDFUNCTIONS DNS SECURITYCENTER LOGGING COMPUTE SERVICEUSAGE; do
  export "CLOUDSDK_API_ENDPOINT_OVERRIDES_${api}=$BASE/"
done
echo "== gcloud against $BASE project=$PROJECT =="

# ── Cloud DNS ──
out=$(gcloud dns managed-zones create "$S-zone" --dns-name="$S.test." --description=smoke --visibility=public 2>&1); chk $? "dns managed-zones create" "$out"
gcloud dns managed-zones list --format='value(name)' 2>/dev/null | grep -q "$S-zone"; chk $? "dns managed-zones list finds it"
out=$(gcloud dns record-sets create "www.$S.test." --zone="$S-zone" --type=A --ttl=60 --rrdatas=10.1.2.3 2>&1); chk $? "dns record-sets create" "$out"
v=$(gcloud dns record-sets list --zone="$S-zone" --name="www.$S.test." --type=A --format='value(rrdatas)' 2>/dev/null); [ "$v" = "10.1.2.3" ]; chk $? "dns record-sets list shows the A record" "$v"
out=$(gcloud dns record-sets update "www.$S.test." --zone="$S-zone" --type=A --ttl=120 --rrdatas=10.1.2.4 2>&1); chk $? "dns record-sets update" "$out"
out=$(gcloud dns record-sets delete "www.$S.test." --zone="$S-zone" --type=A 2>&1); chk $? "dns record-sets delete" "$out"
out=$(gcloud dns managed-zones delete "$S-zone" 2>&1); chk $? "dns managed-zones delete" "$out"

# ── Cloud Functions (v2 + v1) ──
d=$(mktemp -d); cat > "$d/main.py" <<'PY'
import functions_framework

@functions_framework.http
def hello(request):
    return "hello from " + request.args.get("who", "vyomi")
PY
out=$(gcloud functions deploy "$S-fn" --gen2 --region=$R --runtime=python312 --trigger-http --allow-unauthenticated --entry-point=hello --source="$d" 2>&1); chk $? "functions deploy (gen2)" "$out"
gcloud functions list --v2 --regions=$R --format='value(name)' 2>/dev/null | grep -q "$S-fn"; chk $? "functions list finds it"
st=$(gcloud functions describe "$S-fn" --gen2 --region=$R --format='value(state)' 2>/dev/null); [ "$st" = "ACTIVE" ]; chk $? "functions describe state ACTIVE" "$st"
out=$(gcloud functions call "$S-fn" --gen2 --region=$R --data='{}' 2>&1); echo "$out" | grep -q "hello from"; chk $? "functions call runs the uploaded code" "$out"
out=$(gcloud functions delete "$S-fn" --gen2 --region=$R --quiet 2>&1); chk $? "functions delete" "$out"
rm -rf "$d"

# ── Security Command Center (v1) ──
ORG=organizations/1234567890
out=$(gcloud scc sources describe "$ORG" --source=0 2>&1); echo "$out" | grep -qi "error" && chk 1 "scc sources" "$out" || chk 0 "scc sources reachable"
out=$(gcloud scc findings list "$ORG" --source=- --limit=1 2>&1); echo "$out" | grep -qi "ERROR:" && chk 1 "scc findings list" "$out" || chk 0 "scc findings list"
out=$(gcloud scc assets list "$ORG" --limit=1 2>&1); echo "$out" | grep -qi "ERROR:" && chk 1 "scc assets list" "$out" || chk 0 "scc assets list"

# ── Cloud Logging at folder / organization scope ──
out=$(gcloud logging sinks create "$S-sink" "bigquery.googleapis.com/projects/$PROJECT/datasets/d" --organization=1234567890 --log-filter='severity>=ERROR' 2>&1); chk $? "logging sinks create (organization)" "$out"
gcloud logging sinks list --organization=1234567890 --format='value(name)' 2>/dev/null | grep -q "$S-sink"; chk $? "logging sinks list (organization) finds it"
out=$(gcloud logging sinks delete "$S-sink" --organization=1234567890 --quiet 2>&1); chk $? "logging sinks delete (organization)" "$out"
out=$(gcloud logging exclusions create "$S-ex" --folder=111 --log-filter='severity<INFO' 2>&1); chk $? "logging exclusions create (folder)" "$out"
gcloud logging exclusions list --folder=111 --format='value(name)' 2>/dev/null | grep -q "$S-ex"; chk $? "logging exclusions list (folder) finds it"
out=$(gcloud logging exclusions delete "$S-ex" --folder=111 --quiet 2>&1); chk $? "logging exclusions delete (folder)" "$out"

echo "== $pass passed, $fail failed =="
[ "$fail" = "0" ]
