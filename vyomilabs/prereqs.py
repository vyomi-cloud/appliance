"""Which chapters a chapter builds on. The list is generated into the course data (layer["requires"], see content/build_courses.py::_requires),
so the browser runner (wasm/labs/labs.js), the Mesh/appliance deployer and vyomilabs.labrun all deploy the same prerequisites first."""
import json
import os

from . import CONTENT_DIR

_CACHE = {}


def _course(cloud):
    if cloud not in _CACHE:
        with open(os.path.join(CONTENT_DIR, cloud + ".json"), encoding="utf-8") as f:
            _CACHE[cloud] = json.load(f)
    return _CACHE[cloud]


def requires(cloud, layer):
    """Chapter ids that must be deployed before `layer`, in build order."""
    for l in _course(cloud)["layers"]:
        if l["id"] == layer:
            return list(l.get("requires", []))
    return []


def titles(cloud):
    return {l["id"]: l["title"] for l in _course(cloud)["layers"]}
