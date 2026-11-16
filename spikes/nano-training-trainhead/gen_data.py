"""Template-generated 5-class intent dataset (1000 train / 200 held-out) + 5 label docs per class for the reranker."""
import json, random, os
random.seed(7)
CL = {
 "billing": ["I was charged twice for my {thing}", "why is my {thing} bill higher this month", "I need a refund for the {thing} payment",
   "update the credit card on my {thing}", "can you send me an invoice for {thing}", "there is a wrong charge on my statement for {thing}"],
 "tech_support": ["the {thing} keeps crashing when I open it", "I get an error message in the {thing} after the update",
   "{thing} is very slow and freezes", "how do I fix the {thing} not syncing", "the {thing} will not start since yesterday", "{thing} shows a blank screen"],
 "account_access": ["I cannot log in to my {thing}", "reset the password for my {thing}", "my {thing} is locked after too many attempts",
   "I lost my two factor code for {thing}", "change the email address on my {thing}", "I do not receive the verification code for {thing}"],
 "shipping": ["where is my {thing} package", "my {thing} order has not arrived yet", "the tracking for my {thing} shipment is stuck",
   "can I change the delivery address for the {thing}", "the {thing} arrived damaged in the box", "when will my {thing} be delivered"],
 "cancellation": ["I want to cancel my {thing} subscription", "please stop my {thing} renewal", "how do I close my {thing} plan",
   "end my {thing} membership at the end of the month", "I would like to unsubscribe from {thing}", "cancel the {thing} before it renews"],
}
THINGS = ["account","app","order","plan","laptop","phone","service","subscription","device","portal","router","card"]
PREF = ["", "", "hi, ", "hello, ", "please help: ", "quick question, ", "urgent: "]
SUF = ["", "", " thanks", " please", " asap", " can you help", " today"]
def typo(s):
    if random.random() < 0.15 and len(s) > 6:
        i = random.randrange(1, len(s)-1); s = s[:i] + s[i+1] + s[i] + s[i+2:]
    return s
def row(c):
    t = random.choice(CL[c]).format(thing=random.choice(THINGS))
    return {"text": typo(random.choice(PREF) + t + random.choice(SUF)), "label": c}
def gen(n):
    cs = list(CL); return [row(cs[i % 5]) for i in range(n)]
tr, te = gen(1000), gen(200); random.shuffle(tr); random.shuffle(te)
DOCS = {"billing": ["Billing and payments: charges, invoices, refunds and card updates.", "Payment help for wrong or duplicate charges and statements."],
 "tech_support": ["Technical support: crashes, errors, slow performance and sync problems.", "Troubleshooting software that will not start or freezes."],
 "account_access": ["Account access: login, password reset, locked accounts and verification codes.", "Sign-in help for two factor and email changes."],
 "shipping": ["Shipping and delivery: tracking, late or damaged packages and address changes.", "Order delivery status and parcel problems."],
 "cancellation": ["Cancellation: end a subscription, stop renewal or close a membership.", "Unsubscribe and plan termination requests."]}
os.makedirs("data", exist_ok=True)
for n, d in (("train", tr), ("test", te)):
    with open(f"data/{n}.jsonl", "w") as f:
        for r in d: f.write(json.dumps(r) + "\n")
json.dump(DOCS, open("data/docs.json", "w"), indent=1)
print(len(tr), len(te), sum(os.path.getsize(f"data/{x}.jsonl") for x in ("train","test")), "bytes")
