"""Google Cloud environment for vyomilabs.labrun: a clean in-process simulator, the real Pub/Sub and Firestore emulators (local Docker image, never pulled)
and the deterministic test LLM stub. start() -> (endpoint, env) where env is what each lab command runs with.

The lab scripts read exactly these variables (nothing else): VYOMI_ENDPOINT (the simulator front door; on real Google Cloud there is no such variable),
GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_REGION and the two standard emulator variables PUBSUB_EMULATOR_HOST / FIRESTORE_EMULATOR_HOST."""
import atexit
import os
import sys

from . import ROOT, ensure_reference_on_path

PROJECT = "vyomi-project"


def start(endpoint=None):
    ensure_reference_on_path()
    os.environ.setdefault("CLOUDLEARN_TIER_ENFORCE", "0")
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", PROJECT)
    os.environ.setdefault("GOOGLE_CLOUD_REGION", "us-central1")
    if not endpoint:
        sys.path.insert(0, os.path.join(ROOT, "tools", "llm_stub"))
        import stub_llm_server
        os.environ.setdefault("VYOMI_LLM_ENDPOINT", stub_llm_server.start())
        if not (os.environ.get("PUBSUB_EMULATOR_HOST") and os.environ.get("FIRESTORE_EMULATOR_HOST")):
            from facilities.gcp.emulators import Emulators
            emu = Emulators(os.environ["GOOGLE_CLOUD_PROJECT"]).start()      # own containers with run-unique names; removed at exit, exactly those two
            atexit.register(emu.stop)
        from facilities.server import start_in_process
        endpoint = start_in_process()
    host = endpoint.split("//", 1)[-1].rstrip("/")
    os.environ.setdefault("PUBSUB_EMULATOR_HOST", host)
    os.environ.setdefault("FIRESTORE_EMULATOR_HOST", host)
    os.environ.setdefault("VYOMI_SELF_ENDPOINT", endpoint)
    return endpoint, dict(os.environ, VYOMI_ENDPOINT=endpoint)
