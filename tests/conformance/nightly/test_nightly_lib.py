from tests.conformance.nightly.lib.roundtrip import run_roundtrip, diff
from tests.conformance.nightly.lib.tunnel_recovery import run_recovery


class Fake:
    fields = ("name", "status")
    def __init__(self, ui_sees_client=True, status_drift=False):
        self.store = {}; self.ui_sees_client = ui_sees_client; self.drift = status_drift
    def ui_create(self, n): self.store[n] = {"name": n, "status": "Succeeded"}
    def client_create(self, n): self.store[n] = {"name": n, "status": "Succeeded"}
    def client_read(self, n): return self.store.get(n)
    def ui_read(self, n):
        r = self.store.get(n)
        if r is None or (not self.ui_sees_client and n.endswith("-client")): return None
        return {**r, "status": "Creating"} if self.drift else r
    def ui_delete(self, n): self.store.pop(n, None)
    def client_delete(self, n): self.store.pop(n, None)


def test_roundtrip_clean():
    assert run_roundtrip(Fake(), "t", emit=lambda s: None) == []

def test_roundtrip_detects_missing_in_ui():
    f = run_roundtrip(Fake(ui_sees_client=False), "t", emit=lambda s: None)
    assert any("client-created" in x.step for x in f)

def test_roundtrip_detects_data_drift_not_just_presence():
    f = run_roundtrip(Fake(status_drift=True), "t", emit=lambda s: None)
    assert f and "status" in f[0].detail

def test_diff_none():
    assert diff(None, {"a": 1}, ("a",))

def _clock():
    t = [0.0]
    return (lambda: t[0]), (lambda s: t.__setitem__(0, t[0] + s))

def test_recovery_ok_and_fails_when_never_back():
    clock, sleep = _clock(); up = [True]
    ok = run_recovery(lambda: up[0], lambda: "m", lambda m: True, {"kill": lambda: up.__setitem__(0, False) or up.__setitem__(0, True)},
                      emit=lambda s: None, clock=clock, sleep=sleep)
    assert ok == []
    clock, sleep = _clock(); up = [True]
    bad = run_recovery(lambda: up[0], lambda: "m", lambda m: True, {"kill": lambda: up.__setitem__(0, False)},
                       deadline=10, emit=lambda s: None, clock=clock, sleep=sleep)
    assert bad and "recovers" in bad[0]

def test_recovery_detects_state_loss():
    clock, sleep = _clock()
    bad = run_recovery(lambda: True, lambda: "m", lambda m: False, {"restart": lambda: None}, emit=lambda s: None, clock=clock, sleep=sleep)
    assert bad and "state survives" in bad[0]
