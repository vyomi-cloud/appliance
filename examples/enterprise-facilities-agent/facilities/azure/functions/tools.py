"""Shared tool logic for the Function App functions (kb-search over Azure AI Search, asset-status over Azure Table storage).
Plain Azure client code that runs unchanged on real Azure: the endpoints and keys come from application settings (environment variables), which on real
Azure would be Key Vault references or a managed identity."""
import os


def _table(name):
    from azure.data.tables import TableClient
    return TableClient.from_connection_string(os.environ["TABLE_CONNECTION_STRING"], name)


def kb_search(args):
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient
    sc = SearchClient(os.environ["SEARCH_ENDPOINT"], os.environ.get("SEARCH_INDEX", "facilities-kb"), AzureKeyCredential(os.environ["SEARCH_KEY"]))
    rows = sc.search(search_text=args.get("query", ""), top=int(args.get("top_k", 3)))
    return {"results": [{"text": r["content"], "score": r.get("@search.score"), "source": r.get("source") or r.get("title") or r["id"]} for r in rows]}


def asset_status(args):
    from azure.core.exceptions import ResourceNotFoundError
    aid = args["asset_id"]
    try:
        asset = dict(_table(os.environ.get("ASSETS_TABLE", "assets")).get_entity("asset", aid))
    except ResourceNotFoundError:
        return {"found": False}
    wos = [dict(e) for e in _table(os.environ.get("WORK_ORDERS_TABLE", "workorders")).query_entities("asset_id eq @a", parameters={"a": aid})]
    clean = lambda d: {k: v for k, v in d.items() if k not in ("PartitionKey", "RowKey", "Timestamp") and not hasattr(v, "isoformat")}
    return {"found": True, "asset": clean(asset), "work_orders": [clean(w) for w in wos]}
