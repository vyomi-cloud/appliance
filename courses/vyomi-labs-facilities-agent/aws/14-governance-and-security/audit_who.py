import iamkit

recs = iamkit._admin("GET", "/api/iam/aws/audit?limit=500")["records"]
sends = [r for r in recs if r["action"] == "states:SendTaskSuccess"]
allowed = [r for r in sends if r["decision"] == "allow" and "duty-manager" in r["principal"]]
refused = [r for r in sends if r["decision"] == "deny" and "facilities-agent" in r["principal"]]
if not allowed or not refused:
    raise SystemExit("missing prerequisite: run chapter 5 'Real approver identity and no self-approval' first "
                     "(found %d approvals by the duty manager and %d refused self-approvals)" % (len(allowed), len(refused)))
approver, requester = allowed[-1]["principal"], refused[-1]["principal"]
assert approver != requester, "approver and requester must be different identities"
print("approved by :", approver, "at", allowed[-1]["time"])
print("refused     :", requester, "tried to approve its own request at", refused[-1]["time"])
denials = [r for r in recs if r["decision"] == "deny"]
print("every denial in the trail names a principal and an action:", all(r["principal"] and r["action"] for r in denials), "(%d denials)" % len(denials))
print("identity audit verified")
