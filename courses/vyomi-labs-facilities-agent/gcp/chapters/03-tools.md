# Chapter 3: Tools

_Read-only and approval-gated tools your agents can call_

**What you build:** Build the tools the agents call: read-only lookups first, then write tools that sit behind approval.

## Code, in order

### 1. Install the libraries

Chapter 7 builds the tools as Cloud Run functions over Firestore. It relies on gcp.py from chapter 10 and runs after chapter 3. The kb-search tool needs the knowledge base, so it is built in chapter 6; the MCP tool server is built in chapter 4 and the approval inbox wiring in chapter 5. This chapter deploys the three Firestore-only tools: asset-status (read-only), approval-decision and create-work-order (the write tool).

- File: [`app/install_7.sh`](../app/install_7.sh)

### 2. Seed Firestore

Firestore holds the operational data: collection assets and collection work-orders (the names the rest of the course uses). Boiler B-12 is running at 34 psi, which every later chapter uses as the example problem. The Firestore client reads FIRESTORE_EMULATOR_HOST, as it does for Google's emulator.

- File: [`app/seed.py`](../app/seed.py)
- Run: `cd app && python seed.py`
- You should see: `seeded work-orders 3`

### 3. Write the read-only tool

asset-status returns one asset and its work orders and never writes. A Cloud Run function exposes a handler(request) that receives the HTTP request and returns JSON. This is plain Google client code: on real Google Cloud it runs unchanged.

- File: [`app/asset_status_fn.py`](../app/asset_status_fn.py)

### 4. Write the approval-decision tool

The approver sends a decision here. The function checks the request is still PENDING in the ledger and that the approver is authorised (a company address), then records APPROVED or REJECTED. It never creates a work order itself.

- File: [`app/approval_decision_fn.py`](../app/approval_decision_fn.py)

### 5. Write the work-order tool

create-work-order is the write tool and it never trusts its caller: it refuses unless the ledger says APPROVED, writes the work order, then marks the ledger entry EXECUTED. Calling it twice returns the same work order instead of creating a second one.

- File: [`app/create_work_order_fn.py`](../app/create_work_order_fn.py)

### 6. Write the deploy helper

One small helper shared by this chapter and chapters 6, 4, 5 and 12: it zips a source file as main.py, asks Cloud Functions for an upload URL, uploads the zip and creates (or updates) the function, then returns its HTTPS address. The environment variables carry the project and where Firestore is.

- File: [`app/functions.py`](../app/functions.py)

### 7. Deploy the three functions

Cloud Functions gen2 CreateFunction, three times. Names follow the course contract: facilities-asset-status, facilities-approval-decision, facilities-create-work-order.

- File: [`app/deploy_tools.py`](../app/deploy_tools.py)
- Run: `cd app && python deploy_tools.py`
- You should see: `deployed facilities-create-work-order`

### 8. Call the read-only tool

Invoke asset-status for boiler B-12 over HTTPS, the way an agent will. The function runs inside the simulator's function runtime and reads Firestore.

- File: [`app/call_asset_status.py`](../app/call_asset_status.py)
- Run: `cd app && python call_asset_status.py`
- You should see: `found: True | status: RUNNING | open work orders: 1`

### 9. Prove the write tool is gated

The three safety properties of a write tool, checked end to end with a throwaway ledger row: it refuses before approval, a stranger cannot approve, and after an authorised approval it creates exactly one work order. The script removes its test rows afterwards. Chapter 5 connects this same pair of functions to Pub/Sub so a person receives the request.

- File: [`app/check_write_tool.py`](../app/check_write_tool.py)
- Run: `cd app && python check_write_tool.py`
- You should see: `ledger: EXECUTED`

## It works when

- five functions exist
- asset-status returns a seeded asset
- kb-search returns documents
