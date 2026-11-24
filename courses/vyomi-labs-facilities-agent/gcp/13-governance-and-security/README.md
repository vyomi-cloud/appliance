# Layer 13: Governance and Security

_Encrypted records and an audit trail of the run_

**What you build:** Protect and audit the whole app: encrypt the sensitive records and prove who did what.

## Code, in order

### 1. Install the libraries

Chapter 13 protects and audits the app. It relies on gcp.py (chapter 10) and on the approval ledger and requests from chapter 5. The pattern is envelope encryption: a fresh data key encrypts the record locally and Cloud KMS wraps that data key, so the sensitive record itself never leaves your process and the key never leaves KMS.

- File: [`install_13.sh`](./install_13.sh)

### 2. Create the key ring and the key

A key ring facilities with a symmetric key ledger-key (purpose ENCRYPT_DECRYPT) that rotates every 90 days.

- File: [`create_key.py`](./create_key.py)
- Run: `python create_key.py` (or `./run_all.sh 13` from the project root)
- You should see: `key: facilities/cryptoKeys/ledger-key with 90-day rotation`

### 3. Encrypt an approval record with an encryption context

Envelope encryption: generate a data key, encrypt the record with it, have KMS wrap the data key and bind the wrap to additional authenticated data (the encryption context, here the ledger collection name). Decrypting with the same context works; decrypting with a different context must be refused, so a wrapped key lifted from one place cannot be replayed in another.

- File: [`seal_record.py`](./seal_record.py)
- Run: `python seal_record.py` (or `./run_all.sh 13` from the project root)
- You should see: `wrong context refused`

### 4. Read the audit trail

Cloud Audit Logs record who created what. Read the admin-activity log and check that the key ring and key you just created, the approval topic from chapter 5 and the service account from chapter 1 (if you ran it) appear. Data-access audit logs are opt-in on Google Cloud and are not asserted here.

- File: [`audit_trail.py`](./audit_trail.py)
- Run: `python audit_trail.py` (or `./run_all.sh 13` from the project root)
- You should see: `the run is in the audit log`

### 5. Check the application-level audit record

The Firestore ledger approval-ledger is the system of record for the approvals themselves: who asked, who decided, what executed. This lists it and requires that an executed request from chapter 5 is there.

- File: [`ledger_audit.py`](./ledger_audit.py)
- Run: `python ledger_audit.py` (or `./run_all.sh 13` from the project root)
- You should see: `approved by duty.manager@example.com`

## It works when

- key with rotation
- wrong AAD refused
- audit entries for the run
