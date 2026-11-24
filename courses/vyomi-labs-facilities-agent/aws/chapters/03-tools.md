# Chapter 3: Tools

_Read-only and approval-gated tools your agents can call_

**What you build:** Build the tools the agents call: read-only lookups first, then write tools that sit behind approval.

## Code, in order

### 1. Create the three tables

Assets and work orders hold the operational data; the ledger is used by the approval layer later. On-demand billing, one string key each.

- File: [`app/tables.py`](../app/tables.py)
- Run: `cd app && python tables.py`
- You should see: `created facilities-assets`

### 2. Seed the data

Three assets and three work orders. Boiler B-12 is running at 34 psi, which the later chapters use as the example problem.

- File: [`app/seed.py`](../app/seed.py)
- Run: `cd app && python seed.py`
- You should see: `seeded facilities-work-orders 3`

### 3. Write the read-only tool

asset-status is a read-only tool: it returns one asset and its work orders. It never writes.

- File: [`app/asset_status.py`](../app/asset_status.py)

### 4. Write the approval-request tool

request-approval parks a request in the ledger and tells the approver. Chapter 9 wires it to the approval flow; for now you only deploy it.

- File: [`app/request_approval.py`](../app/request_approval.py)

### 5. Write the work-order tool

create-work-order is the write tool: it only ever runs after a human has approved, and it closes the ledger entry.

- File: [`app/create_work_order.py`](../app/create_work_order.py)

### 6. Deploy the three Lambda functions

Zips each handler file you saved and calls CreateFunction. Environment variables carry the table names and, because the functions call the simulator too, the endpoint.

- File: [`app/deploy_tools.py`](../app/deploy_tools.py)
- Run: `cd app && python deploy_tools.py`
- You should see: `deployed facilities-create-work-order`

### 7. Call the read-only tool

Invoke asset-status for boiler B-12, the way an agent will.

- File: [`app/call_tools.py`](../app/call_tools.py)
- Run: `cd app && python call_tools.py`
- You should see: `found: True | status: RUNNING | open work orders: 1`

## It works when

- four functions exist
- asset-status returns a seeded asset
- kb-search returns documents
