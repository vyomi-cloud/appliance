# Layer 10: Actions and Approval

_Writes that wait for a human, with a ledger of every decision_

**What you build:** Make write actions safe: park the action for a human, record every decision, and only then execute.

## Code, in order

### 1. Install the libraries

Chapter 5 makes write actions safe: the agent never writes a work order directly. It parks a request for a human, the human decides, and only an APPROVED request can be executed. Honest scope note: Azure has no single managed service for this, so the flow is ASSEMBLED from three real parts, and the code says so: an Azure Table ledger is the system of record (`approvalledger`), an Azure Service Bus topic with an `approver-inbox` subscription delivers the request to the approver (AMQP 1.0), and the two functions from chapter 7 (`approval-decision`, `create-work-order`) enforce the rules. Logic Apps and Durable Functions are the managed orchestrators Azure also offers; they are not used here. Needs chapter 7 (functions, tables).

- File: [`install5.sh`](./install5.sh)

### 2. Create the Service Bus namespace, topic and approver inbox

Through `azure-mgmt-servicebus`: a Standard namespace `facilities-bus`, a topic `work-order-approval` (every request is published here) and a subscription `approver-inbox` (the approver reads from it). Chapter 2 later uses the same inbox for notifications.

- File: [`create_bus.py`](./create_bus.py)
- Run: `python create_bus.py` (or `./run_all.sh 10` from the project root)
- You should see: `subscription approver-inbox`

### 3. Write the approval helpers

The three halves of the flow in one module. `request_approval` is what the agent calls: ledger row `PENDING` first, then the message on the topic, and nothing else (no work order). `pull_request` is the approver's side: read the inbox over AMQP with peek-lock, complete the message that belongs to this request and put the others back. `wait_decision` is the parked caller: it polls the ledger until the status leaves `PENDING`. The Service Bus connection string is the vendor emulator form (`UseDevelopmentEmulator=true`); on real Azure it is the same string without that flag.

- File: [`approval.py`](./approval.py)

### 4. Park a request: nothing is written yet

The agent asks for a work order on boiler B-12. Check the four guarantees of the parking step: the ledger row is `PENDING`; no work order exists; `create-work-order` refuses the request even if someone calls it directly; and an approver who is not on the allow-list cannot decide it (the ledger stays `PENDING`).

- File: [`park_request.py`](./park_request.py)
- Run: `python park_request.py` (or `./run_all.sh 10` from the project root)
- You should see: `ledger status: PENDING
work orders requested by maria: 0`

### 5. Approve: the parked caller proceeds and the work order is created

The approver pulls the request from the inbox, then calls `approval-decision`. A background thread plays the parked agent: it polls the ledger and wakes the moment the status changes. Only then does `create-work-order` run, and it writes the work order and closes the ledger row (`EXECUTED`, with the approver recorded). A second call is idempotent: still one work order.

- File: [`approve_request.py`](./approve_request.py)
- Run: `python approve_request.py` (or `./run_all.sh 10` from the project root)
- You should see: `second call idempotent: True | work orders for B-12 from this request: 1`

### 6. Reject, and refuse a late decision

A second request is rejected: the ledger says `REJECTED`, `create-work-order` refuses, and no work order is written. Last, optimistic concurrency: a decision written with a stale ETag is refused with HTTP 412, so two approvers can never both decide the same request.

- File: [`reject_request.py`](./reject_request.py)
- Run: `python reject_request.py` (or `./run_all.sh 10` from the project root)
- You should see: `decision with a stale ETag refused: 412`

## It works when

- request parks as PENDING
- nothing written before approval
- unauthorised approver rejected
- approve creates the work order
