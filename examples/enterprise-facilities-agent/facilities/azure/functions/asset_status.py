"""Read-only tool: asset + work orders from Azure Table storage."""
import json
import azure.functions as func
from tools import asset_status


def main(req: func.HttpRequest) -> func.HttpResponse:
    body = req.get_json() if req.get_body() else {}
    return func.HttpResponse(json.dumps(asset_status(body)), mimetype="application/json")
