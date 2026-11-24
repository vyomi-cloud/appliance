"""Learner progress, stored locally (JSON). One file per learner machine; nothing leaves it."""
import json
import os
import tempfile
import threading
import time

_LOCK = threading.Lock()


def _path():
    home = os.environ.get("VYOMILABS_HOME") or os.path.join(os.path.expanduser("~"), ".vyomilabs")
    os.makedirs(home, exist_ok=True)
    return os.path.join(home, "progress.json")


def load():
    try:
        with open(_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(data):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(_path()), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, _path())


def record(layer_id, status, steps):
    with _LOCK:
        data = load()
        key = str(layer_id)
        entry = data.get(key, {})
        entry["status"] = status
        entry["checked_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        entry["attempts"] = int(entry.get("attempts", 0)) + 1
        entry["steps"] = [{"name": s["name"], "status": s["status"], "detail": s["detail"]} for s in steps]
        if status == "PASS" and not entry.get("passed_at"):
            entry["passed_at"] = entry["checked_at"]
        data[key] = entry
        _save(data)
        return entry


def reset(layer_id=None):
    with _LOCK:
        data = load()
        if layer_id is None:
            data = {}
        else:
            data.pop(str(layer_id), None)
        _save(data)
        return data
