"""A function app blade must not offer a tab whose backing route 404s: azure_webapp_core refuses
deployment slots on a function app (ResourceTypeNotSupported), so the tab list must not show them either."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "core"))
import azure_subblades as sb

def keys(blades):
    return [i["key"] for g in blades for i in g.get("items", [])]

ok = True
fk = keys(sb.SUB_BLADES["functionapp"])
for name, cond in (("function app has no slots tab", "slots" not in fk),
                   ("function app keeps Deployment Center", "deployCenter" in fk)):
    print(("  ok  " if cond else "  FAIL  ") + name); ok &= cond
print("PASS" if ok else "FAIL"); sys.exit(0 if ok else 1)
