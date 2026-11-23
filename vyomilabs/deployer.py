"""Deploys a chapter's lab blocks exactly as written (the same code the learner sees) into a running simulator and streams progress.

deploy(cloud, layer) -> iterator of events (dicts). It first deploys any earlier chapters (course order) that are not yet deployed in
this session, then the chapter itself, so a chapter can rely on the resources earlier chapters create. One simulator process per cloud
is kept for the session; the workspace is shared across chapters like a learner's project folder."""
import atexit
import importlib
import json
import os
import subprocess
import sys
import tempfile
import threading

ORDER = [10, 3, 7, 12, 6, 11, 9, 4, 5, 1, 2, 8, 13]
_LOCK = threading.Lock()
_ENVS = {}      # cloud -> dict(proc, endpoint, env, work, done:set)


def _env_for(cloud, endpoint=None):
    e = _ENVS.get(cloud)
    if e and e["proc"].poll() is None:
        return e
    yield dict(t="status", text="Starting the %s simulator (first deploy only)..." % cloud)
    cmd = [sys.executable, "-m", "vyomilabs.simproc", cloud] + ([endpoint] if endpoint else [])
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, cwd=os.path.dirname(os.path.dirname(__file__)))
    atexit.register(lambda: proc.poll() is None and proc.terminate())
    line = ""
    for line in proc.stdout:
        if line.startswith("VYOMI_ENV "):
            break
    else:
        raise RuntimeError("the %s simulator did not start" % cloud)
    info = json.loads(line[len("VYOMI_ENV "):])
    e = dict(proc=proc, endpoint=info["endpoint"], env=dict(os.environ, **info["env"]), work=tempfile.mkdtemp(prefix="vy-deploy-"), done=set())
    e["env"]["PYTHONPATH"] = e["work"]
    _ENVS[cloud] = e
    return e


def reset(cloud):
    e = _ENVS.pop(cloud, None)
    if e and e["proc"].poll() is None:
        e["proc"].terminate()


def deploy(cloud, layer, endpoint=None):
    lab = importlib.import_module(f"vyomilabs.content.labs_{cloud}").LAB
    if layer not in lab:
        yield dict(t="done", ok=False, error="no lab code for chapter %s" % layer)
        return
    with _LOCK:
        try:
            gen = _env_for(cloud, endpoint)
            e = None
            while True:
                try:
                    ev = next(gen)
                    yield ev
                except StopIteration as stop:
                    e = stop.value
                    break
            if e is None:
                e = _ENVS[cloud]
        except Exception as ex:
            yield dict(t="done", ok=False, error=str(ex))
            return
        chain = ORDER[:ORDER.index(layer) + 1]
        ok_all = True
        for cid in chain:
            if cid != layer and cid in e["done"]:
                continue
            target = cid == layer
            if not target:
                yield dict(t="status", text="Deploying chapter %s first (this chapter builds on it)..." % cid)
            ok = True
            for i, blk in enumerate(lab.get(cid, [])):
                with open(os.path.join(e["work"], blk["file"]), "w") as f:
                    f.write(blk["code"])
                if not blk["run"]:
                    if target:
                        yield dict(t="block", i=i, status="saved")
                    continue
                if blk.get("needs_runtime") and not os.environ.get("VYOMILABS_HAS_RUNTIME"):
                    if target:
                        yield dict(t="block", i=i, status="blocked", out="This step runs real function code. It needs a runtime (the offline appliance or a Mesh).")
                    continue
                if target:
                    yield dict(t="block", i=i, status="running")
                try:
                    p = subprocess.run([sys.executable] + blk["run"].split()[1:], cwd=e["work"], env=e["env"], capture_output=True, text=True, timeout=240)
                    out = (p.stdout or "") + (("\n" + p.stderr) if p.returncode else "")
                    passed = p.returncode == 0 and (not blk["expect"] or blk["expect"] in p.stdout)
                except subprocess.TimeoutExpired:
                    out, passed = "Timed out after 240 s.", False
                ok &= passed
                if target:
                    yield dict(t="block", i=i, status="passed" if passed else "failed", out=out[-4000:])
                elif not passed:
                    yield dict(t="status", text="Chapter %s step '%s' failed:\n%s" % (cid, blk["run"], out[-800:]))
            if ok:
                e["done"].add(cid)
            ok_all &= ok if target else True
            if not ok and not target:
                yield dict(t="done", ok=False, error="A chapter this one builds on failed to deploy (chapter %s)." % cid)
                return
        yield dict(t="done", ok=ok_all, endpoint=e["endpoint"])
