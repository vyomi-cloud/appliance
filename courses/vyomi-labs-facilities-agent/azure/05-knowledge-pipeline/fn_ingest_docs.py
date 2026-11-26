import json
import os
import azure.functions as func


def main(req: func.HttpRequest) -> func.HttpResponse:
    events = req.get_json() if req.get_body() else []
    events = events if isinstance(events, list) else [events]
    out = lambda d: func.HttpResponse(json.dumps(d), mimetype="application/json")
    for ev in events:
        if ev.get("eventType") == "Microsoft.EventGrid.SubscriptionValidationEvent":
            return out({"validationResponse": ev["data"]["validationCode"]})
    ran = []
    for ev in events:
        if ev.get("eventType") != "Microsoft.Storage.BlobCreated":
            continue
        from azure.core.credentials import AzureKeyCredential
        from azure.search.documents.indexes import SearchIndexerClient
        SearchIndexerClient(os.environ["SEARCH_ENDPOINT"], AzureKeyCredential(os.environ["SEARCH_KEY"])).run_indexer(os.environ.get("INDEXER_NAME", "docs-indexer"))
        ran.append(ev.get("subject", ""))
    return out({"received": len(events), "indexer_runs": ran})
