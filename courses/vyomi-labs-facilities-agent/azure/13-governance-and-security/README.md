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

## It works when

- key exists
- wrap/unwrap round trip
- activity log shows the run
