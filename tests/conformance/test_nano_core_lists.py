"""Every `from core import X_core` inside a function (a lazy import the static import-closure check cannot see) must be in the Nano core lists
(wasm/nano-boot.js and wasm/relay/relay-shared-worker.js). A missing one made `gcloud storage` fail in Nano with
`UnboundLocalError: cannot access local variable '_orgp'` (v4.1.1) and silently disabled Budgets / Resource Groups / management groups."""
import glob
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LAZY = re.compile(r"^[ \t]+from core import (\w+_core)\b", re.M)
# modules the Nano relay does not ship on purpose (server-only), with the reason
SERVER_ONLY = {}


def _lazy_modules():
    out = {}
    for p in glob.glob(os.path.join(ROOT, "core", "*.py")):
        for m in LAZY.finditer(open(p, encoding="utf-8").read()):
            out.setdefault(m.group(1), os.path.basename(p))
    return out


def test_lazily_imported_cores_are_shipped_to_nano():
    for lst in ("wasm/nano-boot.js", "wasm/relay/relay-shared-worker.js"):
        text = open(os.path.join(ROOT, lst), encoding="utf-8").read()
        missing = sorted(m for m in _lazy_modules() if m not in SERVER_ONLY and ('"%s.py"' % m) not in text
                         and os.path.exists(os.path.join(ROOT, "wasm", "core", m + ".py")))
        assert not missing, "%s lacks %s (imported lazily by %s)" % (lst, missing, [_lazy_modules()[m] for m in missing])


def test_orgpolicy_gate_survives_a_missing_module():
    src = open(os.path.join(ROOT, "core", "aws_wire_router.py"), encoding="utf-8").read()
    assert "_orgp = None" in src      # the except clause names _orgp: the import must never be the thing that fails
