import re
import unicodedata

import boto3

from guardrail import ensure_guardrail

_LOOKALIKE = str.maketrans("013457@$", "oieastas")
PATTERNS = [
    r"(ignore|disregard|forget|override)\W+(all\W+|any\W+|the\W+|your\W+)*(previous|prior|above|earlier|preceding|system)\W+(instructions?|rules?|prompts?|context|messages?)",
    r"(reveal|print|show|output|repeat)\W+(your\W+|the\W+)*(system|hidden|secret|initial)\W+(prompt|rules?|instructions?)",
    r"(you\W+are\W+now|act\W+as|pretend\W+to\W+be)\W+(an?\W+)?(unrestricted|jailbroken|developer\W+mode|dan)\b",
    r"(do\W+not|don\W*t|never)\W+(tell|inform|warn|mention)\W+(this\W+to\W+)?the\W+(user|operator|engineer)",
    r"\bsystem\W+(note|override|message)\b",
]


def normalise(text):
    text = unicodedata.normalize("NFKC", text)
    text = "".join(c for c in text if unicodedata.category(c) not in ("Cf", "Cc") or c in "\n\t")      # zero-width and control characters
    return re.sub(r"\s+", " ", text.lower().translate(_LOOKALIKE))


def pattern_hits(text):
    t = normalise(text)
    return [p for p in PATTERNS if re.search(p, t)]


def guardrail_hit(text):
    r = boto3.client("bedrock-runtime").apply_guardrail(guardrailIdentifier=ensure_guardrail(), guardrailVersion="DRAFT", source="INPUT",
                                                        content=[{"text": {"text": text}}])
    return r["action"] == "GUARDRAIL_INTERVENED"


def screen(text):
    """Which layers blocked the text: [] means it is clean."""
    by = []
    if guardrail_hit(text):
        by.append("guardrail")
    if pattern_hits(text):
        by.append("patterns")
    return by
