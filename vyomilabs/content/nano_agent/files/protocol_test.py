"""The protocol needs no model to test: feed the parser and the validator replies a small model really produces, good and bad."""
import llmx
from llmx import BadAction, parse_action, validate_action

ALL = ("search_docs", "lookup_record", "file_ticket", "answer", "refuse")

# 1. A clean reply, a reply wrapped in prose and a code fence, and a pretty-printed one all parse to the same action.
good = ['{"action":"lookup_record","id":"AHU-7"}',
        'Sure! ```json\n{"action": "lookup_record", "id": "AHU-7"}\n``` Hope that helps.',
        '{\n  "action": "lookup_record",\n  "id": "AHU-7"\n}']
for text in good:
    assert validate_action(parse_action(text), ALL) == {"action": "lookup_record", "id": "AHU-7"}, text
print("3 well-formed replies accepted")

# 2. Replies that must be rejected, each for a named reason.
bad = [("I think the status is degraded", "no JSON object"),
       ('{"action":"lookup_record","id":"AHU-7"', "not closed"),
       ('{"action":"delete_asset","id":"B-12"}', "unknown action"),
       ('{"action":"lookup_record","id":"the boiler"}', "must look like"),
       ('{"action":"file_ticket","asset_id":"EL-3","summary":"door","priority":"urgent"}', "P1, P2 or P3"),
       ('{"action":"answer"}', "non-empty string")]
for text, reason in bad:
    try:
        validate_action(parse_action(text), ALL)
        raise AssertionError("accepted a bad reply: " + text)
    except BadAction as e:
        assert reason in str(e), (reason, str(e))
print(len(bad), "bad replies rejected, each with a reason")

# 3. The allow-list: an action that exists but is not allowed right now is refused too.
try:
    validate_action({"action": "file_ticket", "asset_id": "EL-3", "summary": "x", "priority": "P2"}, ("answer", "refuse"))
    raise AssertionError("an action outside the allow-list was accepted")
except BadAction as e:
    assert "not available" in str(e)
print("allow-list enforced")
print("protocol tests passed")
