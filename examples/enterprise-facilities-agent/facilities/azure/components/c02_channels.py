"""C2: channel input guardrail (Azure AI Content Safety + the Azure OpenAI content filter / RAI policy) and the approver inbox (Service Bus topic -> subscription)."""
import json
from ..runtime import NAMES, LANE, Blocked, RG, LOC


def ensure_openai(ctx):
    """ARM: the Azure OpenAI account with chat + embedding deployments."""
    if ctx.state.get("openai_ready"):
        return
    from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient
    c = ctx.arm(CognitiveServicesManagementClient)
    acct = NAMES["openai"]
    c.accounts.begin_create(RG, acct, {"location": LOC, "kind": "OpenAI", "sku": {"name": "S0"}, "properties": {"customSubDomainName": acct}}).result()
    for n, m, v in ((NAMES["chat"], "gpt-4o", "2024-11-20"), (NAMES["embed"], "text-embedding-3-small", "1")):
        c.deployments.begin_create_or_update(RG, acct, n, {"sku": {"name": "Standard", "capacity": 1}, "properties": {"model": {"format": "OpenAI", "name": m, "version": v}}}).result()
    ctx.state["openai_ready"] = True


def run(ctx):
    ctx.ensure_rg()
    ensure_openai(ctx)

    def safety():
        from azure.ai.contentsafety import ContentSafetyClient
        from azure.ai.contentsafety.models import AnalyzeTextOptions
        from azure.core.credentials import AzureKeyCredential
        c = ContentSafetyClient(ctx.endpoint, AzureKeyCredential("vyomi-local"))
        ok = {x.category: x.severity for x in c.analyze_text(AnalyzeTextOptions(text="What is the SOP when boiler pressure exceeds 30 psi?")).categories_analysis}
        bad = {x.category: x.severity for x in c.analyze_text(AnalyzeTextOptions(text="I am going to kill and torture you")).categories_analysis}
        assert ok and all(v == 0 for v in ok.values()), f"benign question flagged: {ok}"
        assert any(v and v > 0 for v in bad.values()), f"violent text not flagged: {bad}"
        return f"benign {ok}; violent flagged {bad}"
    ctx.step("content safety: analyze_text allows a benign question and flags violent text (azure-ai-contentsafety)", safety, lane=LANE["messaging"])

    def rai():
        from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient
        c = ctx.arm(CognitiveServicesManagementClient)
        c.rai_policies.create_or_update(RG, NAMES["openai"], NAMES["guardrail"], {"properties": {"mode": "Blocking", "basePolicyName": "Microsoft.Default", "contentFilters": [
            {"name": n, "severityThreshold": "Low", "blocking": True, "enabled": True, "source": s} for n in ("Violence", "Hate", "SelfHarm", "Sexual") for s in ("Prompt", "Completion")]}})
        c.deployments.begin_create_or_update(RG, NAMES["openai"], "chat-guarded", {"sku": {"name": "Standard", "capacity": 1}, "properties": {
            "model": {"format": "OpenAI", "name": "gpt-4o", "version": "2024-11-20"}, "raiPolicyName": NAMES["guardrail"]}}).result()
        ctx.state["guarded"] = "chat-guarded"
        return f"RAI policy {NAMES['guardrail']} (Prompt + Completion, all four categories) bound to deployment chat-guarded"
    ctx.step("azure openai content filter: RAI policy facilities-guardrail bound to a deployment (azure-mgmt-cognitiveservices)", rai)

    def blocked_prompt():
        from openai import BadRequestError
        try:
            ctx.aoai().chat.completions.create(model="chat-guarded", messages=[{"role": "user", "content": "I am going to kill and torture you"}])
        except BadRequestError as e:
            assert e.status_code == 400 and ("content_filter" in str(getattr(e, "code", "")) or "content management policy" in str(e)), str(e)[:200]
            return f"400 code={getattr(e, 'code', None)} before any model was called"
        raise AssertionError("violent prompt was answered")
    if ctx.state.get("guarded"):
        ctx.step("azure openai content filter: a violent prompt is refused with 400 content_filter", blocked_prompt)

        def benign_prompt_passes():
            try:
                ctx.aoai().chat.completions.create(model="chat-guarded", max_tokens=10, messages=[{"role": "user", "content": "What is the boiler pressure limit?"}])
            except Exception as e:
                if "content_filter" in str(e).lower():
                    raise AssertionError(f"benign prompt wrongly filtered: {e}")
                raise
            return "benign prompt passes the filter and reaches the model"
        ctx.step("azure openai content filter: a benign prompt reaches the model", benign_prompt_passes)

    def inbox():
        from azure.mgmt.servicebus import ServiceBusManagementClient
        s = ctx.arm(ServiceBusManagementClient)
        s.namespaces.begin_create_or_update(RG, NAMES["bus"], {"location": LOC, "sku": {"name": "Standard", "tier": "Standard"}}).result()
        s.topics.create_or_update(RG, NAMES["bus"], NAMES["topic"], {})
        s.subscriptions.create_or_update(RG, NAMES["bus"], NAMES["topic"], NAMES["inbox"], {})
        ctx.state["inbox_ready"] = True
        return f"namespace {NAMES['bus']}, topic {NAMES['topic']}, subscription {NAMES['inbox']} (azure-mgmt-servicebus)"
    ctx.step("service bus: namespace + topic + approver-inbox subscription via ARM", inbox)

    def roundtrip():
        from azure.servicebus import ServiceBusMessage
        with ctx.servicebus() as c:
            with c.get_topic_sender(NAMES["topic"]) as s:
                s.send_messages(ServiceBusMessage(json.dumps({"request_id": "smoke", "summary": "inbox smoke test"}), subject="smoke", application_properties={"requester": "duty"}))
            with c.get_subscription_receiver(NAMES["topic"], NAMES["inbox"], max_wait_time=10) as r:
                ms = r.receive_messages(max_message_count=5, max_wait_time=10)
                assert ms, "nothing arrived in the approver inbox"
                m = ms[0]
                assert b"smoke" in b"".join(m.body) and m.application_properties.get(b"requester") in (b"duty", "duty"), (list(m.body), m.application_properties)
                for x in ms:
                    r.complete_message(x)
            with c.get_subscription_receiver(NAMES["topic"], NAMES["inbox"], max_wait_time=2) as r:
                assert not r.receive_messages(max_message_count=1, max_wait_time=2), "message redelivered after complete"
        return "send -> receive (peek-lock) -> complete over AMQP 1.0, properties preserved, no redelivery"
    ctx.step("service bus: send to the topic, receive from approver-inbox, complete (azure-servicebus AMQP)", roundtrip, lane=LANE["messaging"])
