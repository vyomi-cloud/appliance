# Layer 1: Models

_A model client any layer can import: chat, tool calling and embeddings_

**What you build:** Call a model this simulator hosts from code the way every other layer will: a chat turn, a tool-calling turn and an embedding.

## Code, in order

### 1. Install the libraries

Chapter 10 uses the official Azure management library for the Azure OpenAI account and the official `openai` library (its `AzureOpenAI` client) for the model calls. Nothing is modified or wrapped.

- File: [`install10.sh`](./install10.sh)

### 2. Write the shared Azure settings

Every chapter imports this one file, so keep the name `azlab.py` and keep it next to your other files. It reads the simulator address from environment variables and builds the real Azure clients. The management clients (`azure-mgmt-*`) are pointed at the simulator with `base_url`, which is exactly how you point them at a sovereign cloud. The simulator accepts any bearer token on its control plane, so a small fixed-token credential is enough here (on real Azure you would pass `DefaultAzureCredential()`). Later chapters add to the helpers at the bottom, never change the top.

- File: [`azlab.py`](./azlab.py)

### 3. Create the Azure OpenAI account and the two deployments

Azure OpenAI is a resource: an account of kind `OpenAI`, and inside it one *deployment* per model. Your code never names the model, it names the deployment (`chat`, `embed`). Resource group first, then the account, then the deployments, all through the real `azure-mgmt-cognitiveservices` client.

- File: [`create_openai.py`](./create_openai.py)
- Run: `python create_openai.py` (or `./run_all.sh 1` from the project root)
- You should see: `deployments: ['chat', 'embed']`

### 4. Write the model client

Every other chapter imports these three functions, so keep the names. The model behind your deployments is one the simulator hosts (a small open model on Nano, the Mesh model pool on a Mesh), so replies are those of a small open model; the calls are identical to what you would send to a larger hosted model.

- File: [`models.py`](./models.py)

### 5. Try chat, a tool call and an embedding

A chat turn, a tool-calling turn (the model asks for `asset_status`, your code would run it) and an embedding (a list of numbers: its length depends on the embedding model your simulator hosts). The tool definition is the one the agents use later.

- File: [`try_models.py`](./try_models.py)
- Run: `python try_models.py` (or `./run_all.sh 1` from the project root)
- You should see: `embed: vector of`

### 6. Streaming, smaller embeddings and an unknown deployment

`stream=True` returns chunks as they are produced. `dimensions=256` shrinks an embedding (ask for a shorter vector). Calling a deployment that does not exist is a 404 `DeploymentNotFound`: the most common first mistake, so see it once.

- File: [`try_more.py`](./try_more.py)
- Run: `python try_more.py` (or `./run_all.sh 1` from the project root)
- You should see: `unknown deployment -> 404`

## It works when

- deployments listed
- embeddings return a vector
- chat answers
- tool call works
- unknown deployment is 404
