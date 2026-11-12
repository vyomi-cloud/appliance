"""Unit tests for aws-tunnel-recovery.py: it must never score green without a real run."""
import importlib.util
import os

_spec = importlib.util.spec_from_file_location("aws_tunnel_recovery", os.path.join(os.path.dirname(__file__), "aws-tunnel-recovery.py"))
atr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(atr)


def test_not_run_without_opt_in():
    assert "NIGHTLY_TUNNEL_FAULTS" in atr.not_run_reason({})


def test_not_run_without_any_fault_command():
    assert "no NIGHTLY_FAULT" in atr.not_run_reason({"NIGHTLY_TUNNEL_FAULTS": "1"})


def test_runs_when_opted_in_with_a_fault():
    assert atr.not_run_reason({"NIGHTLY_TUNNEL_FAULTS": "1", "NIGHTLY_FAULT_DROP_SSH": "true"}) == ""


def test_only_configured_faults_are_built():
    f = atr.build_faults({"NIGHTLY_FAULT_KILL_RELAY": "true"})
    assert list(f) == ["kill the relay"]
    f["kill the relay"]()  # `true` succeeds


def test_not_run_prints_no_pass_line(capsys, monkeypatch):
    monkeypatch.delenv("NIGHTLY_TUNNEL_FAULTS", raising=False)
    assert atr.main() == 0
    out = capsys.readouterr().out
    assert out.startswith("NOT RUN") and "PASS" not in out


def test_unreachable_link_is_not_ok(monkeypatch):
    monkeypatch.setenv("VYOMI_BASE_URL", "http://127.0.0.1:1")
    assert atr.link_ok() is False
