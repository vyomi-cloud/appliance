"""Lambda CI/CD pipeline application: Source -> Build -> Deploy over the CI seam + the real Lambda core. Hermetic.
Run: PYTHONPATH=. python tests/conformance/test_lambda_cicd.py"""
import base64, io, json, tarfile
from core import ci_core as ci, lambda_core as lam


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def _tgz(files, top="o-r-abc"):
    b = io.BytesIO()
    with tarfile.open(fileobj=b, mode="w:gz") as tf:
        for p, c in files.items():
            c = c.encode() if isinstance(c, str) else c
            ti = tarfile.TarInfo(f"{top}/{p}"); ti.size = len(c); tf.addfile(ti, io.BytesIO(c))
    return b.getvalue()


class Store:
    def persist(self):
        pass


def main():
    ci.set_git(None); ci.set_builder(None); ci.set_fetcher(None); ci.set_http(None)
    st = Store()

    def call(m, path, doc=None, ok=None):
        r = lam.dispatch(st, m, path, {}, {}, json.dumps(doc).encode() if doc is not None else b"")
        j = json.loads(r.body or b"{}")
        if ok:
            assert r.status == ok, (m, path, r.status, j)
        return r.status, j

    for bad in ({"Repository": "gitlab.com/x/y"}, {"Repository": "vyomi/r", "Runtime": "nodejs20.x"}, {"Repository": "vyomi/r", "Handler": "nodot"},
                {"Repository": "vyomi/r", "FunctionName": "bad name"}):
        s, _ = call("POST", "/2015-03-31/applications", {"Name": "x", "Pipeline": bad})
        _check(f"invalid pipeline rejected: {list(bad.values())[-1]}", s == 400)
    s, a = call("POST", "/2015-03-31/applications", {"Name": "shop", "Pipeline": {"Repository": "vyomi/shop", "FunctionName": "shop-fn"}}, 201)
    ex = a["Pipeline"]["Executions"]
    _check("creating the app seeds the repo and runs the pipeline once", len(ex) == 1 and ex[0]["Status"] == "Succeeded" and [s["Status"] for s in ex[0]["Stages"]] == ["Succeeded"] * 3)
    s, fn = call("GET", "/2015-03-31/functions/shop-fn", None, 200)
    _check("the function really exists with an alias 'live' on version 1", fn["Configuration"]["Handler"] == "app.handler" and call("GET", "/2015-03-31/functions/shop-fn/aliases/live", None, 200)[1]["FunctionVersion"] == "1")
    def invoke(q=""):
        r = lam.dispatch(st, "POST", f"/2015-03-31/functions/shop-fn/invocations", {}, {}, b"{}")
        return json.loads(r.body)
    _check("invoking the deployed function runs the pipeline's code (v1)", "version 1" in json.dumps(invoke()))
    s, a = call("POST", "/2015-03-31/applications/shop/pipeline/push", {"Files": {"app.py": 'def handler(e, c):\n    return {"body": "shipped v2"}\n'}, "Message": "v2"}, 200)
    s, a = call("GET", "/2015-03-31/applications/shop", None, 200)
    _check("a push ran a new execution that deployed version 2", a["Pipeline"]["Executions"][0]["FunctionVersion"] == "2" and a["Pipeline"]["LastExecution"]["Status"] == "Succeeded")
    _check("the function now runs the pushed code; alias moved", "shipped v2" in json.dumps(invoke()) and call("GET", "/2015-03-31/functions/shop-fn/aliases/live", None, 200)[1]["FunctionVersion"] == "2")
    call("POST", "/2015-03-31/applications/shop/pipeline/push", {"Files": {"app.py": "def handler(e, c:\n    return 1\n"}, "Message": "broken"}, 200)
    ex = call("GET", "/2015-03-31/applications/shop/pipeline/executions", None, 200)[1]["Executions"][0]
    _check("syntax error stops at Build with file:line, Deploy never ran", ex["Status"] == "Failed" and ex["FailedStage"] == "Build" and "app.py:1" in ex["Error"] and ex["Stages"][2]["Status"] == "NotStarted")
    _check("the deployed function is untouched by the failed build", "shipped v2" in json.dumps(invoke()))
    call("POST", "/2015-03-31/applications/shop/pipeline/push", {"Files": {"app.py": None}, "Message": "rm"}, 200)
    ex = call("GET", "/2015-03-31/applications/shop/pipeline/executions", None, 200)[1]["Executions"][0]
    _check("missing handler module fails Build", ex["Status"] == "Failed" and "Handler module 'app.py'" in ex["Error"])
    # GitHub repo through the fetcher (PAT) + manual execution
    ci.set_fetcher(lambda u, h: (200, _tgz({"app.py": 'def handler(e, c):\n    return "gh"\n'})) if h.get("Authorization") == "Bearer ghp_lambdapat12" else (404, b""))
    s, a = call("POST", "/2015-03-31/applications", {"Name": "gh", "Pipeline": {"Repository": "https://github.com/o/r", "GitHubToken": "ghp_lambdapat12"}}, 201)
    _check("GitHub source fetched with the user's PAT and deployed", a["Pipeline"]["Executions"][0]["Status"] == "Succeeded" and "ghp_lambdapat12" not in json.dumps(a))
    ci.set_fetcher(None)
    s, a = call("POST", "/2015-03-31/applications/gh/pipeline/executions", {}, 200)
    ex = a["Pipeline"]["Executions"][0]
    _check("unreachable GitHub (Nano) fails at Source with the reason", ex["Status"] == "Failed" and ex["FailedStage"] == "Source")
    _check("push to a GitHub-backed pipeline is refused", call("POST", "/2015-03-31/applications/gh/pipeline/push", {"Files": {"a": "b"}})[0] == 400)
    _check("app list shows both", len(call("GET", "/2015-03-31/applications", None, 200)[1]["Applications"]) == 2)
    call("DELETE", "/2015-03-31/applications/gh", None, 200)
    _check("plain applications still work", call("POST", "/2015-03-31/applications", {"Name": "plain"}, )[0] == 201)
    print("PASS test_lambda_cicd")


if __name__ == "__main__":
    main()
