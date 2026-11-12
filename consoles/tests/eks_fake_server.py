#!/usr/bin/env python3
"""TEST HARNESS ONLY: consoles/dev_server.py with the k3s runtime backed by tests/conformance/test_aws_eks_core.FakeDocker, so the EKS console
can be exercised (Playwright) with no Docker. Clusters turn ACTIVE ~4 s after CreateCluster; kubectl answers are canned. The REAL-k3s run is
tests/conformance/test_aws_eks_live.py (and `VYOMI_K8S_BACKEND=k3s python3 consoles/dev_server.py`).
    python3 consoles/tests/eks_fake_server.py [--port 8741]"""
import importlib.util
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "consoles"))
spec = importlib.util.spec_from_file_location("eks_core_test", ROOT / "tests" / "conformance" / "test_aws_eks_core.py")
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)
from core import k3s_runtime as k3s          # noqa: E402
from core import kube_state_core as kube     # noqa: E402

fd = t.FakeDocker()
fd.ready = False
rt = k3s.K3sRuntime(docker=fd, sleep=lambda s: time.sleep(0.3))
kube.CLUSTER_RUNTIME = rt
kube.BACKEND_FACTORY = rt.backend_factory()
_orig = rt.create_cluster


def _create(*a, **k):
    threading.Timer(4.0, lambda: setattr(fd, "ready", True)).start()     # the "control plane" becomes ready 4 s later
    return _orig(*a, **k)


rt.create_cluster = _create
import dev_server  # noqa: E402

if __name__ == "__main__":
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8741
    print("EKS console on fake docker: http://127.0.0.1:%d/v4/aws/#/eks" % port, flush=True)
    dev_server.ThreadingHTTPServer(("127.0.0.1", port), dev_server.Handler).serve_forever()
