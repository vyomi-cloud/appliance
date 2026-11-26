import json
import os
import azure.functions as func


def main(req: func.HttpRequest) -> func.HttpResponse:
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient
    body = req.get_json() if req.get_body() else {}
    sc = SearchClient(os.environ["SEARCH_ENDPOINT"], os.environ.get("SEARCH_INDEX", "facilities-kb"), AzureKeyCredential(os.environ["SEARCH_KEY"]))
    rows = sc.search(search_text=body.get("query", ""), top=int(body.get("top_k", os.environ.get("RAG_TOP_K", 3))))      # your design (chapter 14), set as the RAG_TOP_K app setting
    results = [{"text": r["content"], "score": r.get("@search.score"), "source": r.get("source") or r.get("title") or r["id"]} for r in rows]
    caller = req.headers.get("x-vyomi-caller") or "anonymous"      # set by the API Management gateway in chapter 1 after it validated the token
    return func.HttpResponse(json.dumps({"results": results, "caller": caller}), mimetype="application/json")
