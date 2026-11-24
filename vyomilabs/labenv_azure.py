"""Azure environment for vyomilabs.labrun: a clean local Azure simulator the way the Azure reference app starts it, plus the test LLM stub.
start() -> (endpoint, env) where env is what each lab command runs with (everything the NATIVE Azure SDKs need).

What it brings up (examples/enterprise-facilities-agent/facilities/azure/server.py):
  * the Vyomi appliance app in-process on TWO ports: https://localhost:<port> (local CA, for the SDKs that refuse bearer tokens over plain http) and
    http://127.0.0.1:<port> (call-backs from functions and the Container Apps host), and the Service Bus AMQP 1.0 listener;
  * the CA bundle exported through REQUESTS_CA_BUNDLE / SSL_CERT_FILE, exactly how a developer trusts a local dev CA;
  * optionally (VYOMI_LABS_AZURITE=1) a real Azurite container for the Table service, as `run_e2e.py --start-azurite` does.
Against an existing appliance pass --endpoint https://host:port and set VYOMI_AZURE_HTTP_ENDPOINT / VYOMI_AZURE_AMQP_PORT / REQUESTS_CA_BUNDLE yourself."""
import os
import sys

from . import ROOT, ensure_reference_on_path

SUBSCRIPTION = "00000000-0000-0000-0000-cloudlearn01"


def start(endpoint=None):
    ensure_reference_on_path()
    if not endpoint:
        sys.path.insert(0, os.path.join(ROOT, "tools", "llm_stub"))
        import stub_llm_server
        os.environ.setdefault("VYOMI_LLM_ENDPOINT", stub_llm_server.start())
        if os.environ.get("VYOMI_LABS_AZURITE") == "1":
            from facilities.azure.azurite import Azurite
            Azurite().start()
        from facilities.azure.server import start_in_process
        endpoint, http_endpoint, amqp_port, ca = start_in_process()
        os.environ.update(VYOMI_AZURE_HTTP_ENDPOINT=http_endpoint, VYOMI_AZURE_AMQP_PORT=str(amqp_port))
    env = dict(os.environ, VYOMI_AZURE_ENDPOINT=endpoint, AZURE_SUBSCRIPTION_ID=SUBSCRIPTION)
    env.setdefault("VYOMI_AZURE_HTTP_ENDPOINT", endpoint)
    env.setdefault("VYOMI_AZURE_AMQP_PORT", "5672")
    return endpoint, env
