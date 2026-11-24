# Chapter 11: Channels and Input Guardrails

_Input guardrails and an approver inbox_

**What you build:** Let people reach the agent, filter what comes in, and tell approvers what is waiting.

## Code, in order

### 1. Install the libraries

Chapter 2 guards what comes in and tells approvers what is waiting. Input guardrails: Azure AI Content Safety (`azure-ai-contentsafety`, you call it) and the Azure OpenAI content filter (a policy bound to a deployment that filters every prompt and completion for you). The approver inbox is the Service Bus subscription you created in chapter 5. It uses `azlab.py` (chapter 10) and `approval.py` (chapter 5). Scope note: the simulator's filters are a deterministic rule set, not Microsoft's trained classifiers.

- File: [`app/install2.sh`](../app/install2.sh)

### 2. Screen an input with Content Safety

`analyze_text` returns a severity per harm category (Hate, SelfHarm, Sexual, Violence). A normal facilities question scores 0 everywhere; a threat is flagged. Your channel code calls this before the text reaches the agent, and refuses at or above a threshold you choose.

- File: [`app/screen_input.py`](../app/screen_input.py)
- Run: `cd app && python screen_input.py`
- You should see: `benign question flagged: False`

### 3. Bind a content-filter policy to a model deployment

The second guardrail needs no code in your app: a Responsible AI (RAI) policy, `facilities-guardrail`, filters Violence, Hate, SelfHarm and Sexual content on both the Prompt and the Completion, and is attached to a deployment (`chat-guarded`, same model as `chat`). A harmful prompt is refused with HTTP 400 `content_filter` before any model runs; a benign one reaches the model. Uses `azure-mgmt-cognitiveservices`.

- File: [`app/content_filter.py`](../app/content_filter.py)
- Run: `cd app && python content_filter.py`
- You should see: `violent prompt refused: 400 content_filter`

### 4. Use the approver inbox

The inbox is a Service Bus topic with a subscription behind it. This block makes sure the resources exist (creating them again is a no-op after chapter 5), sends a notification to the topic, and reads it from `approver-inbox` over AMQP 1.0 with peek-lock: *receive* leaves the message locked, *complete* removes it, so it is never delivered twice. It also reads the subscription's message count through Azure Resource Manager, the number an operations dashboard shows.

- File: [`app/inbox.py`](../app/inbox.py)
- Run: `cd app && python inbox.py`
- You should see: `redelivered after complete: 0`

## It works when

- benign allowed, violent flagged
- violent prompt refused
- message reaches the inbox
