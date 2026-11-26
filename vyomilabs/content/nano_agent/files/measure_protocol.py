"""How reliable is the protocol with THIS model? Twelve questions, one first action each. We count replies that were valid first time, valid after the one retry,
and never valid, and whether the first action was the sensible one. Measure it: a model that cannot meet the bar below cannot run this agent."""
import llmx

ALL = ("search_docs", "lookup_record", "file_ticket", "answer", "refuse")
CASES = [("What is the status of AHU-7?", "lookup_record"), ("Is work order WO-000102 still open?", "lookup_record"),
         ("When was B-12 last inspected?", "lookup_record"), ("Which asset does WO-000103 belong to?", "lookup_record"),
         ("How often is the pressure relief valve inspected?", "search_docs"), ("What should I do if someone is stuck in an elevator?", "search_docs"),
         ("At what pressure do I close the main steam valve?", "search_docs"), ("What is the procedure for a water leak near electrics?", "search_docs"),
         ("File a P2 ticket for EL-3: the door sensor is faulty.", "file_ticket"), ("Please raise a P1 ticket for B-12, the pressure is too high.", "file_ticket"),
         ("Open a ticket for AHU-7: the filter is clogged, priority P3.", "file_ticket"), ("Log a P2 ticket for EL-3, the cabin lights flicker.", "file_ticket")]
first, retried, failed, sensible = 0, 0, 0, 0
for question, want in CASES:
    try:
        act, raw, did_retry = llmx.ask([{"role": "user", "content": "Question: " + question}], ALL)
    except llmx.BadAction:
        failed += 1
        print("INVALID after retry:", question)
        continue
    first += 0 if did_retry else 1
    retried += 1 if did_retry else 0
    sensible += act["action"] == want
print("valid first time: %d | valid after one retry: %d | never valid: %d | sensible first action: %d of %d" % (first, retried, failed, sensible, len(CASES)))
assert failed == 0, "the model could not produce a valid action for %d questions, even after a retry" % failed
assert sensible >= 10, "the model chose a sensible first action for only %d of %d questions (need 10)" % (sensible, len(CASES))
print("protocol reliability ok")
