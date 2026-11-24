import re

DOCS = {
    "boiler-sop.md": "SOP-101 Boiler plant operation (Site HQ-1, Building A). If boiler pressure exceeds 30 psi, close the main steam valve, notify the duty engineer and raise a P1 work order. The pressure relief valve (PRV) must be inspected every 90 days. Record the inspection in the maintenance log. Never bypass the low-water cutoff. Boiler B-12 serves floors 1 to 6.",
    "elevator-sop.md": "SOP-215 Elevator faults. An elevator reporting door-zone faults must be taken out of service and tagged. Raise a P2 work order with the vendor. Passengers trapped in a car: call the vendor emergency line and keep security on the floor until released.",
    "fire-safety-sop.md": "SOP-310 Fire safety and evacuation. Fire alarm panels are tested monthly. When an alarm sounds, security must verify within 2 minutes and start evacuation of the affected zone. Fire extinguishers are inspected annually. Sprinkler valve closures require a P1 work order and a fire watch until restored.",
    "hvac-maintenance-manual.md": "MM-220 HVAC air handling unit maintenance manual (AHU-7). Replace the AHU-7 filter every 60 days or when differential pressure exceeds 250 Pa. Inspect belts and bearings quarterly. A supply air temperature drift greater than 3 degrees C indicates a failing chilled water valve. Raise a P2 work order for chilled water valve replacement. Spare valves are stocked in store room S-2.",
}
ASSETS = {
    "B-12": {"asset_id": "B-12", "name": "Boiler B-12", "site": "HQ-1", "type": "boiler", "status": "RUNNING", "pressure_psi": 34},
    "AHU-7": {"asset_id": "AHU-7", "name": "Air handling unit 7", "site": "HQ-1", "type": "hvac", "status": "DEGRADED"},
    "EL-3": {"asset_id": "EL-3", "name": "Elevator 3", "site": "HQ-2", "type": "elevator", "status": "RUNNING"},
}
WORK_ORDERS = [
    {"work_order_id": "WO-000101", "asset_id": "AHU-7", "title": "Replace AHU-7 filter", "priority": "P3", "status": "CLOSED"},
    {"work_order_id": "WO-000102", "asset_id": "B-12", "title": "Quarterly PRV inspection", "priority": "P2", "status": "OPEN"},
    {"work_order_id": "WO-000103", "asset_id": "EL-3", "title": "Door-zone sensor check", "priority": "P2", "status": "OPEN"},
]


def _words(s):
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def kb_search(query, top_k=3):
    """Keyword overlap over the four snippets (chapter 12 and 6 replace this with Vertex RAG Engine)."""
    ranked = sorted(DOCS.items(), key=lambda kv: -len(_words(query) & _words(kv[1])))
    return [{"source": "gs://facilities-docs/docs/" + name, "text": text} for name, text in ranked[:top_k]]


def asset_status(asset_id):
    asset = ASSETS.get(asset_id)
    if not asset:
        return {"found": False}
    return {"found": True, "asset": asset, "work_orders": [w for w in WORK_ORDERS if w["asset_id"] == asset_id]}


def work_order_stats():
    by = {}
    for w in WORK_ORDERS:
        by.setdefault(w["status"], {}).setdefault(w["priority"], 0)
        by[w["status"]][w["priority"]] += 1
    return {"total": len(WORK_ORDERS), "by_status_priority": by}
