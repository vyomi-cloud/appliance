import os
import time
from urllib.parse import urlparse

ENDPOINT = os.environ["VYOMI_AZURE_ENDPOINT"]                          # https://localhost:<port>  (the simulator, TLS with a local CA)
HTTP_ENDPOINT = os.environ.get("VYOMI_AZURE_HTTP_ENDPOINT", ENDPOINT)   # the same simulator on plain http, used by functions and containers
AMQP_PORT = int(os.environ.get("VYOMI_AZURE_AMQP_PORT", "5672"))        # Service Bus AMQP 1.0 listener
SUB = os.environ.get("AZURE_SUBSCRIPTION_ID", "00000000-0000-0000-0000-cloudlearn01")
RG = "rg-facilities"
LOC = "eastus"
TENANT = "facilities-tenant"
HOST = urlparse(ENDPOINT).hostname or "localhost"
STORAGE = "devstoreaccount1"
ACCOUNT_KEY = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="   # the public Azurite development key
CHAT, EMBED = "chat", "embed"                                            # your deployment names
OPENAI_ACCOUNT = "facilities-openai"

_cache = {}


class DevToken:
    """A TokenCredential that always returns the same development token (the simulator does not check it)."""
    def get_token(self, *scopes, **kwargs):
        from azure.core.credentials import AccessToken
        return AccessToken(os.environ.get("VYOMI_ACCESS_TOKEN", "vyomi-local"), int(time.time()) + 3600)


def arm(cls, **kw):
    """Any azure-mgmt-* client, pointed at the simulator."""
    if cls not in _cache:
        _cache[cls] = cls(DevToken(), SUB, base_url=ENDPOINT, polling_interval=0, **kw)
    return _cache[cls]


def rid(provider, kind, name):
    return f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/{provider}/{kind}/{name}"


def ensure_rg():
    from azure.mgmt.resource.resources import ResourceManagementClient
    arm(ResourceManagementClient).resource_groups.create_or_update(RG, {"location": LOC})


def pick_models():
    """The models are the ones this simulator hosts: in-browser models on Nano, the Mesh model pool on a Mesh. Returns (chat, embedding) as
    the {format, name, version} a deployment needs. Never hard-code a vendor model."""
    from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient
    ms = [{"format": m.model.format, "name": m.model.name, "version": m.model.version} for m in arm(CognitiveServicesManagementClient).models.list(LOC) if m.kind == "OpenAI"]
    emb = [m for m in ms if "embed" in m["name"] or "minilm" in m["name"]]
    return [m for m in ms if m not in emb][0], emb[0]


def aoai(api_version="2024-10-21"):
    from openai import AzureOpenAI
    key = ("aoai", api_version)
    if key not in _cache:
        _cache[key] = AzureOpenAI(azure_endpoint=ENDPOINT, api_key="vyomi-local", api_version=api_version, max_retries=0, timeout=120)
    return _cache[key]
