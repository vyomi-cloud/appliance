"""When the simulator's https listener (core/azure_tls_front.py) starts: a Mesh serves :9443 by default, offline / Nano do not."""
import pytest

from core import azure_tls_front as tls

KEYS = ("VYOMI_ROLE", "VYOMI_AZURE_TLS", "VYOMI_AZURE_TLS_PORT", "VYOMI_AZURE_REAL_BACKENDS")


@pytest.mark.parametrize("env,want", [
    ({}, False),                                                    # offline appliance: unchanged, off
    ({"VYOMI_ROLE": "mesh"}, True),                                 # a Mesh serves https :9443 by default
    ({"VYOMI_ROLE": "MESH"}, True),
    ({"VYOMI_ROLE": "mesh", "VYOMI_AZURE_TLS": "0"}, False),        # explicit opt-out
    ({"VYOMI_ROLE": "mesh", "VYOMI_AZURE_TLS": "off", "VYOMI_AZURE_TLS_PORT": "9555"}, True),   # an explicit port still wins
    ({"VYOMI_ROLE": "appliance"}, False),
    ({"VYOMI_AZURE_TLS": "1"}, True),
    ({"VYOMI_AZURE_TLS_PORT": "0"}, True),
    ({"VYOMI_AZURE_REAL_BACKENDS": "1"}, True),
])
def test_wanted(monkeypatch, env, want):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert tls.wanted() is want
