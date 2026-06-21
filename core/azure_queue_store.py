"""Real Azure Storage Queue messages via Azurite.

Mirror of ``core/azure_blob_store`` for the Queue service: the simulator keeps
*speaking* the native Azure Queue REST surface to clients (so unmodified
``azure-storage-queue`` SDKs round-trip), but messages live in **Azurite** — the
official open-source Azure Storage emulator — so they survive simulator restarts
and use a real emulator (parity with MinIO/S3, fake-gcs/GCS, Azurite/Blob).

This is the **AMQP→HTTP substitution for Azure Service Bus**: the native Service
Bus SDK speaks AMQP 1.0 (which the appliance can't serve), so Azure messaging
conformance is delivered through the native HTTP ``azure-storage-queue`` SDK
instead — a different service, stated plainly, but a real native Azure queue SDK
with full runtime create/send/receive/delete.

If ``CLOUDLEARN_AZURITE_QUEUE_URL`` is unset/unreachable, callers degrade (the
native surface returns empty results rather than 500ing).

Storage model
-------------
The simulator supports arbitrary ``(space, account, queue)`` triples; Azurite
(default) only knows ``devstoreaccount1``. We map each onto a single,
always-valid Azurite queue name and keep the original simulator identifiers in
the Azurite queue's **metadata** so ``list_queues`` can recover them:

    azurite_queue = "vyomi-" + sha1(space|account|queue)[:28]   # always valid
    metadata      = {vyomisid, vyomiaccount, vyomiqueue}
"""
from __future__ import annotations

import hashlib
import os

# Azurite's well-known development account + key.
_WK_ACCOUNT = "devstoreaccount1"
_WK_KEY = ("Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/"
           "K1SZFPTOtr/KBHBeksoGMGw==")


def _base() -> str:
    return os.environ.get("CLOUDLEARN_AZURITE_QUEUE_URL", "").rstrip("/")


def available() -> bool:
    return bool(_base())


def _conn_str() -> str:
    return ("DefaultEndpointsProtocol=http;"
            f"AccountName={_WK_ACCOUNT};AccountKey={_WK_KEY};"
            f"QueueEndpoint={_base()}/{_WK_ACCOUNT};")


def _svc():
    from azure.storage.queue import QueueServiceClient
    return QueueServiceClient.from_connection_string(_conn_str())


def _azurite_queue(sid: str, account: str, queue: str) -> str:
    """Deterministic, always-valid Azurite queue name (lowercase alnum + hyphen,
    3-63 chars). Recomputed from (sid, account, queue) every time, so message
    ops never need a reverse lookup."""
    h = hashlib.sha1(f"{sid}|{account}|{queue}".encode("utf-8")).hexdigest()[:28]
    return "vyomi-" + h


def _qcli(sid: str, account: str, queue: str):
    return _svc().get_queue_client(_azurite_queue(sid, account, queue))


# ---------------------------------------------------------------------------
# Queue operations
# ---------------------------------------------------------------------------
def create_queue(sid: str, account: str, queue: str) -> None:
    """Create the backing Azurite queue (idempotent), tagging it with the
    simulator identifiers so list_queues can recover the original name."""
    from azure.core.exceptions import ResourceExistsError
    try:
        _qcli(sid, account, queue).create_queue(
            metadata={"vyomisid": sid, "vyomiaccount": account, "vyomiqueue": queue})
    except ResourceExistsError:
        pass


def delete_queue(sid: str, account: str, queue: str) -> bool:
    from azure.core.exceptions import ResourceNotFoundError
    try:
        _qcli(sid, account, queue).delete_queue()
        return True
    except ResourceNotFoundError:
        return False
    except Exception:
        return False


def list_queues(sid: str, account: str) -> list[str]:
    out: list[str] = []
    try:
        for q in _svc().list_queues(include_metadata=True):
            md = q.metadata or {}
            if md.get("vyomisid") == sid and md.get("vyomiaccount") == account:
                out.append(md.get("vyomiqueue") or str(q.name))
    except Exception:
        return []
    return sorted(out)


def send_message(sid: str, account: str, queue: str, text: str) -> dict:
    """Enqueue (auto-creating the queue if needed). Returns the Azurite-assigned
    message id / pop receipt / visibility times for the native XML response."""
    qc = _qcli(sid, account, queue)
    try:
        m = qc.send_message(text)
    except Exception:
        create_queue(sid, account, queue)
        m = qc.send_message(text)
    return {"id": m.id, "pop_receipt": m.pop_receipt, "content": text,
            "insertion_time": m.inserted_on, "expiration_time": m.expires_on,
            "time_next_visible": m.next_visible_on, "dequeue_count": 0}


def receive_messages(sid: str, account: str, queue: str,
                     num: int = 1, visibility: int = 30) -> list[dict]:
    out: list[dict] = []
    try:
        for m in _qcli(sid, account, queue).receive_messages(
                messages_per_page=num, visibility_timeout=visibility):
            out.append({"id": m.id, "pop_receipt": m.pop_receipt, "content": m.content,
                        "insertion_time": m.inserted_on, "expiration_time": m.expires_on,
                        "time_next_visible": m.next_visible_on,
                        "dequeue_count": int(getattr(m, "dequeue_count", 1) or 1)})
            if len(out) >= num:
                break
    except Exception:
        return []
    return out


def delete_message(sid: str, account: str, queue: str,
                   message_id: str, pop_receipt: str) -> bool:
    try:
        _qcli(sid, account, queue).delete_message(message_id, pop_receipt)
        return True
    except Exception:
        return False
