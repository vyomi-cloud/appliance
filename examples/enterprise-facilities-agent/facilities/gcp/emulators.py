"""Developer helper (run_e2e.py --start-emulators): start the REAL Google Pub/Sub and Firestore emulators in two Docker containers with exact,
run-unique names and point PUBSUB_EMULATOR_HOST / FIRESTORE_EMULATOR_HOST at them, then remove exactly those containers.
This is what VYOMI_GCP_REAL_BACKENDS=1 does inside the simulator once lane realbackend lands; the app only ever reads the standard variables.
Uses the local image only (never pulls)."""
import os, socket, subprocess, time, uuid

IMG = os.environ.get("VYOMI_EMULATOR_IMAGE", "gcr.io/google.com/cloudsdktool/google-cloud-cli:emulators")


def _free():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def _sh(*a):
    return subprocess.run(a, capture_output=True, text=True, timeout=120)


class Emulators:
    def __init__(self, project):
        tag = uuid.uuid4().hex[:6]
        self.names = [f"gcpapp-pubsub-{tag}", f"gcpapp-firestore-{tag}"]
        self.project, self.ports = project, (_free(), _free())

    def start(self):
        if _sh("docker", "image", "inspect", IMG).returncode != 0:
            raise SystemExit(f"emulator image {IMG} is not in the local Docker store (this helper never pulls)")
        _sh("docker", "run", "-d", "--rm", "--name", self.names[0], "-p", f"127.0.0.1:{self.ports[0]}:8085", IMG, "gcloud", "beta", "emulators", "pubsub", "start",
            "--host-port=0.0.0.0:8085", f"--project={self.project}")
        _sh("docker", "run", "-d", "--rm", "--name", self.names[1], "-p", f"127.0.0.1:{self.ports[1]}:8080", IMG, "gcloud", "emulators", "firestore", "start", "--host-port=0.0.0.0:8080")
        import requests
        for port in self.ports:
            for _ in range(120):
                try:
                    requests.get(f"http://127.0.0.1:{port}/", timeout=2)
                    break
                except Exception:
                    time.sleep(1)
            else:
                self.stop()
                raise SystemExit(f"emulator on :{port} did not come up")
        os.environ["PUBSUB_EMULATOR_HOST"] = f"127.0.0.1:{self.ports[0]}"
        os.environ["FIRESTORE_EMULATOR_HOST"] = f"127.0.0.1:{self.ports[1]}"
        os.environ["VYOMI_GCP_REAL_BACKENDS"] = "1"
        return self

    def stop(self):
        for n in self.names:            # exact names created by this run only
            _sh("docker", "rm", "-f", n)
