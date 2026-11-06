#!/usr/bin/env bash
# Real Google Cloud SDK `bq` CLI against Vyomi's BigQuery (bigquery/v2), only the
# endpoint overridden (bq reads the API shape from its bundled discovery document, which
# is pointed at the appliance). One [PASS]/[FAIL] line per check; non-zero on failure.
#   ENDPOINT=http://localhost:9000 bash tests/cli/gcp-bigquery-cli-smoke.sh
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
PROJECT="${PROJECT:-gcp-dev}"
SUFFIX="$(date +%s)"
DS="cli_bq_${SUFFIX}"
WORK="$(mktemp -d)"
fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; else echo "[FAIL] $2 :: $3"; fail=$((fail+1)); fi; }

export HOME="$WORK/home"; mkdir -p "$HOME"
gcloud config set auth/disable_credentials true >/dev/null 2>&1
gcloud config set core/project "$PROJECT" >/dev/null 2>&1

# bq ships a bundled copy of the BigQuery discovery document; point its rootUrl at Vyomi.
BQ_BIN="$(readlink -f "$(command -v bq)")"
DOC="$(find "$(dirname "$BQ_BIN")/.." /usr/lib/google-cloud-sdk /usr/share/google-cloud-sdk -path '*discovery_next/bigquery.json' 2>/dev/null | head -1)"
if [ -z "$DOC" ]; then
  DOC="$WORK/orig.json"; curl -fsS 'https://bigquery.googleapis.com/$discovery/rest?version=v2' -o "$DOC"
fi
sed "s#https://bigquery.googleapis.com/#${BASE%/}/#g" "$DOC" > "$WORK/bigquery.json"
bqc() { bq --discovery_file="$WORK/bigquery.json" --api="$BASE" --oauth_access_token=vyomi --project_id="$PROJECT" --headless "$@" 2>&1 | tr '\n' ' '; }
bqraw() { bq --discovery_file="$WORK/bigquery.json" --api="$BASE" --oauth_access_token=vyomi --project_id="$PROJECT" --headless "$@" 2>/dev/null; }

out=$(bqc mk --dataset --location=US --description="cli smoke" "$PROJECT:$DS"); echo "$out" | grep -q "successfully created"; chk $? "bq mk --dataset" "$out"
out=$(bqc mk --dataset "$PROJECT:$DS"); echo "$out" | grep -qi "already exists"; chk $? "duplicate dataset fails with Already Exists" "$out"
out=$(bqc ls --format=json); echo "$out" | grep -q "$DS"; chk $? "bq ls lists the dataset" "$out"
out=$(bqc show --format=json "$PROJECT:$DS"); echo "$out" | grep -q '"location": *"US"' && echo "$out" | grep -q 'cli smoke'; chk $? "bq show dataset (location + description)" "$out"
out=$(bqc update --description="updated by cli" "$PROJECT:$DS"); chk $? "bq update dataset" "$out"
out=$(bqc show --format=json "$PROJECT:$DS"); echo "$out" | grep -q "updated by cli"; chk $? "dataset shows the updated description" "$out"

out=$(bqc mk --table "$PROJECT:$DS.people" id:INTEGER,name:STRING,score:FLOAT); echo "$out" | grep -q "successfully created"; chk $? "bq mk --table with schema" "$out"
out=$(bqc show --format=json "$PROJECT:$DS.people"); echo "$out" | grep -q '"INTEGER"' && echo "$out" | grep -q '"numRows": *"0"'; chk $? "bq show table (schema, 0 rows)" "$out"
printf '{"id":1,"name":"ann","score":1.5}\n{"id":2,"name":"bob","score":2.5}\n{"id":3,"name":"cy","score":3.5}\n' > "$WORK/rows.json"
out=$(bqraw insert "$PROJECT:$DS.people" "$WORK/rows.json"); chk $? "bq insert (tabledata.insertAll)" "$out"
out=$(bqc head --format=json -n 10 "$PROJECT:$DS.people"); echo "$out" | grep -q '"name":"bob"\|"name": "bob"'; chk $? "bq head returns the inserted rows" "$out"
out=$(bqc query --use_legacy_sql=false --format=json "SELECT name, score FROM \`$PROJECT.$DS.people\` WHERE score > 2 ORDER BY id")
echo "$out" | grep -q 'bob' && echo "$out" | grep -q 'cy' && ! echo "$out" | grep -q 'ann'; chk $? "bq query SELECT with WHERE/ORDER BY" "$out"
out=$(bqraw query --use_legacy_sql=false --format=csv "SELECT COUNT(*) AS n, SUM(score) AS total FROM \`$PROJECT.$DS.people\`")
echo "$out" | tail -1 | grep -q "^3,7.5"; chk $? "bq query aggregate (COUNT/SUM)" "$out"
out=$(bqc query --use_legacy_sql=false "UPDATE \`$PROJECT.$DS.people\` SET score = score + 1 WHERE id = 1"); echo "$out" | grep -qi "1 row\|Number of affected rows: 1"; chk $? "bq query DML UPDATE affects 1 row" "$out"
out=$(bqraw query --use_legacy_sql=false --format=csv "SELECT score FROM \`$PROJECT.$DS.people\` WHERE id = 1"); echo "$out" | tail -1 | grep -q "^2.5"; chk $? "UPDATE is visible to the next query" "$out"
out=$(bqc query --use_legacy_sql=false "SELEC nope"); echo "$out" | grep -qi "error\|invalid"; chk $? "syntax error is reported" "$out"
out=$(bqc query --dry_run --use_legacy_sql=false "SELECT * FROM \`$PROJECT.$DS.people\`"); echo "$out" | grep -qi "will process"; chk $? "bq query --dry_run reports bytes processed" "$out"
out=$(bqc ls --jobs --format=json); echo "$out" | grep -q '"jobId"\|jobReference'; chk $? "bq ls --jobs lists query jobs" "$out"
out=$(bqc cp -f "$PROJECT:$DS.people" "$PROJECT:$DS.people_copy"); chk $? "bq cp copies a table" "$out"
out=$(bqc ls "$PROJECT:$DS"); echo "$out" | grep -q "people_copy"; chk $? "bq ls dataset lists tables" "$out"
out=$(bqc rm -f -t "$PROJECT:$DS.people_copy"); chk $? "bq rm table" "$out"
out=$(bqc rm -f -d "$PROJECT:$DS"); echo "$out" | grep -qi "in use"; chk $? "bq rm non-empty dataset fails (resourceInUse)" "$out"
out=$(bqc rm -f -r -d "$PROJECT:$DS"); chk $? "bq rm -r dataset" "$out"
out=$(bqc show "$PROJECT:$DS"); echo "$out" | grep -qi "not found"; chk $? "dataset is gone (Not found)" "$out"

rm -rf "$WORK"
[ "$fail" = "0" ] || { echo "$fail check(s) failed"; exit 1; }
echo "all checks passed"
