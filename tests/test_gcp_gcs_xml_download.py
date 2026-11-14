"""GCS XML API download (`GET /{bucket}/{object}`): google-cloud-storage (Go) reads objects
this way against STORAGE_EMULATOR_HOST. A GCS bucket must be served, not 404 as an S3 NoSuchBucket
(GCS state is provider-scoped; the S3 catch-all used to look in the default AWS space)."""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path

_D = Path(tempfile.mkdtemp(prefix="vyomi-gcsxml-"))
os.environ.setdefault("CLOUDLEARN_STATE_FILE", str(_D / "state.sqlite3"))
os.environ.setdefault("CLOUDLEARN_LEGACY_STATE_FILE", str(_D / "state.pkl"))
os.environ.setdefault("VYOMI_NO_TELEMETRY", "1")
os.environ["CLOUDLEARN_TIER_ENFORCE"] = "0"
os.environ.setdefault("CLOUDLEARN_MINIO_URL", "http://127.0.0.1:1")

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402


def test_xml_get_serves_gcs_object_and_misses_stay_404():
    b = "gx-" + uuid.uuid4().hex[:8]
    with TestClient(server.app) as c:
        r = c.post("/storage/v1/b?project=vyomi-project", content=json.dumps({"name": b}),
                   headers={"content-type": "application/json"})
        assert r.status_code == 200, r.text
        r = c.post(f"/upload/storage/v1/b/{b}/o?uploadType=media&name=dir/g.txt", content=b"hello-xml",
                   headers={"content-type": "text/plain"})
        assert r.status_code == 200, r.text
        r = c.get(f"/{b}/dir/g.txt")
        assert r.status_code == 200 and r.content == b"hello-xml", r.text
        assert c.get(f"/{b}/missing.txt").status_code == 404
        assert c.get(f"/nobucket-{b}/x").status_code == 404
