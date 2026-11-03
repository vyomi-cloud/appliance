"""AWS-08 CloudFormation sweep — stack policy enforcement, CloudWatch-alarm rollback triggers (real rollback),
SNS stack notifications. Through AwsWireRouter (Nano / unified ingress entry).
Run: PYTHONPATH=. python3 tests/conformance/test_cfn_sweep_core.py
"""
import json
import re
from urllib.parse import urlencode

from core.aws_wire_router import AwsWireRouter


def _auth(svc):
    return f"AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/{svc}/aws4_request, SignedHeaders=host, Signature=0"


def q(r, svc, action, params=None, version="2010-05-15"):
    body = urlencode({"Action": action, "Version": version, **(params or {})}).encode()
    out = r.handle("POST", "/", {}, {"authorization": _auth(svc), "content-type": "application/x-www-form-urlencoded"}, body)
    return out["status"], out["body"].decode()


def cfn(r, action, params=None):
    return q(r, "cloudformation", action, params)


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def tmpl(topic_name, queue_delay="0"):
    return json.dumps({"Resources": {
        "Topic": {"Type": "AWS::SNS::Topic", "Properties": {"TopicName": topic_name}},
        "Queue": {"Type": "AWS::SQS::Queue", "Properties": {"QueueName": "q-" + topic_name, "DelaySeconds": queue_delay}}}})


def field(xml, tag):
    m = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.S)
    return m.group(1) if m else ""


def main():
    r = AwsWireRouter()
    # ── stack policy
    policy = json.dumps({"Statement": [
        {"Effect": "Allow", "Action": "Update:*", "Principal": "*", "Resource": "*"},
        {"Effect": "Deny", "Action": ["Update:Replace", "Update:Delete", "Update:Modify"], "Principal": "*", "Resource": "LogicalResourceId/Queue"}]})
    st, x = cfn(r, "CreateStack", {"StackName": "pol", "TemplateBody": tmpl("pol-t"), "StackPolicyBody": policy})
    _check("CreateStack with StackPolicyBody", st == 200)
    st, x = cfn(r, "GetStackPolicy", {"StackName": "pol"})
    _check("GetStackPolicy returns the policy", "LogicalResourceId/Queue" in x.replace("&quot;", '"') or "Update:Replace" in x)
    st, x = cfn(r, "SetStackPolicy", {"StackName": "pol", "StackPolicyBody": "not json"})
    _check("SetStackPolicy rejects an invalid document", st == 400)
    st, x = cfn(r, "UpdateStack", {"StackName": "pol", "TemplateBody": tmpl("pol-t", "5")})
    st, d = cfn(r, "DescribeStacks", {"StackName": "pol"})
    _check("update touching a protected resource is denied and rolled back", field(d, "StackStatus") == "UPDATE_ROLLBACK_COMPLETE" and "Action denied by stack policy" in field(d, "StackStatusReason"))
    st, ev = cfn(r, "DescribeStackEvents", {"StackName": "pol"})
    _check("UPDATE_FAILED event names the resource + statement", "UPDATE_FAILED" in ev and "Queue" in ev)
    st, t = cfn(r, "GetTemplate", {"StackName": "pol"})
    _check("denied update changed nothing (template unchanged)", 'DelaySeconds&quot;: &quot;5' not in t and '"5"' not in t.replace("&quot;", '"'))
    t2 = json.loads(tmpl("pol-t")); t2["Resources"]["Topic"]["Properties"]["DisplayName"] = "x"
    st, _ = cfn(r, "UpdateStack", {"StackName": "pol", "TemplateBody": json.dumps(t2)})
    st, d = cfn(r, "DescribeStacks", {"StackName": "pol"})
    _check("update of an unprotected resource proceeds", field(d, "StackStatus") == "UPDATE_COMPLETE")
    ov = json.dumps({"Statement": [{"Effect": "Allow", "Action": "Update:*", "Principal": "*", "Resource": "*"}]})
    st, _ = cfn(r, "UpdateStack", {"StackName": "pol", "TemplateBody": tmpl("pol-t", "7"), "StackPolicyDuringUpdateBody": ov})
    st, d = cfn(r, "DescribeStacks", {"StackName": "pol"})
    _check("StackPolicyDuringUpdateBody temporarily overrides the policy", field(d, "StackStatus") == "UPDATE_COMPLETE")
    rm = json.dumps({"Statement": [{"Effect": "Allow", "Action": "Update:*", "Principal": "*", "Resource": "*"}]})
    cfn(r, "SetStackPolicy", {"StackName": "pol", "StackPolicyBody": json.dumps({"Statement": [{"Effect": "Deny", "Action": "Update:Delete", "Principal": "*", "Resource": "*"}]})})
    st, _ = cfn(r, "UpdateStack", {"StackName": "pol", "TemplateBody": json.dumps({"Resources": {"Topic": t2["Resources"]["Topic"]}})})
    st, d = cfn(r, "DescribeStacks", {"StackName": "pol"})
    _check("a Deny on Update:Delete blocks removing a resource (and nothing else is allowed: default deny)", field(d, "StackStatus") == "UPDATE_ROLLBACK_COMPLETE")

    # ── notifications
    st, x = q(r, "sns", "CreateTopic", {"Name": "cfn-events"}, "2010-03-31")
    topic = field(x, "TopicArn")
    st, x = q(r, "sqs", "CreateQueue", {"QueueName": "cfn-sink"}, "2012-11-05")
    qurl = field(x, "QueueUrl")
    qarn = "arn:aws:sqs:us-east-1:123456789012:cfn-sink"
    q(r, "sns", "Subscribe", {"TopicArn": topic, "Protocol": "sqs", "Endpoint": qarn}, "2010-03-31")
    st, x = cfn(r, "CreateStack", {"StackName": "nfy", "TemplateBody": tmpl("nfy-t"), "NotificationARNs.member.1": "arn:aws:sns:us-east-1:123456789012:missing"})
    _check("a non-existent notification topic is rejected", st == 400)
    st, x = cfn(r, "CreateStack", {"StackName": "nfy", "TemplateBody": tmpl("nfy-t"), "NotificationARNs.member.1": topic})
    _check("CreateStack with NotificationARNs", st == 200)
    st, d = cfn(r, "DescribeStacks", {"StackName": "nfy"})
    _check("DescribeStacks lists NotificationARNs", topic in d)
    st, x = q(r, "sqs", "ReceiveMessage", {"QueueUrl": qurl, "MaxNumberOfMessages": "10"}, "2012-11-05")
    _check("stack events were really published to the SNS topic (and fanned out to SQS)", "CREATE_COMPLETE" in x and "AWS::CloudFormation::Stack" in x and "StackName=" in x)

    # ── rollback triggers
    st, _ = q(r, "monitoring", "PutMetricAlarm", {"AlarmName": "guard", "MetricName": "M", "Namespace": "N", "Statistic": "Average", "Period": "60",
                                                    "EvaluationPeriods": "1", "Threshold": "1", "ComparisonOperator": "GreaterThanThreshold"}, "2010-08-01")
    alarm = "arn:aws:cloudwatch:us-east-1:123456789012:alarm:guard"
    rb = {"RollbackConfiguration.RollbackTriggers.member.1.Arn": alarm, "RollbackConfiguration.RollbackTriggers.member.1.Type": "AWS::CloudWatch::Alarm",
          "RollbackConfiguration.MonitoringTimeInMinutes": "5"}
    st, _ = cfn(r, "CreateStack", {"StackName": "rb", "TemplateBody": tmpl("rb-t"), **rb})
    st, d = cfn(r, "DescribeStacks", {"StackName": "rb"})
    _check("stack created with a rollback configuration (alarm OK)", field(d, "StackStatus") == "CREATE_COMPLETE" and alarm in d and "<MonitoringTimeInMinutes>5" in d)
    q(r, "monitoring", "SetAlarmState", {"AlarmName": "guard", "StateValue": "ALARM", "StateReason": "test"}, "2010-08-01")
    st, _ = cfn(r, "UpdateStack", {"StackName": "rb", "TemplateBody": tmpl("rb-t", "9")})
    st, d = cfn(r, "DescribeStacks", {"StackName": "rb"})
    _check("update with the trigger alarm in ALARM is rolled back", field(d, "StackStatus") == "UPDATE_ROLLBACK_COMPLETE" and "ALARM" in field(d, "StackStatusReason"))
    st, t = cfn(r, "GetTemplate", {"StackName": "rb"})
    _check("rollback restored the previous template", '"9"' not in t.replace("&quot;", '"'))
    st, qa = q(r, "sqs", "GetQueueAttributes", {"QueueUrl": "http://sqs.us-east-1.localhost/123456789012/q-rb-t", "AttributeName.1": "DelaySeconds"}, "2012-11-05")
    _check("the underlying SQS queue was really reverted", "<Value>9</Value>" not in qa)
    q(r, "monitoring", "SetAlarmState", {"AlarmName": "guard", "StateValue": "OK", "StateReason": "test"}, "2010-08-01")
    st, _ = cfn(r, "UpdateStack", {"StackName": "rb", "TemplateBody": tmpl("rb-t", "9")})
    st, d = cfn(r, "DescribeStacks", {"StackName": "rb"})
    _check("with the alarm OK the same update completes", field(d, "StackStatus") == "UPDATE_COMPLETE")
    print("CloudFormation sweep: all checks passed")


if __name__ == "__main__":
    main()
