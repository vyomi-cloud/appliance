# v4/ai-kmsgov

Owner: AI session (round 2 gap-fix). Base: v4/ai-integration (5cb53ee00). Purpose: refapp component 13, KMS Decrypt must reject a wrong EncryptionContext; CloudTrail must audit KMS calls with the context.

## Change
- `core/kms_core.py` (+ vendored `wasm/core/`): the context is bound AEAD-style. Every Encrypt/GenerateDataKey/ReEncrypt seals `MAGIC || SHA-256(canonical JSON of context) || plaintext` through the existing engine, whose HMAC-SHA256 encrypt-then-MAC (or Vault Transit on the appliance) authenticates it. Decrypt verifies the digest in constant time; wrong, missing or extra context gives `InvalidCiphertextException`. Done above the engine so it works with every engine, including Vault. Pre-change ciphertext (no magic) still decrypts.
- New ops: `ReEncrypt` (separate source/destination context and key), `CreateGrant`, `ListGrants`, `RevokeGrant`, `RetireGrant`, `ListRetirableGrants` (persisted on the key record; operations validated).
- `core/cloudtrail_events_core.py`: KMS events carry `requestParameters` (camelCased, `encryptionContext`, `keyId`, never Plaintext/CiphertextBlob), visible in `CloudTrailEvent` from LookupEvents.

## OSS choices
| Need | Choice | Why |
|---|---|---|
| AAD crypto | stdlib hmac/hashlib already in the engine; Vault Transit on appliance | pure Python for Pyodide, no new dep, zero size |
No new backend hand-built; the grant store is a thin metadata list.

## Substrates
Nano (Pyodide, vendored wasm/core) and Mesh both: same core.

## Tests
`PYTHONPATH=. python3 tests/conformance/test_kms_context.py` (real boto3, 16 checks, all pass). Existing kms/c0c/secrets-rotation/gcp-kms suites still green. Facilities e2e: component 13 now PASS 6/6 (9 PASS, 3 BLOCKED, 1 FAIL overall; remaining FAIL c10 ListFoundationModels is another lane's).

## Declared limits
- Key policies and grants are stored and listed but NOT enforced on Decrypt/Encrypt (no IAM evaluation on KMS calls).
- Grant tokens are not honoured as credentials. ListGrants has no pagination.
- Context is not exposed as readable text in the ciphertext (only its hash is bound), unlike nothing in AWS that depends on it.
- CloudTrail is an in-memory ring (see cloudtrail_events_core docstring).
