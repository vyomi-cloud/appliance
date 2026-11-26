"""Measure retrieval instead of trusting it. Thirteen questions whose answer IS in the handbook, and six whose answer is not.
For each search mode we count questions whose best passage comes from the right document, and the highest score any unsupported question reaches."""
import rag

FOUND = [("At what boiler pressure should I close the main steam valve?", "boiler-sop.md"), ("boiler pressure", "boiler-sop.md"),
         ("How often should the AHU-7 filter be replaced?", "hvac-maintenance-manual.md"), ("AHU-7 filter replacement frequency", "hvac-maintenance-manual.md"),
         ("Someone is stuck in an elevator. What should I do?", "elevator-sop.md"), ("elevator stuck", "elevator-sop.md"),
         ("Water is leaking near an electrical panel. What is the procedure?", "water-leak-sop.md"), ("leaking electrical panel", "water-leak-sop.md"),
         ("AHU-7 supply air temperature drifted by 4 degrees", "hvac-maintenance-manual.md"), ("pressure relief valve inspection interval", "boiler-sop.md"),
         ("visitor parking rules", "visitor-parking.md"), ("How quickly must a P2 ticket be answered?", "ticket-policy.md"), ("How often are fire alarm panels tested?", "fire-safety-sop.md")]
NOT_FOUND = ["What is the company vacation policy?", "vacation policy", "What is the replacement interval for the chiller compressor oil?",
             "chiller compressor oil replacement", "what is for lunch in the cafeteria", "who is the chief executive"]
chunks = rag.load_index()
table = {}
for mode in ("keyword", "dense", "hybrid"):
    right = sum(rag.search(q, chunks, k=1, mode=mode)[0]["doc"] == doc for q, doc in FOUND)
    worst = max(rag.search(q, chunks, k=1, mode=mode)[0]["score"] for q in NOT_FOUND)
    table[mode] = (right, worst)
    print("%-8s right document first: %2d of %d | highest score of an unsupported question: %.2f" % (mode, right, len(FOUND), worst))
right, worst = table["hybrid"]
print("support threshold in rag.py: %.2f" % rag.SUPPORT_MIN)
assert right == len(FOUND), "hybrid search missed %d questions" % (len(FOUND) - right)
assert worst < rag.SUPPORT_MIN, "an unsupported question scored %.2f, above the threshold" % worst
print("retrieval ok")
