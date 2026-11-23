"""The learner's workspace: the folder where they write their layers (layers/lNN_*.py). `vyomilabs init` copies the starter files in.

Code layers (for example layer 10, the model client) are checked by importing the learner's module and calling it. Resource layers
(for example layer 2, the guardrail) are checked by inspecting what the learner created in the simulator, by the contract names."""
import importlib.util
import os
import shutil

from . import ROOT  # noqa: F401  (kept for symmetry with other modules)

PKG = os.path.dirname(os.path.abspath(__file__))
STARTER = os.path.join(PKG, "starter")
SOLUTIONS = os.path.join(PKG, "solutions")


def default_dir():
    return os.path.abspath(os.environ.get("VYOMILABS_WORKSPACE") or "vyomilabs-workspace")


def init(dest=None):
    dest = os.path.abspath(dest or default_dir())
    shutil.copytree(STARTER, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    return dest


def load_layer(filename, workspace=None):
    """Import layers/<filename> from the workspace. Raises FileNotFoundError with a helpful message when it is missing."""
    path = os.path.join(workspace or default_dir(), "layers", filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f"{filename} not found in {os.path.dirname(path)}: run `python -m vyomilabs init` and edit the file")
    spec = importlib.util.spec_from_file_location("vy_learner_" + filename[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
