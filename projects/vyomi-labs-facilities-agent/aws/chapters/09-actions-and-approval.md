# Chapter 9: Actions and Approval

_Writes that wait for a human, with a ledger of every decision_

**What you build:** Make write actions safe: park the action for a human, record every decision, and only then execute.

## Code, in order

### 1. Create the approver inbox

An SNS topic fans an approval request out to an SQS queue that the approver (a person or an app) reads. The script also tells the request-approval function from chapter 7 which topic to publish to. It is safe to re-run.

- File: [`app/approver_inbox.py`](../app/approver_inbox.py)
- Run: `cd app && python approver_inbox.py`
- You should see: `request-approval now publishes to the inbox`

### 2. Create the approval state machine

The workflow is the safety rail. `RequestApproval` is a callback task (`waitForTaskToken`): Step Functions calls the request-approval function with a task token and then waits, for up to a day, until a human sends the token back with SendTaskSuccess or SendTaskFailure. Only then does `CreateWorkOrder` run; a rejection goes to the failing `Rejected` state and nothing is written.

- File: [`app/state_machine.py`](../app/state_machine.py)
- Run: `cd app && python state_machine.py`
- You should see: `state machine arn:aws:states`

### 3. Let the agent ask for a work order

Sends the boiler question to the hosted agent. The Maintenance sub-agent finds B-12, sees the request to raise a work order and starts an execution of the state machine instead of writing. The script then proves the write is parked: the execution is RUNNING, the ledger says PENDING, and no work order exists for this requester yet.

- File: [`app/request_work_order.py`](../app/request_work_order.py)
- Run: `cd app && python request_work_order.py`
- You should see: `work orders written before approval: 0`

### 4. Approve the request

Plays the approver. It reads the approval message from the inbox queue (delivered through SNS), takes the task token from it and sends SendTaskSuccess. The execution resumes, CreateWorkOrder runs, and the ledger entry becomes EXECUTED.

- File: [`app/approve.py`](../app/approve.py)
- Run: `cd app && python approve.py`
- You should see: `work order: OPEN`

### 5. Reject a request

The other branch. A request for an elevator replacement is rejected with SendTaskFailure: the execution FAILS, the ledger keeps the decision, and no work order is written.

- File: [`app/reject.py`](../app/reject.py)
- Run: `cd app && python reject.py`
- You should see: `work orders written despite rejection: 0`

### 6. Read the execution history

The history is the audit trail of the workflow: every state entered, the callback task and who resolved it.

- File: [`app/history.py`](../app/history.py)
- Run: `cd app && python history.py`
- You should see: `history:`

## It works when

- state machine exists
- request parks as PENDING
- nothing written before approval
- approve creates, reject writes nothing
