# Layer 1: Models

_A model client any layer can import: chat, tool calling and embeddings_

**What you build:** Call a model this simulator hosts from code the way every other layer will: a chat turn, a tool-calling turn and an embedding.

## Code, in order

### 1. Write the model client

Every other layer imports these three functions, so keep the names. boto3 reads the simulator address from AWS_ENDPOINT_URL, exactly as it would on real AWS.

- File: [`models.py`](./models.py)

### 2. Try all three calls

A chat call, a tool-calling call and an embedding. The tool definition is the one the agents use later.

- File: [`try_models.py`](./try_models.py)
- Run: `python try_models.py` (or `./run_all.sh 1` from the project root)
- You should see: `embed: vector of`

## It works when

- ListFoundationModels returns models
- Converse returns text and usage
- Converse with toolConfig returns tool_use or end_turn
- InvokeModel returns an embedding
