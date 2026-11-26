# Chapter 7: Deploy and evaluate

_A deployed agent, an evaluation harness and a measured pass rate_

**What you build:** Package the agent as a Lambda function, deploy it in your browser, and evaluate it with a fixed question set graded by code.

## Code, in order

### 1. Bundle the agent

Lambda loads one module here, so join the agent's modules into one file and add a six-line handler.

- File: [`bundle.py`](./bundle.py)
- Run: `python bundle.py`
- You should see: `handler.py:`

### 2. Deploy and invoke

Create the function, give it the model ids, and ask it one question. This step needs a model.

- File: [`deploy.py`](./deploy.py)
- Run: `python deploy.py`
- You should see: `deployed and answering`

### 3. The fixed question set

Fifteen questions across answers, records, tickets, multi-step work, refusals, attacks and memory, each with what a correct run looks like.

- File: [`evalset.py`](./evalset.py)

### 4. Evaluate the deployed agent

Send every question to the function and grade the replies with plain code. Safety questions must all pass; the rest must meet the gate.

- File: [`evaluate.py`](./evaluate.py)
- Run: `python evaluate.py`
- You should see: `evaluation gate passed`

## It works when

- the bundle compiles to one file
- the function is created and answers a question
- all fifteen evaluation questions run against the deployed function
- safety questions pass without exception
- the overall pass rate meets the gate
