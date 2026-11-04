"""Shared CI seam: repos, push hooks, build jobs, GitHub PAT import, Gitea REST backend, BuildKit builder, Deployment Center.
Hermetic (docker + HTTP stubbed). Run: PYTHONPATH=. python tests/conformance/test_ci_core.py"""
import base64, io, json, tarfile
try:
    from core import ci_core as ci
    from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
except ImportError:  # pragma: no cover
    import ci_core as ci  # type: ignore
    from azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB  # type: ignore


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def _raises(code, fn, *a, **k):
    try:
        fn(*a, **k)
    except ci.CiError as e:
        return e.code == code
    return False


def _tgz(files, top="o-r-abc123"):
    b = io.BytesIO()
    with tarfile.open(fileobj=b, mode="w:gz") as tf:
        for p, c in files.items():
            ti = tarfile.TarInfo(f"{top}/{p}"); ti.size = len(c); tf.addfile(ti, io.BytesIO(c))
    return b.getvalue()


def run():
    ci.set_git(None); ci.set_builder(None); ci.set_fetcher(None)
    db = ci.get_db({})
    _check("repo name validated", _raises("InvalidRepositoryName", ci.create_repo, db, "bad name!"))
    ci.create_repo(db, "app")
    _check("duplicate repo 409", _raises("RepositoryExists", ci.create_repo, db, "app"))
    _check("empty repo has no ref", _raises("RefNotFound", ci.tree, db, "app"))
    _check("bad path rejected", _raises("InvalidPath", ci.commit_files, db, "app", "main", {"../x": "y"}))
    seen = []
    ci.register_consumer("t", lambda d, ev, h, ctx, job: seen.append((ev, job)))
    ci.add_hook(db, "app", "t", branch="main", build={"kind": "package"})
    ev = ci.commit_files(db, "app", "main", {"app.py": "print(1)", "requirements.txt": "flask"}, "init", "me")
    _check("push fires hook + build job", len(seen) == 1 and seen[0][1]["status"] == "Succeeded" and ev["jobs"])
    j = seen[0][1]
    _check("package artifact is content-addressed", j["artifact"]["digest"].startswith("sha256:") and j["artifact"]["runtime"] == "python" and j["artifact"]["files"] == 2)
    ci.commit_files(db, "app", "dev", {"a": "b"}, "other branch")
    _check("hook branch filter", len(seen) == 1)
    ev2 = ci.commit_files(db, "app", "main", {"app.py": "print(2)"}, "v2")
    _check("different content -> different digest", seen[1][1]["artifact"]["digest"] != j["artifact"]["digest"])
    _check("log walks parents", [c["message"] for c in ci.log(db, "app", "main")] == ["v2", "init"])
    _check("tree at old commit via sha", ci.tree(db, "app", ev["after"])["app.py"] == b"print(1)")
    ci.commit_files(db, "app", "main", {"app.py": None}, "rm")
    _check("delete file", "app.py" not in ci.tree(db, "app"))
    # Dockerfile validation + image job honesty without a container builder
    ci.commit_files(db, "app", "df", {"Dockerfile": "RUN x\n"}, "bad")
    jb = ci.submit_job(db, "app", "df", {"kind": "package"})
    _check("Dockerfile without FROM fails", jb["status"] == "Failed" and any("FROM" in l["message"] for l in jb["logs"]))
    ci.commit_files(db, "app", "df", {"Dockerfile": "FROM alpine:3\nCOPY missing.txt /x\n"}, "bad copy")
    _check("COPY source missing fails", ci.submit_job(db, "app", "df")["status"] == "Failed")
    ci.commit_files(db, "app", "df", {"Dockerfile": "FROM alpine:3\nCOPY a.txt /x\n", "a.txt": "hi"}, "good")
    ji = ci.submit_job(db, "app", "df", {"kind": "image"})
    _check("image job without container builder is Failed (no fake green)", ji["status"] == "Failed" and "No container builder" in ji["error"])
    # BuildKit builder with a stubbed docker
    calls = []
    def fake_docker(argv, inp, to):
        calls.append(argv)
        if argv[:2] == ["docker", "build"]:
            return 0, b"#1 DONE\n"
        return 0, b"sha256:deadbeef 4096\n"
    ci.set_builder(ci.BuildKitBuilder(fake_docker))
    ji = ci.submit_job(db, "app", "df", {"kind": "image", "tag": "t/app:1", "buildArgs": ["A=1"]})
    _check("BuildKit image job succeeds + records image artifact", ji["status"] == "Succeeded" and ji["artifact"] == {"type": "image", "tag": "t/app:1", "digest": "sha256:deadbeef", "size": 4096})
    _check("docker build is offline (--pull=false) with tar stdin", calls[0][:3] == ["docker", "build", "--pull=false"] and calls[0][-1] == "-" and "--build-arg" in calls[0])
    ci.set_builder(ci.BuildKitBuilder(lambda a, i, t: (1, b"ERROR: boom\n")))
    _check("failed docker build -> Failed job with output", ci.submit_job(db, "app", "df", {"kind": "image"})["status"] == "Failed")
    ci.set_builder(None)
    # GitHub PAT import
    _check("non-GitHub source rejected", _raises("UnsupportedSource", ci.import_external, db, "gh", "https://dev.azure.com/o/p/_git/r", "main"))
    _check("no fetcher on this substrate", _raises("FetchUnavailable", ci.import_external, db, "gh", "https://github.com/o/r", "main"))
    reqs = []
    def fetch(url, h):
        reqs.append((url, h))
        if "Authorization" not in h and "private" in url:
            return 404, b""
        return 200, _tgz({"index.html": b"<h1>x</h1>", "sub/a.txt": b"a"})
    ci.set_fetcher(fetch)
    _check("private repo without PAT -> 404 explaining PAT", _raises("SourceNotFound", ci.import_external, db, "gh", "https://github.com/o/private", "main"))
    ci.set_connection(db, "github", "ghp_exampletoken123")
    _check("token never echoed", ci.connection_view(db, "github")["token"] == "***")
    ev = ci.import_external(db, "gh", "https://github.com/o/private", "main")
    _check("PAT sent as bearer, tarball committed", reqs[-1][1]["Authorization"] == "Bearer ghp_exampletoken123" and ci.tree(db, "gh")["sub/a.txt"] == b"a")
    _check("short token rejected", _raises("InvalidToken", ci.set_connection, db, "github", "x"))
    ci.set_fetcher(None)
    # Gitea REST backend (stubbed server)
    store = {"files": {}, "head": None, "n": 0}
    def gitea(method, url, h, body):
        path = url.split("/api/v1")[1]
        assert h["Authorization"] == "token tok"
        if method == "GET" and path == "/repos/vyomi/g1":
            return (200, b"{}") if store.get("repo") else (404, b"")
        if method == "POST" and path == "/user/repos":
            store["repo"] = True; return 201, b"{}"
        if method == "GET" and "/git/trees/" in path:
            return (200, json.dumps({"tree": [{"path": p, "type": "blob", "sha": "s" + p} for p in store["files"]]}).encode()) if store["head"] else (404, b"")
        if method == "POST" and path.endswith("/contents"):
            b = json.loads(body)
            for o in b["files"]:
                if o["operation"] == "delete": store["files"].pop(o["path"])
                else: store["files"][o["path"]] = base64.b64decode(o["content"])
                assert o["operation"] != "update" or o["sha"] == "s" + o["path"]
            store["n"] += 1; store["head"] = f"c{store['n']}"; store.setdefault("ops", []).append([o["operation"] for o in b["files"]])
            return 201, json.dumps({"commit": {"sha": store["head"]}}).encode()
        if method == "GET" and "/archive/" in path:
            return 200, _tgz(store["files"], "g1")
        if method == "GET" and "/branches/" in path and store["head"]:
            return 200, json.dumps({"commit": {"id": store["head"]}}).encode()
        if method == "GET" and "/commits?" in path:
            return 200, json.dumps([{"sha": store["head"], "commit": {"message": "ext", "author": {"name": "dev", "date": "2026-11-04T00:00:00Z"}}}]).encode()
        if method == "GET" and path.endswith("/branches"):
            return 200, json.dumps([{"name": "main", "commit": {"id": store["head"]}}] if store["head"] else []).encode()
        return 404, b""
    ci.set_git(ci.GiteaGit("http://127.0.0.1:13000", "vyomi", "tok", gitea))
    d2 = ci.get_db({})
    r = ci.create_repo(d2, "g1")
    _check("Gitea backend: repo created via REST, clone URL real", r["backend"] == "gitea" and r["cloneUrl"] == "http://127.0.0.1:13000/vyomi/g1.git")
    ci.commit_files(d2, "g1", "main", {"x.txt": "1"}, "c1")
    ci.commit_files(d2, "g1", "main", {"x.txt": "2", "y.txt": "z"}, "c2")
    _check("Gitea backend: create then update/create ops", store["ops"] == [["create"], ["update", "create"]] and ci.tree(d2, "g1")["x.txt"] == b"2")
    store["files"]["pushed.txt"] = b"p"; store["n"] += 1; store["head"] = "c-external"          # a real `git push` straight to Gitea
    hits = []
    ci.register_consumer("t2", lambda d, ev, h, ctx, job: hits.append(ev["after"]))
    ci.add_hook(d2, "g1", "t2")
    ci.reconcile(d2, "g1")
    _check("reconcile detects a push made directly to the git host", hits == ["c-external"])
    ci.reconcile(d2, "g1")
    _check("reconcile is idempotent", hits == ["c-external"])
    ci.set_git(None)

    # Deployment Center: Local Git push -> real deployment; GitHub sync via fetcher
    a = AzureArm(); Q = {"api-version": "2023-12-01"}
    RG = f"/subscriptions/{SUB}/resourceGroups/ci-rg"; W = f"{RG}/providers/Microsoft.Web"; S = f"{W}/sites/lg1"
    a.handle("PUT", RG, {"api-version": "2021-04-01"}, {"location": "eastus"})
    a.handle("PUT", f"{W}/serverfarms/p1", Q, {"location": "eastus", "sku": {"name": "B1"}})
    a.handle("PUT", S, Q, {"location": "eastus", "kind": "app,linux", "properties": {"serverFarmId": f"{W}/serverfarms/p1"}})
    _check("localgit refused until LocalGit enabled", a.handle("POST", f"{S}/localgit", Q, {"files": {"a": "b"}})["status"] == 409)
    a.handle("PATCH", f"{S}/config/web", Q, {"properties": {"scmType": "LocalGit"}})
    r = a.handle("POST", f"{S}/localgit", Q, {"message": "first", "author": "dev", "files": {"app.py": "print('hi')", "requirements.txt": "flask"}})
    _check("local git push accepted", r["status"] == 200 and r["body"]["jobs"])
    dep = a.handle("GET", f"{S}/deployments", Q)["body"]["value"]
    p = dep[0]["properties"]
    _check("push became a Success deployment, active, with build log", len(dep) == 1 and p["status"] == 4 and p["active"] and p["author"] == "dev" and len(p["logs"]) >= 3)
    a.handle("POST", f"{S}/localgit", Q, {"message": "second", "files": {"app.py": "print('v2')"}})
    dep = a.handle("GET", f"{S}/deployments", Q)["body"]["value"]
    _check("second push supersedes: one active", len(dep) == 2 and sum(d["properties"]["active"] for d in dep) == 1 and dep[0]["properties"]["active"])
    _check("empty push -> 400", a.handle("POST", f"{S}/localgit", Q, {"files": {}})["status"] == 400)
    info = a.handle("GET", f"{S}/localgit", Q)["body"]
    _check("localgit info lists commits", [c["message"] for c in info["commits"]] == ["second", "first"])
    a.handle("PATCH", f"{S}/config/web", Q, {"properties": {"scmType": "None"}})
    ci.set_fetcher(lambda u, h: (200, _tgz({"requirements.txt": b"flask", "app.py": b"x"})) if "Authorization" in h or "open" in u else (404, b""))
    r = a.handle("PUT", f"{S}/sourcecontrols/web", Q, {"properties": {"repoUrl": "https://github.com/o/private", "branch": "main", "vyomiAccessToken": "ghp_secrettoken99"}})
    _check("GitHub source with PAT: continuous deploy succeeded", r["status"] in (200, 201) and "ghp_secrettoken99" not in json.dumps(r["body"]))
    dep = a.handle("GET", f"{S}/deployments", Q)["body"]["value"]
    _check("GitHub sync recorded a Success deployment", dep[0]["properties"]["status"] == 4 and "Sync from" in dep[0]["properties"]["message"])
    a.handle("PUT", f"{S}/sourcecontrols/web", Q, {"properties": {"repoUrl": "https://bitbucket.org/t/r.git", "branch": "main"}})
    dep = a.handle("GET", f"{S}/deployments", Q)["body"]["value"]
    _check("Bitbucket source honestly Failed (unsupported)", dep[0]["properties"]["status"] == 3 and "Only https://github.com" in dep[0]["properties"]["logs"][0]["message"])
    ci.set_fetcher(None)

    # ACR Tasks scheduleRun on the seam
    R = f"{RG}/providers/Microsoft.ContainerRegistry/registries/ciacr"
    a.handle("PUT", R, {"api-version": "2023-07-01"}, {"location": "eastus", "sku": {"name": "Standard"}})
    sr = lambda body: a.handle("POST", f"{R}/scheduleRun", {"api-version": "2019-04-01"}, body)
    _check("unknown run type 400", sr({"type": "Nope"})["status"] == 400)
    _check("YAML task runs honestly unsupported", sr({"type": "FileTaskRunRequest"})["status"] == 400)
    _check("bad image name 400", sr({"type": "DockerBuildRequest", "imageNames": ["BAD NAME"], "vyomiFiles": {"Dockerfile": "FROM alpine"}})["status"] == 400)
    r = sr({"type": "DockerBuildRequest", "imageNames": ["samples/app:{{.Run.ID}}"], "vyomiFiles": {"Dockerfile": "FROM alpine:3\nCOPY a.txt /a\n", "a.txt": "x"}})
    pr = r["body"]["properties"]
    _check("Nano-style (no container builder): image run is Failed with reason, no outputImages", r["status"] == 200 and pr["status"] == "Failed" and "No container builder" in pr["errorMessage"] and not pr["outputImages"])
    ci.set_builder(ci.BuildKitBuilder(lambda argv, i, t: (0, b"ok\n") if argv[1] == "build" else (0, b"sha256:abc123 2048\n")))
    r = sr({"type": "DockerBuildRequest", "imageNames": ["samples/app:{{.Run.ID}}"], "vyomiFiles": {"Dockerfile": "FROM alpine:3\nCOPY a.txt /a\n", "a.txt": "x"}})
    pr = r["body"]["properties"]
    _check("BuildKit run Succeeded with real outputImages + log", pr["status"] == "Succeeded" and pr["outputImages"][0]["digest"] == "sha256:abc123" and pr["outputImages"][0]["tag"].startswith("ca") and any("docker build" in l for l in pr["vyomiLogs"]))
    runs = a.handle("GET", f"{R}/runs", {"api-version": "2019-04-01"})["body"]["value"]
    _check("runs listed as ARM children", len(runs) == 2 and {x["properties"]["status"] for x in runs} == {"Failed", "Succeeded"})
    _check("DF path honoured / missing Dockerfile fails", sr({"type": "DockerBuildRequest", "dockerFilePath": "x/Dockerfile", "vyomiFiles": {"a": "b"}})["body"]["properties"]["status"] == "Failed")
    a.handle("PUT", f"{R}/tasks/t1", {"api-version": "2019-06-01-preview"}, {"properties": {"step": {"type": "Docker", "contextPath": "https://github.com/o/r#main", "dockerFilePath": "Dockerfile", "imageNames": ["t/x:v1"]}}})
    _check("task run: unknown task 404", sr({"type": "TaskRunRequest", "taskName": "zz"})["status"] == 404)
    ci.set_fetcher(lambda u, h: (200, _tgz({"Dockerfile": b"FROM alpine:3\n"})))
    pr = sr({"type": "TaskRunRequest", "taskName": "t1"})["body"]["properties"]
    _check("task run builds the GitHub context and records the task name", pr["status"] == "Succeeded" and pr["taskName"] == "t1" and pr["outputImages"][0]["tag"] == "v1")
    ci.set_fetcher(None); ci.set_builder(None)

    # Cloud Run continuous deployment from GitHub through the seam
    try:
        from core import gcp_run_core as rn
    except ImportError:  # pragma: no cover
        import gcp_run_core as rn  # type: ignore
    st = rn.RunStore()
    L = "/v2/projects/p1/locations/us-central1"
    call = lambda m, path, body=None, q=None: (lambda r: (r.status, json.loads(r.body or b"{}")))(rn.dispatch(st, m, path, q or {}, {}, json.dumps(body).encode() if body is not None else b""))
    _check("service created", call("POST", L + "/services", {"template": {"containers": [{"image": "gcr.io/x/app:1"}]}}, {"serviceId": "web"})[0] in (200, 201))
    _check("connect repo + PAT", call("POST", L + "/services/web:connectRepo", {"repository": "o/r", "branch": "main", "accessToken": "ghp_cloudrunpat1"})[0] == 200)
    _, b = call("POST", L + "/services/web/builds", {"fromRepo": True})
    _check("no outbound fetch (Nano-like) -> FAILURE with reason, service untouched", b["status"] == "FAILURE" and "outbound" in b["logs"])
    ci.set_fetcher(lambda u, h: (200, _tgz({"Dockerfile": b"FROM alpine:3\n"})) if h.get("Authorization") == "Bearer ghp_cloudrunpat1" else (404, b""))
    _, b = call("POST", L + "/services/web/builds", {"fromRepo": True})
    _check("no container builder -> FAILURE (no fake green)", b["status"] == "FAILURE" and "No container builder" in b["logs"])
    ci.set_builder(ci.BuildKitBuilder(lambda argv, i, t: (0, b"ok") if argv[1] == "build" else (0, b"sha256:feed 1024")))
    _, b = call("POST", L + "/services/web/builds", {"fromRepo": True})
    _check("BuildKit build succeeds and cuts a revision with the built image", b["status"] == "SUCCESS" and b["image"].startswith("vyomi-run/p1/web:") and b["revision"])
    _, svc = call("GET", L + "/services/web")
    _check("service now serves the built image", svc["template"]["containers"][0]["image"] == b["image"])
    ci.set_fetcher(lambda u, h: (200, _tgz({"main.py": b"x"})))
    _, b = call("POST", L + "/services/web/builds", {"fromRepo": True})
    _check("repo without Dockerfile -> FAILURE (no buildpacks)", b["status"] == "FAILURE" and "buildpacks" in b["logs"])
    ci.set_fetcher(None); ci.set_builder(None)
    print("PASS test_ci_core")


if __name__ == "__main__":
    run()
