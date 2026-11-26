# Chapter 2: A model in your browser

_A model client that returns one validated action per call, with a measured reliability_

**What you build:** Replace the rules with a small language model that runs in your browser, and make it reliable with a strict action protocol.

## Code, in order

### 1. Create the AWS clients

One file that creates the Bedrock, S3, DynamoDB and SQS clients, so every module shares them. Later chapters reuse it.

- File: [`aws.py`](./aws.py)

### 2. Write the model client

The Converse call, the action list, the parser, the schema check and the one retry. Read parse_action and validate_action first.

- File: [`llmx.py`](./llmx.py)

### 3. Test the protocol without a model

Feed the parser replies a small model really produces: clean, wrapped in prose or a code fence, unclosed, with an invented action, with a bad id.

- File: [`protocol_test.py`](./protocol_test.py)
- Run: `python protocol_test.py`
- You should see: `protocol tests passed`

### 4. Talk to the model

A plain chat turn, then three questions through the protocol. This step needs a model: Deploy will offer to load one.

- File: [`try_model.py`](./try_model.py)
- Run: `python try_model.py`
- You should see: `valid actions: 3 of 3`

### 5. Measure the protocol

Twelve questions: how many replies are valid first time, how many after the one retry, and how many are the sensible first action. A model that misses the bar cannot run this agent.

- File: [`measure_protocol.py`](./measure_protocol.py)
- Run: `python measure_protocol.py`
- You should see: `protocol reliability ok`

## It works when

- the parser and validator accept good replies and reject bad ones with a reason
- the model answers a chat turn
- the model picks the right first action for three questions
- the protocol is reliable on twelve questions
