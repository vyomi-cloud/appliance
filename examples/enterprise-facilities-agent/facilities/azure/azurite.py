"""Developer helper (run_e2e.py --cloud azure --start-azurite): start the REAL Azurite (Microsoft's open-source Azure Storage emulator, Table service) in its own
Docker container with an exact run-unique name and point the simulator at it (VYOMI_AZURE_REAL_BACKENDS=1, VYOMI_AZURE_AZURITE_ENDPOINT), then remove exactly that
container. This is the opt-in the data lane (az-ref-data) defines for the simulator; the app only reads the two variables. Local image only, never pulls."""
import os, socket, subprocess, time, uuid

IMG = os.environ.get("VYOMI_AZURITE_IMAGE", "mcr.microsoft.com/azure-storage/azurite:latest")


def _free():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def _sh(*a):
    return subprocess.run(a, capture_output=True, text=True, timeout=120)


class Azurite:
    def __init__(self):
        self.name = f"azapp-azurite-{uuid.uuid4().hex[:6]}"
        self.port = _free()

    def start(self):
        if _sh("docker", "image", "inspect", IMG).returncode != 0:
            raise SystemExit(f"image {IMG} is not in the local Docker store (this helper never pulls)")
        _sh("docker", "run", "-d", "--rm", "--name", self.name, "-p", f"127.0.0.1:{self.port}:10002", IMG, "azurite-table", "--tableHost", "0.0.0.0", "--tablePort", "10002", "--skipApiVersionCheck")
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=1).close()
                break
            except OSError:
                time.sleep(0.5)
        else:
            self.stop()
            raise SystemExit("azurite did not come up")
        os.environ["VYOMI_AZURE_REAL_BACKENDS"] = "1"
        os.environ["VYOMI_AZURE_AZURITE_ENDPOINT"] = f"http://127.0.0.1:{self.port}"
        return self

    def stop(self):
        _sh("docker", "rm", "-f", self.name)           # exact name created by this run only
