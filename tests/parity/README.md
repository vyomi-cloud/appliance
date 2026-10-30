# DynamoDB differential parity

Since v4 "C0" the offline appliance and Nano serve DynamoDB from the shared pure-Python
core (`core/dynamodb_core.py` + `core/dynamodb_expr.py`), not from AWS's DynamoDB Local.
"Parity" is therefore not assumed — it is **measured** here by running identical request
sequences against the core (in-process, `dispatch` over an `InMemoryNoSqlStore`) and
against DynamoDB Local (AWS's own engine, the oracle) and diffing every response.

- `ddb_differential.py` — the harness: ~150 hand-written cases (table shapes, GSIs/LSIs,
  condition / update / projection expressions, Query/Scan paging, Batch*/Transact* incl.
  failures, sets vs lists, 38-digit numbers, 400 KB item limit, validation messages,
  ReturnValues, TTL, PartiQL, legacy `Expected`/`KeyConditions`) plus seeded random
  sequences (puts / updates / deletes / gets / queries / scans / batch / transact over a
  small key space), compared response-by-response **and** on final table state. A failing
  random sequence is delta-minimised before it is reported.
- `reports/ddb_parity_report.{md,json}` — the latest report (every case's verdict; request
  + both responses wherever they differ).
- `tests/test_ddb_local_migration.py` (one level up) — the DynamoDB Local → core upgrade
  migration, against the same container.

## Commands CI should run

```bash
# 1. a DEDICATED, empty DynamoDB Local (never the appliance's vyomi-dynamodb)
docker run -d --rm --name vyomi-parity-ddblocal -p 127.0.0.1:8123:8000 \
    amazon/dynamodb-local:latest -jar DynamoDBLocal.jar -inMemory -sharedDb
for i in $(seq 1 30); do
  curl -s -o /dev/null -X POST http://127.0.0.1:8123 \
    -H 'X-Amz-Target: DynamoDB_20120810.ListTables' -H 'Content-Type: application/x-amz-json-1.0' \
    -H 'Authorization: AWS4-HMAC-SHA256 Credential=x/20260101/us-east-1/dynamodb/aws4_request, SignedHeaders=host, Signature=0' \
    -d '{}' && break; sleep 1; done

# 2. differential parity (stdlib only; python >= 3.9). Gate: hand-written response parity >= 99 %.
PYTHONPATH=. python3 tests/parity/ddb_differential.py \
    --endpoint http://127.0.0.1:8123 --seeds 400 --length 30 \
    --out tests/parity/reports --min-parity 99
#    → upload tests/parity/reports/ddb_parity_report.{md,json} as the job artifact

# 3. the core's own conformance (no oracle needed) must stay green
for t in tests/conformance/test_dynamodb_core.py tests/conformance/test_dynamodb_gsi_core.py \
         tests/conformance/test_dynamodb_table_ops_core.py tests/conformance/test_dynamodb_table_settings_core.py \
         tests/conformance/test_c0_legacy_parity_core.py tests/conformance/test_capabilities.py; do
  PYTHONPATH=. python3 "$t" || exit 1
done

# 4. DynamoDB Local → core migration on appliance start (boots server.py in-process)
DDB_LOCAL_URL=http://127.0.0.1:8123 python -m pytest -q tests/test_ddb_local_migration.py

docker rm -f vyomi-parity-ddblocal
```

`--min-parity` exits 1 when the hand-written *response* parity (exact + alias, over the
responses DynamoDB Local can answer) drops below the threshold. The harness refuses a
non-empty oracle (`--wipe-oracle` deletes its tables first) because `ListTables`
results would otherwise depend on foreign tables. `PARITY_CORE_ROOT=<dir>` measures a
different checkout's core (used for the pre-fix baseline below).

## How responses are compared

Normalisation removes only what is environment-specific or unspecified by DynamoDB:
request ids, timestamps, `TableId`, `ItemCount`/`TableSizeBytes` (refreshed ~every 6 h in
real DynamoDB), ARN region/account, the order of sets / `AttributeDefinitions` / indexes /
`BatchGetItem` results / hash-only index results, Scan item order + page boundaries +
segment membership (storage-hash order; compared as the union of all pages/segments),
and numeric spelling (`1.50` ≡ `1.5`, compared at full precision). Fields DynamoDB Local
does not emit but the real service does (`TableClassSummary`, `DeletionProtectionEnabled`,
`SSEDescription`) are not diffed.

Verdicts: **exact**; **alias** — identical except an error wording/code where DynamoDB
Local is known to differ from the real service and the core keeps the real wording
(`ORACLE_WORDING` / `ORACLE_CODES` in the harness, e.g. `ResourceNotFoundException`
"Requested resource not found: Table: X not found" vs Local's "Cannot do operations on a
non-existent table"); **message** — same status and `__type`, different text;
**oracle-gap** — DynamoDB Local does not implement it (tagging) or fails internally (500),
excluded from the %; **mismatch**.

## Results (2026-10-30, amazon/dynamodb-local:latest)

| | before (C0 core, `release/v4.0.0-dev` @ f508e64c) | after (this branch) |
|---|---|---|
| hand-written cases matching | 0 / 154 (0 %)¹ | 149 / 152 (98.0 %) |
| hand-written responses matching | 385 / 661 (58.2 %) | 658 / 661 (99.5 %) |
| …data-plane responses only (no Create/Describe/Update/DeleteTable) | 79.3 % | 99.8 % |
| random 30-op sequences fully matching | 0 / 400 (0 %) | 400 / 400 (100 %) |
| random-sequence responses matching | 10 393 / 12 800 (81.2 %) | 12 800 / 12 800 (100 %) |

¹ every case starts with `CreateTable`, whose `ProvisionedThroughput` for on-demand tables
was `5/5` instead of `0/0`, so no case could match end-to-end before.

Main pre-fix divergences (all fixed): items were stored as lossy Python natives — a list
of strings came back as a String Set (`L`→`SS`), numbers as floats (`0.1 + 0.2` =
`0.30000000000000004`, 38-digit values rounded), Binary as String; no attribute-value /
key / item-size (400 KB) validation; `UpdateItem` defaulted to `ReturnValues=ALL_NEW`;
ResourceNotFound answered HTTP 404; LSIs were dropped; GSI projections ignored; Query
missed key-condition validation and DynamoDB's `LastEvaluatedKey` rules; update
expressions lacked overlap / document-path / operand-type checks and evaluated operands
against the partially updated item; no unused `ExpressionAttributeNames/Values` or
reserved-word checks; `BatchWriteItem`/`TransactWriteItems` skipped missing tables,
duplicates and limits; no `CancellationReasons`; PartiQL returned `Count` and ignored
projections / duplicate INSERTs.

Remaining documented deviations (also in `core/capabilities/aws/dynamodb.json`):
- TTL: expired items are removed lazily on the next read (DynamoDB deletes within ~48 h
  and may still return expired items meanwhile; DynamoDB Local never deletes).
- CreateTable accepts table names shorter than 3 characters, and treats a request with
  neither `BillingMode` nor `ProvisionedThroughput` as on-demand (DynamoDB rejects it) —
  kept lenient for existing fixtures / console flows.
- Not measured by the oracle: tagging (unsupported by DynamoDB Local), the 1 MB page limit,
  ConsumedCapacity, throttling.
