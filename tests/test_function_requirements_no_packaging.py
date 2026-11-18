"""check_requirements must honour the provided functions-framework even when `packaging` is not installed (the appliance image
does not ship it): v4.0.8 rejected `functions-framework` in requirements.txt there, so `gcloud functions deploy` returned 400."""
import sys
import pytest

sys.path.insert(0, ".")


@pytest.fixture
def no_packaging(monkeypatch):
    for m in [k for k in sys.modules if k == "packaging" or k.startswith("packaging.")]:
        monkeypatch.delitem(sys.modules, m, raising=False)
    monkeypatch.setitem(sys.modules, "packaging", None)          # `from packaging.requirements import ...` -> ImportError
    monkeypatch.setitem(sys.modules, "packaging.requirements", None)


def test_functions_framework_is_provided_without_packaging(no_packaging):
    from core import gcp_function_runtime as r
    assert r.check_requirements("functions-framework\n") == []
    assert r.check_requirements("functions_framework==3.5.0\n") == []


def test_unknown_requirement_still_rejected_without_packaging(no_packaging):
    from core import gcp_function_runtime as r
    bad = r.check_requirements("functions-framework\nnot-a-real-lib-xyz\n")
    assert len(bad) == 1 and bad[0].startswith("not-a-real-lib-xyz")
