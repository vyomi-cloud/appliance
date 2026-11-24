import pytest
from core.iam_engine import modes, audit

S = {"global": "off", "space": "audit", "services": {"s3": "enforce"}, "resources": {"arn:aws:s3:::locked": "off"}}


def test_default_off():
    assert modes.resolve_mode("aws", {}, "s3", "x") == "off"
    assert modes.resolve_mode("aws", None) == "off"


def test_precedence_resource_over_service():
    assert modes.resolve_mode("aws", S, "s3", "arn:aws:s3:::locked") == "off"


def test_service_over_space():
    assert modes.resolve_mode("aws", S, "s3", "arn:aws:s3:::other") == "enforce"


def test_space_over_global():
    assert modes.resolve_mode("aws", S, "ec2", None) == "audit"


def test_global_fallback():
    assert modes.resolve_mode("gcp", {"global": "enforce"}, "x", "y") == "enforce"


def test_space_off_explicit_beats_global():
    assert modes.resolve_mode("gcp", {"global": "enforce", "space": "off"}) == "off"


def test_azure_resource_case_insensitive():
    s = {"resources": {"/subscriptions/ABC/rg": "enforce"}}
    assert modes.resolve_mode("azure", s, None, "/subscriptions/abc/RG") == "enforce"
    assert modes.resolve_mode("aws", s, None, "/subscriptions/abc/RG") == "off"


def test_service_case_insensitive():
    assert modes.resolve_mode("azure", {"services": {"Microsoft.Storage": "audit"}}, "microsoft.storage") == "audit"


def test_validate_ok_and_normalises():
    out, errs = modes.validate({"space": "ENFORCE", "services": {"s3": "Audit"}})
    assert not errs and out["space"] == "enforce" and out["services"]["s3"] == "audit"
    assert out["allowUnmapped"] is False


@pytest.mark.parametrize("doc", [{"space": "block"}, {"services": {"s3": "x"}}, {"resources": []}, {"bogus": 1},
                                 {"allowUnmapped": "yes"}, "str", {"services": {"": "off"}}])
def test_validate_rejects(doc):
    assert modes.validate(doc)[1]


def test_malformed_never_raises():
    assert modes.resolve_mode("aws", {"services": "bad", "space": 5}, "s3") == "off"


def test_any_active():
    assert not modes.any_active({}) and not modes.any_active({"space": "off"})
    assert modes.any_active({"resources": {"a": "audit"}})


def test_set_mode_levels():
    s = modes.set_mode({}, "enforce", service="s3")
    assert s["services"] == {"s3": "enforce"}
    s = modes.set_mode(s, "audit", resource="r")
    assert s["resources"]["r"] == "audit"
    assert modes.set_mode(s, "audit")["space"] == "audit"
    with pytest.raises(ValueError):
        modes.set_mode(s, "nope")


def test_holder_store_roundtrip_and_persist():
    holder, calls = {}, []
    st = modes.HolderSettingsStore(lambda: holder, persist=lambda: calls.append(1))
    assert st.get()["space"] == "off"
    st.put({"space": "audit"})
    assert holder["iam_enforcement"]["space"] == "audit" and calls == [1]
    with pytest.raises(ValueError):
        st.put({"space": "zzz"})


def test_memory_store():
    m = modes.MemorySettingsStore()
    m.put({"global": "enforce"})
    assert m.get()["global"] == "enforce"


def test_audit_ring_bounded_and_filters():
    log = audit.AuditLog(3)
    for i in range(5):
        log.record("aws" if i % 2 else "gcp", f"p{i}", "a", "r", "audit", "allow" if i < 4 else "deny", "x",
                   [{"source": "identity", "id": "1", "effect": "Allow", "statement": {"big": 1}}])
    assert len(log) == 3
    recs = log.list(10)
    assert [r["principal"] for r in recs] == ["p4", "p3", "p2"]
    assert log.list(10, cloud="aws")[0]["principal"] == "p3"
    assert log.list(10, decision="deny")[0]["principal"] == "p4"
    assert log.list(1)[0]["principal"] == "p4"
    assert "statement" not in recs[0]["matched"][0]
    assert set(recs[0]) >= {"time", "cloud", "principal", "action", "resource", "mode", "decision", "reason", "matched"}
    log.clear()
    assert log.list() == []
