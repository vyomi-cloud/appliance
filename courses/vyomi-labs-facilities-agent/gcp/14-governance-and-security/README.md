# Layer 14: Governance and Security

_Encrypted records and an audit trail of the run_

**What you build:** Protect and audit the whole app: encrypt the sensitive records and prove who did what.

## Code, in order

### 1. Install the libraries

Chapter 13 protects and audits the app. It relies on gcp.py (chapter 10) and on the approval ledger and requests from chapter 5. The pattern is envelope encryption: a fresh data key encrypts the record locally and Cloud KMS wraps that data key, so the sensitive record itself never leaves your process and the key never leaves KMS.

- File: [`install_13.sh`](./install_13.sh)

### 2. Create the key ring and the key

A key ring facilities with a symmetric key ledger-key (purpose ENCRYPT_DECRYPT) that rotates every 90 days.

- File: [`create_key.py`](./create_key.py)
- Run: `python create_key.py` (or `./run_all.sh 14` from the project root)
- You should see: `key: facilities/cryptoKeys/ledger-key with 90-day rotation`

### 3. Encrypt an approval record with an encryption context

Envelope encryption: generate a data key, encrypt the record with it, have KMS wrap the data key and bind the wrap to additional authenticated data (the encryption context, here the ledger collection name). Decrypting with the same context works; decrypting with a different context must be refused, so a wrapped key lifted from one place cannot be replayed in another.

- File: [`seal_record.py`](./seal_record.py)
- Run: `python seal_record.py` (or `./run_all.sh 14` from the project root)
- You should see: `wrong context refused`

### 4. Read the audit trail

Cloud Audit Logs record who created what. Read the admin-activity log and check that the key ring and key you just created, the approval topic from chapter 5 and the service account from chapter 1 (if you ran it) appear. Data-access audit logs are opt-in on Google Cloud and are not asserted here.

- File: [`audit_trail.py`](./audit_trail.py)
- Run: `python audit_trail.py` (or `./run_all.sh 14` from the project root)
- You should see: `the run is in the audit log`

### 5. Check the application-level audit record

The Firestore ledger approval-ledger is the system of record for the approvals themselves: who asked, who decided, what executed. This lists it and requires that an executed request from chapter 5 is there.

- File: [`ledger_audit.py`](./ledger_audit.py)
- Run: `python ledger_audit.py` (or `./run_all.sh 14` from the project root)
- You should see: `approved by duty.manager@example.com`

### 6. Key rotation without re-encrypting data

Rotation adds a new key VERSION and makes it primary; earlier versions still decrypt what they sealed, so nothing already wrapped breaks. The block wraps a data key, creates a new version, promotes it, asserts the primary changed, decrypts the OLD ciphertext (Cloud KMS picks the version from the ciphertext) and wraps again under the new primary.

- File: [`key_rotation.py`](./key_rotation.py)
- Run: `python key_rotation.py` (or `./run_all.sh 14` from the project root)
- You should see: `key rotation verified`

### 7. Tamper-evident audit trail

Cloud Audit Logs record the control plane; they cannot prove nobody edited your own approval records. Chain them: each audit document stores the SHA-256 of the previous one plus its own content, so changing, deleting or re-ordering any entry breaks every hash after it. The block writes five events to Firestore, verifies the chain, edits one entry the way an attacker with database access would and asserts the verifier names exactly that entry.

- File: [`audit_chain.py`](./audit_chain.py)
- Run: `python audit_chain.py` (or `./run_all.sh 14` from the project root)
- You should see: `audit chain verified`

### 8. Ship it: deploy the stack with Infrastructure Manager

The capstone. Infrastructure Manager runs Terraform for you: you hand it a configuration and a service account, it creates a deployment, a revision and the resources. Here the configuration describes the course's bucket and Pub/Sub topic. The block creates the deployment through the real `config.googleapis.com` REST API, waits for the long-running operation, asserts the revision applied and lists its resources. On real Google Cloud you point `gcsSource` or `gitSource` at the same files, and replace simulator-only values (project id, bucket names must be globally unique) first.

- File: [`ship_it.py`](./ship_it.py)
- Run: `python ship_it.py` (or `./run_all.sh 14` from the project root)
- You should see: `ship it verified`

## It works when

- key with rotation
- wrong AAD refused
- audit entries for the run
