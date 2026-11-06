"""Tier + booster trial + pills plumbing (in-process).

Run:  PYTHONPATH=. python3 tests/conformance/test_tier_trial.py   (non-zero exit on failure)
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core import license_remote as lr  # noqa: E402
from core import tier_policy as tp  # noqa: E402

DAY = 86400
T0 = 1_800_000_000.0
EXP = T0 + 14 * DAY
CLAIMS = {"tier": "free", "trial": True, "booster_trial_expires": EXP}
FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("PASS" if cond else "FAIL"), name, detail if not cond else "")
    if not cond:
        FAILS.append(name)


def status(now: float, d: str, claims=CLAIMS, **kw) -> dict:
    return lr.trial_status(now=now, claims=claims, data_dir=d, **kw)


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        s = status(T0, d)
        check("day0 is trial, 14 left", s["state"] == "trial" and s["days_left"] == 14, str(s))
        s = status(T0 + 6 * DAY, d)
        check("day6 still trial (8 left)", s["state"] == "trial" and s["days_left"] == 8, str(s))
        s = status(T0 + 7 * DAY, d)
        check("reminder at 7 days left", s["state"] == "reminder" and s["days_left"] == 7 and s["reminder"], str(s))
        s = status(T0 + 13.5 * DAY, d)
        check("reminder on last day", s["state"] == "reminder" and s["days_left"] == 1, str(s))
        s = status(EXP - 1, d)
        check("not locked one second before expiry", not s["locked"], str(s))
        s = status(EXP, d)
        check("locked at day 15 (expiry), no grace", s["state"] == "locked" and s["locked"] and s["days_left"] == 0, str(s))
        check("locked blocks export (flag)", s["export_blocked"] is True)
        json.dumps(s)
        check("summary JSON-serialisable", True)

    with tempfile.TemporaryDirectory() as d:
        status(T0 + 10 * DAY, d)                       # high-water mark day 10
        s = status(T0, d)                              # clock rolled back to day 0
        check("rollback keeps day-10 view", s["state"] == "reminder" and s["days_left"] == 4, str(s))
        status(EXP + DAY, d)
        s = status(T0, d)
        check("rollback after expiry stays locked", s["state"] == "locked", str(s))
        check("high-water record persisted", (Path(d) / "booster_clock.json").exists())
        s = status(T0, d, claims={"tier": "pro", "booster_trial_expires": EXP})
        check("paid entitlement overrides lock", s["state"] == "paid" and not s["locked"], str(s))
        s = status(T0, d, claims={})
        check("no claim -> none", s["state"] == "none", str(s))
        out = lr.booster_status_summary({"license_claims": CLAIMS}, now=T0, data_dir=d)
        check("booster_status_summary works", out["state"] == "locked", str(out))
        check("claims payload carries booster_trial_expires",
              lr.claims_to_tier_payload({"tier": "free", "booster_trial_expires": "x"})["booster_trial_expires"] == "x")

    # pills
    check("pill Pro", tp.pill_for({"tier": "pro"}) == "Pro")
    check("pill Max", tp.pill_for({"tier": "max"}) == "Max")
    check("pill Booster wins", tp.pill_for({"tier": "pro", "booster": True}) == "Booster")
    check("pill none (free/unset)", tp.pill_for({}) is None and tp.pill_for({"tier": "free"}) is None and tp.pill_for(None) is None)
    check("validator rejects bad tier", bool(tp.validate_entry_gating("x", {"tier": "gold"})))
    check("validator rejects bad booster", bool(tp.validate_entry_gating("x", {"booster": "yes"})))
    check("validator accepts good", not tp.validate_entry_gating("x", {"tier": "max", "booster": True}))

    # feature_allowed
    pro_e, max_e, bst = {"tier": "pro"}, {"tier": "max"}, {"booster": True, "tier": "pro"}
    check("free blocked on pro feature", not tp.feature_allowed("free", "aws", "ec2", entry=pro_e))
    check("free allowed on ungated", tp.feature_allowed("free", "aws", "s3", entry={}))
    check("pro allowed on primary cloud", tp.feature_allowed("pro", "aws", "ec2", entry=pro_e, primary_cloud="aws"))
    check("pro blocked off primary cloud", not tp.feature_allowed("pro", "gcp", "compute", entry=pro_e, primary_cloud="aws"))
    check("pro blocked on max feature", not tp.feature_allowed("pro", "aws", "iam", entry=max_e, primary_cloud="aws"))
    check("max allowed on all 3 clouds", all(tp.feature_allowed("max", c, "x", entry=max_e) for c in ("aws", "gcp", "azure")))
    check("booster feature needs booster", not tp.feature_allowed("max", "aws", "x", entry=bst)
          and tp.feature_allowed("max", "aws", "x", entry=bst, booster_available=True))
    check("free never booster", not tp.feature_allowed("free", "aws", "x", entry=bst, booster_available=True))
    check("cloud counts free0/pro1/max3", (tp.FULL_CLOUDS["free"], tp.FULL_CLOUDS["pro"], tp.FULL_CLOUDS["max"]) == (0, 1, 3))

    # registry + generated manifest
    sys.path.insert(0, str(ROOT / "scripts"))
    import gen_tier_pills as g  # noqa: E402
    rules = g.load_rules()
    bad = []
    for f in g.registry_files():
        for fid, ent in json.loads(f.read_text()).items():
            if fid.startswith("$"):
                continue
            bad += tp.validate_entry_gating(fid, ent)
            r = g.rule_for(fid, rules)
            want = {k: r[k] for k in ("tier", "booster") if r and k in r}
            have = {k: ent[k] for k in ("tier", "booster") if k in ent}
            if want != have:
                bad.append(f"{fid}: registry {have} != _tiers.json {want}")
    check("registry matches _tiers.json and validates", not bad, "; ".join(bad[:5]))
    man = json.loads((ROOT / "wasm" / "tier-pills.json").read_text())
    check("manifest up to date", g.main.__module__ and man == g.build())
    check("manifest maps known ids", man["pills"].get("gcp.kubernetes.workloads") == "Booster"
          and man["pills"].get("dynamodb.backups") == "Pro" and man["pills"].get("iam.organizations.policies") == "Max")
    check("core CRUD ungated", "ec2.instances.lifecycle" not in man["pills"] and "s3.bucket.crud" not in man["pills"])

    print("RESULT:", "FAIL - " + ", ".join(FAILS) if FAILS else "PASS")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
