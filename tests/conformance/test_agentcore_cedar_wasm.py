"""Cedar policy enforcement on Nano: the OSS Cedar core compiled to WebAssembly (wasm/cedar, @cedar-policy/cedar-wasm 4.14.0) behind the
cedarpy-shaped facade core/cedar_wasm_shim.py. The page-side evaluator (the exact module nano-boot.js installs) runs in Node; Python reaches
it through a fake Pyodide `js` module, so this exercises the Nano code path end to end (everything except Pyodide itself).
  1. decision PARITY between the real cedarpy (Mesh/host) and the wasm evaluator on a battery of policies;
  2. an ENFORCE AgentCore gateway no longer denies everything: the whole Facilities AgentCore suite (Cedar group policy, tag-based
     permit, tool filtering) passes with the wasm engine standing in for cedarpy;
  3. with NO evaluator loaded the gateway still fails closed.
Run: PYTHONPATH=. python tests/conformance/test_agentcore_cedar_wasm.py   (needs node)
"""
import json
import os
import subprocess
import sys
import threading
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {str(extra)[:700]}")


def main():
    import cedarpy as real
    from core import agentcore_ext_core as ext
    from core import cedar_wasm_shim as shim
    node = subprocess.Popen(["node", os.path.join(os.path.dirname(os.path.abspath(__file__)), "cedar_wasm_bridge.mjs")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    assert node.stdout.readline().strip() == "ready"
    lock = threading.Lock()

    def evaluate(call_json):
        with lock:
            node.stdin.write(call_json + "\n")
            node.stdin.flush()
            return node.stdout.readline().strip()
    fake_js = types.ModuleType("js")
    fake_js.globalThis = types.SimpleNamespace(__vyomi_cedar_eval=evaluate)
    sys.modules["js"] = fake_js
    wasm = shim._WasmCedar()
    ents = [{"uid": {"type": "AgentCore::OAuthUser", "id": "mona"}, "attrs": {}, "parents": [], "tags": {"cognito:groups": "managers,staff", "dept": "ops"}}]
    P, G = 'AgentCore::OAuthUser::"mona"', 'AgentCore::Gateway::"gw"'
    cases = [
        ("simple permit on the action", 'permit(principal, action == AgentCore::Action::"a", resource);', "a", {}, "Allow"),
        ("no matching policy -> default deny", 'permit(principal, action == AgentCore::Action::"a", resource);', "b", {}, "Deny"),
        ("forbid overrides permit", 'permit(principal, action, resource);\nforbid(principal, action == AgentCore::Action::"b", resource);', "b", {}, "Deny"),
        ("principal tag + like", 'permit(principal, action, resource) when { principal.hasTag("cognito:groups") && principal.getTag("cognito:groups") like "*managers*" };', "a", {}, "Allow"),
        ("tag mismatch", 'permit(principal, action, resource) when { principal.getTag("dept") == "finance" };', "a", {}, "Deny"),
        ("context.input value", 'permit(principal, action, resource) when { context.input.amount < 100 };', "a", {"input": {"amount": 50}}, "Allow"),
        ("context.input value too large", 'permit(principal, action, resource) when { context.input.amount < 100 };', "a", {"input": {"amount": 500}}, "Deny"),
        ("unless clause", 'permit(principal, action, resource) unless { context.input.dry_run == true };', "a", {"input": {"dry_run": True}}, "Deny"),
        ("resource constraint", f'permit(principal, action, resource == {G});', "a", {}, "Allow"),
        ("evaluation error (missing attr) -> policy skipped -> Deny", 'permit(principal, action, resource) when { context.input.nope == 1 };', "a", {"input": {}}, "Deny"),
    ]
    print("== decision parity: cedarpy (Rust) vs cedar-wasm")
    for name, pol, act, ctx, want in cases:
        req = {"principal": P, "action": f'AgentCore::Action::"{act}"', "resource": G, "context": ctx}
        a = "Allow" if str(real.is_authorized(req, pol, ents).decision) == "Decision.Allow" else "Deny"
        b = "Allow" if str(wasm.is_authorized(req, pol, ents).decision) == "Decision.Allow" else "Deny"
        check(f"{name}: cedarpy={a} wasm={b} expected={want}", a == b == want, (a, b))
    try:
        wasm.is_authorized({"principal": P, "action": 'AgentCore::Action::"a"', "resource": G, "context": {}}, "permit(principal action resource nonsense", ents)
        check("a malformed policy raises in the wasm engine", False)
    except ValueError as e:
        check("a malformed policy raises in the wasm engine (-> ValidationException at CreatePolicy)", "parse" in str(e).lower() or "expected" in str(e).lower(), e)
    check("the facade reports which engine decided", wasm.engine == "cedar-wasm")

    print("== ENFORCE gateway with the wasm engine (Facilities AgentCore suite)")
    import test_agentcore_facilities as fac
    ext.cedarpy = wasm
    try:
        fac.main()
    except SystemExit:
        pass
    check(f"Facilities AgentCore suite on the wasm engine: {fac.PASS} passed", fac.FAIL == 0 and fac.PASS >= 20, (fac.PASS, fac.FAIL))

    print("== fail closed when the evaluator is not loaded")
    del fake_js.globalThis.__vyomi_cedar_eval
    st = {"policy_engines": {"e": {"policyEngineArn": "arn:e", "policies": {"p": {"definition": {"cedar": {"statement": "permit(principal, action, resource);"}}}}}}, "policy_audit": []}
    gw = {"gatewayId": "g", "gatewayArn": "arn:g", "policyEngineConfiguration": {"arn": "arn:e", "mode": "ENFORCE"}}
    ok, why = ext.authorize(st, gw, {"sub": "x"}, "t", {})
    check("ENFORCE + evaluator missing -> denied, with the reason", ok is False and "not loaded" in why, (ok, why))
    gw["policyEngineConfiguration"]["mode"] = "LOG_ONLY"
    ok, why = ext.authorize(st, gw, {"sub": "x"}, "t", {})
    check("LOG_ONLY + evaluator missing -> allowed and audited", ok is True, (ok, why))
    node.kill()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
