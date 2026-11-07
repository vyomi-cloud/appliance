"""Pause/resume of the booster model pool (running-time window), hermetic: fake dispatcher + fake clock, no node/relay.
pause -> EVERY runner cancelled via the dispatcher, clock frozen; resume -> all ten restarted with the REMAINING running time.
Run: PYTHONPATH=. python tests/conformance/test_booster_runner_pause.py"""
import os
import sys
import tempfile

os.environ.setdefault("CLOUDLEARN_STATE_DIR", tempfile.mkdtemp(prefix="booster-pause-"))
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, ROOT)
from core import booster_runner_pool as P  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail)[:300] if detail and not ok else ''}")


class Clock:
    def __init__(self): self.t = 1_000_000.0
    def __call__(self): return self.t


class Disp:
    def __init__(self): self.started, self.stopped = [], []
    def start(self, rid, spec, *, rotation=False): self.started.append(rid)
    def stop(self, rid): self.stopped.append(rid)


H = 3600.0
SLOTS = ["fast", "general", "coder", "agents", "gemma", "qwen3", "r1", "mistral", "big#0", "big#1"]
clk, d = Clock(), Disp()
pool = P.RunnerPool("http://127.0.0.1:9", lambda: "t", d, window_s=30 * H, clock=clk, stagger_s=0, idle_s=10 * H)

pool.start_all()
check("start: all ten slots dispatched", sorted(d.started) == sorted(SLOTS), d.started)
clk.t += 2 * H
pool.touch(); pool.tick()
check("running 2 h: 28 h left", abs(pool.remaining_s() - 28 * H) < 1, pool.remaining_s())

d.stopped.clear()
w = pool.pause()
check("pause: EVERY runner cancelled through the dispatcher", sorted(set(d.stopped)) == sorted(SLOTS), d.stopped)
check("pause: phase paused, 2 h banked, label says paused", pool.phase == "paused" and w["consumed_s"] == 2 * H and "paused" in w["label"], w)
clk.t += 10 * H                                                   # a long pause (wall-clock) must cost nothing
pool.tick()
check("paused 10 h wall-clock: window frozen at 28 h, pool NOT destroyed by tick/idle", pool.phase == "paused" and abs(pool.remaining_s() - 28 * H) < 1)
try:
    pool.route("POST", "/v1/chat/completions", b'{"model":"qwen2.5-7b"}'); code = None
except P.PoolError as e:
    code = e.code
check("paused: requests get 503 ModelPoolPaused (no fake answer)", code == "ModelPoolPaused", code)
check("paused: every model reports stopped", all(m["state"] == "stopped" for m in pool.models_status()["models"]))
n = len(d.stopped); pool.pause()
check("pause is idempotent (no second cancel storm)", len(d.stopped) == n)

d.started.clear()
pool.resume()
check("resume: ALL ten runners restarted (cold)", sorted(d.started) == sorted(SLOTS), d.started)
check("resume: continues with the remaining 28 h, not 30 h", pool.phase == "running" and abs(pool.remaining_s() - 28 * H) < 1 and abs(pool.deadline - (clk.t + 28 * H)) < 1)
clk.t += 3 * H; pool.touch(); pool.tick()
check("second segment 3 h: 25 h left, 5 h consumed", abs(pool.remaining_s() - 25 * H) < 1 and pool.window()["consumed_s"] == 5 * H, pool.window())

# portal figure wins on resume (e.g. another device consumed time): remaining 4 h granted
pool.pause(); d.started.clear(); pool.resume(window_s=4 * H)
check("resume with portal remaining=4 h: deadline = now + 4 h, window total = consumed + 4 h", abs(pool.remaining_s() - 4 * H) < 1 and abs(pool.window_s - 9 * H) < 1, (pool.remaining_s(), pool.window_s))
clk.t += 4 * H + 1; pool.tick()
check("destroy at the remaining window: window_end, all runners cancelled", pool.phase == "destroyed" and pool.destroyed_why == "window_end" and set(SLOTS) <= set(d.stopped))
try:
    pool.resume(); r = None
except P.PoolError as e:
    r = e.code
check("a destroyed pool cannot resume", r == "ModelPoolDestroyed", r)

# start with a REMAINING window (portal token claim) rather than the tier window
d2, clk2 = Disp(), Clock()
p2 = P.RunnerPool("http://127.0.0.1:9", lambda: "t", d2, window_s=30 * H, clock=clk2, stagger_s=0)
p2.start_all(window_s=7 * H)
check("start_all(window_s=remaining): pool destroys at 7 h, not 30 h", abs(p2.deadline - (clk2.t + 7 * H)) < 1)
clk2.t += 7 * H + 1; p2.tick()
check("... and destroys exactly there", p2.phase == "destroyed" and p2.destroyed_why == "window_end")
p3 = P.RunnerPool("http://127.0.0.1:9", lambda: "t", Disp(), window_s=30 * H, clock=Clock(), stagger_s=0)
try:
    p3.start_all(window_s=0); e3 = None
except P.PoolError as e:
    e3 = e.code
check("zero remaining window refuses to start", e3 == "ModelWindowExhausted", e3)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
