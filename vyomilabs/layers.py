"""Course content: the 14 layers of the reference architecture, one file per cloud (wasm/labs/data/<cloud>.json). Checkers exist for AWS only so far."""
import json
import os
from . import CONTENT_DIR

_CACHE = {}


def course(cloud="aws"):
    if cloud not in _CACHE:
        with open(os.path.join(CONTENT_DIR, cloud + ".json"), encoding="utf-8") as f:
            _CACHE[cloud] = json.load(f)
    return _CACHE[cloud]


def layers():
    return course()["layers"]


def get(layer_id):
    for layer in layers():
        if layer["id"] == int(layer_id):
            return layer
    return None


def order():
    """Layer ids in the recommended build order."""
    return [layer["id"] for layer in sorted(layers(), key=lambda x: x["order"])]


def next_layer(progress):
    """The first layer, in build order, that is not yet verified."""
    for lid in order():
        if progress.get(str(lid), {}).get("status") != "PASS":
            return lid
    return None
