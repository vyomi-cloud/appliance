"""Read-only tool: asset + work orders from Firestore."""
from tools import asset_status


def handler(request):
    return asset_status(request.get_json(silent=True) or {})
