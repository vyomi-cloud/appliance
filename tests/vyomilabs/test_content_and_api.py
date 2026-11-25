"""Vyomi Labs: content integrity for all three clouds, progress store and API. No simulator needed."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from vyomilabs import CONTENT_DIR, WEB_DIR, checks, layers, progress  # noqa: E402

CLOUDS = ("aws", "gcp", "azure")


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("VYOMILABS_HOME", str(tmp_path))


def _doc(cloud):
    return json.load(open(os.path.join(CONTENT_DIR, cloud + ".json"), encoding="utf-8"))


@pytest.mark.parametrize("cloud", CLOUDS)
def test_fourteen_layers_same_across_clouds(cloud):
    d = _doc(cloud)
    assert sorted(x["id"] for x in d["layers"]) == list(range(1, 15))
    assert [x["id"] for x in d["layers"]] == [x["id"] for x in _doc("aws")["layers"]], "same build order on every cloud"
    assert [x["order"] for x in d["layers"]] == list(range(1, 15))


@pytest.mark.parametrize("cloud", CLOUDS)
def test_every_chapter_is_complete_and_honest(cloud):
    for x in _doc(cloud)["layers"]:
        for k in ("objective", "learn", "services", "build", "checks", "simplified"):
            assert x[k], f"{cloud} layer {x['id']} missing {k}"
        assert x["reference"].startswith("examples/enterprise-facilities-agent/facilities/")


@pytest.mark.parametrize("cloud", CLOUDS)
def test_hotspots_inside_image_and_image_exists(cloud):
    d = _doc(cloud)
    w, h = d["image_size"]
    assert os.path.exists(os.path.join(WEB_DIR, d["image"]))
    for x in d["layers"]:
        x1, y1, x2, y2 = x["hotspot"]
        assert 0 <= x1 < x2 <= w and 0 <= y1 < y2 <= h


@pytest.mark.parametrize("cloud", CLOUDS)
def test_reference_files_exist(cloud):
    base = os.path.join(os.path.dirname(WEB_DIR), "..")
    for x in _doc(cloud)["layers"]:
        assert os.path.exists(os.path.join(base, x["reference"])), x["reference"]


def test_cloud_native_services_differ_and_gaps_are_declared():
    aws, gcp, az = (_doc(c) for c in CLOUDS)
    assert "Amazon Bedrock Runtime" in aws["layers"][0]["services"][0] and "Vertex" in gcp["layers"][0]["services"][0] and "Azure OpenAI" in az["layers"][0]["services"][0]
    by = {x["id"]: x for x in az["layers"]}
    assert by[9]["native"] and "no managed long-term memory" in by[9]["native"].lower()
    assert "Cedar" in by[4]["simplified"][0]


def test_progress_roundtrip_and_next_layer():
    assert layers.next_layer(progress.load()) == 10
    progress.record(10, "PASS", [{"name": "a", "status": "PASS", "detail": ""}])
    assert layers.next_layer(progress.load()) == 3
    progress.reset(10)
    assert layers.next_layer(progress.load()) == 10


def test_checkers_registered():
    assert {2, 10} <= set(checks.available())


def test_api_course_layer_and_static_labs():
    from fastapi.testclient import TestClient
    from vyomilabs.server import create_app
    c = TestClient(create_app("http://127.0.0.1:1"))
    d = c.get("/api/course").json()
    assert d["total"] == 14 and d["done"] == 0 and d["next"] == 10
    assert c.get("/api/health").json()["ok"] is True
    assert c.get("/api/layers/5").json()["title"].startswith("Actions")
    assert c.get("/api/layers/99").status_code == 404
    assert c.get("/").status_code == 200 and c.get("/data/gcp.json").status_code == 200 and c.get("/img/azure.svg").status_code == 200
