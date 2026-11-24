import os

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter


def handler(request):
    body = request.get_json(silent=True) or {}
    db = firestore.Client(project=os.environ["GOOGLE_CLOUD_PROJECT"])
    snap = db.collection(os.environ.get("ASSETS_COLLECTION", "assets")).document(body["asset_id"]).get()
    if not snap.exists:
        return {"found": False}
    orders = db.collection(os.environ.get("WORK_ORDERS_COLLECTION", "work-orders")).where(filter=FieldFilter("asset_id", "==", body["asset_id"])).stream()
    return {"found": True, "asset": snap.to_dict(), "work_orders": [d.to_dict() for d in orders]}
