# Layer 14: Governance and Security

_Encrypted records and an audit trail of the run_

**What you build:** Protect and audit the whole app: encrypt the sensitive records and prove who did what.

## Code, in order

### 1. Create a key and protect an approval record

A customer-managed KMS key with an alias and yearly rotation. The approval record is encrypted with an encryption context bound to the ledger table: decrypting with the same context works, decrypting with any other context is refused. Then the same key writes an SSE-KMS object to the bucket.

- File: [`kms_protect.py`](./kms_protect.py)
- Run: `python kms_protect.py` (or `./run_all.sh 14` from the project root)
- You should see: `SSE-KMS object written`

### 2. Turn on CloudTrail

A trail records API calls (who did what, when) into the audit prefix of the bucket. Turn it on before the approvals you want recorded.

- File: [`trail.py`](./trail.py)
- Run: `python trail.py` (or `./run_all.sh 14` from the project root)
- You should see: `logging: True`

### 3. Audit the approval

Looks the approval up in CloudTrail (the Step Functions StartExecution and SendTaskSuccess calls from chapter 5) and in the application-level ledger. Between them they answer: who asked, who approved, what was written.

- File: [`audit.py`](./audit.py)
- Run: `python audit.py` (or `./run_all.sh 14` from the project root)
- You should see: `approval is fully audited: True`

### 4. Rotate the key and prove old data still opens

Rotation must never strand data. This block rotates the key on demand, checks the rotation was recorded, then asserts the record encrypted before the rotation still decrypts and a record encrypted after it does too. The policy lesson: rotate on a schedule, never delete old key material while ciphertext depends on it.

- File: [`key_rotation.py`](./key_rotation.py)
- Run: `python key_rotation.py` (or `./run_all.sh 14` from the project root)
- You should see: `key rotation verified`

### 5. Make the audit trail tamper-evident

A trail the writer can edit is not evidence. Every ledger decision is chained: each entry's hash covers the previous hash, so changing, removing or reordering any entry breaks every hash after it. The head hash is signed with a KMS HMAC key held by a different identity than the writer, so even rewriting the whole chain is detected. The block then attacks its own trail three ways (edit an entry, delete the last entry, rewrite the chain) and asserts each is caught and located.

- File: [`audit_chain.py`](./audit_chain.py)
- Run: `python audit_chain.py` (or `./run_all.sh 14` from the project root)
- You should see: `tamper evidence verified`

### 6. Who did what: the identity behind each approval

Joins the two audit sources that chapter 5 produced: the ledger (what was decided) and the IAM audit log (which principal was allowed or refused). It asserts the approver and the requester are different identities, that the refused self-approval is on record, and says plainly which prerequisite is missing if the Enforce step was skipped.

- File: [`audit_who.py`](./audit_who.py)
- Run: `python audit_who.py` (or `./run_all.sh 14` from the project root)
- You should see: `identity audit verified`

### 7. Ship it: export the stack as Terraform, read the real-cloud warnings, rebuild and compare

The stack you built is only worth selling if it can leave the simulator. Infrastructure Studio (in the AWS console: `#/tfstudio`) reads the live stack through the same API calls Terraform's provider makes and writes it as Terraform. This block does what a reviewer would do: export for the simulator and for a real account, read the portability warnings, fix what the warnings flag (the account id baked into the least-privilege policies from the earlier chapters), delete a table to simulate a lost environment, let Terraform plan and apply to rebuild it, and compare before and after. It also lists what the export does NOT cover, so nobody ships a stack believing the diagram is complete.

- File: [`ship_it.py`](./ship_it.py)
- Run: `python ship_it.py` (or `./run_all.sh 14` from the project root)
- You should see: `ship-it verified`

## It works when

- key with rotation exists
- encrypt/decrypt with context
- SSE-KMS object
- trail shows approval events
