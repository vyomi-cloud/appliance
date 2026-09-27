"""console-next (P0) — the fidelity-first console redesign vertical.

Additive routes for the new Lit-based console engine. Coexists with the existing
static/*-console.html consoles; touches none of them.

Endpoints added here:
  GET  /api/console/capabilities        — the capability manifest (§15.1). The UI
                                           reads it and gates on it — NO substrate/
                                           cloud branching in components (§15.2).
  GET  /api/console/calls               — one-shot ring-buffer snapshot (newest-first)
  GET  /api/console/calls/stream        — SSE stream of captured calls (§12.3)
  POST /api/console/calls/clear         — clear the ring buffer (dev convenience)
  GET  /console-next[/...]              — the SPA shell (index.html)

Static assets for the SPA are served from the /console-next-assets mount so that
asset refs are base-path-relative and the same bundle can be served under a subpath
(Nano's /nano/ scope) — §15.1 guarantee #6.
"""

from __future__ import annotations

import os

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

_HERE = os.path.dirname(__file__)
_ASSETS_DIR = os.path.join(_HERE, "..", "static", "console-next")
_INDEX = os.path.join(_ASSETS_DIR, "index.html")


def _capabilities() -> dict:
    """Return the runtime capability manifest for THIS substrate (§15.1).

    On the local FastAPI substrate S3 is backed by real MinIO, so object-browser is
    "full"; there is a real endpoint (not a relay); SSH exists on real compute. The
    other widgets are declared per their conformance/backing status. The UI degrades
    purely from these flags — it never checks the substrate name.
    """
    from core import console_conformance as conf

    substrate = os.environ.get("VYOMI_SUBSTRATE", "local")  # local | codespaces | nano
    connect_mode = os.environ.get("VYOMI_CONNECT_MODE", "endpoint")  # endpoint | ssh | relay

    # ── Conformance-driven widget modes (§14.5) ──
    # The rich widget for a service renders ONLY when its widget mode is "full";
    # otherwise the center-canvas falls back to generic-control-plane. The per-service
    # mode comes from the conformance signal (core/console_conformance.py) so the gate
    # is honest and there is no substrate branching — the UI reads these flags.
    svc_modes = conf.widget_modes()  # service_id -> full|degraded|generic
    # Map the service-level conformance mode onto each service's WIDGET id.
    svc_to_widget = {"s3": "object-browser", "dynamodb": "nosql-item-viewer",
                     "rds": "sql-console", "sqs": "queue-topic-viewer",
                     "secretsmanager": "kv-secret-viewer",
                     "kms": "kms-crypto-view",
                     "ec2": "compute-terminal",
                     "lambda": "serverless-invoke",
                     "iam": "generic-control-plane"}
    widgets = {
        "object-browser": "generic", "sql-console": "generic",
        "compute-terminal": "generic", "serverless-invoke": "generic",
        "nosql-item-viewer": "generic", "kv-secret-viewer": "generic",
        "kms-crypto-view": "generic", "queue-topic-viewer": "generic",
        "generic-control-plane": "full",
    }
    for sid, wid in svc_to_widget.items():
        if wid in widgets:
            widgets[wid] = svc_modes.get(sid, "generic")

    return {
        "substrate": substrate,
        "cloud_lenses": ["aws"],  # lenses with a rich data-plane in this vertical
        "widgets": widgets,
        "features": {
            "glassbox": True,      # Calls tab is live in P0
            "snapshot": False,     # P2
            "fork": False,         # P2
            "replay": False,       # P2
            "relay": substrate == "nano",
            "ssh": substrate == "local" and connect_mode == "ssh",
        },
        "connect": {"mode": connect_mode},
        # The service rail is generated from this catalog — the shell renders only
        # these services, each mapped to a widget the manifest above gates. Each
        # carries its per-service conformance signal so the rail + widgets show the
        # honest state (§14.5).
        "services": [
            {"id": "s3", "label": "S3", "icon": "▤", "widget": "object-browser",
             "terminology": "bucket", "backed_by": "MinIO",
             "conformance": conf.service_signal("s3")},
            {"id": "dynamodb", "label": "DynamoDB", "icon": "⊞", "widget": "nosql-item-viewer",
             "terminology": "table", "backed_by": "DynamoDB-Local",
             "conformance": conf.service_signal("dynamodb")},
            {"id": "rds", "label": "RDS", "icon": "◫", "widget": "sql-console",
             "terminology": "db instance", "backed_by": "PostgreSQL/sqlite",
             "conformance": conf.service_signal("rds")},
            {"id": "sqs", "label": "SQS + SNS", "icon": "⇄", "widget": "queue-topic-viewer",
             "terminology": "queue / topic", "backed_by": "in-proc messaging",
             "conformance": conf.service_signal("sqs")},
            {"id": "secretsmanager", "label": "Secrets Manager", "icon": "⚿",
             "widget": "kv-secret-viewer", "terminology": "secret",
             "backed_by": "in-proc KvStore",
             "conformance": conf.service_signal("secretsmanager")},
            {"id": "kms", "label": "KMS", "icon": "🔑", "widget": "kms-crypto-view",
             "terminology": "key", "backed_by": "in-proc KmsEngine",
             "conformance": conf.service_signal("kms")},
            {"id": "ec2", "label": "EC2", "icon": "🖥", "widget": "compute-terminal",
             "terminology": "instance", "backed_by": "Docker/LXD",
             "conformance": conf.service_signal("ec2")},
            {"id": "lambda", "label": "Lambda", "icon": "ƒ", "widget": "serverless-invoke",
             "terminology": "function", "backed_by": "in-proc runtime",
             "conformance": conf.service_signal("lambda")},
            {"id": "iam", "label": "IAM", "icon": "◆", "widget": "generic-control-plane",
             "terminology": "policy", "backed_by": "in-proc",
             "conformance": conf.service_signal("iam")},
        ],
        # Workspace-level conformance summary for the status-bar pill (§4): flat
        # {services_total, services_full, checks_passed, checks_total, status}.
        "conformance": conf.summary(),
        "workspace": {
            "name": os.environ.get("VYOMI_WORKSPACE_NAME", "vyomi-dev-01"),
            "endpoint": os.environ.get("VYOMI_S3_ENDPOINT", ""),
        },
        "glassbox": {
            "event_schema_version": 1,
            "ring_max": int(os.environ.get("VYOMI_GLASSBOX_RING", "500") or "500"),
        },
    }


def register(app: FastAPI) -> None:
    # ── Static assets for the SPA ──
    if os.path.isdir(_ASSETS_DIR):
        app.mount("/console-next-assets",
                  StaticFiles(directory=_ASSETS_DIR),
                  name="console-next-assets")

    # ── Capability manifest (§15.1) ──
    @app.get("/api/console/capabilities", include_in_schema=False)
    def api_console_capabilities():
        return JSONResponse(_capabilities())

    # ── Glass-box: one-shot buffer snapshot ──
    @app.get("/api/console/calls", include_in_schema=False)
    def api_console_calls(limit: int = Query(default=200, ge=1, le=2000)):
        from core.glassbox import RING
        return JSONResponse({"calls": RING.snapshot(limit=limit)})

    # ── Glass-box: SSE stream (§12.3) ──
    @app.get("/api/console/calls/stream", include_in_schema=False)
    async def api_console_calls_stream(replay: int = Query(default=50, ge=0, le=500)):
        from core.glassbox import sse_stream
        return StreamingResponse(
            sse_stream(replay=replay),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.post("/api/console/calls/clear", include_in_schema=False)
    def api_console_calls_clear():
        from core.glassbox import RING
        RING.clear()
        return {"ok": True}

    # ── Conformance signal (F5 seam) — per-service + workspace rollup. The pill
    #    reads the rollup; the widgets/rail read per-service. Stubbed source today
    #    (core/console_conformance.py), live-runner-ready shape. ──
    @app.get("/api/console/conformance", include_in_schema=False)
    def api_console_conformance():
        from core import console_conformance as conf
        return {"rollup": conf.rollup(), "services": conf.all_signals()}

    # ── RDS sql-console (§13.4): relay-safe SQL via the RDS Data API core ──
    @app.get("/api/console/rds/databases", include_in_schema=False)
    def api_console_rds_databases():
        from core import console_sql
        return console_sql.list_databases()

    @app.post("/api/console/rds/execute", include_in_schema=False)
    async def api_console_rds_execute(payload: dict = Body(default=None)):
        from core import console_sql
        payload = payload or {}
        sql = (payload.get("sql") or "").strip()
        if not sql:
            raise HTTPException(400, detail="ValidationError sql is required")
        return await console_sql.execute(payload.get("db") or "",
                                         sql, payload.get("parameters"))

    @app.get("/api/console/rds/databases/{db_id}/schema", include_in_schema=False)
    async def api_console_rds_schema(db_id: str):
        from core import console_sql
        return await console_sql.schema(db_id)

    # ── SQS + SNS queue/topic-viewer (§13): ONE shared MessagingStore so the widget
    #    can show REAL SNS→SQS fan-out. Drives core/sqs_core + core/sns_core. ──
    def _msg():
        from core import console_messaging as m
        return m

    def _guard(fn):
        from core.console_messaging import MessagingError
        try:
            return fn()
        except MessagingError as e:
            raise HTTPException(e.status, detail=e.message)

    @app.get("/api/console/messaging/queues", include_in_schema=False)
    def api_console_mq_list():
        return _msg().list_queues()

    @app.post("/api/console/messaging/queues", include_in_schema=False)
    def api_console_mq_create(payload: dict = Body(default=None)):
        name = (payload or {}).get("name", "").strip()
        if not name:
            raise HTTPException(400, detail="ValidationError name is required")
        return _guard(lambda: _msg().create_queue(name))

    @app.delete("/api/console/messaging/queues/{name}", include_in_schema=False)
    def api_console_mq_delete(name: str):
        return _guard(lambda: _msg().delete_queue(name))

    @app.post("/api/console/messaging/queues/{name}/send", include_in_schema=False)
    def api_console_mq_send(name: str, payload: dict = Body(default=None)):
        body = (payload or {}).get("body", "")
        return _guard(lambda: _msg().send_message(name, body))

    @app.post("/api/console/messaging/queues/{name}/receive", include_in_schema=False)
    def api_console_mq_receive(name: str, payload: dict = Body(default=None)):
        p = payload or {}
        return _guard(lambda: _msg().receive_messages(
            name, int(p.get("max", 10)), int(p.get("visibility", 0))))

    @app.get("/api/console/messaging/queues/{name}/peek", include_in_schema=False)
    def api_console_mq_peek(name: str):
        return _guard(lambda: _msg().peek_messages(name))

    @app.post("/api/console/messaging/queues/{name}/purge", include_in_schema=False)
    def api_console_mq_purge(name: str):
        return _guard(lambda: _msg().purge_queue(name))

    @app.get("/api/console/messaging/topics", include_in_schema=False)
    def api_console_topics_list():
        return _msg().list_topics()

    @app.post("/api/console/messaging/topics", include_in_schema=False)
    def api_console_topics_create(payload: dict = Body(default=None)):
        name = (payload or {}).get("name", "").strip()
        if not name:
            raise HTTPException(400, detail="ValidationError name is required")
        return _guard(lambda: _msg().create_topic(name))

    # Topic ARNs contain ':' (and are awkward in a path segment), so the ARN travels
    # in the body/query for topic sub-operations — keeps the routes unambiguous.
    @app.post("/api/console/messaging/topics/delete", include_in_schema=False)
    def api_console_topics_delete(payload: dict = Body(default=None)):
        arn = (payload or {}).get("topic_arn", "").strip()
        return _guard(lambda: _msg().delete_topic(arn))

    @app.get("/api/console/messaging/topics/subscriptions", include_in_schema=False)
    def api_console_topics_subs(topic_arn: str = Query(...)):
        return _guard(lambda: _msg().list_subscriptions(topic_arn))

    @app.post("/api/console/messaging/topics/subscribe", include_in_schema=False)
    def api_console_topics_subscribe(payload: dict = Body(default=None)):
        p = payload or {}
        arn = p.get("topic_arn", "").strip()
        queue = p.get("queue", "").strip()
        if not arn or not queue:
            raise HTTPException(400, detail="ValidationError topic_arn and queue are required")
        return _guard(lambda: _msg().subscribe_queue(arn, queue))

    @app.post("/api/console/messaging/topics/publish", include_in_schema=False)
    def api_console_topics_publish(payload: dict = Body(default=None)):
        p = payload or {}
        arn = p.get("topic_arn", "").strip()
        if not arn:
            raise HTTPException(400, detail="ValidationError topic_arn is required")
        return _guard(lambda: _msg().publish(arn, p.get("message", ""), p.get("subject")))

    # ── Secrets Manager kv-secret-viewer (§13): clean JSON facade over the
    #    substrate-agnostic secrets_core + a shared KvStore (core/console_secrets).
    #    Values are only fetched on a deliberate reveal; the widget masks by default.
    def _sec():
        from core import console_secrets as s
        return s

    def _sguard(fn):
        from core.console_secrets import SecretsError
        try:
            return fn()
        except SecretsError as e:
            raise HTTPException(e.status, detail=e.message)

    @app.get("/api/console/secrets", include_in_schema=False)
    def api_console_secrets_list():
        return _sguard(lambda: _sec().list_secrets())

    @app.post("/api/console/secrets", include_in_schema=False)
    def api_console_secrets_create(payload: dict = Body(default=None)):
        p = payload or {}
        name = (p.get("name") or "").strip()
        if not name:
            raise HTTPException(400, detail="ValidationError name is required")
        return _sguard(lambda: _sec().create_secret(
            name, p.get("secret_string", ""), (p.get("description") or "").strip()))

    @app.get("/api/console/secrets/{name}", include_in_schema=False)
    def api_console_secrets_describe(name: str):
        return _sguard(lambda: _sec().describe_secret(name))

    @app.delete("/api/console/secrets/{name}", include_in_schema=False)
    def api_console_secrets_delete(name: str):
        return _sguard(lambda: _sec().delete_secret(name))

    @app.get("/api/console/secrets/{name}/value", include_in_schema=False)
    def api_console_secrets_value(name: str,
                                  version_id: str = Query(default=None),
                                  version_stage: str = Query(default=None)):
        return _sguard(lambda: _sec().get_secret_value(name, version_id, version_stage))

    @app.post("/api/console/secrets/{name}/value", include_in_schema=False)
    def api_console_secrets_put(name: str, payload: dict = Body(default=None)):
        p = payload or {}
        return _sguard(lambda: _sec().put_secret_value(name, p.get("secret_string", "")))

    # ── KMS kms-crypto-view (§13): clean JSON facade over the substrate-agnostic
    #    kms_core + a shared KeyStore (core/console_kms). Reuses the REAL crypto core
    #    (no fake crypto); plaintext/ciphertext cross the wire base64-encoded (the
    #    native KMS shape). Purely additive — touches no existing KMS handlers.
    def _kms():
        from core import console_kms as k
        return k

    def _kguard(fn):
        from core.console_kms import KmsError
        try:
            return fn()
        except KmsError as e:
            raise HTTPException(e.status, detail=e.message)

    @app.get("/api/console/kms/keys", include_in_schema=False)
    def api_console_kms_list():
        return _kguard(lambda: _kms().list_keys())

    @app.post("/api/console/kms/keys", include_in_schema=False)
    def api_console_kms_create(payload: dict = Body(default=None)):
        p = payload or {}
        return _kguard(lambda: _kms().create_key((p.get("description") or "").strip()))

    @app.get("/api/console/kms/keys/{key_id}", include_in_schema=False)
    def api_console_kms_describe(key_id: str):
        return _kguard(lambda: _kms().describe_key(key_id))

    @app.post("/api/console/kms/encrypt", include_in_schema=False)
    def api_console_kms_encrypt(payload: dict = Body(default=None)):
        p = payload or {}
        key_id = (p.get("key_id") or "").strip()
        if not key_id:
            raise HTTPException(400, detail="ValidationError key_id is required")
        return _kguard(lambda: _kms().encrypt(key_id, p.get("plaintext", "")))

    @app.post("/api/console/kms/decrypt", include_in_schema=False)
    def api_console_kms_decrypt(payload: dict = Body(default=None)):
        p = payload or {}
        blob = p.get("ciphertext_blob", "")
        if not blob:
            raise HTTPException(400, detail="ValidationError ciphertext_blob is required")
        return _kguard(lambda: _kms().decrypt(blob, (p.get("key_id") or "").strip() or None))

    @app.post("/api/console/kms/data-key", include_in_schema=False)
    def api_console_kms_data_key(payload: dict = Body(default=None)):
        p = payload or {}
        key_id = (p.get("key_id") or "").strip()
        if not key_id:
            raise HTTPException(400, detail="ValidationError key_id is required")
        return _kguard(lambda: _kms().generate_data_key(key_id, p.get("key_spec", "AES_256")))

    # ── The SPA shell — serves index.html at /console-next and any sub-path so the
    #    client-side router can own deep-links. Asset refs inside index.html are
    #    relative to /console-next-assets/, base-path-friendly. ──
    @app.get("/console-next", include_in_schema=False)
    @app.get("/console-next/", include_in_schema=False)
    @app.get("/console-next/{path:path}", include_in_schema=False)
    def console_next_spa(path: str = ""):
        try:
            with open(_INDEX, "rb") as f:
                html = f.read().decode("utf-8")
        except FileNotFoundError:
            return HTMLResponse("<h1>console-next not built</h1>", status_code=500)
        return HTMLResponse(content=html, headers={"Cache-Control": "no-store, max-age=0"})
