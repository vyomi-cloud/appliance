import json
import os
import random
import time

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


def _pick():
    """The models are the ones this simulator hosts: in-browser models on Nano, the Mesh model pool on a Mesh. Ask it, never hard-code a vendor id."""
    ms = [m for m in boto3.client("bedrock").list_foundation_models()["modelSummaries"] if m["modelId"].startswith("vyomi.")]
    chat = [m["modelId"] for m in ms if "EMBEDDING" not in m["outputModalities"]]
    emb = [m["modelId"] for m in ms if "EMBEDDING" in m["outputModalities"]]
    return chat[0], emb[0]


CHAT_MODEL, EMBED_MODEL = _pick()
# One attempt per boto3 call: this module owns the retry policy so the learner can see and test it.
_rt = boto3.client("bedrock-runtime", config=Config(retries={"total_max_attempts": 1}, read_timeout=60))

RETRYABLE = {"ThrottlingException", "ServiceUnavailableException", "ModelTimeoutException", "TooManyRequestsException", "InternalServerException"}
MAX_ATTEMPTS = 4


class ModelUnavailable(RuntimeError):
    """The model kept failing after every retry: surface it, never loop forever."""


class BudgetExceeded(RuntimeError):
    """The spend limit for this layer is used up: refuse the call before it is made."""


# Notional price per 1,000 tokens. The simulator's models are free; the numbers only make the meter and the limit tangible.
PRICE_PER_1K = {"input": 0.003, "output": 0.015, "embed": 0.0001}


class Budget:
    def __init__(self, limit_usd):
        self.limit, self.spent, self.calls, self.tokens = float(limit_usd), 0.0, 0, {"input": 0, "output": 0}

    def check(self):
        if self.spent >= self.limit:
            raise BudgetExceeded("budget of $%.4f used up after %d calls" % (self.limit, self.calls))

    def charge(self, kind, tokens_in=0, tokens_out=0):
        self.calls += 1
        self.tokens["input"] += tokens_in
        self.tokens["output"] += tokens_out
        self.spent += tokens_in / 1000 * PRICE_PER_1K["embed" if kind == "embed" else "input"] + tokens_out / 1000 * PRICE_PER_1K["output"]


BUDGET = Budget(os.environ.get("VY_BUDGET_USD", "1.00"))


def _call(fn):
    """Retry throttling and transient errors with exponential backoff and jitter; anything else (validation, access denied) fails at once."""
    BUDGET.check()
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return fn()
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code not in RETRYABLE:
                raise
            if attempt == MAX_ATTEMPTS:
                raise ModelUnavailable("%s after %d attempts" % (code, attempt)) from e
            time.sleep(0.05 * 2 ** attempt + random.random() * 0.05)


def _text(resp):
    return "".join(b.get("text", "") for b in resp["output"]["message"]["content"])


def chat(prompt):
    r = _call(lambda: _rt.converse(modelId=CHAT_MODEL, messages=[{"role": "user", "content": [{"text": prompt}]}], inferenceConfig={"maxTokens": 200}))
    BUDGET.charge("chat", r["usage"]["inputTokens"], r["usage"]["outputTokens"])
    return _text(r)


def chat_with_tools(prompt, tools):
    r = _call(lambda: _rt.converse(modelId=CHAT_MODEL, messages=[{"role": "user", "content": [{"text": prompt}]}], toolConfig={"tools": tools}))
    BUDGET.charge("chat", r["usage"]["inputTokens"], r["usage"]["outputTokens"])
    tool = next((b["toolUse"] for b in r["output"]["message"]["content"] if "toolUse" in b), None)
    return {"stop_reason": r["stopReason"], "tool_use": tool, "text": _text(r)}


def embed(text):
    r = _call(lambda: _rt.invoke_model(modelId=EMBED_MODEL, body=json.dumps({"inputText": text})))
    BUDGET.charge("embed", len(text.split()))
    return json.loads(r["body"].read())["embedding"]
