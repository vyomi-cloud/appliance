"""Read-only tool: knowledge search (Azure AI Search). HTTP trigger; also the backend behind the APIM gateway."""
import json
import azure.functions as func
from tools import kb_search


def main(req: func.HttpRequest) -> func.HttpResponse:
    body = req.get_json() if req.get_body() else {}
    caller = req.headers.get("x-vyomi-caller") or "anonymous"     # set by the APIM gateway policy after validate-jwt
    return func.HttpResponse(json.dumps(dict(kb_search(body), caller=caller)), mimetype="application/json")
