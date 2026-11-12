"""run_suites.count(): a check NAME containing "400 error" must not be read as a pytest summary."""
import importlib.util, os, sys

spec = importlib.util.spec_from_file_location(
    "run_suites", os.path.join(os.path.dirname(__file__), "hourly", "run_suites.py"))
rs = importlib.util.module_from_spec(spec); spec.loader.exec_module(rs)


def test_go_check_name_with_400_error_is_not_a_failure():
    log = "[PASS] a\n[PASS] unsupported KQL → 400 error\n[PASS] b\nall checks passed\n"
    assert rs.count(log) == (3, 0)


def test_real_failure_lines_still_count():
    assert rs.count("[PASS] a\n[FAIL] b boom\n") == (1, 1)


def test_pytest_summary_still_counts_errors():
    assert rs.count("==== 5 passed, 2 failed, 1 error in 3.21s ====\n") == (5, 3)
    assert rs.count("5 passed in 0.1s\n") == (5, 0)


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
    print("ok")
