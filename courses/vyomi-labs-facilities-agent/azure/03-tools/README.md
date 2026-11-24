# Layer 3: Tools

_Read-only and approval-gated tools your agents can call_

**What you build:** Build the tools the agents call: read-only lookups first, then write tools that sit behind approval.

## Code, in order

### 1. Install the libraries

Chapter 7 reads and writes Azure Table storage (`azure-data-tables`), creates the Function App and the AI Search service through Azure Resource Manager, and calls the functions over HTTPS. It uses `azlab.py` from chapter 10.

- File: [`install7.sh`](./install7.sh)

### 2. Write the data helpers

Small helpers shared by chapters 7, 5, 9 and 6: the Storage connection string in the Azurite form with an explicit `TableEndpoint` (that is how the Azure SDKs are pointed at an emulator), the AI Search address and admin key as ARM reports them, and an HTTPS call to a function with its host key.

- File: [`azdata.py`](./azdata.py)

### 3. Create the AI Search service

The knowledge-search tool needs the address and key of an Azure AI Search service as application settings, so create the service now (chapters 12 and 6 fill and query it). Basic SKU, one ARM call with the real `azure-mgmt-search` client.

- File: [`create_search.py`](./create_search.py)
- Run: `python create_search.py` (or `./run_all.sh 3` from the project root)
- You should see: `search service facilities-search ready`

### 4. Create the Table storage tables and seed the data

Table storage holds the operational data. Three tables: `assets`, `workorders`, and `approvalledger` (the approval system of record, used from chapter 5). Rows are addressed by PartitionKey plus RowKey. Boiler B-12 runs at 34 psi, the example problem used in later chapters.

- File: [`seed.py`](./seed.py)
- Run: `python seed.py` (or `./run_all.sh 3` from the project root)
- You should see: `created approvalledger (empty)`

### 5. Write the knowledge-search tool

Read-only. It calls Azure AI Search with the real `azure-search-documents` client, using the address and key from the function's application settings. It returns passages with their source name so answers can cite them. It runs after chapter 12 has filled the index.

- File: [`fn_kb_search.py`](./fn_kb_search.py)

### 6. Write the asset-status tool

Read-only. It returns one asset and its work orders from Table storage. It never writes.

- File: [`fn_asset_status.py`](./fn_asset_status.py)

### 7. Write the approval-decision tool

The decision half of the approval flow (used in chapter 5). It records APPROVED or REJECTED in the ledger only if the request is still PENDING and the approver is on the allow-list, using an ETag-conditional update so two approvers cannot both decide. It never creates the work order.

- File: [`fn_approval_decision.py`](./fn_approval_decision.py)

### 8. Write the work-order tool

The write tool. It refuses unless the ledger says APPROVED, creates the work order, then marks the ledger row EXECUTED. Calling it twice creates one work order (idempotent).

- File: [`fn_create_work_order.py`](./fn_create_work_order.py)

### 9. Deploy the Function App

Four steps, the same ones `az functionapp create`, `az functionapp config appsettings set` and `az functionapp deployment source config-zip` perform: an App Service plan (consumption), the site, its application settings (the Table connection string, the search address and key, the table names) and a zip deploy of the four functions in the Python v1 layout (`<name>/__init__.py` plus `function.json`). On real Azure the settings would be Key Vault references or a managed identity.

- File: [`deploy_tools.py`](./deploy_tools.py)
- Run: `python deploy_tools.py` (or `./run_all.sh 3` from the project root)
- You should see: `deployed facilities-tools ['approval-decision', 'asset-status', 'create-work-order', 'kb-search']`

### 10. Call the read-only tool

Call asset-status for boiler B-12 over HTTPS with the host key (`x-functions-key`), the way an agent or the API Management gateway will. The table read happens inside the function.

- File: [`call_tools.py`](./call_tools.py)
- Run: `python call_tools.py` (or `./run_all.sh 3` from the project root)
- You should see: `found: True | status: RUNNING | work orders: 1`

## It works when

- functions listed
- asset-status returns a seeded asset
- kb-search returns documents
