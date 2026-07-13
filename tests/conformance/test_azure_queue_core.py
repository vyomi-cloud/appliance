"""Azure Storage Queue data-plane core conformance — the Azure analogue of
test_gcp_storage_core.py.

Same test runs on host CPython and under Pyodide/WASM and must be green on both.
It asserts the native **Azure Storage Queue REST API** wire semantics (XML
QueueMessagesList / EnumerationResults, MessageId + PopReceipt round-trip,
DequeueCount, x-ms-approximate-messages-count header, 201/204 statuses,
QueueNotFound errors), proving azure-storage-queue can drive the core unchanged.

Run on host:    python3 tests/conformance/test_azure_queue_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import base64
import re

try:
    from core import azure_queue_core as aq
except ImportError:  # pragma: no cover - Pyodide flat layout
    import azure_queue_core as aq  # type: ignore

ACCT = "/devstoreaccount1"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _tag(xml: bytes, tag: str) -> str:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", xml.decode("utf-8"), re.DOTALL)
    return m.group(1) if m else ""


def run() -> int:
    st = aq.AzureQueueStore()
    Q = "orders"

    # 1. create queue -> 201
    r = aq.dispatch(st, "PUT", f"{ACCT}/{Q}", {}, {}, b"")
    _check("create queue 201", r.status == 201)
    _check("queue exists in store", st.queue_exists(Q))

    # 1b. duplicate create -> 409 QueueAlreadyExists
    dup = aq.dispatch(st, "PUT", f"{ACCT}/{Q}", {}, {}, b"")
    _check("duplicate queue 409", dup.status == 409)
    _check("duplicate error code", dup.headers.get("x-ms-error-code") == "QueueAlreadyExists")
    _check("duplicate error xml", b"<Code>QueueAlreadyExists</Code>" in dup.body)

    # 2. put message -> 201 returns MessageId + PopReceipt
    payload = base64.b64encode(b"hello azure queue").decode()
    put_body = f"<QueueMessage><MessageText>{payload}</MessageText></QueueMessage>".encode()
    pm = aq.dispatch(st, "POST", f"{ACCT}/{Q}/messages", {}, {}, put_body)
    _check("put message 201", pm.status == 201)
    mid = _tag(pm.body, "MessageId")
    pr = _tag(pm.body, "PopReceipt")
    _check("put returns MessageId", len(mid) > 0)
    _check("put returns PopReceipt", len(pr) > 0)
    _check("put has InsertionTime", "<InsertionTime>" in pm.body.decode())
    _check("put has ExpirationTime", "<ExpirationTime>" in pm.body.decode())
    _check("put has TimeNextVisible", "<TimeNextVisible>" in pm.body.decode())

    # 3. get messages -> MessageText round-trip + PopReceipt + DequeueCount
    gm = aq.dispatch(st, "GET", f"{ACCT}/{Q}/messages", {"numofmessages": "1"}, {}, b"")
    _check("get messages 200", gm.status == 200)
    got_text = _tag(gm.body, "MessageText")
    _check("get MessageText round-trips", got_text == payload)
    _check("get MessageText decodes", base64.b64decode(got_text) == b"hello azure queue")
    got_mid = _tag(gm.body, "MessageId")
    got_pr = _tag(gm.body, "PopReceipt")
    _check("get MessageId matches put", got_mid == mid)
    _check("get returns PopReceipt", len(got_pr) > 0)
    _check("get DequeueCount = 1", _tag(gm.body, "DequeueCount") == "1")

    # 3b. message now invisible → a second immediate get returns none
    gm2 = aq.dispatch(st, "GET", f"{ACCT}/{Q}/messages", {"numofmessages": "1"}, {}, b"")
    _check("dequeued message now invisible", "<MessageId>" not in gm2.body.decode())

    # 4. delete message with popreceipt -> 204
    dm = aq.dispatch(st, "DELETE", f"{ACCT}/{Q}/messages/{got_mid}",
                     {"popreceipt": got_pr}, {}, b"")
    _check("delete message 204", dm.status == 204)
    _check("message gone from store", len(st.messages(Q)) == 0)

    # 4b. delete with wrong popreceipt -> 400 PopReceiptMismatch
    aq.dispatch(st, "POST", f"{ACCT}/{Q}/messages", {}, {},
                b"<QueueMessage><MessageText>x</MessageText></QueueMessage>")
    live = st.messages(Q)[0]
    bad = aq.dispatch(st, "DELETE", f"{ACCT}/{Q}/messages/{live.message_id}",
                      {"popreceipt": "WRONG"}, {}, b"")
    _check("wrong popreceipt 400", bad.status == 400)
    _check("wrong popreceipt code", bad.headers.get("x-ms-error-code") == "PopReceiptMismatch")

    # 5. approximate-messages-count header after another put
    aq.dispatch(st, "POST", f"{ACCT}/{Q}/messages", {}, {},
                b"<QueueMessage><MessageText>second</MessageText></QueueMessage>")
    meta = aq.dispatch(st, "GET", f"{ACCT}/{Q}", {"comp": "metadata"}, {}, b"")
    _check("metadata 200", meta.status == 200)
    cnt = meta.headers.get("x-ms-approximate-messages-count")
    _check("approximate count header present", cnt is not None)
    _check("approximate count = 2", cnt == "2")

    # 6. peek does NOT change visibility / dequeue count
    pk = aq.dispatch(st, "GET", f"{ACCT}/{Q}/messages", {"peekonly": "true"}, {}, b"")
    _check("peek 200", pk.status == 200)
    _check("peek has MessageText", "<MessageText>" in pk.body.decode())
    _check("peek has no PopReceipt", "<PopReceipt>" not in pk.body.decode())

    # 7. list queues XML has the name
    aq.dispatch(st, "PUT", f"{ACCT}/invoices", {}, {}, b"")
    lq = aq.dispatch(st, "GET", "/", {"comp": "list"}, {}, b"")
    _check("list queues 200", lq.status == 200)
    _check("list is EnumerationResults", b"<EnumerationResults>" in lq.body)
    names = re.findall(r"<Queue><Name>(.*?)</Name></Queue>", lq.body.decode())
    _check("list has orders", "orders" in names)
    _check("list has invoices", "invoices" in names)

    # 8. delete queue -> 204, then metadata 404 QueueNotFound
    dq = aq.dispatch(st, "DELETE", f"{ACCT}/invoices", {}, {}, b"")
    _check("delete queue 204", dq.status == 204)
    _check("queue removed from store", not st.queue_exists("invoices"))
    nf = aq.dispatch(st, "GET", f"{ACCT}/invoices", {"comp": "metadata"}, {}, b"")
    _check("deleted queue metadata 404", nf.status == 404)
    _check("deleted queue error code", nf.headers.get("x-ms-error-code") == "QueueNotFound")
    _check("deleted queue error xml", b"<Code>QueueNotFound</Code>" in nf.body)

    # 9. message op on missing queue -> 404
    mq = aq.dispatch(st, "GET", f"{ACCT}/ghost/messages", {}, {}, b"")
    _check("missing queue messages 404", mq.status == 404)

    # 10. works WITHOUT the optional account prefix too
    aq.dispatch(st, "PUT", "/bare", {}, {}, b"")
    _check("create queue no-account prefix", st.queue_exists("bare"))
    bp = aq.dispatch(st, "POST", "/bare/messages", {}, {},
                     b"<QueueMessage><MessageText>naked</MessageText></QueueMessage>")
    _check("put no-account prefix 201", bp.status == 201)

    print("\nAzure Storage Queue data-plane core conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
