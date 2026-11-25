# Layer 1: Models

_A model client any layer can import: chat, tool calling and embeddings_

**What you build:** Call a model this simulator hosts from code the way every other layer will: a chat turn, a tool-calling turn and an embedding.

## Code, in order

### 1. Write the model client

Every other layer imports these three functions, so keep the names. boto3 reads the simulator address from AWS_ENDPOINT_URL, exactly as it would on real AWS.

- File: [`vymodels.py`](./vymodels.py)

### 2. Try all three calls

A chat call, a tool-calling call and an embedding. The tool definition is the one the agents use later.

- File: [`try_models.py`](./try_models.py)
- Run: `python try_models.py` (or `./run_all.sh 1` from the project root)
- You should see: `embed: vector of`

### 3. Meter, retry and limit the model client

The model client you wrote already retries throttling with backoff and meters notional cost against a budget. This block proves both behaviours instead of describing them: it makes the service throttle on purpose, shows the retry recovering, shows the retry giving up with a clear error (never an endless loop), and shows the budget refusing a call before it is made.

- File: [`chaos.py`](./chaos.py)

### 4. Failure lab: throttling and a spent budget

Break it on purpose. Two throttles in a row: the third attempt must succeed. A model that throttles forever: the client must stop and say so. A spent budget: the call must be refused before it reaches the model. Every outcome is asserted, not printed and hoped for.

- File: [`fail_models.py`](./fail_models.py)
- Run: `python fail_models.py` (or `./run_all.sh 1` from the project root)
- You should see: `failure lab passed`

### 5. Give the model client its own identity

Helper used by every later least-privilege step: it creates an IAM user with ONE inline policy, switches the simulator to Enforce, and reads the audit log. The root test credentials stay allowed, so only the principals you create are judged.

- File: [`iamkit.py`](./iamkit.py)

### 6. Least privilege for the model caller, from the audit log

Start with a policy that is too thin on purpose: the caller may invoke the two models and nothing else. Call the model as that identity, get refused, and read the audit log to find exactly which action and resource were missing. `settle()` grants only what the log names and re-runs, so the final policy is the narrowest that works. Note: the simulator's Converse check also asks for `bedrock:ApplyGuardrail` (the IAM catalog lists it as a related action); on real AWS it is only needed when a guardrail is attached, so check your account's behaviour before copying this policy.

- File: [`iam_models.py`](./iam_models.py)
- Run: `python iam_models.py` (or `./run_all.sh 1` from the project root)
- You should see: `least-privilege model caller verified`

## It works when

- ListFoundationModels returns models
- Converse returns text and usage
- Converse with toolConfig returns tool_use or end_turn
- InvokeModel returns an embedding
