"""Amazon SNS push delivery for the offline appliance — durable, through NATS JetStream.

The engine (core/sns_core.py) stays substrate-free and only decides *what* must be delivered
(filter policies, raw delivery, FIFO dedup, effective retry policy, redrive target). This module
is the data plane behind it:

  * one JetStream stream (`VYOMI_SNS`, file storage) holds every pending delivery, so messages
    published while the appliance restarts are still delivered afterwards;
  * one durable pull consumer per subscription — a slow or failing endpoint never blocks the
    others, and a subscription's messages are delivered in order (FIFO topics rely on this);
  * workers really call the target: HTTP/HTTPS POST (with the real SubscriptionConfirmation
    handshake and RSA-signed messages, certificate served by the appliance), Lambda invoke,
    SMTP (Mailpit) for email;
  * failed deliveries are retried by the subscription's own delivery policy (min/max delay,
    backoff function) and then land in the subscription's RedrivePolicy SQS dead-letter queue.

If no NATS broker is reachable (CLI-only runs, unit tests) the same workers run on in-process
queues — same behaviour, just not durable across a restart.
"""
from __future__ import annotations

import asyncio
import base64
import datetime as _dt
import json
import os
import smtplib
import threading
import time
import urllib.error
import urllib.request
from email.message import EmailMessage
from typing import Any, Callable

try:
    import nats
    from nats.js.api import ConsumerConfig, StreamConfig
except ImportError:      # pragma: no cover - nats-py is a runtime dependency of the appliance
    nats = None          # type: ignore[assignment]

from core import sns_core

STREAM = "VYOMI_SNS"
SUBJECT_PREFIX = "sns.deliver."
HTTP_TIMEOUT = float(os.environ.get("VYOMI_SNS_HTTP_TIMEOUT", "15"))


# ── message signing (SignatureVersion 1 = SHA1withRSA, 2 = SHA256withRSA) ───────────────────
_KEY = None
_CERT_PEM = b""
_KEY_LOCK = threading.Lock()


def _keypair():
    global _KEY, _CERT_PEM
    with _KEY_LOCK:
        if _KEY is None:
            from cryptography import x509
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.x509.oid import NameOID
            _KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "sns.amazonaws.com")])
            now = _dt.datetime.now(_dt.timezone.utc)
            cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                    .public_key(_KEY.public_key()).serial_number(x509.random_serial_number())
                    .not_valid_before(now - _dt.timedelta(days=1)).not_valid_after(now + _dt.timedelta(days=3650))
                    .sign(_KEY, hashes.SHA256()))
            _CERT_PEM = cert.public_bytes(serialization.Encoding.PEM)
    return _KEY


def signing_cert_pem() -> bytes:
    _keypair()
    return _CERT_PEM


_SIGNED_FIELDS = {
    "Notification": ("Message", "MessageId", "Subject", "Timestamp", "TopicArn", "Type"),
    "SubscriptionConfirmation": ("Message", "MessageId", "SubscribeURL", "Timestamp", "Token", "TopicArn", "Type"),
}


def sign_envelope(env: dict, version: str) -> dict:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    string = "".join(f"{k}\n{env[k]}\n" for k in _SIGNED_FIELDS[env["Type"]] if k in env)
    algo = hashes.SHA256() if version == "2" else hashes.SHA1()
    sig = _keypair().sign(string.encode(), padding.PKCS1v15(), algo)
    env["SignatureVersion"] = "2" if version == "2" else "1"
    env["Signature"] = base64.b64encode(sig).decode()
    return env


# ── retry timing (shared with the Nano/dev_server synchronous simulation, so both
# substrates honour the exact same healthyRetryPolicy schedule) ──────────────────────────────
retry_delay = sns_core.retry_delay


# ── one delivery attempt (blocking; runs in a worker thread) ────────────────────────────────
class DeliveryError(Exception):
    pass


class Delivery:
    def __init__(self, store, *, base_url: Callable[[], str], invoke_lambda: Callable[[str, dict], Any],
                 deliver_sqs: Callable[..., bool], nats_url: str | None = None,
                 smtp: tuple[str, int] | None = None):
        self.store = store
        self._base_url = base_url
        self._invoke_lambda = invoke_lambda
        self._deliver_sqs = deliver_sqs
        self.nats_url = nats_url or os.environ.get("CLOUDLEARN_NATS_URL", "nats://vyomi-nats:4222")
        self.smtp = smtp or (os.environ.get("VYOMI_SMTP_HOST", "vyomi-mailpit"),
                             int(os.environ.get("VYOMI_SMTP_PORT", "1025")))
        self.loop: asyncio.AbstractEventLoop | None = None
        self.thread: threading.Thread | None = None
        self._nc = None
        self._js = None
        self._workers: dict[str, asyncio.Task] = {}
        self._queues: dict[str, asyncio.Queue] = {}
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self.mode = "starting"           # "jetstream" | "memory"

    # lifecycle ---------------------------------------------------------------------------
    def start(self) -> None:
        with self._lock:
            if self.thread is not None:
                return
            self.loop = asyncio.new_event_loop()
            self.thread = threading.Thread(target=self._run, daemon=True, name="sns-delivery")
            self.thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.create_task(self._boot())
        self.loop.run_forever()

    async def _boot(self) -> None:
        try:
            if nats is None:
                raise RuntimeError("nats-py missing")
            self._nc = await nats.connect(self.nats_url, connect_timeout=3, max_reconnect_attempts=-1)
            self._js = self._nc.jetstream()
            cfg = StreamConfig(name=STREAM, subjects=[SUBJECT_PREFIX + ">"], storage="file", retention="workqueue")
            try:
                await self._js.add_stream(cfg)
            except Exception:
                await self._js.stream_info(STREAM)       # already there (older config is fine); else -> memory mode
            self.mode = "jetstream"
            # resume the durable consumer of every subscription that still has queued work
            try:
                for ci in await self._js.consumers_info(STREAM):
                    self._ensure_worker(ci.name, None)
            except Exception:
                pass
        except Exception:
            self._nc = self._js = None
            self.mode = "memory"
        self._ready.set()

    def _sub_key(self, sub_arn: str) -> str:
        return sub_arn.rsplit(":", 1)[-1]          # the subscription UUID

    # enqueue -----------------------------------------------------------------------------
    def enqueue(self, job: dict) -> bool:
        self.start()
        if not self._ready.wait(8):
            return False
        asyncio.run_coroutine_threadsafe(self._enqueue(job), self.loop)
        return True

    async def _enqueue(self, job: dict) -> None:
        key = self._sub_key(job["subscription_arn"])
        self._ensure_worker(key, job)
        if self._js is not None:
            try:
                await self._js.publish(SUBJECT_PREFIX + key, json.dumps(job).encode())
                return
            except Exception:
                pass
        self._queues.setdefault(key, asyncio.Queue()).put_nowait((job, 1))

    def _ensure_worker(self, key: str, job: dict | None) -> None:
        t = self._workers.get(key)
        if t is None or t.done():
            self._workers[key] = self.loop.create_task(self._worker(key))

    # worker ------------------------------------------------------------------------------
    async def _worker(self, key: str) -> None:
        psub = None
        if self._js is not None:
            try:
                psub = await self._js.pull_subscribe(
                    SUBJECT_PREFIX + key, durable=key,
                    config=ConsumerConfig(ack_wait=120, max_deliver=-1, inactive_threshold=7 * 24 * 3600))
            except Exception:
                psub = None
        q = self._queues.setdefault(key, asyncio.Queue())
        idle = 0
        while True:
            msg = None
            if psub is not None:
                try:
                    msg = (await psub.fetch(1, timeout=2))[0]
                    job, attempt = json.loads(msg.data), msg.metadata.num_delivered
                except Exception:
                    job = None
            else:
                try:
                    job, attempt = await asyncio.wait_for(q.get(), 2)
                except asyncio.TimeoutError:
                    job = None
            if job is None:
                idle += 1
                if psub is None and idle > 150 and q.empty():
                    self._workers.pop(key, None)       # nothing queued for 5 minutes: retire
                    return
                continue
            idle = 0
            await self._process(job, attempt, msg, q)

    async def _process(self, job: dict, attempt: int, msg, q: asyncio.Queue) -> None:
        topic, sub = self._find(job)
        if sub is None or (sub.get("pending") and job["kind"] != "SubscriptionConfirmation"):
            if msg is not None:
                await msg.ack()
            return                                   # unsubscribed meanwhile: drop
        policy = job.get("retry_policy") or {}
        retries = int(policy.get("numRetries", 3))
        try:
            note = await asyncio.get_running_loop().run_in_executor(None, self._attempt, job)
        except Exception as e:                        # noqa: BLE001 — any failure is a failed attempt
            err = str(e)[:300] or e.__class__.__name__
            if attempt <= retries:
                delay = retry_delay(policy, attempt)
                self._log(job, "DeliveryFailure", f"attempt {attempt} failed ({err}); retry {attempt} of {retries} in {delay:g}s")
                if msg is not None:
                    await msg.nak(delay=delay)
                else:
                    await asyncio.sleep(delay)
                    q.put_nowait((job, attempt + 1))
                return
            self._log(job, "DeliveryFailure", f"gave up after {attempt} attempts ({err})")
            self._redrive(job, err)
            if msg is not None:
                await msg.ack()
            return
        self._log(job, "Notification", note or "delivered", ok=True)
        if msg is not None:
            await msg.ack()

    # helpers -----------------------------------------------------------------------------
    def _find(self, job: dict):
        for topic in list(self.store.topics.values()):
            sub = topic["subscriptions"].get(job["subscription_arn"])
            if sub is not None:
                return topic, sub
        return None, None

    def _log(self, job: dict, kind: str, note: str, ok: bool = False) -> None:
        try:
            sns_core._log_delivery(self.store, kind=kind, topic_arn=job["topic_arn"], protocol=job["protocol"],
                                   endpoint=job["endpoint"], subscription_arn=job["subscription_arn"],
                                   subject=job.get("subject") or "", message=job.get("message") or "",
                                   message_id=job.get("message_id") or "", status="delivered" if ok else "failed",
                                   error="" if ok else note, note=note)
            self.store.persist()
        except Exception:
            pass

    def _redrive(self, job: dict, err: str) -> None:
        arn = job.get("redrive_arn")
        if not arn:
            return
        body = json.dumps(self._payload(job)[0] if job["protocol"] != "lambda" else job["envelope"])
        try:
            if self._deliver_sqs(arn, body, None, job.get("group") or None, job.get("message_id")):
                self._log(job, "DeadLetter", f"moved to dead-letter queue {arn}", ok=True)
            else:
                self._log(job, "DeadLetter", f"dead-letter queue {arn} does not exist")
        except Exception as e:                        # noqa: BLE001
            self._log(job, "DeadLetter", f"dead-letter delivery failed: {e}")

    def _payload(self, job: dict) -> tuple[Any, str]:
        """(JSON-able body or raw text, content type) — signed and with local URLs."""
        base = self._base_url().rstrip("/")
        if job["raw"] and job["kind"] == "Notification":
            return job["message"], "text/plain; charset=UTF-8"
        env = dict(job["envelope"]) if job["kind"] == "Notification" else {
            "Type": "SubscriptionConfirmation", "MessageId": job["message_id"], "Token": job["token"],
            "TopicArn": job["topic_arn"], "Message": job["message"],
            "SubscribeURL": f"{base}/?Action=ConfirmSubscription&TopicArn={job['topic_arn']}&Token={job['token']}",
            "Timestamp": job["enqueued"]}
        env["SigningCertURL"] = f"{base}/SimpleNotificationService-vyomi.pem"
        if env["Type"] == "Notification":
            env["UnsubscribeURL"] = f"{base}/?Action=Unsubscribe&SubscriptionArn={job['subscription_arn']}"
        return sign_envelope(env, job.get("signature_version", "1")), "text/plain; charset=UTF-8"

    def _attempt(self, job: dict) -> str:
        proto = job["protocol"]
        if proto in ("http", "https"):
            body, ctype = self._payload(job)
            data = (body if isinstance(body, str) else json.dumps(body)).encode()
            req = urllib.request.Request(job["endpoint"], data=data, method="POST", headers={
                "Content-Type": ctype, "x-amz-sns-message-type": job["kind"],
                "x-amz-sns-message-id": job.get("message_id") or "", "x-amz-sns-topic-arn": job["topic_arn"],
                "x-amz-sns-subscription-arn": job["subscription_arn"],
                "User-Agent": "Amazon Simple Notification Service Agent"})
            try:
                with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
                    return f"HTTP {r.status} from {job['endpoint']}"
            except urllib.error.HTTPError as e:
                raise DeliveryError(f"HTTP {e.code} from {job['endpoint']}")
            except Exception as e:                    # noqa: BLE001
                raise DeliveryError(f"{job['endpoint']}: {e}")
        if proto == "lambda":
            env, _ = self._payload(job)
            fn = job["endpoint"].split(":function:", 1)[-1].split(":")[0]
            sns_rec = {k: env.get(k) for k in ("Type", "MessageId", "TopicArn", "Subject", "Message", "Timestamp",
                                               "SignatureVersion", "Signature")}
            sns_rec.update(SigningCertUrl=env.get("SigningCertURL"), UnsubscribeUrl=env.get("UnsubscribeURL"),
                           MessageAttributes=env.get("MessageAttributes", {}))
            self._invoke_lambda(fn, {"Records": [{"EventSource": "aws:sns", "EventVersion": "1.0",
                                                  "EventSubscriptionArn": job["subscription_arn"], "Sns": sns_rec}]})
            return f"invoked Lambda {fn}"
        if proto in ("email", "email-json"):
            body = job["message"] if proto == "email" else json.dumps(job["envelope"], indent=2)
            m = EmailMessage()
            m["From"], m["To"] = "no-reply@sns.amazonaws.com", job["endpoint"]
            m["Subject"] = job.get("subject") or "AWS Notification Message"
            m.set_content(body)
            try:
                with smtplib.SMTP(*self.smtp, timeout=5) as s:
                    s.send_message(m)
                return f"email sent to {job['endpoint']} via {self.smtp[0]}"
            except OSError:
                return f"email to {job['endpoint']} recorded (no SMTP relay at {self.smtp[0]}:{self.smtp[1]})"
        raise DeliveryError(f"unsupported protocol {proto}")
