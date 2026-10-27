"""SES v2 engine conformance — host (CPython).

Drives core/sesv2_core.py on the native REST-JSON wire through a REAL boto3 `sesv2`
client whose transport is short-circuited into `dispatch` (so request serialization and
response parsing are the SDK's, validated against the botocore model), plus the console
REST view built on the same engine.
"""
import json
import urllib.parse

import boto3
from botocore.awsrequest import AWSResponse
from botocore.config import Config
from botocore.exceptions import ClientError

from core import sesv2_core as ses


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _client(store):
    c = boto3.client("sesv2", region_name="us-east-1", aws_access_key_id="a", aws_secret_access_key="b",
                     endpoint_url="http://sesv2.test", config=Config(retries={"max_attempts": 0}))

    def hook(request, **kw):
        u = urllib.parse.urlsplit(request.url)
        q = {}
        for k, v in urllib.parse.parse_qsl(u.query, keep_blank_values=True):
            if k in q:
                q[k] = (q[k] if isinstance(q[k], list) else [q[k]]) + [v]
            else:
                q[k] = v
        body = request.body or b""
        if isinstance(body, str):
            body = body.encode()
        r = ses.dispatch(store, request.method, u.path, q, dict(request.headers), body)
        resp = AWSResponse(request.url, r.status, {**r.headers, "content-type": r.media_type}, None)
        resp._content = r.body
        return resp

    c.meta.events.register("before-send.sesv2.*", hook)
    return c


def _err(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except ClientError as e:
        return e.response["Error"]["Code"], e.response["ResponseMetadata"]["HTTPStatusCode"]
    raise AssertionError("expected ClientError")


def run(store=None):
    s = store or ses.SesV2Store()
    c = _client(s)

    # identities
    r = c.create_email_identity(EmailIdentity="dev@example.com", Tags=[{"Key": "env", "Value": "dev"}])
    _check("create email identity", r["IdentityType"] == "EMAIL_ADDRESS" and r["VerifiedForSendingStatus"])
    r = c.create_email_identity(EmailIdentity="example.org")
    _check("domain identity has 3 DKIM tokens", r["IdentityType"] == "DOMAIN" and len(r["DkimAttributes"]["Tokens"]) == 3)
    _check("duplicate identity", _err(c.create_email_identity, EmailIdentity="dev@example.com") == ("AlreadyExistsException", 400))
    _check("invalid identity", _err(c.create_email_identity, EmailIdentity="not valid")[0] == "BadRequestException")
    g = c.get_email_identity(EmailIdentity="dev@example.com")
    _check("get identity + tags", g["VerificationStatus"] == "SUCCESS" and g["Tags"] == [{"Key": "env", "Value": "dev"}])
    _check("missing identity 404", _err(c.get_email_identity, EmailIdentity="nope@example.com") == ("NotFoundException", 404))
    ids = c.list_email_identities()["EmailIdentities"]
    _check("list identities", [i["IdentityName"] for i in ids] == ["dev@example.com", "example.org"])
    p1 = c.list_email_identities(PageSize=1)
    p2 = c.list_email_identities(PageSize=1, NextToken=p1["NextToken"])
    _check("pagination", len(p1["EmailIdentities"]) == 1 and p2["EmailIdentities"][0]["IdentityName"] == "example.org" and "NextToken" not in p2)
    c.put_email_identity_mail_from_attributes(EmailIdentity="example.org", MailFromDomain="mail.example.org", BehaviorOnMxFailure="REJECT_MESSAGE")
    _check("mail-from", c.get_email_identity(EmailIdentity="example.org")["MailFromAttributes"]["MailFromDomain"] == "mail.example.org")
    c.put_email_identity_feedback_attributes(EmailIdentity="example.org", EmailForwardingEnabled=False)
    _check("feedback", c.get_email_identity(EmailIdentity="example.org")["FeedbackForwardingStatus"] is False)
    c.put_email_identity_dkim_attributes(EmailIdentity="example.org", SigningEnabled=False)
    _check("dkim toggle", c.get_email_identity(EmailIdentity="example.org")["DkimAttributes"]["SigningEnabled"] is False)
    c.create_email_identity_policy(EmailIdentity="example.org", PolicyName="p1", Policy='{"Version":"2012-10-17"}')
    _check("identity policy", c.get_email_identity_policies(EmailIdentity="example.org")["Policies"] == {"p1": '{"Version":"2012-10-17"}'})
    _check("dup policy", _err(c.create_email_identity_policy, EmailIdentity="example.org", PolicyName="p1", Policy="{}")[0] == "AlreadyExistsException")
    c.delete_email_identity_policy(EmailIdentity="example.org", PolicyName="p1")

    # configuration sets + event destinations
    c.create_configuration_set(ConfigurationSetName="prod", TrackingOptions={"CustomRedirectDomain": "t.example.org"},
                               Tags=[{"Key": "a", "Value": "b"}])
    _check("dup config set", _err(c.create_configuration_set, ConfigurationSetName="prod")[0] == "AlreadyExistsException")
    cs = c.get_configuration_set(ConfigurationSetName="prod")
    _check("get config set", cs["TrackingOptions"]["CustomRedirectDomain"] == "t.example.org" and cs["SendingOptions"]["SendingEnabled"])
    c.put_configuration_set_reputation_options(ConfigurationSetName="prod", ReputationMetricsEnabled=True)
    c.put_configuration_set_delivery_options(ConfigurationSetName="prod", TlsPolicy="REQUIRE")
    cs = c.get_configuration_set(ConfigurationSetName="prod")
    _check("put options", cs["ReputationOptions"]["ReputationMetricsEnabled"] and cs["DeliveryOptions"]["TlsPolicy"] == "REQUIRE")
    c.create_configuration_set_event_destination(ConfigurationSetName="prod", EventDestinationName="sns1", EventDestination={
        "Enabled": True, "MatchingEventTypes": ["SEND", "BOUNCE"], "SnsDestination": {"TopicArn": "arn:aws:sns:us-east-1:123456789012:t"}})
    d = c.get_configuration_set_event_destinations(ConfigurationSetName="prod")["EventDestinations"]
    _check("event destination", d[0]["Name"] == "sns1" and d[0]["MatchingEventTypes"] == ["SEND", "BOUNCE"])
    c.update_configuration_set_event_destination(ConfigurationSetName="prod", EventDestinationName="sns1", EventDestination={
        "Enabled": False, "MatchingEventTypes": ["SEND"], "SnsDestination": {"TopicArn": "arn:aws:sns:us-east-1:123456789012:t"}})
    _check("update event destination", c.get_configuration_set_event_destinations(ConfigurationSetName="prod")["EventDestinations"][0]["Enabled"] is False)
    c.delete_configuration_set_event_destination(ConfigurationSetName="prod", EventDestinationName="sns1")
    _check("config sets list", c.list_configuration_sets()["ConfigurationSets"] == ["prod"])

    # templates
    c.create_email_template(TemplateName="welcome", TemplateContent={"Subject": "Hi {{name}}", "Text": "Hello {{name}}", "Html": "<b>{{name}}</b>"})
    _check("dup template", _err(c.create_email_template, TemplateName="welcome", TemplateContent={"Subject": "x", "Text": "y"})[0] == "AlreadyExistsException")
    _check("get template", c.get_email_template(TemplateName="welcome")["TemplateContent"]["Subject"] == "Hi {{name}}")
    rendered = c.test_render_email_template(TemplateName="welcome", TemplateData='{"name":"Ada"}')["RenderedTemplate"]
    _check("render template", "Subject: Hi Ada" in rendered and "Hello Ada" in rendered)
    c.update_email_template(TemplateName="welcome", TemplateContent={"Subject": "Welcome {{name}}", "Text": "t"})
    _check("update template", c.get_email_template(TemplateName="welcome")["TemplateContent"]["Subject"] == "Welcome {{name}}")
    _check("list templates", [t["TemplateName"] for t in c.list_email_templates()["TemplatesMetadata"]] == ["welcome"])

    # sending
    r = c.send_email(FromEmailAddress="dev@example.com", Destination={"ToAddresses": ["a@x.com"]},
                     Content={"Simple": {"Subject": {"Data": "s"}, "Body": {"Text": {"Data": "b"}}}}, ConfigurationSetName="prod")
    _check("send email", len(r["MessageId"]) > 10 and s.messages[-1]["To"] == ["a@x.com"])
    c.send_email(FromEmailAddress="Ops <anyone@example.org>", Destination={"ToAddresses": ["a@x.com"]},
                 Content={"Template": {"TemplateName": "welcome", "TemplateData": "{}"}})
    _check("send from verified domain", len(s.messages) == 2)
    _check("unverified sender rejected", _err(c.send_email, FromEmailAddress="x@evil.com", Destination={"ToAddresses": ["a@x.com"]},
           Content={"Simple": {"Subject": {"Data": "s"}, "Body": {"Text": {"Data": "b"}}}}) == ("MessageRejected", 400))
    _check("no recipients", _err(c.send_email, FromEmailAddress="dev@example.com", Destination={},
           Content={"Simple": {"Subject": {"Data": "s"}, "Body": {"Text": {"Data": "b"}}}})[0] == "BadRequestException")
    _check("unknown config set", _err(c.send_email, FromEmailAddress="dev@example.com", Destination={"ToAddresses": ["a@x.com"]},
           Content={"Simple": {"Subject": {"Data": "s"}, "Body": {"Text": {"Data": "b"}}}}, ConfigurationSetName="zzz")[0] == "NotFoundException")
    b = c.send_bulk_email(FromEmailAddress="dev@example.com", DefaultContent={"Template": {"TemplateName": "welcome", "TemplateData": "{}"}},
                          BulkEmailEntries=[{"Destination": {"ToAddresses": ["a@x.com"]}}, {"Destination": {}}])
    _check("bulk email", [e["Status"] for e in b["BulkEmailEntryResults"]] == ["SUCCESS", "INVALID_PARAMETER"])

    # contact lists
    c.create_contact_list(ContactListName="news", Description="News", Topics=[{"TopicName": "t1", "DisplayName": "T1", "Description": "d", "DefaultSubscriptionStatus": "OPT_IN"}])
    _check("get contact list", c.get_contact_list(ContactListName="news")["Topics"][0]["TopicName"] == "t1")
    c.create_contact(ContactListName="news", EmailAddress="u@x.com", TopicPreferences=[{"TopicName": "t1", "SubscriptionStatus": "OPT_OUT"}])
    ct = c.get_contact(ContactListName="news", EmailAddress="u@x.com")
    _check("get contact", ct["TopicPreferences"][0]["SubscriptionStatus"] == "OPT_OUT" and ct["TopicDefaultPreferences"][0]["SubscriptionStatus"] == "OPT_IN")
    _check("bad topic", _err(c.create_contact, ContactListName="news", EmailAddress="v@x.com", TopicPreferences=[{"TopicName": "zz", "SubscriptionStatus": "OPT_IN"}])[0] == "BadRequestException")
    c.update_contact(ContactListName="news", EmailAddress="u@x.com", UnsubscribeAll=True)
    _check("list contacts", c.list_contacts(ContactListName="news")["Contacts"][0]["UnsubscribeAll"] is True)
    c.delete_contact(ContactListName="news", EmailAddress="u@x.com")
    _check("contact gone", _err(c.get_contact, ContactListName="news", EmailAddress="u@x.com")[0] == "NotFoundException")

    # suppression
    c.put_suppressed_destination(EmailAddress="bad@x.com", Reason="BOUNCE")
    _check("get suppressed", c.get_suppressed_destination(EmailAddress="bad@x.com")["SuppressedDestination"]["Reason"] == "BOUNCE")
    _check("list suppressed", [x["EmailAddress"] for x in c.list_suppressed_destinations()["SuppressedDestinationSummaries"]] == ["bad@x.com"])
    c.delete_suppressed_destination(EmailAddress="bad@x.com")

    # pools, tags, tenants, account
    c.create_dedicated_ip_pool(PoolName="pool1", ScalingMode="MANAGED")
    _check("ip pool", c.get_dedicated_ip_pool(PoolName="pool1")["DedicatedIpPool"]["ScalingMode"] == "MANAGED" and c.list_dedicated_ip_pools()["DedicatedIpPools"] == ["pool1"])
    arn = "arn:aws:ses:us-east-1:123456789012:identity/dev@example.com"
    c.tag_resource(ResourceArn=arn, Tags=[{"Key": "k", "Value": "v"}, {"Key": "k2", "Value": "v2"}])
    _check("tags", len(c.list_tags_for_resource(ResourceArn=arn)["Tags"]) == 3)
    c.untag_resource(ResourceArn=arn, TagKeys=["k", "k2"])
    _check("untag (multi-value query)", c.list_tags_for_resource(ResourceArn=arn)["Tags"] == [{"Key": "env", "Value": "dev"}])
    t = c.create_tenant(TenantName="acme")
    _check("tenant", c.get_tenant(TenantName="acme")["Tenant"]["TenantId"] == t["TenantId"] and c.list_tenants()["Tenants"][0]["TenantName"] == "acme")
    c.delete_tenant(TenantName="acme")
    a = c.get_account()
    _check("account", a["SendingEnabled"] and a["SendQuota"]["SentLast24Hours"] >= 3 and a["EnforcementStatus"] == "HEALTHY")
    c.put_account_sending_attributes(SendingEnabled=False)
    _check("sending paused", _err(c.send_email, FromEmailAddress="dev@example.com", Destination={"ToAddresses": ["a@x.com"]},
           Content={"Simple": {"Subject": {"Data": "s"}, "Body": {"Text": {"Data": "b"}}}})[0] == "SendingPausedException")
    c.put_account_sending_attributes(SendingEnabled=True)

    # deletes
    c.delete_email_identity(EmailIdentity="dev@example.com")
    c.delete_email_identity(EmailIdentity="example.org")
    c.delete_configuration_set(ConfigurationSetName="prod")
    c.delete_email_template(TemplateName="welcome")
    c.delete_contact_list(ContactListName="news")
    c.delete_dedicated_ip_pool(PoolName="pool1")
    _check("all deleted", not (s.identities or s.config_sets or s.templates or s.contact_lists or s.ip_pools))

    # console REST view
    st, out = ses.console_dispatch(s, "POST", "/api/aws/sesv2/identities", {}, {"identity": "console@example.com"})
    _check("console create", st == 200 and out["status"] == "Verified")
    row = ses.console_dispatch(s, "GET", "/api/aws/sesv2/identities", {}, None)[1]["items"][0]
    _check("console row has no blank cells", all(row[k] not in ("", None, "-") for k in ("identity", "type", "status", "sending", "dkim", "mail_from", "config_set", "region")))
    for kind, body in (("configuration-sets", {"name": "cs1"}), ("templates", {"name": "t1"}), ("contact-lists", {"name": "l1"}),
                       ("suppression", {"name": "z@x.com", "reason": "complaint"})):
        _check(f"console {kind} create", ses.console_dispatch(s, "POST", f"/api/aws/sesv2/{kind}", {}, body)[0] == 200)
        rows = ses.console_dispatch(s, "GET", f"/api/aws/sesv2/{kind}", {}, None)[1]["items"]
        _check(f"console {kind} filled", rows and all(v not in ("", None, "-") for v in rows[0].values()))
        _check(f"console {kind} delete", ses.console_dispatch(s, "DELETE", f"/api/aws/sesv2/{kind}/{body['name']}", {}, None)[0] == 200)
    _check("console delete", ses.console_dispatch(s, "DELETE", "/api/aws/sesv2/identities/console@example.com", {}, None)[0] == 200)
    _check("console 404", ses.console_dispatch(s, "GET", "/api/aws/sesv2/identities/console@example.com", {}, None)[0] == 404)
    return True


def test_sesv2_core():
    assert run()


if __name__ == "__main__":
    run()
    print("sesv2 core: PASS")
