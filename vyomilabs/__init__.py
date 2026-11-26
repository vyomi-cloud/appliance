"""Vyomi Labs: learn cloud and agentic-AI architecture by building the Enterprise Facilities agent, layer by layer, on the Vyomi simulator.

v1 (AI track): an interactive map of the 14-layer reference architecture, a guide per layer, and a checker that inspects what the learner
built through the real cloud SDK. Layers not yet built by the learner can be supplied by the reference implementation in
examples/enterprise-facilities-agent (same layer numbers)."""
import os
import sys

__version__ = "0.1.0"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REFERENCE_APP = os.path.join(ROOT, "examples", "enterprise-facilities-agent")
WEB_DIR = os.path.join(ROOT, "wasm", "labs")           # the Labs pages (also served by Nano as /nano/labs/)
CONTENT_DIR = os.path.join(WEB_DIR, "data")             # one course file per cloud: aws.json, gcp.json, azure.json


def ensure_reference_on_path():
    """The checker reuses the reference app's step recorder (PASS / BLOCKED / FAIL); make it importable."""
    if REFERENCE_APP not in sys.path:
        sys.path.insert(0, REFERENCE_APP)
