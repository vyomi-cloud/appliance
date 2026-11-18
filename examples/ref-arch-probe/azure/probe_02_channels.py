"""Component 2 Channels: input guardrail (Content Safety / RAI content filter) + approver inbox (Service Bus topic -> subscription over AMQP)."""
import time
from _common import *

P = Probe(2, "channels", "Channels: input guardrail + approver inbox")
B = endpoint(); ensure_rg(B); ensure_openai(B)
H = {}


def contentsafety():
    from azure.ai.contentsafety import ContentSafetyClient
    from azure.ai.contentsafety.models import AnalyzeTextOptions
    from azure.core.credentials import AzureKeyCredential
    from azure.core.pipeline.policies import SansIOHTTPPolicy
    c = ContentSafetyClient(B, AzureKeyCredential("k"))
    r = c.analyze_text(AnalyzeTextOptions(text="I will hurt you badly"))
    cats = {x.category: x.severity for x in r.categories_analysis}
    assert cats, "no categories returned"
    return cats


def rai_policy():
    from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient
    c = arm(CognitiveServicesManagementClient, B)
    p = c.rai_policies.create_or_update(RG, "aoai1", "strict", {"properties": {"mode": "Blocking", "basePolicyName": "Microsoft.Default",
        "contentFilters": [{"name": "Violence", "severityThreshold": "Low", "blocking": True, "enabled": True, "source": "Prompt"}]}})
    return p.name


def input_filtered_chat():
    """A violent prompt on a deployment bound to the strict RAI policy must be refused by the filter BEFORE any model is called."""
    from openai import BadRequestError
    from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient
    arm(CognitiveServicesManagementClient, B).deployments.begin_create_or_update(RG, "aoai1", "chat-strict", {"sku": {"name": "Standard", "capacity": 1},
        "properties": {"model": {"format": "OpenAI", "name": "gpt-4o", "version": "2024-11-20"}, "raiPolicyName": "strict"}}).result()
    oc = aoai(B)
    try:
        oc.chat.completions.create(model="chat-strict", messages=[{"role": "user", "content": "I am going to kill and torture you"}])
    except BadRequestError as e:
        assert e.status_code == 400 and ("content_filter" in str(getattr(e, "code", "")) or "content management policy" in str(e)), str(e)[:200]
        return f"400 code={getattr(e, 'code', None)}"
    except Exception as e:  # 503 = no model reached after the filter let it through
        raise AssertionError(f"filter did not block, request went on to the model: {type(e).__name__}: {str(e)[:120]}")
    raise AssertionError("no error: violent prompt answered")


def sb_arm():
    from azure.mgmt.servicebus import ServiceBusManagementClient
    s = arm(ServiceBusManagementClient, B)
    s.namespaces.begin_create_or_update(RG, "ns1", {"location": LOC, "sku": {"name": "Standard", "tier": "Standard"}}).result()
    s.topics.create_or_update(RG, "ns1", "approvals", {})
    s.subscriptions.create_or_update(RG, "ns1", "approvals", "inbox", {})


def sb_arm_reaches_amqp():
    from azure.servicebus import ServiceBusClient, ServiceBusMessage
    with ServiceBusClient.from_connection_string(sb_conn(amqp_port())) as c:
        with c.get_topic_sender("approvals") as s:
            s.send_messages(ServiceBusMessage("x"))


def sb_amqp_loop():
    from azure.servicebus import ServiceBusClient, ServiceBusMessage
    sb_seed(topic="approvals-h", sub="inbox")
    with ServiceBusClient.from_connection_string(sb_conn(amqp_port())) as c:
        with c.get_topic_sender("approvals-h") as s:
            s.send_messages(ServiceBusMessage('{"request_id":"r1","amount":900}', application_properties={"kind": "approval"}, subject="approval"))
        with c.get_subscription_receiver("approvals-h", "inbox", max_wait_time=5) as r:
            ms = r.receive_messages(max_message_count=1, max_wait_time=5)
            assert len(ms) == 1, "nothing received"
            body = b"".join(ms[0].body).decode()
            r.complete_message(ms[0])
        with c.get_subscription_receiver("approvals-h", "inbox", max_wait_time=2) as r:
            assert not r.receive_messages(max_message_count=1, max_wait_time=2), "message not removed after complete"
    return body


P.step("Content Safety analyze_text (azure-ai-contentsafety)", contentsafety)
P.step("Azure OpenAI RAI (content filter) policy create via ARM (raiPolicies)", rai_policy)
P.step("violent prompt refused by the input content filter before the model", input_filtered_chat, "b")
P.step("Service Bus namespace + topic + subscription via ARM (azure-mgmt-servicebus)", sb_arm)
P.step("an ARM-created topic is reachable over AMQP (azure-servicebus)", sb_arm_reaches_amqp)
P.step("topic -> subscription: send, receive, complete over AMQP (entities seeded straight into the runtime store: harness shortcut)", sb_amqp_loop)
P.finish()
