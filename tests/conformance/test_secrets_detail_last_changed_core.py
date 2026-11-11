"""Secrets Manager details: a secret with no versions yet still has a Last changed date (real AWS: LastChangedDate = creation)."""
try:
    from core import aws_console_detail as d
except ImportError:  # pragma: no cover
    import aws_console_detail as d  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"[PASS] {name}")


def run():
    created = "2026-11-11T08:00:00Z"
    empty = d.secret_section({"created": created}, "details", [], "s1", "arn:aws:secretsmanager:us-east-1:123456789012:secret:s1")
    _check("no versions: Last changed falls back to the creation time", empty["last_changed"] == created)
    v = d.secret_section({"created": created}, "details", [{"version_id": "v1", "stages": ["AWSCURRENT"], "created": "2026-11-11T09:00:00Z"}], "s1", "arn")
    _check("with versions: Last changed is the newest version's time", v["last_changed"] == "2026-11-11T09:00:00Z")
    _check("never blank for a secret that exists", bool(empty["last_changed"]) and bool(v["last_changed"]))
    print("SECRETS LAST CHANGED OK")


if __name__ == "__main__":
    run()
