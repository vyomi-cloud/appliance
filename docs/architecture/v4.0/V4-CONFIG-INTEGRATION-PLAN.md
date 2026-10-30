# v4 — Integrating console configs into Vyomi backends (S3 + DynamoDB first)

**Status:** proposal · **Date:** 2026-10-30 · **Parent:** V4-NATIVE-FIDELITY-CONSOLES-PLAN.md

## 1. Problem

The v4 S3 and DynamoDB consoles now match the native layout, but most sub-sections are grey
"Not simulated" panels: 29 S3 config sections and 11 DynamoDB ones, from the real-console
spec. Each one needs a decision:

- back it with a real backend behaviour,
- store it faithfully without enforcing it, or
- leave it out, saying so clearly.

The user must always be able to tell which of these a setting is.

## 2. Support levels (the disclaimer model)

Every feature gets exactly one level per substrate (offline appliance, Codespaces sandbox, Nano).

| Level | Meaning | UI treatment |
|---|---|---|
| **Full** | Stored and behaves like the cloud (enforced, observable through SDK/CLI) | No badge |
| **Limited** | Works, with stated limitations (e.g. TTL expiry on next access, not within 48 h) | Blue **"Limited in Vyomi"** badge; popover lists the limitations |
| **Config only** | Accepted, persisted and returned by the API exactly like the cloud, but not enforced | Grey-blue **"Config only"** badge; save confirmations say "Saved. Vyomi stores this setting but does not enforce it." |
| **Not simulated** | Not available. The API returns the native "not implemented" error | Grey panel (today's `NotSimulated`) |

Rules:
- Badges sit beside the section header, so they're visible without clicking.
- The help panel gets a "Vyomi notes" section listing every limitation on the page.
- Native API responses are never altered. The disclaimer lives in the UI and in the
  compatibility docs, not in the wire.

## 3. Single source of truth: the capability registry

`core/capabilities/<cloud>/<service>.json` (vendored to `wasm/core` with the cores):

```json
{
  "s3.bucket.lifecycle": {
    "title": "Lifecycle rules",
    "spec_sections": ["Lifecycle rules"],
    "api": ["PutBucketLifecycleConfiguration", "GetBucketLifecycleConfiguration", "DeleteBucketLifecycle"],
    "level": { "offline": "limited", "nano": "limited", "sandbox": "limited" },
    "limitations": [
      "Expiration runs when objects are listed or read (and on a 1-minute sweep offline), not on AWS's daily schedule.",
      "Transitions change the reported storage class; no data moves between tiers."
    ],
    "tests": ["tests/conformance/test_s3_lifecycle_core.py"]
  }
}
```

The registry is used in three places:
1. **Console:** a `<Capability id="s3.bucket.lifecycle">` wrapper renders the badge, the
   popover and the save notice from the registry. Agents never hand-write disclaimers.
2. **Conformance:** `tests/conformance/test_capabilities.py` proves every claim.
   - `full`/`limited` features must have their listed tests passing.
   - `config_only` features must round-trip (PUT → GET returns the same document).
   - `not_simulated` features must return the native 501/UnknownOperation.

   So the disclaimer cannot be wrong in either direction: it can't claim support that
   doesn't exist, and it can't hide support that does.
3. **Docs:** a generated "Vyomi compatibility" page per service, published with releases.
   The same data can feed the portal's service matrix.

## 4. Prerequisite: one engine per service across substrates

Today the same S3 feature had to be fixed twice:
- **Nano** uses `core/s3_object_core.py`.
- **The offline appliance** uses the legacy `routes/aws_s3.py`. The shared core runs offline
  only with `VYOMI_UNIFIED_INGRESS=1`, which no compose file sets.
- `MinioBackedObjectStore` rebuilds its bucket list from MinIO on start, so bucket
  configuration lives only in memory.

**Step C0 (do first):**
- Make the shared cores the offline engine for S3 and DynamoDB in v4.
- Turn on unified ingress for those two services, with the legacy path kept behind a flag.
- Give the MinIO-backed store a SQLite sidecar for bucket metadata: config, versioning,
  object lock, tags.
- Validate with the existing conformance suites, the v4 smoke tests and
  `tests/test_wire_prefix.py` on a real MinIO stack.

After C0, each feature is implemented once and appears on every substrate.

## 5. Triage — S3

| Feature | Today | Target | How (backend) |
|---|---|---|---|
| Bucket Versioning + Versions tab | stored, versioned writes in core | **Full** | `?versions` (ListObjectVersions), get/delete by `versionId`; "Show versions" toggle in the Objects tab |
| Bucket tags / object tags | bucket only | **Full** | object `?tagging` |
| Object metadata, content-type, checksums | partial | **Full** | real CRC32/SHA-256 on upload (`x-amz-checksum-*`) |
| Default encryption (SSE-S3 / SSE-KMS / DSSE) | stored | **Limited** | objects report `x-amz-server-side-encryption`; SSE-KMS key validated against the KMS store. *Limitation: data is not encrypted at rest in Nano.* |
| Block Public Access | stored | **Limited** | enforced on PutBucketPolicy / PutBucketAcl (public grants rejected). *Limitation: Vyomi does not authenticate requests, so anonymous reads are not blocked.* |
| Bucket policy | stored | **Limited** | JSON validated (principal/action/resource/condition syntax). *Not evaluated for authorization.* |
| Object Ownership / ACLs | stored (ACL default) | **Config only** | round-trip only |
| CORS | stored | **Limited** | CORS headers applied to browser requests and OPTIONS preflight served |
| Lifecycle rules | stored | **Limited** | expiration (current + non-current versions, delete markers, incomplete MPU) applied lazily + sweep; transitions relabel storage class |
| Object Lock (retention, legal hold) | flag only | **Full** | enforce on DeleteObject/PutObject with versionId; governance bypass header |
| Static website hosting | 501 | **Limited** | serve index/error documents + redirects at `/_website/<bucket>/` (Nano) / the gateway (offline) |
| Event notifications | 501 in core | **Limited** | deliver to SQS / SNS / Lambda / EventBridge in the same router (stores already shared) |
| Amazon EventBridge toggle | none | **Limited** | emits "Object Created/Deleted" events to the events store |
| Server access logging | 501 | **Limited** | log objects written to the target bucket/prefix (simplified format) |
| Metrics tab (storage, requests) | grey | **Limited** | computed from the store + request counters, labelled "simulated metrics" |
| Replication rules | 501 | **Limited** (later wave) | async copy to a destination bucket inside the simulator |
| Requester pays, Transfer acceleration, Intelligent-Tiering archive | 501 | **Config only** | round-trip |
| CloudTrail data events | grey | **Limited** | link to Vyomi's cloudsim event log for the bucket |
| Access Points | grey | **Not simulated** (re-evaluate later) | — |
| S3 Metadata tables, Directory/Table/Vector buckets, File systems, Storage Lens, Batch Operations, Access Grants, Access Analyzer, Inventory, Analytics | grey | **Not simulated** | allowlisted |

## 6. Triage — DynamoDB

| Feature | Today | Target | How (backend) |
|---|---|---|---|
| Capacity mode, throughput (UpdateTable) | create only | **Limited** | UpdateTable persists. *Limitation: no throttling.* |
| Table class | stored | **Config only** | — |
| Warm throughput | none | **Config only** | — |
| GSIs / LSIs | GSI in core | **Full** | add/delete GSI through UpdateTable; LSI at create; Query on index |
| Encryption at rest | stored | **Limited** | KMS key validated against the KMS store; not encrypted at rest |
| Deletion protection | stored | **Full** | DeleteTable rejected while enabled |
| TTL | none | **Limited** | items expire lazily on read/scan + sweep. *Real DynamoDB deletes within ~48 h.* |
| On-demand backups + restore | none | **Full** | snapshot copies in the store |
| PITR | none | **Limited** | restore to any minute within the window, from a change log. *Window capped (e.g. 24 h) in Nano.* |
| DynamoDB Streams | flag only | **Limited** | change log exposed through the Streams API (DescribeStream / GetShardIterator / GetRecords); Lambda triggers via router |
| Kinesis data stream | none | **Limited** (later) | write change records to the Kinesis store |
| Export to S3 / Import from S3 | none | **Limited** | DynamoDB-JSON export into the S3 store and import from it (same router; offline needs C0) |
| PartiQL | none | **Limited** | SELECT / INSERT / UPDATE / DELETE subset; unsupported syntax returns the native ValidationException |
| Monitor (CloudWatch metrics + alarms) | grey | **Limited** | request/consumed-capacity counters, labelled simulated |
| Resource-based policy | grey | **Config only** | — |
| Tags | done | **Full** | — |
| Global tables | grey | **Not simulated** | single-region simulator |
| DAX, reserved capacity, integrations | grey | **Not simulated** | allowlisted |

Result after all waves: S3 has 23 of 29 sections behind real or limited backends. DynamoDB has
14 of 17 feature rows. Every remaining gap is labelled.

## 7. Waves

| Wave | Content | Who |
|---|---|---|
| **W0 — Foundation** | Capability registry + schema; `<Capability>` badge/popover/save-notice component; `test_capabilities.py`; help-panel "Vyomi notes"; generated compatibility page | Orchestrator (serial; shared files) |
| **C0 — One engine** | Shared cores serve S3 + DynamoDB offline (unified ingress for these services); SQLite sidecar for MinIO bucket metadata; legacy behind a flag | Orchestrator + one agent; validated on a real MinIO stack |
| **W1 — Config round-trip** | Every "Config only" / "Limited" setting persists and round-trips on all substrates, with editable UI forms (Edit buttons, not just read-only views) | Runner agents, one queue file per cluster |
| **W2 — Enforced behaviour** | Versions tab, Object Lock, lifecycle expiry, BPA enforcement, CORS, deletion protection, TTL, backups/PITR, UpdateTable/GSIs, PartiQL | Runner agents |
| **W3 — Cross-service emulation** | S3 event notifications / EventBridge, website hosting, access logging, metrics; DynamoDB Streams, export/import, Kinesis | Runner agents (touch the router: serialized per service) |

Work items are queued **per feature cluster**, not per service, so several agents can work on
one service in parallel. Example: `aws-s3--object-lock.json` carries the registry ids it must
deliver. The gate adds one rule: every registry entry touched by the run must pass
`test_capabilities.py` on both dev_server (core) and the offline appliance.

## 8. Decisions needed

1. **C0:** make the shared cores the offline engine for S3 + DynamoDB in v4 (legacy behind a
   flag). This is recommended: without it, every feature is built twice and the substrates
   drift.
2. **The four levels and badge wording:** Full / Limited in Vyomi / Config only / Not simulated.
3. **Simulated metrics:** CloudWatch-style numbers computed from real request counts, clearly
   labelled. Acceptable?
4. **Priority:** W1 → W2 → W3 as listed, or pull specific features forward (e.g. event
   notifications, static website hosting)?
