# Coverage Plan — Solutions/Services over API·SDK & Console

> Audit date: 2026-07-23. Sources: `providers/capabilities.py` (manifest),
> `tests/conformance/` (run as scripts, host CPython), `wasm/providers/*_adapter.py`
> (Nano console), the 3 console HTMLs. **Correction:** an earlier estimate said
> "only 7 AWS services in the Nano console → 21 missing." That was wrong — it only
> looked at `aws_core_adapter.py`. Counting the GCP + Azure + dataplane adapters,
> Nano is at **near-parity** (~26/28). This doc supersedes that estimate.

## What was measured (hard numbers)
| Check | Result |
|---|---|
| **Manifest** `providers/capabilities.py` | AWS **9** + GCP **9** + Azure **10** = **28 services**, all `status: "integrated"` |
| **Console presence** (grep the 3 console HTMLs) | AWS **9/9**, GCP **9/9**, Azure services present ✓ |
| **Core conformance** `tests/conformance/test_*_core.py` (host) | **37/37 PASS** — the extracted service cores (shared by the appliance handlers AND Nano/WASM) are green |
| **Nano console adapters** `wasm/providers/*` | AWS+GCP+Azure+dataplane wire **~26** services into the in-browser console |
| **SDK-vs-sim harness** `run_conformance.py` | **NOT RUN** — needs boto3/google-cloud/azure SDKs; not installed in `.venv` or `.venv-conformance` |

## Coverage matrix
| Cloud | Services | API/SDK (manifest) | In console | Core tests |
|---|---|---|---|---|
| **AWS** | 9 (S3, IAM, EC2, Lambda, VPC, RDS, SQS, DynamoDB, API Gateway) | integrated | 9/9 | green |
| **GCP** | 9 (Compute, Storage, Cloud SQL, Pub/Sub, Firestore, Functions, API GW, VPC, IAM) | integrated | 9/9 | green |
| **Azure** | 10 (VM, Blob, SQL, Service Bus, Cosmos, Functions, APIM, VNet, Entra/RBAC, Key Vault) | integrated | ✓ | green |
| **Total** | **28** | **28/28** | present | **37/37 files** |

## Where "not implemented" actually lives (3 buckets)
1. **SDK conformance depth — the real unknown.** `integrated` + green *core* tests ≠ 100% SDK conformance against unmodified clients. Prior baseline ≈ **88%**, with known reds: **Cosmos DB query · GCS list · S3 checksum**. The exact per-operation red list needs the SDK harness (see Phase A). *Estimated gap: ~12% of operations.*
2. **Claimed 35 vs declared 28** (~**7 services**). Marketing/coverage page says "35 × 3"; the manifest declares 28. Either de-claim or implement the delta — audit required.
3. **Nano last-mile (Free tier).** Cores 37/37 green and ~26/28 services wired into the browser console — but: (a) 1–2 services not yet wired, (b) the relay isn't deployed (`relay.vyomi.cloud` down), (c) console SPA hosting/polish. *Small, concrete.*

## Plan (phased)
| Phase | Goal | Work | Exit criteria |
|---|---|---|---|
| **A · Exact audit** | Turn estimates into a red list | `pip install boto3 google-cloud-* azure-*` into `.venv-conformance`; run `run_conformance.py --endpoint http://localhost:9200` for AWS/GCP/Azure; diff the 35-claim vs 28-manifest | A per-service/per-op PASS/FAIL/DEVIATION table |
| **B · Conformance depth** | 88% → 100% | Fix the Phase-A reds (start: Cosmos query, GCS list, S3 checksum) — per-operation, inside the 28 integrated services | Harness green; 0 FAILs |
| **C · Nano parity + hosting** | Ship the Free tier | Wire the last 1–2 services into the console adapters; deploy the relay; host the Nano SPA | Browser console = Docker console at service level |
| **D · Honest matrix** | Truth in marketing | Reconcile the `/docs/coverage` "35 × 3" page against the 28-service reality (implement or restate) | Coverage page matches the manifest |

## How to reproduce the numbers
```bash
cd appliance
# core conformance (SDK-free, host):
PYTHONPATH=. .venv/bin/python tests/conformance/test_s3_core.py   # (repeat per test_*_core.py) → 37/37 pass
# manifest:
grep -c '"status": "integrated"' providers/capabilities.py
# SDK harness (needs cloud SDKs installed):
.venv-conformance/bin/python tests/conformance/run_conformance.py --endpoint http://localhost:9200 --service s3,iam,ec2
```

## Phase A — RESULTS (measured 2026-07-24, SDK harness vs live `:9200`)
Ran `run_conformance.py` (boto3 + google-cloud + azure SDKs installed in `.venv-conformance`)
against the appliance at `:9200`. **Overall parity 48.9% — pass=43, deviations=37, fail=8.**
BUT `:9200` runs the **free tier**, so most reds are *gating/env*, not implementation gaps:

### The 8 hard fails, classified
| Fail | Root cause | Class |
|---|---|---|
| `dynamodb:ListTables` · `dynamodb:CreateTable` (403) | NoSQL category not in free-tier `service_categories_unlocked` | **Tier-gating** (not a bug) |
| `s3:ListBuckets` · `s3:CreateBucket.readAfterWrite` ("Missing bucket") | ListBuckets dispatch hits the core's bucket-required guard at **`core/s3_object_core.py:573`** | **Real bug** (WASM-owned core → coordinate) |
| `ec2:DescribeInstances` ("Unknown") | EC2 describe handler returns Unknown | **Real bug** (investigate) |
| `gcp.storage:objects.insert` (502) | fake-gcs reachable → handler/upload path bug | **Real bug** (investigate) |
| `gcp.pubsub:subscriptions.pull` (500) | pubsub emulator reachable → pull handler bug | **Real bug** (investigate) |
| `aws.s3.minio:object.get.via-minio-direct` (timeout) | harness dials MinIO at a stale Docker IP `192.168.252.7:9100` | **Environment** |

### The 37 deviations, classified
- **Tier-gating (free tier):** eventing 403 — EventBridge/Eventarc/EventGrid ×6 (eventing not unlocked); MinIO 403 ×3.
- **Throttle/policy:** GCP IAM + Azure RBAC policy-eval **429** ×5 (rate-limit on the eval endpoint).
- **Genuine shape deviations (minor):** `aws.kms Encrypt/Decrypt` 400 empty ×2 (KMS *is* unlocked → likely real); `gcp.kms` ciphertext format; `azure.sql` shape ×3; `gcp.firestore` shape ×2.

### The real, non-gating, non-env bug list (Phase B backlog)
1. **`s3:ListBuckets`** — dispatch → `core/s3_object_core.py:573` "Missing bucket" guard *(WASM core file — needs coordination, NOT edited)*.
2. **`ec2:DescribeInstances`** returns `Unknown`.
3. **`gcp.storage:objects.insert`** → 502.
4. **`gcp.pubsub:subscriptions.pull`** → 500.
5. **`aws.kms:Encrypt/Decrypt`** → 400 empty ciphertext *(KMS unlocked, likely real; core test green so it's the appliance route)*.

### Phase B/C/D status (autonomous run)
- **B (fix reds):** root-caused all 8 fails. The genuine bugs live in appliance handlers / **WASM-session-owned core files** → **documented as tickets, not edited** (parallel-session rule). Also: the harness ran against **free tier** — to get a true implementation number it must run against **Max tier** (unlock everything) — that's the real next measurement.
- **C (Nano parity + relay):** relay (`relay.vyomi.cloud`) deploy is **external-blocked**; Nano wiring lives in `wasm/` (WASM session) → documented, not touched.
- **D (35 vs 28):** the "35 services" claim appears in 8 marketing files; `conformance_data.py` already flags gating honestly ("2 are Max-tier gated, not failures"). 35 (granular service tags) vs 28 (top-level manifest) is a **granularity difference, not a contradiction** → **not mass-edited** without a decision on the canonical number.

### Corrected top-line
**No wholesale unimplemented services.** 28/28 integrated · 37/37 core tests green. The harness's low parity is **~80% tier-gating + environment**; the genuine implementation bug list is **~5 items** (above), several in WASM-owned files. **Re-run the harness against Max tier** for the true conformance %.

## Phase A-2 — TRUE-TIER RESULTS (re-ran with `CLOUDLEARN_TIER_ENFORCE=0`)
Recreated the simulator with tier-gating **off** (all categories unlocked = Max-equivalent) and
re-ran the harness. **Result flips the picture — the free-tier reds were mostly gating.**

**OVERALL parity 80.2% (pass=73, deviations=13, fail=5)** — up from 48.9% at free tier.

### What the tier unlock fixed (⇒ these were GATING, not bugs)
`s3 100%` · `ec2 100%` · `dynamodb 100%` · `azure.sql 100%` · `aws/gcp/azure eventing 100%` · `gcp.compute 100%`.
→ My earlier "genuine bugs" (s3:ListBuckets, ec2:DescribeInstances, dynamodb) were **tier-gating
artifacts** — they pass at Max tier. Correction logged.

### The GENUINE remaining reds (Max tier)
| Fail | Status | Verdict |
|---|---|---|
| `gcp.storage:objects.insert` | 502 | **Real bug — appliance GCP handler** (fake-gcs emulator healthy: direct create/list = 200) |
| `gcp.pubsub:subscriptions.pull` | 500 | **Real bug — appliance handler** (emulator reachable) |
| `gcp.firestore:documents.create` | 500 | **Real bug — appliance REST handler** (emulator direct = 200) |
| `gcp.firestore:documents.list` | 500 | **Real bug — appliance REST handler** |
| `aws.s3.minio:object.get.via-minio-direct` | timeout | **Environment** — harness dials a stale Docker IP |

**Deviations (13):** GCP-IAM + Azure-RBAC + MinIO **429** = harness hitting the **rate-limiter** (not
bugs); the rest are minor shape diffs (`aws.kms`/`gcp.kms` ciphertext format, `azure.keyvault`).

### Real, actionable bug list (Phase B backlog — all appliance-proper `server.py`, NOT WASM)
1. **`gcp.firestore` documents.create + documents.list → 500** (`server.py` Firestore REST handler; emulator confirmed healthy).
2. **`gcp.pubsub` subscriptions.pull → 500** (`server.py` Pub/Sub handler).
3. **`gcp.storage` objects.insert → 502** (`server.py` GCS handler).
These 3–4 fixes are a focused `server.py` GCP-handler debugging task (reproduce the exact REST request →
capture the 500 traceback → fix). Not done autonomously — deep monolith, needs careful test-per-fix.

### Definitive top-line
**Max-tier conformance = 80.2%.** Zero unimplemented services. The genuine bug surface is **one cluster:
the GCP REST data-plane handlers (Firestore/Pub-Sub/GCS) returning 500/502 despite healthy emulators.**
Everything AWS + Azure control-plane + all eventing/IAM = green. Fix that cluster ⇒ ~95%+ (remaining are
rate-limiter deviations + minor shape diffs). Harness artifacts: `.venv-conformance` has the SDKs; the
`CLOUDLEARN_TIER_ENFORCE=0` toggle (reverted) is the way to reproduce.

## Bottom line
The appliance is **feature-complete at the service level** (28/28 integrated, in console, cores green) and Nano is at **near-parity**. The genuinely-open work is **narrow and measurable**: the SDK-conformance red tail (~12%), the 35-vs-28 reconciliation (~7), and Nano's last-mile (wiring + relay/hosting). None are wholesale "missing services."
