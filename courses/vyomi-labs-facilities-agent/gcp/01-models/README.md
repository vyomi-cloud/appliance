# Layer 1: Models

_A model client any layer can import: chat, tool calling and embeddings_

**What you build:** Call a model this simulator hosts from code the way every other layer will: a chat turn, a tool-calling turn and an embedding.

## Code, in order

### 1. Install the libraries

Chapter 10 needs the Google Gen AI SDK (which talks to the Vertex AI generateContent API) and google-auth. Run this once in a fresh virtual environment (Python 3.11 or newer).

- File: [`install_10.sh`](./install_10.sh)

### 2. Write the client factory

Every chapter imports this one file, so keep the name gcp.py. It reads where the simulator is from VYOMI_ENDPOINT (your lab environment sets it, together with GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_REGION, the Pub/Sub and Firestore emulator hosts and the simulator's gRPC address). On real Google Cloud you would delete the endpoint overrides and the libraries would use your Application Default Credentials.

- File: [`gcp.py`](./gcp.py)

### 3. Write the model client

Every other layer imports these three functions, so keep the names. The model ids are not hard-coded: vymodels.py asks the simulator's Model Garden which models it hosts. chat() is a plain generateContent call, chat_with_tools() declares a function so the model can ask your code to run it, and embed() turns text into a vector with text-embedding-005.

- File: [`vymodels.py`](./vymodels.py)

### 4. Try all three calls

A chat call, a tool-calling call and an embedding. The model behind generateContent is one the simulator hosts (a small open model in your browser on Nano, the Mesh model pool on a Mesh), so answers are those of a small open model; the SDK calls, the request shapes and the tool-calling flow are exactly what you would write against real Vertex AI.

- File: [`try_models.py`](./try_models.py)
- Run: `python try_models.py` (or `./run_all.sh 1` from the project root)
- You should see: `embed: vectors of`

## It works when

- catalogue lists models
- generateContent answers
- function calling returns a call or text
- embedContent returns a vector
