# Chapter 9: Actions and Approval

_Writes that wait for a human, with a ledger of every decision_

**What you build:** Make write actions safe: park the action for a human, record every decision, and only then execute.

## Code, in order

### 1. Install the libraries

Chapter 5 makes write actions safe. Google Cloud has no single managed approval-workflow service, so this chapter assembles the pattern from parts, and says so plainly: the agent writes a PENDING row to a Firestore ledger and publishes the request on a Pub/Sub topic; an approver reads it from the approver-inbox subscription and calls the approval-decision function (chapter 7); the waiting caller sees the ledger change; the create-work-order function (chapter 7) runs only on APPROVED. It relies on gcp.py (10), functions.py and the two functions from chapter 7. Chapter 2 later reuses the topic and subscription created here.

- File: [`app/install_5.sh`](../app/install_5.sh)

### 2. Write the approval helpers

Four functions: ensure_inbox() creates the work-order-approval topic and the approver-inbox subscription if they are missing; request_approval() records PENDING in the ledger approval-ledger and publishes the request; pull_request() is what an approver's tool does to receive it; wait_for_decision() is the part of the agent run that waits on the ledger. Pub/Sub and Firestore use the Google clients' default gRPC transport against the emulators.

- File: [`app/approval.py`](../app/approval.py)

### 3. Create the approver inbox

Creates the topic and the subscription.

- File: [`app/setup_inbox.py`](../app/setup_inbox.py)
- Run: `cd app && python setup_inbox.py`
- You should see: `subscription approver-inbox ready`

### 4. Let the agent request a work order

Runs the supervisor from chapter 3 on a question that asks for a work order and, because it is a write, files an approval request instead of writing. The script proves two things: the ledger says PENDING and no work order exists yet. It saves the request id for the next steps.

- File: [`app/submit_request.py`](../app/submit_request.py)
- Run: `cd app && python submit_request.py`
- You should see: `no work order exists before approval`

### 5. Approve it as the approver and let the work order be created

The approver receives the request from the inbox, a stranger fails to approve it, an authorised approver approves it, the waiting caller sees APPROVED and only then create-work-order runs. A second call is idempotent. The ledger ends as EXECUTED with the approver recorded.

- File: [`app/approve_request.py`](../app/approve_request.py)
- Run: `cd app && python approve_request.py`
- You should see: `| ledger: EXECUTED by duty.manager@example.com | idempotent: True`

### 6. Reject a request

The other outcome: a request that is rejected stays out of work-orders. The script files a request for elevator EL-3, rejects it as the approver, and shows create-work-order refusing.

- File: [`app/reject_request.py`](../app/reject_request.py)
- Run: `cd app && python reject_request.py`
- You should see: `decision: REJECTED | create refused: True | work orders written: 0`

## It works when

- request parks as PENDING
- nothing written before approval
- unauthorised approver rejected
- approve creates the work order
