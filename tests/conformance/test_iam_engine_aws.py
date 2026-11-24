"""AWS faithful policy-evaluation engine matrix (core/iam_engine/aws_eval.py)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from core.iam_engine import aws_eval as E  # noqa: E402

ACCT, OTHER = "111111111111", "222222222222"
USER = f"arn:aws:iam::{ACCT}:user/alice"
ROLE = f"arn:aws:iam::{ACCT}:role/dev"
SESS = f"arn:aws:sts::{ACCT}:assumed-role/dev/s1"
OBJ = "arn:aws:s3:::bkt/key.txt"


def pol(*stmts):
    return {"Version": "2012-10-17", "Statement": list(stmts)}


def allow(action="s3:GetObject", resource="*", **kw):
    return dict({"Effect": "Allow", "Action": action, "Resource": resource}, **kw)


def deny(action="s3:GetObject", resource="*", **kw):
    return dict({"Effect": "Deny", "Action": action, "Resource": resource}, **kw)


def ev(policies=None, action="s3:GetObject", resource=OBJ, ctx=None, principal=None, state=None, **extra):
    p = {"arn": USER, "type": "user", "account": ACCT, "policies": policies or []}
    p.update(principal or {})
    req = {"cloud": "aws", "principal": p, "action": action, "resource": resource, "context": ctx or {}}
    req.update(extra)
    return E.evaluate(req, state or {})


def ok(d, reason="allow"):
    assert d["reason"] == reason, d
    assert d["allowed"] == (reason == "allow")


# ---- basics
def test_implicit_deny_no_policy():
    ok(ev([]), "implicit_deny")


def test_allow_exact():
    ok(ev([pol(allow())]))


def test_allow_other_action_implicit():
    ok(ev([pol(allow("s3:PutObject"))]), "implicit_deny")


def test_explicit_deny_beats_allow():
    ok(ev([pol(allow("s3:*"), deny())]), "explicit_deny")


def test_deny_in_other_policy_beats_allow():
    ok(ev([pol(allow()), pol(deny())]), "explicit_deny")


def test_action_wildcard_case_insensitive():
    ok(ev([pol(allow("S3:GET*"))]))


def test_action_question_mark():
    ok(ev([pol(allow("s3:GetObjec?"))]))


def test_star_action():
    ok(ev([pol(allow("*"))]))


def test_service_wildcard_other_service():
    ok(ev([pol(allow("ec2:*"))]), "implicit_deny")


def test_resource_wildcard():
    ok(ev([pol(allow(resource="arn:aws:s3:::bkt/*"))]))


def test_resource_mismatch():
    ok(ev([pol(allow(resource="arn:aws:s3:::other/*"))]), "implicit_deny")


def test_resource_case_sensitive():
    ok(ev([pol(allow(resource="arn:aws:s3:::BKT/*"))]), "implicit_deny")


def test_resource_list():
    ok(ev([pol(allow(resource=["arn:aws:s3:::x/*", "arn:aws:s3:::bkt/*"]))]))


def test_notaction_allows_everything_else():
    ok(ev([pol({"Effect": "Allow", "NotAction": "iam:*", "Resource": "*"})]))


def test_notaction_excludes_listed():
    ok(ev([pol({"Effect": "Allow", "NotAction": "s3:*", "Resource": "*"})]), "implicit_deny")


def test_deny_notaction():
    ok(ev([pol(allow("*"), {"Effect": "Deny", "NotAction": "s3:*", "Resource": "*"})], action="ec2:RunInstances", resource="*"), "explicit_deny")
    ok(ev([pol(allow("*"), {"Effect": "Deny", "NotAction": "s3:*", "Resource": "*"})]))


def test_notresource():
    p = pol({"Effect": "Allow", "Action": "s3:*", "NotResource": "arn:aws:s3:::secret/*"})
    ok(ev([p]))
    ok(ev([p], resource="arn:aws:s3:::secret/x"), "implicit_deny")


def test_deny_notresource():
    p = pol(allow("s3:*"), {"Effect": "Deny", "Action": "s3:*", "NotResource": "arn:aws:s3:::bkt/*"})
    ok(ev([p]))
    ok(ev([p], resource="arn:aws:s3:::z/k"), "explicit_deny")


def test_statement_as_single_dict():
    ok(ev([{"Version": "2012-10-17", "Statement": allow()}]))


def test_managed_policy_wrapper():
    ok(ev([{"id": "arn:aws:iam::aws:policy/X", "document": pol(allow())}]))


def test_matched_records_source_and_id():
    d = ev([{"id": "P1", "document": pol(dict(allow(), Sid="S1"))}])
    assert d["matched"][0]["source"] == "identity" and d["matched"][0]["id"] == "P1#S1" and d["matched"][0]["effect"] == "Allow"


def test_group_policies():
    st = {"groups": {"g1": {"policies": [pol(allow())]}}}
    ok(ev([], principal={"groups": ["g1"]}, state=st))


def test_principals_from_state():
    st = {"principals": {USER: {"policies": [pol(allow())]}}}
    ok(E.evaluate({"principal": {"arn": USER, "type": "user"}, "action": "s3:GetObject", "resource": OBJ}, st))


# ---- conditions: strings
def c(op, key, val, **ctxkw):
    return pol(allow(Condition={op: {key: val}}))


@pytest.mark.parametrize("op,val,ctxv,res", [
    ("StringEquals", "a", "a", True), ("StringEquals", "a", "A", False), ("StringEquals", ["x", "a"], "a", True),
    ("StringNotEquals", "a", "b", True), ("StringNotEquals", "a", "a", False),
    ("StringEqualsIgnoreCase", "a", "A", True), ("StringNotEqualsIgnoreCase", "a", "A", False),
    ("StringLike", "pre*", "prefix", True), ("StringLike", "pre?ix", "prefix", True), ("StringLike", "pre*", "PREFIX", False),
    ("StringNotLike", "pre*", "other", True), ("StringNotLike", "pre*", "prefix", False),
])
def test_string_ops(op, val, ctxv, res):
    d = ev([c(op, "s3:prefix", val)], ctx={"s3:prefix": ctxv})
    ok(d, "allow" if res else "implicit_deny")


@pytest.mark.parametrize("op,val,ctxv,res", [
    ("NumericEquals", "5", "5", True), ("NumericEquals", "5", "6", False), ("NumericNotEquals", "5", "6", True),
    ("NumericLessThan", "5", "4", True), ("NumericLessThan", "5", "5", False), ("NumericLessThanEquals", "5", "5", True),
    ("NumericGreaterThan", "5", "6", True), ("NumericGreaterThanEquals", "5", "5", True), ("NumericGreaterThanEquals", "5", "4", False),
    ("NumericEquals", "5", "abc", False),
])
def test_numeric_ops(op, val, ctxv, res):
    ok(ev([c(op, "s3:max-keys", val)], ctx={"s3:max-keys": ctxv}), "allow" if res else "implicit_deny")


@pytest.mark.parametrize("op,val,ctxv,res", [
    ("DateLessThan", "2030-01-01T00:00:00Z", "2029-01-01T00:00:00Z", True),
    ("DateLessThan", "2030-01-01T00:00:00Z", "2031-01-01T00:00:00Z", False),
    ("DateGreaterThan", "2020-01-01T00:00:00Z", "2029-01-01T00:00:00Z", True),
    ("DateEquals", "2020-01-01T00:00:00Z", "2020-01-01T00:00:00Z", True),
    ("DateNotEquals", "2020-01-01T00:00:00Z", "2021-01-01T00:00:00Z", True),
    ("DateLessThanEquals", "2020-01-01T00:00:00Z", "2020-01-01T00:00:00Z", True),
    ("DateGreaterThanEquals", "1500000000", "2020-01-01T00:00:00Z", True),   # epoch seconds accepted
])
def test_date_ops(op, val, ctxv, res):
    ok(ev([c(op, "aws:CurrentTime", val)], ctx={"aws:CurrentTime": ctxv}), "allow" if res else "implicit_deny")


def test_current_time_defaults_to_now():
    ok(ev([c("DateGreaterThan", "aws:CurrentTime", "2020-01-01T00:00:00Z")]))


@pytest.mark.parametrize("op,val,ctxv,res", [
    ("Bool", "true", "true", True), ("Bool", "true", "false", False), ("Bool", "false", "false", True),
])
def test_bool(op, val, ctxv, res):
    ok(ev([c(op, "aws:SecureTransport", val)], ctx={"aws:SecureTransport": ctxv}), "allow" if res else "implicit_deny")


def test_bool_python_bool_in_context():
    ok(ev([c("Bool", "aws:SecureTransport", "true")], ctx={"aws:SecureTransport": True}))


@pytest.mark.parametrize("op,val,ip,res", [
    ("IpAddress", "10.0.0.0/8", "10.1.2.3", True), ("IpAddress", "10.0.0.0/8", "11.1.2.3", False),
    ("IpAddress", ["1.2.3.4", "10.0.0.0/8"], "1.2.3.4", True), ("NotIpAddress", "10.0.0.0/8", "11.0.0.1", True),
    ("NotIpAddress", "10.0.0.0/8", "10.0.0.1", False), ("IpAddress", "2001:db8::/32", "2001:db8::1", True),
    ("IpAddress", "10.0.0.0/8", "nope", False),
])
def test_ip(op, val, ip, res):
    ok(ev([c(op, "aws:SourceIp", val)], ctx={"aws:SourceIp": ip}), "allow" if res else "implicit_deny")


@pytest.mark.parametrize("op,val,arn,res", [
    ("ArnEquals", "arn:aws:iam::111111111111:role/dev", "arn:aws:iam::111111111111:role/dev", True),
    ("ArnLike", "arn:aws:iam::*:role/d*", "arn:aws:iam::111111111111:role/dev", True),
    ("ArnLike", "arn:aws:iam::*:role/x*", "arn:aws:iam::111111111111:role/dev", False),
    ("ArnNotLike", "arn:aws:iam::*:role/x*", "arn:aws:iam::111111111111:role/dev", True),
    ("ArnNotEquals", "arn:aws:s3:::a", "arn:aws:s3:::a", False),
    ("ArnLike", "arn:aws:s3:::a", "arn:aws:s3:::a:b:c", True) if False else ("ArnLike", "arn:aws:s3:::a", "arn:aws:s3:::a", True),
])
def test_arn(op, val, arn, res):
    ok(ev([c(op, "aws:SourceArn", val)], ctx={"aws:SourceArn": arn}), "allow" if res else "implicit_deny")


def test_binary_equals():
    ok(ev([c("BinaryEquals", "s3:x", "aGVsbG8=")], ctx={"s3:x": "aGVsbG8="}))
    ok(ev([c("BinaryEquals", "s3:x", "aGVsbG8=")], ctx={"s3:x": "d29ybGQ="}), "implicit_deny")


def test_null_true_and_false():
    ok(ev([c("Null", "aws:TokenIssueTime", "true")]))
    ok(ev([c("Null", "aws:TokenIssueTime", "false")]), "implicit_deny")
    ok(ev([c("Null", "aws:TokenIssueTime", "false")], ctx={"aws:TokenIssueTime": "x"}))


def test_missing_key_positive_false_negated_true():
    ok(ev([c("StringEquals", "s3:prefix", "a")]), "implicit_deny")
    ok(ev([c("StringNotEquals", "s3:prefix", "a")]))


def test_if_exists():
    ok(ev([c("StringEqualsIfExists", "s3:prefix", "a")]))
    ok(ev([c("StringEqualsIfExists", "s3:prefix", "a")], ctx={"s3:prefix": "b"}), "implicit_deny")


def test_for_any_value():
    p = c("ForAnyValue:StringEquals", "aws:TagKeys", ["a", "b"])
    ok(ev([p], ctx={"aws:TagKeys": ["b", "z"]}))
    ok(ev([p], ctx={"aws:TagKeys": ["y", "z"]}), "implicit_deny")
    ok(ev([p]), "implicit_deny")


def test_for_all_values():
    p = c("ForAllValues:StringEquals", "aws:TagKeys", ["a", "b"])
    ok(ev([p], ctx={"aws:TagKeys": ["a", "b"]}))
    ok(ev([p], ctx={"aws:TagKeys": ["a", "z"]}), "implicit_deny")
    ok(ev([p]))            # empty / missing -> vacuously true


def test_multiple_conditions_are_anded():
    p = pol(allow(Condition={"StringEquals": {"s3:prefix": "a"}, "Bool": {"aws:SecureTransport": "true"}}))
    ok(ev([p], ctx={"s3:prefix": "a", "aws:SecureTransport": "true"}))
    ok(ev([p], ctx={"s3:prefix": "a", "aws:SecureTransport": "false"}), "implicit_deny")


def test_deny_with_condition_only_when_true():
    p = pol(allow("s3:*"), deny("s3:*", Condition={"Bool": {"aws:SecureTransport": "false"}}))
    ok(ev([p], ctx={"aws:SecureTransport": "false"}), "explicit_deny")
    ok(ev([p], ctx={"aws:SecureTransport": "true"}))


def test_context_key_case_insensitive():
    ok(ev([c("StringEquals", "aws:SourceVpc", "vpc-1")], ctx={"AWS:sourcevpc": "vpc-1"}))


def test_missing_context_reported():
    d = ev([c("StringEquals", "s3:prefix", "a")])
    assert "s3:prefix" in d["missingContext"]


# ---- tags & variables
def test_principal_tag():
    p = c("StringEquals", "aws:PrincipalTag/team", "red")
    ok(ev([p], principal={"tags": {"team": "red"}}))
    ok(ev([p], principal={"tags": {"team": "blue"}}), "implicit_deny")


def test_resource_tag_from_request():
    p = c("StringEquals", "aws:ResourceTag/env", "prod")
    ok(ev([p], resource_tags={"env": "prod"}))
    ok(ev([p], resource_tags={"env": "dev"}), "implicit_deny")


def test_resource_tag_from_state():
    p = c("StringEquals", "aws:ResourceTag/env", "prod")
    ok(ev([p], state={"resource_tags": {OBJ: {"env": "prod"}}}))


def test_principal_tag_equals_resource_tag_variable():
    p = c("StringEquals", "aws:ResourceTag/team", "${aws:PrincipalTag/team}")
    ok(ev([p], principal={"tags": {"team": "red"}}, resource_tags={"team": "red"}))
    ok(ev([p], principal={"tags": {"team": "red"}}, resource_tags={"team": "blue"}), "implicit_deny")


def test_request_tag_and_tagkeys_derived():
    ok(ev([c("StringEquals", "aws:RequestTag/Owner", "me")], ctx={"aws:RequestTag/Owner": "me"}))
    p = c("ForAllValues:StringEquals", "aws:TagKeys", ["Owner"])
    ok(ev([p], ctx={"aws:RequestTag/Owner": "me"}))
    ok(ev([p], ctx={"aws:RequestTag/Owner": "me", "aws:RequestTag/X": "1"}), "implicit_deny")


def test_variable_username_in_resource():
    p = pol(allow("s3:*", "arn:aws:s3:::bkt/home/${aws:username}/*"))
    ok(ev([p], resource="arn:aws:s3:::bkt/home/alice/f"))
    ok(ev([p], resource="arn:aws:s3:::bkt/home/bob/f"), "implicit_deny")


def test_variable_in_condition_value():
    ok(ev([c("StringEquals", "s3:prefix", "${aws:username}/")], ctx={"s3:prefix": "alice/"}))


def test_variable_escapes_literal_star():
    p = pol(allow("s3:*", "arn:aws:s3:::bkt/a${*}b"))
    ok(ev([p], resource="arn:aws:s3:::bkt/a*b"))
    ok(ev([p], resource="arn:aws:s3:::bkt/axb"), "implicit_deny")


def test_unknown_variable_does_not_match():
    ok(ev([pol(allow("s3:*", "arn:aws:s3:::bkt/${aws:nokey}"))]), "implicit_deny")


def test_principal_arn_key_and_account_key():
    ok(ev([c("StringEquals", "aws:PrincipalAccount", ACCT)]))
    ok(ev([c("ArnLike", "aws:PrincipalArn", "arn:aws:iam::*:user/al*")]))


def test_session_principal_arn_is_role_arn():
    ok(ev([c("StringEquals", "aws:PrincipalArn", ROLE)], principal={"arn": SESS, "type": "role"}))


# ---- permissions boundary
def test_boundary_intersection_allows():
    ok(ev([pol(allow("s3:*"))], principal={"boundary": pol(allow("s3:Get*"))}))


def test_boundary_blocks_outside():
    ok(ev([pol(allow("s3:*"))], action="s3:PutObject", principal={"boundary": pol(allow("s3:Get*"))}), "implicit_deny")


def test_boundary_alone_grants_nothing():
    ok(ev([], principal={"boundary": pol(allow("s3:*"))}), "implicit_deny")


def test_boundary_explicit_deny():
    ok(ev([pol(allow("s3:*"))], principal={"boundary": pol(allow("*"), deny())}), "explicit_deny")


def test_boundary_failed_layer_reported():
    d = ev([pol(allow("s3:*"))], action="s3:PutObject", principal={"boundary": pol(allow("s3:Get*"))})
    assert d["failedLayer"] == "boundary"


# ---- session policies
def test_session_policy_restricts():
    pr = {"arn": SESS, "type": "role", "policies": [pol(allow("s3:*"))], "session_policy": [pol(allow("s3:GetObject"))]}
    ok(ev(principal=pr))
    ok(ev(principal=pr, action="s3:PutObject"), "implicit_deny")


def test_session_policy_alone_grants_nothing():
    ok(ev(principal={"arn": SESS, "type": "role", "session_policy": [pol(allow("s3:*"))]}), "implicit_deny")


def test_session_policy_deny():
    pr = {"arn": SESS, "type": "role", "policies": [pol(allow("s3:*"))], "session_policy": [pol(allow("*"), deny())]}
    ok(ev(principal=pr), "explicit_deny")


# ---- SCP / RCP
def test_scp_must_allow():
    st = {"scps": [[pol(allow("ec2:*"))]]}
    ok(ev([pol(allow("s3:*"))], state=st), "implicit_deny")


def test_scp_allows_and_identity_needed():
    st = {"scps": [[pol(allow("*"))]]}
    ok(ev([pol(allow("s3:*"))], state=st))
    ok(ev([], state=st), "implicit_deny")


def test_scp_deny():
    st = {"scps": [[pol(allow("*")), pol(deny("s3:*"))]]}
    ok(ev([pol(allow("s3:*"))], state=st), "explicit_deny")


def test_scp_every_level_must_allow():
    st = {"scps": [[pol(allow("*"))], [pol(allow("ec2:*"))]]}
    ok(ev([pol(allow("s3:*"))], state=st), "implicit_deny")


def test_scp_union_within_level():
    st = {"scps": [[pol(allow("ec2:*")), pol(allow("s3:*"))]]}
    ok(ev([pol(allow("s3:*"))], state=st))


def test_scp_per_account_dict():
    st = {"scps": {OTHER: [[pol(deny("*"))]], "*": [[pol(allow("*"))]]}}
    ok(ev([pol(allow("s3:*"))], state=st))


def test_rcp_must_allow_on_resource():
    st = {"rcps": [[pol(allow("sqs:*", principal=None) if False else allow("sqs:*"))]]}
    ok(ev([pol(allow("s3:*"))], state=st), "implicit_deny")


def test_rcp_deny():
    st = {"rcps": [[pol(allow("*")), pol(deny("s3:*"))]]}
    ok(ev([pol(allow("s3:*"))], state=st), "explicit_deny")


def test_scp_does_not_grant():
    st = {"scps": [[pol(allow("*"))]]}
    ok(ev([], state=st), "implicit_deny")


# ---- resource policies
def rp(principal, effect="Allow", action="s3:GetObject", **kw):
    return pol(dict({"Effect": effect, "Principal": principal, "Action": action, "Resource": "*"}, **kw))


def test_same_account_resource_policy_names_user_directly():
    d = ev([], resource_policy=rp({"AWS": USER}))
    ok(d)
    assert d["matched"][0]["source"] == "resource"


def test_same_account_resource_policy_account_root_needs_identity():
    ok(ev([], resource_policy=rp({"AWS": f"arn:aws:iam::{ACCT}:root"})), "implicit_deny")
    ok(ev([pol(allow())], resource_policy=rp({"AWS": f"arn:aws:iam::{ACCT}:root"})))


def test_resource_policy_account_id_form():
    ok(ev([pol(allow())], resource_policy=rp({"AWS": ACCT})))


def test_resource_policy_other_principal_no_effect():
    ok(ev([], resource_policy=rp({"AWS": f"arn:aws:iam::{ACCT}:user/bob"})), "implicit_deny")


def test_resource_policy_star_principal():
    ok(ev([], resource_policy=rp("*")))
    ok(ev([], resource_policy=rp({"AWS": "*"})))


def test_resource_policy_deny_overrides_identity_allow():
    ok(ev([pol(allow())], resource_policy=rp({"AWS": USER}, "Deny")), "explicit_deny")


def test_resource_policy_not_principal_deny():
    p = rp(None, "Deny")
    p["Statement"][0].pop("Principal")
    p["Statement"][0]["NotPrincipal"] = {"AWS": f"arn:aws:iam::{ACCT}:user/bob"}
    ok(ev([pol(allow())], resource_policy=p), "explicit_deny")


def test_resource_policy_condition():
    p = rp({"AWS": USER}, Condition={"IpAddress": {"aws:SourceIp": "10.0.0.0/8"}})
    ok(ev([], resource_policy=p, ctx={"aws:SourceIp": "10.0.0.1"}))
    ok(ev([], resource_policy=p, ctx={"aws:SourceIp": "8.8.8.8"}), "implicit_deny")


def test_resource_policy_from_state():
    ok(ev([], state={"resource_policies": {OBJ: rp({"AWS": USER})}}))


def test_resource_policy_role_grant_for_session():
    pr = {"arn": SESS, "type": "role", "account": ACCT}
    ok(ev(principal=pr, resource_policy=rp({"AWS": ROLE})))


def test_resource_policy_user_grant_bypasses_boundary():
    ok(ev([], principal={"boundary": pol(allow("ec2:*"))}, resource_policy=rp({"AWS": USER})))


def test_resource_policy_role_grant_limited_by_boundary():
    pr = {"arn": SESS, "type": "role", "boundary": pol(allow("ec2:*"))}
    ok(ev(principal=pr, resource_policy=rp({"AWS": ROLE})), "implicit_deny")


def test_resource_policy_session_grant_bypasses_session_policy():
    pr = {"arn": SESS, "type": "role", "session_policy": [pol(allow("ec2:*"))]}
    ok(ev(principal=pr, resource_policy=rp({"AWS": SESS})))


def test_cross_account_needs_both():
    other = f"arn:aws:iam::{OTHER}:user/eve"
    pr = {"arn": other, "type": "user", "account": OTHER}
    both = ev([pol(allow())], principal=pr, resource_account=ACCT, resource_policy=rp({"AWS": other}))
    ok(both)
    ok(ev([], principal=pr, resource_account=ACCT, resource_policy=rp({"AWS": other})), "implicit_deny")
    ok(ev([pol(allow())], principal=pr, resource_account=ACCT), "implicit_deny")


def test_cross_account_root_principal_grant():
    other = f"arn:aws:iam::{OTHER}:user/eve"
    pr = {"arn": other, "type": "user", "account": OTHER}
    ok(ev([pol(allow())], principal=pr, resource_account=ACCT, resource_policy=rp({"AWS": f"arn:aws:iam::{OTHER}:root"})))


def test_cross_account_wrong_account_in_policy():
    other = f"arn:aws:iam::{OTHER}:user/eve"
    pr = {"arn": other, "type": "user", "account": OTHER}
    ok(ev([pol(allow())], principal=pr, resource_account=ACCT, resource_policy=rp({"AWS": f"arn:aws:iam::{ACCT}:root"})), "implicit_deny")


def test_cross_account_boundary_applies():
    other = f"arn:aws:iam::{OTHER}:user/eve"
    pr = {"arn": other, "type": "user", "account": OTHER, "boundary": pol(allow("ec2:*"))}
    ok(ev([pol(allow())], principal=pr, resource_account=ACCT, resource_policy=rp({"AWS": other})), "implicit_deny")


def test_service_principal():
    pr = {"arn": "", "type": "service", "service": "sns.amazonaws.com"}
    ok(ev(principal=pr, resource_policy=rp({"Service": "sns.amazonaws.com"})))
    ok(ev(principal=pr, resource_policy=rp({"Service": "sqs.amazonaws.com"})), "implicit_deny")


def test_anonymous_only_star():
    pr = {"arn": "", "type": "anonymous"}
    ok(ev(principal=pr, resource_policy=rp("*")))
    ok(ev(principal=pr, resource_policy=rp({"AWS": USER})), "implicit_deny")


# ---- root
def test_root_user_unrestricted_by_identity_but_scp_applies():
    pr = {"arn": f"arn:aws:iam::{ACCT}:root", "type": "root"}
    ok(ev(principal=pr))
    ok(ev(principal=pr, state={"scps": [[pol(allow("ec2:*"))]]}), "implicit_deny")
    ok(ev(principal=pr, resource_policy=rp({"AWS": f"arn:aws:iam::{ACCT}:root"}, "Deny")), "explicit_deny")


# ---- helper
def test_simulate_helper_shapes():
    r = E.simulate({"arn": USER, "type": "user", "policies": [pol(allow("s3:Get*"))]}, ["s3:GetObject", "s3:PutObject"], [OBJ])
    assert [x["EvalDecision"] for x in r] == ["allowed", "implicitDeny"]
    assert r[0]["MatchedStatements"][0]["Source"] == "identity"


def test_simulate_helper_explicit_deny_and_missing():
    r = E.simulate({"arn": USER, "type": "user", "policies": [pol(allow(Condition={"StringEquals": {"s3:prefix": "x"}}))]},
                   ["s3:GetObject"], [OBJ])
    assert r[0]["EvalDecision"] == "implicitDeny" and r[0]["MissingContextValues"] == ["s3:prefix"]
    r = E.simulate({"arn": USER, "type": "user", "policies": [pol(allow(), deny())]}, ["s3:GetObject"], [OBJ])
    assert r[0]["EvalDecision"] == "explicitDeny"
