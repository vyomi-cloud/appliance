# Chapter 6: Guardrails

_A guarded agent that refuses attacks and unsupported questions, tested in code and against a planted instruction_

**What you build:** Add the rules the model cannot talk its way around: a step limit, a tool allow-list, grounded answers, and refusal when the documents do not support one.

## Code, in order

### 1. Write the guardrails

Five small checks: input, action, answer, completeness and the step limit.

- File: [`guard.py`](./guard.py)

### 2. Guard the agent

The loop from chapter 4 with the checks placed between the model and the tools. The model's proposal is checked before anything runs.

- File: [`agent.py`](./agent.py)

### 3. Test the guardrails without a model

Each rule, tried directly: what it stops and what it lets through.

- File: [`guard_test.py`](./guard_test.py)
- Run: `python guard_test.py`
- You should see: `guard tests passed`

### 4. Try the attacks

An unsupported question, a message that attacks the rules, and a handbook page that contains a planted instruction. This step needs a model.

- File: [`try_guarded.py`](./try_guarded.py)
- Run: `python try_guarded.py`
- You should see: `guarded agent ok`

## It works when

- attack messages are stopped before any model call
- a ticket needs a request for one and no call repeats
- an answer without evidence is rejected
- an invented number is rejected
- an unsupported question is refused
- a planted instruction in a document is not obeyed
