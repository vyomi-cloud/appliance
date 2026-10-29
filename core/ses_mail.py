"""Offline mail plane for Amazon SES (the sockets that core/sesv2_core.py deliberately lacks).

Not vendored into Nano: a browser cannot speak SMTP/IMAP, so there `store.mailer` stays None and the
engine only records the message and its SES events.

  * delivery   - every SendEmail / SendBulkEmail / SMTP submission is really sent over SMTP to the
                 shared Mailpit container (inbox UI on :8025), keyed by its Message-ID so the console's
                 Sent list can link to the message.
  * relay      - optional, per space: also deliver to the user's own SMTP server (Gmail app password,
                 Office 365, a company relay). The password is stored sealed (Fernet, key file outside the
                 state DB) and is never logged, returned by an API or put in an error message.
  * SES SMTP   - STARTTLS submission on :2587 with SES SMTP credentials derived from an IAM secret key
                 (same algorithm as AWS). The rules (verified sender, suppression, configuration set,
                 events) are sesv2_core.smtp_ingest.
  * inbound    - an SMTP listener on :2525 for mail to verified identities, plus an optional IMAP poll of a
                 real mailbox, both run through the active SES v1 receipt rule set (S3 / Lambda / SNS / Bounce
                 / Stop / AddHeader actions).
"""
from __future__ import annotations

import asyncio
import base64
import imaplib
import json
import logging
import os
import smtplib
import socket
import ssl
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from email import message_from_bytes
from email.utils import getaddresses

from core import sesv2_core as ses

log = logging.getLogger("vyomi.ses_mail")
MAX_SIZE = 10 * 1024 * 1024


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _key_dir() -> str:
    for d in (_env("VYOMI_SES_KEY_DIR", ""), "/data", os.path.expanduser("~/.vyomi"), tempfile.gettempdir()):
        if d:
            try:
                os.makedirs(d, exist_ok=True)
                if os.access(d, os.W_OK):
                    return d
            except OSError:
                continue
    return tempfile.gettempdir()


class SesMail:
    def __init__(self, store) -> None:
        self.store = store
        self.host = _env("VYOMI_MAILPIT_HOST", "vyomi-mailpit")
        self.smtp_port = int(_env("VYOMI_MAILPIT_SMTP_PORT", "1025"))
        self.api_port = int(_env("VYOMI_MAILPIT_API_PORT", "8025"))
        self.ui_url = _env("VYOMI_MAILPIT_UI", "http://localhost:8025").rstrip("/")
        self.smtp_endpoint = _env("VYOMI_SES_SMTP_ENDPOINT", "localhost:2587")
        self.inbound_endpoint = _env("VYOMI_SES_INBOUND_ENDPOINT", "localhost:2525")
        self.self_url = _env("VYOMI_SELF_URL", "http://127.0.0.1:9000")
        self._fernet = None
        self._servers: list = []
        self._imap_thread: threading.Thread | None = None
        self._imap_lock = threading.Lock()

    # ── sealed secrets ─────────────────────────────────────────────────
    def _f(self):
        if self._fernet is None:
            from cryptography.fernet import Fernet
            path = os.path.join(_key_dir(), "ses_mail.key")
            if not os.path.exists(path):
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as fh:
                    fh.write(Fernet.generate_key())
            self._fernet = Fernet(open(path, "rb").read().strip())
        return self._fernet

    def seal(self, plain: str) -> str:
        return self._f().encrypt(plain.encode()).decode()

    def _unseal(self, token: str) -> str:
        return self._f().decrypt(token.encode()).decode()

    @staticmethod
    def _scrub(text: str, *secrets: str) -> str:
        for s in secrets:
            if s:
                text = text.replace(s, "***")
        return text

    # ── Mailpit ────────────────────────────────────────────────────────
    def _mailpit_host(self) -> str:
        try:
            socket.getaddrinfo(self.host, self.smtp_port)
            return self.host
        except OSError:
            return "localhost"

    def _inbox_lookup(self, message_id: str) -> str:
        url = f"http://{self._mailpit_host()}:{self.api_port}/api/v1/search?" + urllib.parse.urlencode(
            {"query": f"message-id:{message_id}", "limit": 1})
        for _ in range(10):
            try:
                with urllib.request.urlopen(url, timeout=3) as r:
                    msgs = json.load(r).get("messages") or []
                if msgs:
                    return msgs[0]["ID"]
            except Exception:
                pass
            time.sleep(0.2)
        return ""

    def deliver(self, msg: dict, raw: bytes, sender: str, rcpts: list, relay_to: list):
        """Called by the engine for every accepted message. Returns the delivery result dict."""
        out: dict = {"relayed": [], "relay_failed": {}}
        try:
            with smtplib.SMTP(self._mailpit_host(), self.smtp_port, timeout=10) as s:
                s.sendmail(sender, rcpts, raw)
        except Exception as e:
            return {"error": f"451 4.3.0 local inbox (Mailpit) unavailable: {e}"}
        mid = ses._message_id_header(msg["MessageId"])
        inbox_id = self._inbox_lookup(mid)
        out["inbox_id"] = inbox_id
        out["inbox_url"] = f"{self.ui_url}/view/{inbox_id}" if inbox_id else self.ui_url
        if relay_to:
            self._relay(sender, relay_to, raw, out)
        return out

    def _relay(self, sender: str, rcpts: list, raw: bytes, out: dict) -> None:
        cfg = (self.store.mail_settings or {}).get("relay") or {}
        pw = ""
        try:
            pw = self._unseal(cfg["password_enc"]) if cfg.get("password_enc") else ""
            sec = (cfg.get("security") or "starttls").lower()
            host, port = cfg["host"], int(cfg.get("port") or (465 if sec == "tls" else 587))
            if sec == "tls":
                c = smtplib.SMTP_SSL(host, port, timeout=15, context=ssl.create_default_context())
            else:
                c = smtplib.SMTP(host, port, timeout=15)
            with c:
                c.ehlo()
                if sec == "starttls":
                    c.starttls(context=ssl.create_default_context())
                    c.ehlo()
                if cfg.get("username"):
                    c.login(cfg["username"], pw)
                refused = c.sendmail(sender, rcpts, raw)
            for r in rcpts:
                if r in refused:
                    out["relay_failed"][r] = self._scrub(f"{refused[r][0]} {refused[r][1].decode(errors='replace')}", pw)
                else:
                    out["relayed"].append(r)
        except Exception as e:
            err = self._scrub(f"{type(e).__name__}: {e}", pw, cfg.get("username") or "")
            for r in rcpts:
                out["relay_failed"][r] = err

    # ── SNS event destinations ─────────────────────────────────────────
    def _boto(self, svc: str):
        import boto3
        return boto3.client(svc, endpoint_url=self.self_url, region_name="us-east-1",
                            aws_access_key_id="vyomi", aws_secret_access_key="vyomi")

    def publish_sns(self, topic_arn: str, payload: dict) -> None:
        """Fire-and-forget (SES publishes events asynchronously; and this process serves the
        SNS endpoint itself, so a synchronous call from a request handler could deadlock)."""
        def go():
            try:
                self._boto("sns").publish(TopicArn=topic_arn, Message=json.dumps(payload))
            except Exception as e:
                log.warning("SES event to SNS %s failed: %s", topic_arn, e)
        threading.Thread(target=go, daemon=True).start()

    # ── TLS material for STARTTLS ──────────────────────────────────────
    def _tls_context(self) -> ssl.SSLContext:
        import datetime
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        d = _key_dir()
        crt, key = os.path.join(d, "ses_smtp.crt"), os.path.join(d, "ses_smtp.key")
        if not (os.path.exists(crt) and os.path.exists(key)):
            k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "email-smtp.vyomi.local")])
            now = datetime.datetime.now(datetime.timezone.utc)
            cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key())
                    .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
                    .not_valid_after(now + datetime.timedelta(days=3650))
                    .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.DNSName("email-smtp.vyomi.local")]),
                                   critical=False).sign(k, hashes.SHA256()))
            with open(key, "wb") as fh:
                fh.write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                         serialization.NoEncryption()))
            os.chmod(key, 0o600)
            with open(crt, "wb") as fh:
                fh.write(cert.public_bytes(serialization.Encoding.PEM))
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(crt, key)
        return ctx

    # ── SMTP front ends ────────────────────────────────────────────────
    async def start(self) -> None:
        tls = self._tls_context()
        for port, mode in ((int(_env("VYOMI_SES_SMTP_PORT", "2587")), "submit"),
                           (int(_env("VYOMI_SES_INBOUND_PORT", "2525")), "inbound")):
            try:
                srv = await asyncio.start_server(lambda r, w, m=mode: _Session(self, m, r, w, tls).run(), "0.0.0.0", port)
                self._servers.append(srv)
                log.info("SES %s SMTP listening on :%s", mode, port)
            except OSError as e:
                log.warning("SES %s SMTP could not bind :%s (%s)", mode, port, e)
        if not self._imap_thread:
            self._imap_thread = threading.Thread(target=self._imap_loop, name="ses-imap", daemon=True)
            self._imap_thread.start()

    def secret_lookup(self, access_key_id: str):
        """IAM access keys that exist in the appliance's IAM store (SMTP credentials registered
        through the console work regardless)."""
        try:
            from core import app_context as ctx
            for u in (ctx.iam_state.get("users") or {}).values():
                for k in (u.get("access_keys") or []):
                    if isinstance(k, dict) and k.get("access_key_id") == access_key_id:
                        return k.get("secret_access_key")
        except Exception:
            pass
        return None

    # ── inbound ────────────────────────────────────────────────────────
    def receive(self, mail_from: str, rcpts: list, raw: bytes, *, require_verified: bool = True):
        """Run a received message through the active receipt rules. Returns (ok, reply)."""
        if require_verified:
            bad = [r for r in rcpts if not ses.inbound_accepts(self.store, r)]
            if bad:
                return False, (550, f"5.1.1 Mailbox does not exist: {bad[0]}")
        plan = ses.inbound_plan(self.store, rcpts, mail_from, raw)
        if plan["bounce"]:
            b = plan["bounce"]
            return False, (b["code"], f"{b['status']} {b['message']}")
        self._run_actions(plan, raw)
        return True, (250, f"2.0.0 OK {plan['messageId']}")

    def _run_actions(self, plan: dict, raw: bytes) -> None:
        for act in plan["plan"]:
            t, cfg = act["type"], act["cfg"]
            try:
                if t == "AddHeaderAction":
                    raw = f"{cfg.get('HeaderName', 'X-Header')}: {cfg.get('HeaderValue', '')}\r\n".encode() + raw
                elif t == "S3Action":
                    self._boto("s3").put_object(Bucket=cfg["BucketName"], Key=(cfg.get("ObjectKeyPrefix") or "") + plan["messageId"], Body=raw)
                elif t == "LambdaAction":
                    fn = str(cfg["FunctionArn"]).split(":function:")[-1].split(":")[0]
                    self._boto("lambda").invoke(FunctionName=fn, InvocationType=cfg.get("InvocationType") or "Event",
                                                Payload=json.dumps(ses.inbound_event(plan, act)).encode())
                elif t == "SNSAction":
                    body = {"notificationType": "Received", "receipt": ses.inbound_event(plan, act)["Records"][0]["ses"]["receipt"],
                            "mail": plan["mail"]}
                    body["content"] = raw.decode("utf-8", "replace") if (cfg.get("Encoding") or "UTF-8") == "UTF-8" else base64.b64encode(raw).decode()
                    self._boto("sns").publish(TopicArn=cfg["TopicArn"], Message=json.dumps(body))
            except Exception as e:
                log.warning("receipt action %s failed: %s", t, e)

    # ── IMAP poll (real mailbox -> the same receipt rules) ─────────────
    def poll_imap_now(self) -> dict:
        cfg = (self.store.mail_settings or {}).get("imap") or {}
        if not cfg.get("host"):
            return {"processed": 0, "errors": ["IMAP is not configured"]}
        with self._imap_lock:
            return self._poll(cfg)

    def _poll(self, cfg: dict) -> dict:
        n, errors, pw = 0, [], ""
        try:
            pw = self._unseal(cfg["password_enc"]) if cfg.get("password_enc") else ""
            sec = (cfg.get("security") or "tls").lower()
            port = int(cfg.get("port") or (993 if sec == "tls" else 143))
            c = (imaplib.IMAP4_SSL(cfg["host"], port, timeout=20) if sec == "tls" else imaplib.IMAP4(cfg["host"], port, timeout=20))
            try:
                if sec == "starttls":
                    c.starttls(ssl.create_default_context())
                c.login(cfg.get("username") or "", pw)
                c.select(cfg.get("folder") or "INBOX")
                typ, data = c.search(None, "UNSEEN")
                for num in (data[0].split() if typ == "OK" and data and data[0] else []):
                    typ, parts = c.fetch(num, "(BODY.PEEK[])")
                    raw = next((p[1] for p in parts if isinstance(p, tuple)), b"")
                    parsed = message_from_bytes(raw)
                    addrs = [a for _, a in getaddresses(parsed.get_all("To", []) + parsed.get_all("Cc", [])
                                                        + parsed.get_all("Delivered-To", []) + parsed.get_all("X-Original-To", [])) if a]
                    frm = (getaddresses([parsed.get("From", "")]) or [("", "")])[0][1]
                    ok, reply = self.receive(frm, addrs or [cfg.get("username") or ""], raw, require_verified=False)
                    c.store(num, "+FLAGS", "\\Seen")
                    n += 1
                    if not ok:
                        errors.append(f"{reply[0]} {reply[1]}")
            finally:
                try:
                    c.logout()
                except Exception:
                    pass
        except Exception as e:
            errors.append(self._scrub(f"{type(e).__name__}: {e}", pw))
        return {"processed": n, "errors": errors}

    def _imap_loop(self) -> None:
        while True:
            time.sleep(5)
            try:
                cfg = (self.store.mail_settings or {}).get("imap") or {}
                if cfg.get("enabled") and cfg.get("host"):
                    last = getattr(self, "_last_poll", 0)
                    if time.time() - last >= int(cfg.get("interval") or 30):
                        self._last_poll = time.time()
                        self.poll_imap_now()
            except Exception as e:   # never let the poller die
                log.warning("IMAP poll error: %s", e)


class _Session:
    def __init__(self, mail: SesMail, mode: str, reader, writer, tls) -> None:
        self.mail, self.mode, self.r, self.w, self.tls = mail, mode, reader, writer, tls
        self.secure = False
        self.user: str | None = None
        self._reset()

    def _reset(self) -> None:
        self.mail_from, self.rcpts, self.have_mail = "", [], False

    async def say(self, code: int, text: str, more: bool = False) -> None:
        self.w.write(f"{code}{'-' if more else ' '}{text}\r\n".encode())
        await self.w.drain()

    async def line(self) -> str | None:
        try:
            raw = await asyncio.wait_for(self.r.readline(), 300)
        except (asyncio.TimeoutError, ConnectionError):
            return None
        return raw.decode("utf-8", "replace").rstrip("\r\n") if raw else None

    async def run(self) -> None:
        try:
            await self.say(220, "email-smtp.vyomi.local ESMTP Vyomi SES")
            while True:
                ln = await self.line()
                if ln is None:
                    break
                cmd, _, arg = ln.partition(" ")
                cmd = cmd.upper()
                if cmd in ("EHLO", "HELO"):
                    await self.say(250, "email-smtp.vyomi.local", True)
                    await self.say(250, f"SIZE {MAX_SIZE}", True)
                    if not self.secure:
                        await self.say(250, "STARTTLS", True)
                    if self.mode == "submit":
                        await self.say(250, "AUTH PLAIN LOGIN", True)
                    await self.say(250, "8BITMIME")
                elif cmd == "STARTTLS":
                    if self.secure:
                        await self.say(503, "5.5.1 TLS already active")
                        continue
                    await self.say(220, "2.0.0 Ready to start TLS")
                    await self.w.start_tls(self.tls)
                    self.secure = True
                    self._reset()
                    self.user = None
                elif cmd == "AUTH":
                    await self._auth(arg)
                elif cmd == "MAIL":
                    if self.mode == "submit" and not self.user:
                        await self.say(530, "5.7.0 Authentication required")
                        continue
                    self.mail_from, self.have_mail = _addr(arg), True
                    self.rcpts = []
                    await self.say(250, "2.1.0 Ok")
                elif cmd == "RCPT":
                    if not self.have_mail:
                        await self.say(503, "5.5.1 Need MAIL first")
                        continue
                    a = _addr(arg)
                    if self.mode == "inbound" and not await _blocking(ses.inbound_accepts, self.mail.store, a):
                        await self.say(550, f"5.1.1 Mailbox does not exist: {a}")
                        continue
                    self.rcpts.append(a)
                    await self.say(250, "2.1.5 Ok")
                elif cmd == "DATA":
                    if not self.rcpts:
                        await self.say(503, "5.5.1 Need RCPT first")
                        continue
                    await self.say(354, "End data with <CR><LF>.<CR><LF>")
                    raw = await self._data()
                    if raw is None:
                        await self.say(552, "5.3.4 Message size exceeds the SES limit of 10 MB")
                    else:
                        await self._finish(raw)
                    self._reset()
                elif cmd == "RSET":
                    self._reset()
                    await self.say(250, "2.0.0 Ok")
                elif cmd == "NOOP":
                    await self.say(250, "2.0.0 Ok")
                elif cmd == "QUIT":
                    await self.say(221, "2.0.0 Bye")
                    break
                else:
                    await self.say(502, "5.5.2 Command not recognized")
        except (ConnectionError, ssl.SSLError, asyncio.IncompleteReadError):
            pass
        except Exception as e:
            log.warning("SMTP session error: %s", e)
        finally:
            try:
                self.w.close()
            except Exception:
                pass

    async def _auth(self, arg: str) -> None:
        if self.mode != "submit":
            await self.say(502, "5.5.1 Authentication not available on this port")
            return
        if not self.secure:
            await self.say(530, "5.7.0 Must issue a STARTTLS command first")
            return
        mech, _, initial = arg.partition(" ")
        mech = mech.upper()
        user = pw = ""
        try:
            if mech == "PLAIN":
                if not initial:
                    await self.say(334, "")
                    initial = (await self.line()) or ""
                _, user, pw = base64.b64decode(initial).decode().split("\x00", 2)
            elif mech == "LOGIN":
                await self.say(334, "VXNlcm5hbWU6")
                user = base64.b64decode((await self.line()) or "").decode()
                await self.say(334, "UGFzc3dvcmQ6")
                pw = base64.b64decode((await self.line()) or "").decode()
            else:
                await self.say(504, "5.5.4 Unrecognized authentication type")
                return
        except Exception:
            await self.say(501, "5.5.2 Cannot decode credentials")
            return
        ok = await _blocking(ses.smtp_authenticate, self.mail.store, user, pw, self.mail.secret_lookup)
        if ok:
            self.user = user
            await self.say(235, "2.7.0 Authentication successful")
        else:
            await self.say(535, "5.7.8 Authentication credentials invalid")

    async def _data(self) -> bytes | None:
        buf, size, over = [], 0, False
        while True:
            ln = await self.r.readline()
            if not ln:
                raise ConnectionError
            if ln in (b".\r\n", b".\n"):
                break
            if ln.startswith(b".."):
                ln = ln[1:]
            size += len(ln)
            if size > MAX_SIZE:
                over = True
            elif not over:
                buf.append(ln)
        return None if over else b"".join(buf)

    async def _finish(self, raw: bytes) -> None:
        if self.mode == "submit":
            try:
                text = await _blocking(ses.smtp_ingest, self.mail.store, self.mail_from, list(self.rcpts), raw)
                await self.say(250, "Ok " + text.split(" ", 1)[-1])
            except ses.SmtpRefused as e:
                await self.say(e.code, e.text)
        else:
            ok, (code, text) = await _blocking(self.mail.receive, self.mail_from, list(self.rcpts), raw)
            await self.say(code, text)


def _addr(arg: str) -> str:
    a = arg.split(":", 1)[-1].strip()
    if a.startswith("<"):
        a = a[1:a.find(">")] if ">" in a else a[1:]
    return a.split(" ")[0].strip()


async def _blocking(fn, *a):
    return await asyncio.get_running_loop().run_in_executor(None, lambda: fn(*a))
