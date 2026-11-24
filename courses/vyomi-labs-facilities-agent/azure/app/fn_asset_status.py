import json
import os
import azure.functions as func


def _table(name):
    from azure.data.tables import TableClient
    return TableClient.from_connection_string(os.environ["TABLE_CONNECTION_STRING"], name)


def _clean(d):
    return {k: v for k, v in d.items() if k not in ("PartitionKey", "RowKey", "Timestamp") and not hasattr(v, "isoformat")}


def main(req: func.HttpRequest) -> func.HttpResponse:
    from azure.core.exceptions import ResourceNotFoundError
    body = req.get_json() if req.get_body() else {}
    aid = body["asset_id"]
    try:
        asset = dict(_table(os.environ.get("ASSETS_TABLE", "assets")).get_entity("asset", aid))
    except ResourceNotFoundError:
        return func.HttpResponse(json.dumps({"found": False}), mimetype="application/json")
    wos = [dict(e) for e in _table(os.environ.get("WORK_ORDERS_TABLE", "workorders")).query_entities("asset_id eq @a", parameters={"a": aid})]
    return func.HttpResponse(json.dumps({"found": True, "asset": _clean(asset), "work_orders": [_clean(w) for w in wos]}), mimetype="application/json")
