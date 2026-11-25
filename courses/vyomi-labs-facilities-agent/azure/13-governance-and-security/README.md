# Layer 13: Governance and Security

_Encrypted records and an audit trail of the run_

**What you build:** Protect and audit the whole app: encrypt the sensitive records and prove who did what.

## Code, in order

### 1. Install the libraries

Chapter 13 protects and audits the app. Azure Key Vault holds a key (`azure-mgmt-keyvault` creates the vault, `azure-keyvault-keys` uses the key); you encrypt the sensitive approval record with envelope encryption; and the Azure Activity Log (`azure-mgmt-monitor`) is the audit trail of the control-plane operations the whole course performed. It needs the approval record from chapter 5 and uses `approval.py` and `azlab.py`.

- File: [`install13.sh`](./install13.sh)

### 2. Create the Key Vault

The vault `facilities-kv` through Azure Resource Manager, standard SKU, no access policies (the simulator does not enforce them: RBAC evaluation is simplified).

- File: [`create_vault.py`](./create_vault.py)
- Run: `python create_vault.py` (or `./run_all.sh 13` from the project root)
- You should see: `vault facilities-kv created`

### 3. Create the key

`KeyClient.create_rsa_key` makes the 2048-bit RSA key `ledger-key`. On real Azure the vault address is `https://facilities-kv.vault.azure.net`. The simulator serves its vault API on its own https host, so the client is given that address and `verify_challenge_resource=False`, the documented option for vault hosts that are not `*.vault.azure.net` (private endpoints, sovereign clouds).

- File: [`make_key.py`](./make_key.py)
- Run: `python make_key.py` (or `./run_all.sh 13` from the project root)
- You should see: `listed: ['ledger-key']`

### 4. Encrypt the approval record with envelope encryption

Never encrypt data directly with a vault key: generate a random 256-bit data key (DEK), encrypt the record locally with AES-GCM (the approval ledger row from chapter 5 as the associated data is the table name), and ask Key Vault only to *wrap* the DEK. Store the wrapped DEK next to the ciphertext. To read it back, unwrap the DEK in the vault and decrypt locally. Rotating the vault key then never means re-encrypting the data. The last lines check a plain encrypt/decrypt round trip with the same key.

- File: [`envelope.py`](./envelope.py)
- Run: `python envelope.py` (or `./run_all.sh 13` from the project root)
- You should see: `unwrap + decrypt restores the record: True`

### 5. Read the audit trail from the Activity Log

Every create you ran in this course was a control-plane operation, and Azure records each one in the Activity Log. `activity_logs.list` takes an OData filter on time and resource group. The check looks for the vault and the function app you created.

- File: [`audit.py`](./audit.py)
- Run: `python audit.py` (or `./run_all.sh 13` from the project root)
- You should see: `vault create recorded: True | function app create recorded: True`

### 6. Key rotation without re-encrypting data

Rotation creates a new key VERSION under the same name; old versions stay available to decrypt, so nothing already wrapped breaks. The block wraps a data key, rotates `ledger-key`, asserts the version list grew and the current version changed, then unwraps the OLD wrapped key (pinned to its version) and wraps a new one with the new version.

- File: [`key_rotation.py`](./key_rotation.py)
- Run: `python key_rotation.py` (or `./run_all.sh 13` from the project root)
- You should see: `key rotation verified`

### 7. Tamper-evident audit trail

The Activity Log tells you what happened; it cannot prove nobody edited your own approval records. Chain them: each audit entry stores the SHA-256 of the previous entry plus its own content, so changing, deleting or re-ordering any entry breaks every hash after it. The block writes five approval events to a table, verifies the chain, edits one entry the way an attacker with table access would, and asserts the verifier finds exactly where.

- File: [`audit_chain.py`](./audit_chain.py)
- Run: `python audit_chain.py` (or `./run_all.sh 13` from the project root)
- You should see: `audit chain verified`

### 8. Ship it: export the resource group as an ARM template

The capstone. Export `rg-facilities` as an ARM template (the same call as the portal's Export template and `az group export`), read the portability warnings the export returns, and check the template is a real deployable: schema, parameters, and the resources the course created. On real Azure you would deploy it with `az deployment group create` into a new subscription, after replacing simulator-only values (storage keys, host names) and resolving the warnings.

- File: [`ship_it.py`](./ship_it.py)
- Run: `python ship_it.py` (or `./run_all.sh 13` from the project root)
- You should see: `ship it verified`

## It works when

- key exists
- wrap/unwrap round trip
- activity log shows the run
