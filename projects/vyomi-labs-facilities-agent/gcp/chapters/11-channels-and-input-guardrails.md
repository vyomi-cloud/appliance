# Chapter 11: Channels and Input Guardrails

_Input guardrails and an approver inbox_

**What you build:** Let people reach the agent, filter what comes in, and tell approvers what is waiting.

## Code, in order

### 1. Install the libraries

Chapter 2 lets people reach the agent safely. It relies on gcp.py (chapter 10), guardrail.py (the Model Armor helper from chapter 11, which creates or reuses the template facilities-guardrail) and approval.py (chapter 5, which created the work-order-approval topic and the approver-inbox subscription this chapter checks).

- File: [`app/install_2.sh`](../app/install_2.sh)

### 2. Screen what comes in

sanitizeUserPrompt runs the template's filters on a user message before the agent sees it. The benign facilities question must pass and the classic prompt-injection attack must be flagged (MATCH_FOUND). The screen_input function is what the channel front end calls.

- File: [`app/intake.py`](../app/intake.py)
- Run: `cd app && python intake.py`
- You should see: `benign question allowed: True | prompt injection allowed: False`

### 3. Check the approver inbox

The inbox is the Pub/Sub subscription approver-inbox on the topic work-order-approval. Publish a test request, pull it as an approver would, acknowledge it, and confirm it is not delivered again. The message attributes (requester, kind) travel with the data.

- File: [`app/inbox_check.py`](../app/inbox_check.py)
- Run: `cd app && python inbox_check.py`
- You should see: `redelivered after ack: False`

## It works when

- template exists
- normal question allowed
- prompt injection blocked
- message reaches the inbox
