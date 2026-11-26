"""Call the model in your browser. First a plain chat turn, then three questions through the action protocol."""
import llmx

text, usage = llmx.converse("You are brief.", [{"role": "user", "content": "Say hello to the facilities team in one short sentence."}], max_tokens=40)
assert text.strip(), "the model returned no text"
print("model said:", text.strip()[:90], "| tokens:", usage["totalTokens"])

ALL = ("search_docs", "lookup_record", "file_ticket", "answer", "refuse")
CASES = [("What is the status of AHU-7?", "lookup_record"),
         ("How often is the pressure relief valve inspected?", "search_docs"),
         ("File a P2 ticket for EL-3: the door sensor is faulty.", "file_ticket")]
right = 0
for question, want in CASES:
    act, raw, retried = llmx.ask([{"role": "user", "content": "Question: " + question}], ALL)
    right += act["action"] == want
    print("%-58s -> %s%s" % (question, act["action"], " (after one retry)" if retried else ""))
assert right == len(CASES), "the model picked the wrong action for %d of %d questions" % (len(CASES) - right, len(CASES))
print("valid actions: %d of %d" % (right, len(CASES)))
