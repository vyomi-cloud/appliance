from google.cloud import compute_v1 as cv

import gcp

client = gcp.rest(cv.SecurityPoliciesClient)
policy = cv.SecurityPolicy(name="facilities-armor", description="facilities edge policy", rules=[
    cv.SecurityPolicyRule(priority=1000, action="deny(403)", match=cv.SecurityPolicyRuleMatcher(expr=cv.Expr(expression="evaluatePreconfiguredExpr('xss-stable')"))),
    cv.SecurityPolicyRule(priority=2147483647, action="allow", match=cv.SecurityPolicyRuleMatcher(versioned_expr="SRC_IPS_V1", config=cv.SecurityPolicyRuleMatcherConfig(src_ip_ranges=["*"])))])
try:
    client.insert(project=gcp.PROJECT, security_policy_resource=policy)
except Exception as e:
    if "already exists" not in str(e).lower() and "409" not in str(e):
        raise
got = client.get(project=gcp.PROJECT, security_policy="facilities-armor")
print("policy", got.name, "with", len(got.rules), "rules; first rule:", got.rules[0].match.expr.expression)
assert any("xss" in r.match.expr.expression for r in got.rules)
