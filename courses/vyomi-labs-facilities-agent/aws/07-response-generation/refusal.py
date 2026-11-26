import re

import boto3

import vymodels

STOP = set("what when where which who whom whose how why does did the and for are was were with that this from have has had will shall should would could into than then them they their there about above below your you our not but can may might must any all out off over under again further once only own same too very just also".split())
ag, rt = boto3.client("bedrock-agent"), boto3.client("bedrock-agent-runtime")
kb = next(k for k in ag.list_knowledge_bases()["knowledgeBaseSummaries"] if k["name"] == "facilities-kb")["knowledgeBaseId"]


def content_words(text):
    return {w for w in re.findall(r"[a-z0-9\-]+", text.lower()) if len(w) > 2 and w not in STOP}


def answer(question):
    hits = rt.retrieve(knowledgeBaseId=kb, retrievalQuery={"text": question},
                       retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 3}})["retrievalResults"]
    evidence = set().union(*[content_words(h["content"]["text"]) for h in hits]) if hits else set()
    support = content_words(question) & evidence
    if not support:                                            # nothing in the documents mentions what was asked: refuse, do not guess
        return {"refused": True, "answer": "I cannot find that in the facilities documents.", "citations": []}
    context = "\n\n".join(h["content"]["text"] for h in hits)
    reply = vymodels.chat("Answer ONLY from the context and cite it.\n\nContext:\n%s\n\nQuestion: %s" % (context, question))
    return {"refused": False, "answer": reply, "citations": [h["location"]["s3Location"]["uri"] for h in hits], "support": sorted(support)}


if __name__ == "__main__":
    calls = vymodels.BUDGET.calls
    for q in ("What is the CEO's salary?", "Who won the football match yesterday?", "qwxz plmk"):
        r = answer(q)
        assert r["refused"] and not r["citations"], "an unanswerable question must be refused: %r" % q
        print("refused:", q)
    assert vymodels.BUDGET.calls == calls, "a refusal must not spend a model call"
    r = answer("What should I do when boiler pressure exceeds 30 psi?")
    assert not r["refused"] and r["citations"] and any("boiler-sop" in c for c in r["citations"]), r
    print("answered with evidence", r["support"], "and cited", sorted(set(r["citations"]))[0])
    print("refusal verified")
