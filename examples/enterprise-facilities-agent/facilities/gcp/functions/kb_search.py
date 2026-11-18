"""Read-only tool: knowledge search (Vertex RAG Engine retrieveContexts). HTTP function; also the backend behind API Gateway."""
import base64, json
from tools import kb_search


def handler(request):
    body = request.get_json(silent=True) or {}
    caller = "anonymous"
    info = request.headers.get("X-Apigateway-Api-Userinfo")      # set by API Gateway after it validated the JWT
    if info:
        try:
            caller = json.loads(base64.urlsafe_b64decode(info + "=" * (-len(info) % 4))).get("email", "anonymous")
        except Exception:
            pass
    return dict(kb_search(body), caller=caller)
