import boto3

import rag_design

ag = boto3.client("bedrock-agent")
rt = boto3.client("bedrock-agent-runtime")
kb = next(k for k in ag.list_knowledge_bases()["knowledgeBaseSummaries"] if k["name"] == "facilities-kb")["knowledgeBaseId"]


def search(q, k=None):
    cfg = {"numberOfResults": k or rag_design.top_k()}                 # your design: how many passages
    if rag_design.search_type() != "vector":
        cfg["overrideSearchType"] = "HYBRID"                           # Bedrock has two modes: SEMANTIC (vector) and HYBRID (vector plus keyword)
    return rt.retrieve(knowledgeBaseId=kb, retrievalQuery={"text": q},
                       retrievalConfiguration={"vectorSearchConfiguration": cfg})["retrievalResults"]


def uri(hit):
    return hit.get("location", {}).get("s3Location", {}).get("uri", "")


if __name__ == "__main__":
    r = search("What should I do when boiler pressure exceeds 30 psi?")
    print("boiler question, top hit:", uri(r[0]), "score", r[0].get("score"))
    print("  text:", r[0]["content"]["text"][:90].replace("\n", " "))
    r = search("AHU-7 supply air temperature drift chilled water valve")
    print("AHU question, top hit:", uri(r[0]))
    r = search("fire alarm evacuation")
    print("every hit has text and a source:", all(x["content"]["text"] and uri(x) for x in r))
