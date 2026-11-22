"""TEST ONLY (tools/mcp-eval/prerelease-it.sh, local-mesh stage): make this container also trust the PUBLIC test-vector key.

Since v1 (HMAC) session tokens are retired (V1_ACCEPTED = False, finding F2), nothing can self-mint a token the Mesh image
trusts; the IT therefore mints a v2 token with the published test seed (tests/mesh_testkey.py) and mounts this directory with
PYTHONPATH=/opt/vyomi-it so Python loads it at start. It adds one entry to core.mesh_session.TRUSTED_KEYS right after that
module is imported. Nothing here ships in the image (.dockerignore excludes tests/; tools/ is never copied).

This is no new hole: whoever can mount files and set PYTHONPATH on the container can already replace the code itself. Closing
that is lockdown + the compiled image (MCP-GUARDRAILS F4, MESH-SOFTWARE-PROTECTION layers 4 and 6), not this file.
"""
import importlib.abc
import importlib.machinery
import sys

_TARGET, _KID, _PUB = "core.mesh_session", "test-vector", "A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg"


class _Trust(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name != _TARGET:
            return None
        spec = importlib.machinery.PathFinder.find_spec(name, path)
        if spec is None or spec.loader is None:
            return spec
        run = spec.loader.exec_module

        def exec_module(module):
            run(module)
            module.TRUSTED_KEYS = {**module.TRUSTED_KEYS, _KID: _PUB}
            print("[vyomi-it] TEST: core.mesh_session also trusts the public test-vector key", file=sys.stderr)
        spec.loader.exec_module = exec_module
        return spec


sys.meta_path.insert(0, _Trust())
