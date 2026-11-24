# Layer 13: Governance and Security

_Encrypted records and an audit trail of the run_

**What you build:** Protect and audit the whole app: encrypt the sensitive records and prove who did what.

## Code, in order

### 1. Create a key and protect an approval record

A customer-managed KMS key with an alias and yearly rotation. The approval record is encrypted with an encryption context bound to the ledger table: decrypting with the same context works, decrypting with any other context is refused. Then the same key writes an SSE-KMS object to the bucket.

- File: [`kms_protect.py`](./kms_protect.py)
- Run: `python kms_protect.py` (or `./run_all.sh 13` from the project root)
- You should see: `SSE-KMS object written`

### 2. Turn on CloudTrail

A trail records API calls (who did what, when) into the audit prefix of the bucket. Turn it on before the approvals you want recorded.

- File: [`trail.py`](./trail.py)
- Run: `python trail.py` (or `./run_all.sh 13` from the project root)
- You should see: `logging: True`

### 3. Audit the approval

Looks the approval up in CloudTrail (the Step Functions StartExecution and SendTaskSuccess calls from chapter 5) and in the application-level ledger. Between them they answer: who asked, who approved, what was written.

- File: [`audit.py`](./audit.py)
- Run: `python audit.py` (or `./run_all.sh 13` from the project root)
- You should see: `approval is fully audited: True`

## It works when

- key with rotation exists
- encrypt/decrypt with context
- SSE-KMS object
- trail shows approval events
