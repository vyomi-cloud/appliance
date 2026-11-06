#!/usr/bin/env bash
# Real `gcloud dns` CLI against Vyomi's Cloud DNS API (endpoint override only).
# ENDPOINT (default http://127.0.0.1:9000), PROJECT. One [PASS]/[FAIL] line per check.
set -u
BASE="${ENDPOINT:-http://127.0.0.1:9000}"
PROJECT="${PROJECT:-cli-dns-proj}"
ZONE="cli-zone-$(date +%s)"
DOMAIN="$ZONE.example.com."
pass=0; fail=0
chk() { if [ "$1" = "0" ]; then echo "[PASS] $2"; pass=$((pass+1)); else echo "[FAIL] $2 :: $3"; fail=$((fail+1)); fi; }

export CLOUDSDK_CORE_DISABLE_PROMPTS=1
export CLOUDSDK_CORE_PROJECT="$PROJECT"
export CLOUDSDK_AUTH_DISABLE_CREDENTIALS=true
export CLOUDSDK_API_ENDPOINT_OVERRIDES_DNS="$BASE/"
F="--project=$PROJECT --quiet"
echo "== gcloud dns against $BASE project=$PROJECT =="

out=$(gcloud dns managed-zones create "$ZONE" $F --dns-name="$DOMAIN" --description="cli zone" --visibility=public 2>&1)
chk $? "gcloud dns managed-zones create" "$out"

out=$(gcloud dns managed-zones describe "$ZONE" $F --format=json 2>&1)
echo "$out" | grep -q "\"dnsName\": \"$DOMAIN\"" && echo "$out" | grep -q '"description": "cli zone"' && echo "$out" | grep -q 'ns-cloud-'
chk $? "describe (dnsName, description, nameServers)" "$(echo "$out" | head -5)"

out=$(gcloud dns managed-zones list $F --format='value(name)' 2>&1); echo "$out" | grep -q "$ZONE"
chk $? "managed-zones list contains the zone" "$out"

out=$(gcloud dns managed-zones update "$ZONE" $F --description="cli zone updated" 2>&1); chk $? "managed-zones update" "$out"
out=$(gcloud dns managed-zones describe "$ZONE" $F --format='value(description)' 2>&1); [ "$out" = "cli zone updated" ]
chk $? "update persisted (description)" "$out"

out=$(gcloud dns record-sets list --zone="$ZONE" $F --format='value(type)' 2>&1 | sort | tr '\n' ' ')
[ "$out" = "NS SOA " ]; chk $? "new zone has NS + SOA" "$out"

out=$(gcloud dns record-sets create "www.$DOMAIN" --zone="$ZONE" $F --type=A --ttl=120 --rrdatas=192.0.2.1,192.0.2.2 2>&1)
chk $? "record-sets create A" "$out"
out=$(gcloud dns record-sets create "mail.$DOMAIN" --zone="$ZONE" $F --type=CNAME --ttl=300 --rrdatas="www.$DOMAIN" 2>&1)
chk $? "record-sets create CNAME" "$out"
out=$(gcloud dns record-sets list --zone="$ZONE" $F --name="www.$DOMAIN" --type=A --format='value(ttl,rrdatas)' 2>&1)
echo "$out" | grep -q "120" && echo "$out" | grep -q "192.0.2.1"
chk $? "record-sets list filtered (ttl, rrdatas)" "$out"
out=$(gcloud dns record-sets create "www.$DOMAIN" --zone="$ZONE" $F --type=A --ttl=60 --rrdatas=192.0.2.9 2>&1); [ $? -ne 0 ] && echo "$out" | grep -qi "already exists"
chk $? "duplicate record set rejected (already exists)" "$out"

out=$(gcloud dns record-sets update "www.$DOMAIN" --zone="$ZONE" $F --type=A --ttl=30 --rrdatas=198.51.100.5 2>&1); chk $? "record-sets update" "$out"
out=$(gcloud dns record-sets list --zone="$ZONE" $F --name="www.$DOMAIN" --type=A --format='value(rrdatas)' 2>&1); echo "$out" | grep -q "198.51.100.5"
chk $? "update persisted (rrdatas)" "$out"

# transaction flow (gcloud dns record-sets transaction …) builds one atomic change
TX=$(mktemp -u)
out=$(gcloud dns record-sets transaction start --zone="$ZONE" $F --transaction-file="$TX" 2>&1); chk $? "transaction start" "$out"
gcloud dns record-sets transaction add --zone="$ZONE" $F --transaction-file="$TX" --name="tx.$DOMAIN" --type=TXT --ttl=60 '"hello"' >/dev/null 2>&1
out=$(gcloud dns record-sets transaction execute --zone="$ZONE" $F --transaction-file="$TX" 2>&1); chk $? "transaction execute" "$out"
out=$(gcloud dns record-sets list --zone="$ZONE" $F --name="tx.$DOMAIN" --format='value(type)' 2>&1); [ "$out" = "TXT" ]
chk $? "transaction record present" "$out"
rm -f "$TX"

out=$(gcloud dns record-sets changes list --zone="$ZONE" $F --format='value(id)' 2>&1); [ "$(echo "$out" | wc -l)" -ge 3 ]
chk $? "changes list shows each change" "$out"

out=$(gcloud dns managed-zones delete "$ZONE" $F 2>&1); [ $? -ne 0 ]
chk $? "delete non-empty zone is rejected" "$out"

for r in "www.$DOMAIN:A" "mail.$DOMAIN:CNAME" "tx.$DOMAIN:TXT"; do
  gcloud dns record-sets delete "${r%%:*}" --zone="$ZONE" $F --type="${r##*:}" >/dev/null 2>&1
done
out=$(gcloud dns record-sets list --zone="$ZONE" $F --format='value(type)' 2>&1 | sort | tr '\n' ' '); [ "$out" = "NS SOA " ]
chk $? "record-sets delete (back to NS + SOA)" "$out"

out=$(gcloud dns managed-zones delete "$ZONE" $F 2>&1); chk $? "managed-zones delete" "$out"
out=$(gcloud dns managed-zones describe "$ZONE" $F 2>&1); [ $? -ne 0 ] && echo "$out" | grep -qi "not exist\|not found\|notFound"
chk $? "deleted zone is gone (notFound)" "$out"

echo "RESULT pass=$pass fail=$fail"
[ "$fail" = "0" ] || exit 1
