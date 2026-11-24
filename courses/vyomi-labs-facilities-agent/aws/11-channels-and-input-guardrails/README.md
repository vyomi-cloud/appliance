# Layer 11: Channels and Input Guardrails

_Input guardrails and an approver inbox_

**What you build:** Let people reach the agent, filter what comes in, and tell approvers what is waiting.

## Code, in order

### 1. Test the input guardrail

The guardrail from chapter 11 also guards the way in. Three probes through ApplyGuardrail with source INPUT: a normal question passes, a prompt-injection attempt is blocked, and the denied word is blocked. Your channel (web chat, Slack bot, API) calls this before the text ever reaches the agent.

- File: [`input_guardrail.py`](./input_guardrail.py)
- Run: `python input_guardrail.py` (or `./run_all.sh 11` from the project root)
- You should see: `denied word: GUARDRAIL_INTERVENED`

### 2. Read the approver inbox

The approver inbox from chapter 5 is the human channel: this publishes a test notification to the topic and reads it from the queue, exactly as an approver app would. Needs the inbox from chapter 5.

- File: [`inbox_channel.py`](./inbox_channel.py)
- Run: `python inbox_channel.py` (or `./run_all.sh 11` from the project root)
- You should see: `inbox delivered: inbox smoke test`

## It works when

- guardrail and version exist
- normal question allowed
- prompt injection blocked
- queue subscribed to the topic
