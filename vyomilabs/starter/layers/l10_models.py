"""Layer 10: Foundation Models via Bedrock. YOU write this file.

Every other layer will import these three functions, so their shape is the contract. Use the AWS SDK for Python (boto3) exactly as you
would against real AWS: the simulator is reached through the standard AWS_ENDPOINT_URL setting, so no simulator-specific code is needed.

Docs to read first: Bedrock Runtime "Converse" and "InvokeModel".
Check your work with:  python -m vyomilabs check 10
"""
import boto3

CHAT_MODEL = "anthropic.claude-3-haiku-20240307-v1:0"
EMBED_MODEL = "amazon.titan-embed-text-v2:0"


def chat(prompt: str) -> str:
    """Send one user message to the chat model and return the reply text."""
    raise NotImplementedError("write chat(): call bedrock-runtime Converse and return the text of the reply")


def chat_with_tools(prompt: str, tools: list) -> dict:
    """Send a message with tool definitions (Converse toolConfig).

    Return {"stop_reason": <Converse stopReason>, "tool_use": <the toolUse block, or None>, "text": <reply text, or "">}."""
    raise NotImplementedError("write chat_with_tools(): pass toolConfig={'tools': tools} to Converse")


def embed(text: str) -> list:
    """Return the embedding vector (list of floats) for the text, using InvokeModel."""
    raise NotImplementedError("write embed(): call InvokeModel with the Titan embedding model")
