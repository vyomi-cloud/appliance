"""x-google-backend naming a Cloud Function's public URL reaches the simulated function, not the real internet."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from core import gateway_common as gc

fails = 0
def check(name, ok, extra=""):
    global fails
    fails += 0 if ok else 1
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' :: ' + str(extra)}")

os.environ["VYOMI_SELF_ENDPOINT"] = "http://127.0.0.1:9000"
check("function URL maps to /gcf", gc.local_function_url("https://us-central1-vyomi-project.cloudfunctions.net/hello") == "http://127.0.0.1:9000/gcf/vyomi-project/us-central1/hello", gc.local_function_url("https://us-central1-vyomi-project.cloudfunctions.net/hello"))
check("path and query kept", gc.local_function_url("https://europe-west1-p1.cloudfunctions.net/f/x?a=1") == "http://127.0.0.1:9000/gcf/p1/europe-west1/f/x?a=1")
check("other hosts untouched", gc.local_function_url("https://example.com/hello") is None and gc.local_function_url("http://us-central1-p.cloudfunctions.net/f") is None)
sys.exit(1 if fails else 0)
