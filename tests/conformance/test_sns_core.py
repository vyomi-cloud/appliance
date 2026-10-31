"""SNS core conformance — the full operation surface on the in-memory substrate
(host + Pyodide). Mirrors what the AWS SDK sends on the Query wire."""
import json
import re

try:
    from core.messaging_store import InMemoryMessagingStore
    from core import sqs_core as sqs, sns_core as sns
except ImportError:  # pragma: no cover - Pyodide flat layout
    from messaging_store import InMemoryMessagingStore  # type: ignore
    import sqs_core as sqs  # type: ignore
    import sns_core as sns  # type: ignore

ACCT = "123456789012"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _v(xml, tag):
    m = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.S)
    return m.group(1) if m else ""


def run(store=None):
    st = store or InMemoryMessagingStore()
    call = lambda a, **p: sns.dispatch(st, dict(p, Action=a))
    err = lambda r, code: r.status >= 400 and f"<Code>{code}</Code>" in r.body
    SQS = "AmazonSQS."

    # topics
    arn = _v(call("CreateTopic", Name="orders").body, "TopicArn")
    _check("create topic arn", arn == f"arn:aws:sns:us-east-1:{ACCT}:orders")
    _check("create is idempotent", _v(call("CreateTopic", Name="orders").body, "TopicArn") == arn)
    _check("bad name rejected", err(call("CreateTopic", Name="bad name!"), "InvalidParameter"))
    _check("fifo name needs suffix", err(call("CreateTopic", Name="x", **{"Attributes.entry.1.key": "FifoTopic", "Attributes.entry.1.value": "true"}), "InvalidParameter"))
    _check("same name, different attrs", err(call("CreateTopic", Name="orders", **{"Attributes.entry.1.key": "DisplayName", "Attributes.entry.1.value": "Z"}), "InvalidParameter"))
    ta = call("GetTopicAttributes", TopicArn=arn).body
    _check("topic attributes", f"<key>Owner</key><value>{ACCT}</value>" in ta and "<key>Policy</key>" in ta and "SubscriptionsConfirmed" in ta)
    _check("get missing topic NotFound", call("GetTopicAttributes", TopicArn=arn + "x").status == 404)
    _check("set DisplayName", call("SetTopicAttributes", TopicArn=arn, AttributeName="DisplayName", AttributeValue="Orders").status == 200
           and "<value>Orders</value>" in call("GetTopicAttributes", TopicArn=arn).body)
    _check("set bad attribute", err(call("SetTopicAttributes", TopicArn=arn, AttributeName="Nope", AttributeValue="1"), "InvalidParameter"))
    _check("set Policy must be JSON", err(call("SetTopicAttributes", TopicArn=arn, AttributeName="Policy", AttributeValue="{bad"), "InvalidParameter"))
    _check("add permission", call("AddPermission", TopicArn=arn, Label="share", **{"AWSAccountId.member.1": "111122223333", "ActionName.member.1": "Publish"}).status == 200
           and "111122223333" in call("GetTopicAttributes", TopicArn=arn).body)
    _check("remove permission", call("RemovePermission", TopicArn=arn, Label="share").status == 200
           and "111122223333" not in call("GetTopicAttributes", TopicArn=arn).body)
    _check("remove missing permission", err(call("RemovePermission", TopicArn=arn, Label="share"), "InvalidParameter"))

    # tags + data protection
    call("TagResource", ResourceArn=arn, **{"Tags.member.1.Key": "env", "Tags.member.1.Value": "dev"})
    _check("tags listed", "<Key>env</Key><Value>dev</Value>" in call("ListTagsForResource", ResourceArn=arn).body)
    call("UntagResource", ResourceArn=arn, **{"TagKeys.member.1": "env"})
    _check("untag", "<Key>env</Key>" not in call("ListTagsForResource", ResourceArn=arn).body)
    _check("tags on missing resource", err(call("ListTagsForResource", ResourceArn=arn + "x"), "ResourceNotFound"))
    pol = json.dumps({"Name": "p", "Version": "2021-06-01", "Statement": [{"DataDirection": "Inbound", "Principal": ["*"], "DataIdentifier": []}]})
    _check("data protection roundtrip", call("PutDataProtectionPolicy", ResourceArn=arn, DataProtectionPolicy=pol).status == 200
           and json.loads(_v(call("GetDataProtectionPolicy", ResourceArn=arn).body, "DataProtectionPolicy").replace("&quot;", '"'))["Name"] == "p")

    # subscriptions
    sqs.dispatch(st, SQS + "CreateQueue", {"QueueName": "q1"})
    q1_url = sqs.dispatch(st, SQS + "GetQueueUrl", {"QueueName": "q1"}).body["QueueUrl"]
    q1_arn = st.get_queue("q1")["queue_arn"]
    sub = _v(call("Subscribe", TopicArn=arn, Protocol="sqs", Endpoint=q1_arn).body, "SubscriptionArn")
    _check("sqs sub confirmed immediately", sub.startswith(arn + ":"))
    _check("subscribe idempotent", _v(call("Subscribe", TopicArn=arn, Protocol="sqs", Endpoint=q1_arn).body, "SubscriptionArn") == sub)
    _check("bad protocol", err(call("Subscribe", TopicArn=arn, Protocol="carrier-pigeon", Endpoint="x"), "InvalidParameter"))
    _check("bad endpoint for protocol", err(call("Subscribe", TopicArn=arn, Protocol="sqs", Endpoint="nope"), "InvalidParameter"))
    pend = _v(call("Subscribe", TopicArn=arn, Protocol="email", Endpoint="dev@example.com").body, "SubscriptionArn")
    _check("email pending confirmation", pend == "pending confirmation")
    _check("pending listed", "PendingConfirmation" in call("ListSubscriptionsByTopic", TopicArn=arn).body)
    _check("counts", "<key>SubscriptionsPending</key><value>1</value>" in call("GetTopicAttributes", TopicArn=arn).body)
    tok = next(d["token"] for d in st.sns["deliveries"] if d["kind"] == "SubscriptionConfirmation")
    _check("bad token", err(call("ConfirmSubscription", TopicArn=arn, Token="zzz"), "InvalidParameter"))
    conf = _v(call("ConfirmSubscription", TopicArn=arn, Token=tok).body, "SubscriptionArn")
    _check("confirm returns arn", conf.startswith(arn + ":"))
    _check("confirmed attribute", "<key>PendingConfirmation</key><value>false</value>" in call("GetSubscriptionAttributes", SubscriptionArn=conf).body)
    _check("list subscriptions", call("ListSubscriptions").body.count("<member>") == 2)
    _check("sub attrs raw delivery", call("SetSubscriptionAttributes", SubscriptionArn=sub, AttributeName="RawMessageDelivery", AttributeValue="true").status == 200)
    _check("sub bad attr", err(call("SetSubscriptionAttributes", SubscriptionArn=sub, AttributeName="Nope", AttributeValue="1"), "InvalidParameter"))

    # publish
    r = call("Publish", TopicArn=arn, Message="hello", Subject="greeting", **{
        "MessageAttributes.entry.1.Name": "color", "MessageAttributes.entry.1.Value.DataType": "String",
        "MessageAttributes.entry.1.Value.StringValue": "red"})
    _check("publish id", bool(_v(r.body, "MessageId")))
    got = sqs.dispatch(st, SQS + "ReceiveMessage", {"QueueUrl": q1_url, "MessageAttributeNames": ["All"]}).body["Messages"]
    _check("raw delivery body is the message", got[0]["Body"] == "hello")
    sqs.dispatch(st, SQS + "DeleteMessage", {"QueueUrl": q1_url, "ReceiptHandle": got[0]["ReceiptHandle"]})
    call("SetSubscriptionAttributes", SubscriptionArn=sub, AttributeName="RawMessageDelivery", AttributeValue="false")
    call("Publish", TopicArn=arn, Message="hi", Subject="s")
    env = json.loads(sqs.dispatch(st, SQS + "ReceiveMessage", {"QueueUrl": q1_url}).body["Messages"][0]["Body"])
    _check("envelope", env["Type"] == "Notification" and env["Subject"] == "s" and env["Message"] == "hi")
    _check("email delivery logged", any(d["kind"] == "Notification" and d["protocol"] == "email" and d["message"] == "hi" for d in st.sns["deliveries"]))
    _check("empty message", err(call("Publish", TopicArn=arn, Message=""), "InvalidParameter"))
    _check("no destination", err(call("Publish", Message="x"), "InvalidParameter"))
    _check("json structure needs default", err(call("Publish", TopicArn=arn, Message='{"a":"b"}', MessageStructure="json"), "InvalidParameter"))
    _check("too long", err(call("Publish", TopicArn=arn, Message="x" * 262145), "InvalidParameter"))
    call("Publish", TopicArn=arn, Message=json.dumps({"default": "d", "sqs": "for-sqs"}), MessageStructure="json")
    env = json.loads(sqs.dispatch(st, SQS + "ReceiveMessage", {"QueueUrl": q1_url, "MaxNumberOfMessages": 10}).body["Messages"][-1]["Body"])
    _check("json structure picks the sqs entry", env["Message"] == "for-sqs")

    # body-scope filter policy
    sqs.dispatch(st, SQS + "CreateQueue", {"QueueName": "q2"})
    q2_arn = st.get_queue("q2")["queue_arn"]
    s2 = _v(call("Subscribe", TopicArn=arn, Protocol="sqs", Endpoint=q2_arn).body, "SubscriptionArn")
    call("SetSubscriptionAttributes", SubscriptionArn=s2, AttributeName="FilterPolicyScope", AttributeValue="MessageBody")
    call("SetSubscriptionAttributes", SubscriptionArn=s2, AttributeName="FilterPolicy", AttributeValue=json.dumps({"order": {"kind": ["rush"]}}))
    call("Publish", TopicArn=arn, Message=json.dumps({"order": {"kind": "rush"}}))
    call("Publish", TopicArn=arn, Message=json.dumps({"order": {"kind": "slow"}}))
    _check("body filter policy delivers only the match", len(st.get_queue("q2")["messages"]) == 1)

    # data protection policy — Deny / Deidentify / Audit really enforced on Publish
    sqs.dispatch(st, SQS + "CreateQueue", {"QueueName": "q3"})
    q3_url = sqs.dispatch(st, SQS + "GetQueueUrl", {"QueueName": "q3"}).body["QueueUrl"]
    q3_arn = st.get_queue("q3")["queue_arn"]
    s3sub = _v(call("Subscribe", TopicArn=arn, Protocol="sqs", Endpoint=q3_arn).body, "SubscriptionArn")
    call("SetSubscriptionAttributes", SubscriptionArn=s3sub, AttributeName="RawMessageDelivery", AttributeValue="true")
    email_id = "arn:aws:dataprotection::aws:data-identifier/EmailAddress"
    deny_policy = json.dumps({"Name": "p", "Version": "2021-06-01", "Statement": [
        {"Sid": "deny-email", "DataDirection": "Inbound", "Principal": ["*"],
         "DataIdentifier": [email_id], "Operation": {"Deny": {}}}]})
    call("PutDataProtectionPolicy", ResourceArn=arn, DataProtectionPolicy=deny_policy)
    _check("data protection denies publish containing an email", err(call("Publish", TopicArn=arn, Message="reach me at a@b.com"), "AccessDenied"))
    _check("data protection allows publish without a match", call("Publish", TopicArn=arn, Message="no pii here").status == 200)
    sqs.dispatch(st, SQS + "ReceiveMessage", {"QueueUrl": q3_url})  # drain

    mask_policy = json.dumps({"Name": "p", "Version": "2021-06-01", "Statement": [
        {"Sid": "mask-email", "DataDirection": "Inbound", "Principal": ["*"], "DataIdentifier": [email_id],
         "Operation": {"Deidentify": {"MaskConfig": {"MaskWithCharacter": "#"}}}}]})
    call("PutDataProtectionPolicy", ResourceArn=arn, DataProtectionPolicy=mask_policy)
    call("Publish", TopicArn=arn, Message="reach me at a@b.com")
    masked = sqs.dispatch(st, SQS + "ReceiveMessage", {"QueueUrl": q3_url}).body["Messages"][0]["Body"]
    _check("data protection deidentify masks the match", "a@b.com" not in masked and "#" in masked and "reach me at" in masked)

    audit_policy = json.dumps({"Name": "p", "Version": "2021-06-01", "Statement": [
        {"Sid": "audit-email", "DataDirection": "Inbound", "Principal": ["*"],
         "DataIdentifier": [email_id], "Operation": {"Audit": {}}}]})
    call("PutDataProtectionPolicy", ResourceArn=arn, DataProtectionPolicy=audit_policy)
    call("Publish", TopicArn=arn, Message="reach me at a@b.com")
    _check("data protection audit records a finding without blocking", any(d["kind"] == "DataProtectionAudit" for d in st.sns["deliveries"]))
    call("PutDataProtectionPolicy", ResourceArn=arn, DataProtectionPolicy=json.dumps({"Name": "p", "Version": "2021-06-01", "Statement": []}))

    # batch
    b = call("PublishBatch", TopicArn=arn, **{
        "PublishBatchRequestEntries.member.1.Id": "a", "PublishBatchRequestEntries.member.1.Message": "m1",
        "PublishBatchRequestEntries.member.2.Id": "b", "PublishBatchRequestEntries.member.2.Message": ""}).body
    _check("batch partial success", "<Successful><member><Id>a</Id>" in b and "<Failed><member><Id>b</Id>" in b)
    _check("batch ids distinct", err(call("PublishBatch", TopicArn=arn, **{
        "PublishBatchRequestEntries.member.1.Id": "a", "PublishBatchRequestEntries.member.1.Message": "m",
        "PublishBatchRequestEntries.member.2.Id": "a", "PublishBatchRequestEntries.member.2.Message": "m"}), "BatchEntryIdsNotDistinct"))
    _check("batch empty", err(call("PublishBatch", TopicArn=arn), "EmptyBatchRequest"))

    # FIFO
    fa = _v(call("CreateTopic", Name="ev.fifo", **{"Attributes.entry.1.key": "FifoTopic", "Attributes.entry.1.value": "true"}).body, "TopicArn")
    _check("fifo attrs", "<key>FifoTopic</key><value>true</value>" in call("GetTopicAttributes", TopicArn=fa).body)
    _check("fifo needs group", err(call("Publish", TopicArn=fa, Message="m", MessageDeduplicationId="d"), "InvalidParameter"))
    _check("fifo needs dedup", err(call("Publish", TopicArn=fa, Message="m", MessageGroupId="g"), "InvalidParameter"))
    p1 = call("Publish", TopicArn=fa, Message="m", MessageGroupId="g", MessageDeduplicationId="d1").body
    p2 = call("Publish", TopicArn=fa, Message="m", MessageGroupId="g", MessageDeduplicationId="d1").body
    _check("fifo dedup returns same id + sequence", _v(p1, "MessageId") == _v(p2, "MessageId") and _v(p1, "SequenceNumber"))
    _check("group on standard topic rejected", err(call("Publish", TopicArn=arn, Message="m", MessageGroupId="g"), "InvalidParameter"))

    # platform applications + endpoints
    _check("platform needs credential", err(call("CreatePlatformApplication", Name="app", Platform="GCM"), "InvalidParameter"))
    _check("bad platform", err(call("CreatePlatformApplication", Name="app", Platform="PIGEON", **{"Attributes.entry.1.key": "PlatformCredential", "Attributes.entry.1.value": "k"}), "InvalidParameter"))
    app = _v(call("CreatePlatformApplication", Name="app", Platform="GCM", **{"Attributes.entry.1.key": "PlatformCredential", "Attributes.entry.1.value": "k"}).body, "PlatformApplicationArn")
    _check("app arn", app == f"arn:aws:sns:us-east-1:{ACCT}:app/GCM/app")
    pa = call("GetPlatformApplicationAttributes", PlatformApplicationArn=app).body
    _check("credential never echoed", "PlatformCredential" not in pa and "<key>Enabled</key>" in pa)
    ep = _v(call("CreatePlatformEndpoint", PlatformApplicationArn=app, Token="tok-1", CustomUserData="u1").body, "EndpointArn")
    _check("endpoint arn", ep.startswith(f"arn:aws:sns:us-east-1:{ACCT}:endpoint/GCM/app/"))
    _check("endpoint idempotent by token", _v(call("CreatePlatformEndpoint", PlatformApplicationArn=app, Token="tok-1", CustomUserData="u1").body, "EndpointArn") == ep)
    _check("endpoint same token, different attrs", err(call("CreatePlatformEndpoint", PlatformApplicationArn=app, Token="tok-1", CustomUserData="other"), "InvalidParameter"))
    _check("list endpoints", ep in call("ListEndpointsByPlatformApplication", PlatformApplicationArn=app).body)
    _check("publish to endpoint", bool(_v(call("Publish", TargetArn=ep, Message="push").body, "MessageId")))
    call("SetEndpointAttributes", EndpointArn=ep, **{"Attributes.entry.1.key": "Enabled", "Attributes.entry.1.value": "false"})
    _check("disabled endpoint", err(call("Publish", TargetArn=ep, Message="push"), "EndpointDisabled"))
    _check("list apps", app in call("ListPlatformApplications").body)
    call("DeletePlatformApplication", PlatformApplicationArn=app)
    _check("deleting app removes endpoints", err(call("GetEndpointAttributes", EndpointArn=ep), "NotFound"))

    # SMS
    _check("sms attrs", call("SetSMSAttributes", **{"attributes.entry.1.key": "DefaultSMSType", "attributes.entry.1.value": "Transactional"}).status == 200
           and "<value>Transactional</value>" in call("GetSMSAttributes").body)
    _check("sms bad attr", err(call("SetSMSAttributes", **{"attributes.entry.1.key": "Nope", "attributes.entry.1.value": "x"}), "InvalidParameter"))
    _check("sandbox status", _v(call("GetSMSSandboxAccountStatus").body, "IsInSandbox") == "true")
    call("CreateSMSSandboxPhoneNumber", PhoneNumber="+15555550100")
    _check("unverified sandbox number blocked", err(call("Publish", PhoneNumber="+15555550100", Message="hi"), "InvalidParameter"))
    _check("wrong otp", err(call("VerifySMSSandboxPhoneNumber", PhoneNumber="+15555550100", OneTimePassword="000000"), "VerificationException"))
    otp = next(d["token"] for d in st.sns["deliveries"] if d["kind"] == "SMSSandboxVerification")
    call("VerifySMSSandboxPhoneNumber", PhoneNumber="+15555550100", OneTimePassword=otp)
    _check("verified listed", "<Status>Verified</Status>" in call("ListSMSSandboxPhoneNumbers").body)
    _check("sms publish", bool(_v(call("Publish", PhoneNumber="+15555550100", Message="hi").body, "MessageId")))
    call("SetSMSAttributes", **{"attributes.entry.1.key": "MonthlySpendLimit", "attributes.entry.1.value": "0"})
    _check("sms spend limit blocks publish once reached", err(call("Publish", PhoneNumber="+15555550100", Message="hi"), "Throttling"))
    call("SetSMSAttributes", **{"attributes.entry.1.key": "MonthlySpendLimit", "attributes.entry.1.value": "10"})
    _check("raising the spend limit allows publish again", bool(_v(call("Publish", PhoneNumber="+15555550100", Message="hi").body, "MessageId")))
    _check("opt-out check", _v(call("CheckIfPhoneNumberIsOptedOut", phoneNumber="+15555550100").body, "isOptedOut") == "false")
    _check("list opted out", "<phoneNumbers>" in call("ListPhoneNumbersOptedOut").body)
    _check("opt in", call("OptInPhoneNumber", phoneNumber="+15555550100").status == 200)
    _check("origination numbers", call("ListOriginationNumbers").status == 200)
    call("DeleteSMSSandboxPhoneNumber", PhoneNumber="+15555550100")
    _check("delete sandbox number twice", err(call("DeleteSMSSandboxPhoneNumber", PhoneNumber="+15555550100"), "ResourceNotFound"))

    # delivery status logging — real CloudWatch Logs feedback for SQS success/failure
    try:
        from core.logs_core import LogsStore
    except ImportError:  # pragma: no cover - Pyodide flat layout
        from logs_core import LogsStore  # type: ignore
    st.logs_store = LogsStore()
    call("SetTopicAttributes", TopicArn=arn, AttributeName="SQSSuccessFeedbackRoleArn",
         AttributeValue="arn:aws:iam::123456789012:role/Success")
    call("SetTopicAttributes", TopicArn=arn, AttributeName="SQSFailureFeedbackRoleArn",
         AttributeValue="arn:aws:iam::123456789012:role/Failure")
    call("Publish", TopicArn=arn, Message="feedback-ok")
    ok_group = st.logs_store.log_groups.get(f"sns/us-east-1/{ACCT}/orders/Success")
    _check("success feedback log group created", ok_group is not None)
    ok_stream = ok_group["streams"].get(q1_arn.replace(":", "_")) if ok_group else None
    ok_evt = json.loads(ok_stream["events"][-1]["message"]) if ok_stream and ok_stream["events"] else {}
    _check("success feedback event", ok_evt.get("status") == "SUCCESS" and ok_evt["delivery"]["destination"] == q1_arn)

    ghost_arn = "arn:aws:sqs:us-east-1:123456789012:ghost"
    gsub = _v(call("Subscribe", TopicArn=arn, Protocol="sqs", Endpoint=ghost_arn).body, "SubscriptionArn")
    call("Publish", TopicArn=arn, Message="feedback-fail")
    fail_group = st.logs_store.log_groups.get(f"sns/us-east-1/{ACCT}/orders/Failure")
    _check("failure feedback log group created", fail_group is not None)
    fail_stream = fail_group["streams"].get(ghost_arn.replace(":", "_")) if fail_group else None
    fail_evt = json.loads(fail_stream["events"][-1]["message"]) if fail_stream and fail_stream["events"] else {}
    _check("failure feedback event", fail_evt.get("status") == "FAILURE" and fail_evt["delivery"]["destination"] == ghost_arn)
    call("SetTopicAttributes", TopicArn=arn, AttributeName="SQSSuccessFeedbackRoleArn", AttributeValue="")
    call("SetTopicAttributes", TopicArn=arn, AttributeName="SQSFailureFeedbackRoleArn", AttributeValue="")

    # unsubscribe + delete
    _check("unsubscribe", call("Unsubscribe", SubscriptionArn=sub).status == 200)
    _check("unsubscribe missing", err(call("Unsubscribe", SubscriptionArn=sub), "NotFound"))
    _check("deleted count", "<key>SubscriptionsDeleted</key><value>1</value>" in call("GetTopicAttributes", TopicArn=arn).body)
    _check("delete topic", call("DeleteTopic", TopicArn=arn).status == 200)
    _check("delete is idempotent", call("DeleteTopic", TopicArn=arn).status == 200)
    _check("list topics", arn not in call("ListTopics").body and fa in call("ListTopics").body)

    # console REST
    cd = lambda m, p, b=None: sns.console_dispatch(st, m, "/api/aws/sns/" + p, {}, b)
    c, v = cd("POST", "topics", {"name": "MyTopic", "type": "Standard", "display_name": "My topic"})
    _check("console create", c == 200 and v["arn"].endswith(":MyTopic") and v["display_name"] == "My topic" and v["type"] == "Standard")
    c, v = cd("POST", "topics", {"name": "Jobs", "type": "FIFO", "display_name": "Not set"})
    _check("console fifo topic", c == 200 and v["name"] == "Jobs.fifo" and v["type"] == "FIFO" and v["display_name"] == "Not set")
    _check("console fifo publish", cd("POST", "topics/Jobs.fifo/publish", {"message": "j1"})[0] == 200)
    _check("console subscribe", cd("POST", "topics/MyTopic/subscriptions", {"protocol": "email", "endpoint": "a@b.co"})[0] == 200)
    c, subs = cd("GET", "subscriptions")
    _check("console subs have status", subs["items"][0]["status"] == "Pending confirmation")
    _check("console confirm", cd("POST", "subscriptions/" + subs["items"][0]["name"] + "/confirm")[0] == 200)
    _check("console message log", cd("GET", "deliveries")[1]["count"] >= 1)
    _check("console missing topic 404", cd("GET", "topics/nope")[0] == 404)
    _check("console delete", cd("DELETE", "topics/MyTopic")[0] == 200)

    print("\nRESULT: PASS — SNS core conforms.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
