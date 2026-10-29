"""SES really sends and receives mail (issue #61): official boto3 against the appliance, with only
the endpoint changed, plus the SES SMTP interface (smtplib), the opt-in outbound relay (a local fake
SMTP server), inbound mail into SES v1 receipt rules (SMTP :2525 and an IMAP poll against a local fake
IMAP server).  One [PASS]/[FAIL] line per check; exits non-zero on failure.

  VYOMI_BASE_URL=http://localhost:9000 MAILPIT_URL=http://localhost:8025 python3 tests/conformance/test_aws_sesv2_mail_api.py
"""
import base64
import hashlib
import hmac
import json
import os
import smtplib
import socket
import socketserver
import ssl
import subprocess
import sys
import threading
import time
import uuid
from email.message import EmailMessage

import boto3
import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000").rstrip("/")
MAILPIT = os.environ.get("MAILPIT_URL", "http://localhost:8025").rstrip("/")
HOST = BASE.split("//", 1)[1].split(":")[0]
SMTP_PORT = int(os.environ.get("SES_SMTP_PORT", "2587"))
INBOUND_PORT = int(os.environ.get("SES_INBOUND_PORT", "2525"))
# where the appliance (a container) reaches this test process
CALLBACK_HOST = os.environ.get("TEST_CALLBACK_HOST", "host.docker.internal")
failed = False
RUN = uuid.uuid4().hex[:8]


def check(name, ok, detail=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
    failed = failed or not ok


def client(svc):
    return boto3.client(svc, endpoint_url=BASE, region_name="us-east-1", aws_access_key_id="AKIAVYOMITEST000001",
                        aws_secret_access_key="vyomi-test-secret-key-0001")


ses2, s3, lam = client("sesv2"), client("s3"), client("lambda")
ses1 = client("ses")


def inbox(query, want=1, wait=8):
    end = time.time() + wait
    while time.time() < end:
        r = requests.get(f"{MAILPIT}/api/v1/search", params={"query": query}, timeout=10).json()
        if len(r.get("messages") or []) >= want:
            return r["messages"]
        time.sleep(0.3)
    return []


def full(mid):
    return requests.get(f"{MAILPIT}/api/v1/message/{mid}", timeout=10).json()


def smtp_password(secret, region="us-east-1"):          # independent copy of the documented algorithm
    def sign(k, m):
        return hmac.new(k, m.encode(), hashlib.sha256).digest()
    sig = sign(("AWS4" + secret).encode(), "11111111")
    for m in (region, "ses", "aws4_request", "SendRawEmail"):
        sig = sign(sig, m)
    return base64.b64encode(b"\x04" + sig).decode()


# ── minimal fake SMTP / IMAP servers (the "user's own" servers) ────────────
class FakeSmtp(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self):
        self.received, self.logins = [], []
        super().__init__(("0.0.0.0", 0), _SmtpH)


class _SmtpH(socketserver.StreamRequestHandler):
    def w(self, s):
        self.wfile.write((s + "\r\n").encode())

    def handle(self):
        self.w("220 fake.relay ESMTP")
        frm, rc = "", []
        while True:
            ln = self.rfile.readline().decode(errors="replace").strip()
            if not ln:
                return
            c = ln.upper()
            if c.startswith("EHLO") or c.startswith("HELO"):
                self.w("250-fake.relay"); self.w("250 AUTH PLAIN")
            elif c.startswith("AUTH PLAIN"):
                tok = ln.split(" ", 2)[2] if len(ln.split(" ")) > 2 else ""
                self.server.logins.append(base64.b64decode(tok).decode().split("\x00")[1:])
                self.w("235 ok")
            elif c.startswith("MAIL"):
                frm = ln; rc = []; self.w("250 ok")
            elif c.startswith("RCPT"):
                a = ln.split(":", 1)[1].strip().strip("<>")
                if a.startswith("refuse@"):
                    self.w("550 5.1.1 mailbox unavailable")
                else:
                    rc.append(a); self.w("250 ok")
            elif c == "DATA":
                self.w("354 go")
                buf = []
                while True:
                    l = self.rfile.readline()
                    if l in (b".\r\n", b""):
                        break
                    buf.append(l)
                self.server.received.append((frm, rc, b"".join(buf)))
                self.w("250 queued")
            elif c == "QUIT":
                self.w("221 bye"); return
            else:
                self.w("250 ok")


class FakeImap(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, raw):
        self.raw, self.seen, self.logins = raw, False, []
        super().__init__(("0.0.0.0", 0), _ImapH)


class _ImapH(socketserver.StreamRequestHandler):
    def w(self, s):
        self.wfile.write((s + "\r\n").encode())

    def handle(self):
        self.w("* OK fake IMAP ready")
        while True:
            ln = self.rfile.readline().decode().strip()
            if not ln:
                return
            tag, _, rest = ln.partition(" ")
            cmd = rest.split(" ")[0].upper()
            if cmd == "CAPABILITY":
                self.w("* CAPABILITY IMAP4rev1"); self.w(f"{tag} OK done")
            elif cmd == "LOGIN":
                self.server.logins.append(rest.split(" ")[1:]); self.w(f"{tag} OK logged in")
            elif cmd == "SELECT":
                self.w("* 1 EXISTS"); self.w(f"{tag} OK [READ-WRITE] selected")
            elif cmd == "SEARCH":
                self.w("* SEARCH" + ("" if self.server.seen else " 1")); self.w(f"{tag} OK done")
            elif cmd == "FETCH":
                raw = self.server.raw
                self.wfile.write(f"* 1 FETCH (BODY[] {{{len(raw)}}}\r\n".encode() + raw + b")\r\n")
                self.w(f"{tag} OK done")
            elif cmd == "STORE":
                self.server.seen = True; self.w("* 1 FETCH (FLAGS (\\Seen))"); self.w(f"{tag} OK done")
            elif cmd == "LOGOUT":
                self.w("* BYE"); self.w(f"{tag} OK bye"); return
            else:
                self.w(f"{tag} OK")


def serve(srv):
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]


def main():
    sender, dom = f"sender-{RUN}@vyomi.example.com", f"in-{RUN}.example.org"
    for ident in (sender, dom):
        ses2.create_email_identity(EmailIdentity=ident)

    # ── 1. SendEmail really delivers (aws sesv2 send-email -> Mailpit) ──────
    subj = f"Hello {RUN}"
    r = ses2.send_email(FromEmailAddress=sender, Destination={"ToAddresses": [f"to-{RUN}@example.net"], "CcAddresses": [f"cc-{RUN}@example.net"]},
                        ReplyToAddresses=[f"reply-{RUN}@example.net"],
                        Content={"Simple": {"Subject": {"Data": subj}, "Body": {"Text": {"Data": "plain body"}, "Html": {"Data": "<p><b>html body</b></p>"}},
                                            "Headers": [{"Name": "X-Vyomi-Test", "Value": RUN}],
                                            "Attachments": [{"FileName": "report.txt", "ContentType": "text/plain", "RawContent": b"attachment-bytes",
                                                             "ContentDisposition": "ATTACHMENT"}]}})
    msgs = inbox(f'subject:"{subj}"')
    check("SendEmail lands in the Mailpit inbox", len(msgs) == 1, str(r))
    if msgs:
        m = full(msgs[0]["ID"])
        check("subject and sender intact", m["Subject"] == subj and m["From"]["Address"] == sender)
        check("HTML body intact", "<b>html body</b>" in m.get("HTML", ""))
        check("text body intact", "plain body" in m.get("Text", ""))
        check("attachment intact", [a["FileName"] for a in m.get("Attachments", [])] == ["report.txt"]
              and requests.get(f"{MAILPIT}/api/v1/message/{m['ID']}/part/{m['Attachments'][0]['PartID']}", timeout=10).content == b"attachment-bytes")
        raw = requests.get(f"{MAILPIT}/api/v1/message/{m['ID']}/raw", timeout=10).text
        check("custom header X-Vyomi-Test delivered", f"X-Vyomi-Test: {RUN}" in raw)
        check("Reply-To and Cc delivered", f"reply-{RUN}@example.net" in raw and [c["Address"] for c in m.get("Cc", [])] == [f"cc-{RUN}@example.net"])
        check("Message-ID carries the SES MessageId", r["MessageId"] in raw)
        row = next((x for x in requests.get(f"{BASE}/api/aws/sesv2/sent-emails").json()["items"] if x["name"] == r["MessageId"]), {})
        check("console Sent list links to the inbox message", row.get("inbox", "").endswith("/view/" + m["ID"]), str(row))
        check("console Sent list shows delivery status and events", row.get("delivery") == "Delivered" and "Delivery" in row.get("events", ""), str(row))

    # templated + bulk
    ses2.create_email_template(TemplateName=f"t-{RUN}", TemplateContent={"Subject": "Hi {{name}} {{run}}", "Html": "<h1>Dear {{name}}</h1>", "Text": "Dear {{name}}"})
    ses2.send_email(FromEmailAddress=sender, Destination={"ToAddresses": [f"tpl-{RUN}@example.net"]},
                    Content={"Template": {"TemplateName": f"t-{RUN}", "TemplateData": json.dumps({"name": "Ada", "run": RUN})}})
    t = inbox(f'subject:"Hi Ada {RUN}"')
    check("templated send renders the template", bool(t) and "Dear Ada" in full(t[0]["ID"]).get("HTML", ""))
    ses2.send_bulk_email(FromEmailAddress=sender, DefaultContent={"Template": {"TemplateName": f"t-{RUN}", "TemplateData": json.dumps({"name": "x", "run": RUN})}},
                         BulkEmailEntries=[{"Destination": {"ToAddresses": [f"b{i}-{RUN}@example.net"]},
                                            "ReplacementEmailContent": {"ReplacementTemplate": {"ReplacementTemplateData": json.dumps({"name": f"User{i}", "run": RUN})}}}
                                           for i in (1, 2)])
    check("bulk send delivers one message per entry with its own data",
          len(inbox(f'subject:"Hi User1 {RUN}"')) == 1 and len(inbox(f'subject:"Hi User2 {RUN}"')) == 1)
    raw_msg = EmailMessage(); raw_msg["From"], raw_msg["To"], raw_msg["Subject"] = sender, f"raw-{RUN}@example.net", f"Raw {RUN}"
    raw_msg.set_content("raw body")
    ses2.send_email(FromEmailAddress=sender, Destination={"ToAddresses": [f"raw-{RUN}@example.net"]}, Content={"Raw": {"Data": raw_msg.as_bytes()}})
    check("raw send delivers the message as given", len(inbox(f'subject:"Raw {RUN}"')) == 1)
    try:
        ses2.send_email(FromEmailAddress=f"nobody-{RUN}@unverified.test", Destination={"ToAddresses": ["a@example.net"]},
                        Content={"Simple": {"Subject": {"Data": "x"}, "Body": {"Text": {"Data": "x"}}}})
        check("unverified sender refused", False)
    except Exception as e:
        check("unverified sender refused (MessageRejected)", "MessageRejected" in str(e))

    # ── 2. mailbox simulator + suppression -> events ────────────────────────
    ses2.create_configuration_set(ConfigurationSetName=f"cs-{RUN}")
    ses2.create_configuration_set_event_destination(ConfigurationSetName=f"cs-{RUN}", EventDestinationName="cw",
        EventDestination={"Enabled": True, "MatchingEventTypes": ["SEND", "DELIVERY", "BOUNCE", "COMPLAINT"],
                          "SnsDestination": {"TopicArn": "arn:aws:sns:us-east-1:123456789012:ses-events"}})
    for who in ("bounce", "complaint"):
        ses2.send_email(FromEmailAddress=sender, ConfigurationSetName=f"cs-{RUN}", Destination={"ToAddresses": [f"{who}@simulator.amazonses.com"]},
                        Content={"Simple": {"Subject": {"Data": f"sim {who}"}, "Body": {"Text": {"Data": "x"}}}})
    sup = {s["EmailAddress"]: s["Reason"] for s in ses2.list_suppressed_destinations()["SuppressedDestinationSummaries"]}
    check("bounce simulator adds the address to the suppression list (BOUNCE)", sup.get("bounce@simulator.amazonses.com") == "BOUNCE", str(sup))
    check("complaint simulator adds the address to the suppression list (COMPLAINT)", sup.get("complaint@simulator.amazonses.com") == "COMPLAINT", str(sup))
    ev = {}
    for m in requests.get(f"{BASE}/api/aws/sesv2/sent-emails").json()["items"]:
        if m["config_set"] == f"cs-{RUN}":
            ev[m["subject"]] = m["events"]
    check("bounce and complaint events recorded", "Bounce" in ev.get("sim bounce", "") and "Complaint" in ev.get("sim complaint", ""), str(ev))
    ses2.put_suppressed_destination(EmailAddress=f"supp-{RUN}@example.net", Reason="BOUNCE")
    ses2.send_email(FromEmailAddress=sender, Destination={"ToAddresses": [f"supp-{RUN}@example.net"]},
                    Content={"Simple": {"Subject": {"Data": f"Suppressed {RUN}"}, "Body": {"Text": {"Data": "x"}}}})
    time.sleep(1)
    check("suppressed recipient is not delivered", len(inbox(f'subject:"Suppressed {RUN}"', 1, 2)) == 0)

    # ── 3. SES SMTP interface (smtplib, derived credentials, STARTTLS) ──────
    secret = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    akid = f"AKIA{RUN.upper()}SMTP0000"[:20]
    cred = requests.post(f"{BASE}/api/aws/sesv2/smtp-credentials", json={"access_key_id": akid, "secret_access_key": secret}, timeout=10).json()
    check("SMTP password derivation matches the AWS algorithm", cred.get("password") == smtp_password(secret), str(cred)[:80])
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE

    def smtp_msg(frm, subject):
        m = EmailMessage(); m["From"], m["To"], m["Subject"] = frm, f"smtp-{RUN}@example.net", subject
        m.set_content("sent over the SES SMTP interface"); return m

    try:
        with smtplib.SMTP(HOST, SMTP_PORT, timeout=15) as c:
            c.ehlo()
            try:
                c.login(akid, smtp_password(secret)); ok_plain = True
            except smtplib.SMTPException:
                ok_plain = False
            check("AUTH is refused before STARTTLS", not ok_plain)
        with smtplib.SMTP(HOST, SMTP_PORT, timeout=15) as c:
            c.ehlo(); c.starttls(context=ctx); c.ehlo()
            try:
                c.login(akid, "wrong-password"); bad = False
            except smtplib.SMTPAuthenticationError:
                bad = True
            check("wrong SMTP password is refused (535)", bad)
        with smtplib.SMTP(HOST, SMTP_PORT, timeout=15) as c:
            c.ehlo(); c.starttls(context=ctx); c.ehlo(); c.login(akid, smtp_password(secret))
            c.send_message(smtp_msg(sender, f"SMTP {RUN}"))
            check("verified sender accepted over SMTP", True)
            try:
                c.send_message(smtp_msg(f"evil-{RUN}@unverified.test", f"SMTP evil {RUN}")); refused = False
            except smtplib.SMTPException as e:
                refused = "not verified" in str(e) or "554" in str(e)
            check("unverified sender refused over SMTP like SES", refused)
        got = inbox(f'subject:"SMTP {RUN}"')
        check("SMTP submission lands in Mailpit", len(got) == 1)
        check("SMTP submission appears in the console Sent list",
              any(m["subject"] == f"SMTP {RUN}" for m in requests.get(f"{BASE}/api/aws/sesv2/sent-emails").json()["items"]))
    except OSError as e:
        check("SES SMTP interface reachable", False, str(e))

    # ── 4. optional outbound relay to the user's own SMTP server ────────────
    fake = FakeSmtp(); fport = serve(fake)
    ses2.put_account_details(MailType="TRANSACTIONAL", WebsiteURL="https://vyomi.example.com", UseCaseDescription="sandbox", ProductionAccessEnabled=False)
    check("account starts in the SES sandbox", not ses2.get_account()["ProductionAccessEnabled"])
    pw = f"relay-secret-{RUN}"
    r = requests.post(f"{BASE}/api/aws/sesv2/mail-settings", json={"relay": {"enabled": True, "host": CALLBACK_HOST, "port": fport,
                      "security": "none", "username": "relayuser", "password": pw}}, timeout=15)
    check("relay settings saved", r.status_code == 200, r.text[:200])
    rcpt_ok, rcpt_no = f"rcpt-{RUN}@example.net", f"nope-{RUN}@example.net"
    ses2.create_email_identity(EmailIdentity=rcpt_ok)
    ses2.send_email(FromEmailAddress=sender, Destination={"ToAddresses": [rcpt_ok, rcpt_no]},
                    Content={"Simple": {"Subject": {"Data": f"Relay {RUN}"}, "Body": {"Text": {"Data": "relay me"}}}})
    time.sleep(1.5)
    relayed = [a for _, rc, _ in fake.received for a in rc]
    check("sandbox: verified recipient is relayed to the real SMTP server", rcpt_ok in relayed, str(relayed))
    check("sandbox: unverified recipient is NOT relayed", rcpt_no not in relayed, str(relayed))
    check("relay authenticated with the stored password", fake.logins and fake.logins[-1] == ["relayuser", pw], str(fake.logins))
    check("a copy of every message still lands in Mailpit", len(inbox(f'subject:"Relay {RUN}"')) == 1)
    row = next(x for x in requests.get(f"{BASE}/api/aws/sesv2/sent-emails").json()["items"] if x["subject"] == f"Relay {RUN}")
    check("unverified recipient shows as a Reject event", "Reject" in row["events"], row["events"])
    ses2.put_account_details(MailType="TRANSACTIONAL", WebsiteURL="https://vyomi.example.com", UseCaseDescription="relay test", ProductionAccessEnabled=True)
    ses2.send_email(FromEmailAddress=sender, Destination={"ToAddresses": [rcpt_no]},
                    Content={"Simple": {"Subject": {"Data": f"Relay prod {RUN}"}, "Body": {"Text": {"Data": "prod"}}}})
    time.sleep(1.5)
    check("production access lifts the sandbox rule", rcpt_no in [a for _, rc, _ in fake.received for a in rc])
    ses2.send_email(FromEmailAddress=sender, Destination={"ToAddresses": [f"refuse@example.net"]},
                    Content={"Simple": {"Subject": {"Data": f"Relay fail {RUN}"}, "Body": {"Text": {"Data": "x"}}}})
    time.sleep(1.5)
    row = next(x for x in requests.get(f"{BASE}/api/aws/sesv2/sent-emails").json()["items"] if x["subject"] == f"Relay fail {RUN}")
    check("relay failure shows as a delivery event with the SMTP error", "Bounce" in row["events"], row["events"])
    leak = [u for u in ("/api/aws/sesv2/mail-settings", "/api/aws/sesv2/sent-emails", "/api/aws/sesv2/identities", "/v2/email/account")
            if pw in requests.get(BASE + u, timeout=10).text]
    check("password is never returned by an API", not leak, str(leak))
    try:
        logs = subprocess.run(["docker", "logs", os.environ.get("SIMULATOR_CONTAINER", "appliance-simulator-1")], capture_output=True, text=True, timeout=60)
        check("password is never in the logs", pw not in logs.stdout + logs.stderr)
    except Exception:
        pass
    requests.post(f"{BASE}/api/aws/sesv2/mail-settings", json={"relay": {"enabled": False}}, timeout=10)
    ses2.put_account_details(MailType="TRANSACTIONAL", WebsiteURL="https://vyomi.example.com", UseCaseDescription="sandbox", ProductionAccessEnabled=False)

    # ── 5. inbound: SES v1 receipt rules fed by the :2525 listener ──────────
    bucket = f"inbound-{RUN}"
    s3.create_bucket(Bucket=bucket)
    import io, zipfile
    zb = io.BytesIO()
    with zipfile.ZipFile(zb, "w") as z:
        z.writestr("lambda_function.py", "def lambda_handler(event, context):\n    return {'ok': True}\n")
    fn = f"inbound-fn-{RUN}"
    lam.create_function(FunctionName=fn, Runtime="python3.12", Role="arn:aws:iam::123456789012:role/r", Handler="lambda_function.lambda_handler",
                        Code={"ZipFile": zb.getvalue()})
    rs = f"rs-{RUN}"
    ses1.create_receipt_rule_set(RuleSetName=rs)
    ses1.create_receipt_rule(RuleSetName=rs, Rule={"Name": "to-s3", "Enabled": True, "Recipients": [dom], "ScanEnabled": False, "TlsPolicy": "Optional",
        "Actions": [{"S3Action": {"BucketName": bucket, "ObjectKeyPrefix": "mail/"}},
                    {"LambdaAction": {"FunctionArn": f"arn:aws:lambda:us-east-1:123456789012:function:{fn}", "InvocationType": "Event"}}]})
    ses1.create_receipt_rule(RuleSetName=rs, Rule={"Name": "notify", "Enabled": False, "Recipients": [], "ScanEnabled": True,
        "Actions": [{"SNSAction": {"TopicArn": "arn:aws:sns:us-east-1:123456789012:inbound", "Encoding": "UTF-8"}}, {"StopAction": {"Scope": "RuleSet"}}]})
    ses1.create_receipt_rule(RuleSetName=rs, Rule={"Name": "reject-bounce", "Enabled": True, "Recipients": [f"reject@{dom}"], "ScanEnabled": False,
        "Actions": [{"BounceAction": {"SmtpReplyCode": "550", "StatusCode": "5.1.1", "Message": "Mailbox does not exist", "Sender": f"mailer-daemon@{dom}"}}]})
    d = ses1.describe_receipt_rule_set(RuleSetName=rs)
    check("receipt rule set round-trips (3 rules, S3 + Lambda actions on the first)", len(d["Rules"]) == 3 and len(d["Rules"][0]["Actions"]) == 2 and "SNSAction" in next(r for r in d["Rules"] if r["Name"] == "notify")["Actions"][0], str(d)[:200])
    check("receipt rule set is listed", rs in [x["Name"] for x in ses1.list_receipt_rule_sets()["RuleSets"]])
    ses1.set_active_receipt_rule_set(RuleSetName=rs)
    check("active receipt rule set is reported", ses1.describe_active_receipt_rule_set().get("Metadata", {}).get("Name") == rs)
    try:
        ses1.delete_receipt_rule_set(RuleSetName=rs); check("active rule set cannot be deleted", False)
    except Exception as e:
        check("active rule set cannot be deleted (CannotDelete)", "CannotDelete" in str(e))

    def inbound(rcpt, subject):
        m = EmailMessage(); m["From"], m["To"], m["Subject"] = "someone@elsewhere.example", rcpt, subject
        m.set_content("inbound body " + RUN)
        with smtplib.SMTP(HOST, INBOUND_PORT, timeout=15) as c:
            return c.send_message(m)

    inbound(f"hello@{dom}", f"Inbound {RUN}")
    time.sleep(2)
    keys = [o["Key"] for o in s3.list_objects_v2(Bucket=bucket, Prefix="mail/").get("Contents", [])]
    check("inbound mail for a verified domain is saved to S3 by the rule", len(keys) == 1, str(keys))
    if keys:
        body = s3.get_object(Bucket=bucket, Key=keys[0])["Body"].read().decode()
        check("saved S3 object is the raw message", f"Subject: Inbound {RUN}" in body and "inbound body" in body)
    inv = requests.get(f"{BASE}/api/lambda/functions/{fn}/invocations", timeout=10).json().get("invocations", [])
    ev = (inv[0].get("request_payload") or {}).get("Records", [{}])[0] if inv else {}
    check("the Lambda in the receipt rule was invoked with the SES event", ev.get("eventSource") == "aws:ses"
          and ev.get("ses", {}).get("mail", {}).get("commonHeaders", {}).get("subject") == f"Inbound {RUN}", str(inv)[:200])
    try:
        inbound(f"x@unverified-{RUN}.example", "nope"); check("mail for an unverified domain is refused", False)
    except smtplib.SMTPRecipientsRefused as e:
        check("mail for an unverified domain is refused (550)", all(v[0] == 550 for v in e.recipients.values()))
    try:
        inbound(f"reject@{dom}", "bounce me"); check("BounceAction rejects the message", False)
    except (smtplib.SMTPRecipientsRefused, smtplib.SMTPDataError) as e:
        code = getattr(e, "smtp_code", None) or next(iter(e.recipients.values()))[0]
        check("BounceAction rejects the message with its SMTP reply (550)", code == 550, str(e)[:100])
    rec = requests.get(f"{BASE}/api/aws/sesv2/received-emails", timeout=10).json()["items"]
    check("console Received list shows the message, rules and actions",
          any(r["subject"] == f"Inbound {RUN}" and "to-s3" in r["rules"] and "S3Action" in r["actions"] for r in rec), str(rec)[:200])

    # ── 6. inbound over IMAP (a real mailbox, polled) ───────────────────────
    m = EmailMessage(); m["From"], m["To"], m["Subject"] = "friend@gmail.example", f"me@{dom}", f"Imap {RUN}"
    m.set_content("from my real mailbox")
    imap = FakeImap(m.as_bytes()); iport = serve(imap)
    ipw = f"imap-secret-{RUN}"
    r = requests.post(f"{BASE}/api/aws/sesv2/mail-settings", json={"imap": {"enabled": False, "host": CALLBACK_HOST, "port": iport,
                      "security": "none", "username": "me", "password": ipw, "folder": "INBOX"}}, timeout=10)
    check("IMAP settings saved", r.status_code == 200, r.text[:200])
    p = requests.post(f"{BASE}/api/aws/sesv2/inbound-poll", timeout=60).json()
    check("IMAP poll fetched the new message and ran the receipt rules", p.get("processed") == 1 and not p.get("errors"), str(p))
    check("IMAP login used the stored password", imap.logins and imap.logins[-1][1].strip('"') == ipw, str(imap.logins))
    check("IMAP message was saved to S3 by the rule", len(s3.list_objects_v2(Bucket=bucket, Prefix="mail/").get("Contents", [])) == 2)
    check("second poll finds nothing new", requests.post(f"{BASE}/api/aws/sesv2/inbound-poll", timeout=60).json().get("processed") == 0)
    check("IMAP password is never returned by an API", ipw not in requests.get(f"{BASE}/api/aws/sesv2/mail-settings", timeout=10).text)

    ses1.set_active_receipt_rule_set()
    ses1.delete_receipt_rule_set(RuleSetName=rs)
    check("rule set deletable once inactive", rs not in [x["Name"] for x in ses1.list_receipt_rule_sets()["RuleSets"]])
    requests.post(f"{BASE}/api/aws/sesv2/mail-settings", json={"imap": {"enabled": False}}, timeout=10)
    # leave the space as found
    for ident in (sender, dom, rcpt_ok):
        ses2.delete_email_identity(EmailIdentity=ident)
    ses2.delete_email_template(TemplateName=f"t-{RUN}")
    ses2.delete_configuration_set(ConfigurationSetName=f"cs-{RUN}")
    for a in ("bounce@simulator.amazonses.com", "complaint@simulator.amazonses.com", f"supp-{RUN}@example.net"):
        ses2.delete_suppressed_destination(EmailAddress=a)
    s3.delete_object(Bucket=bucket, Key=keys[0]) if keys else None
    sys.exit(1 if failed else 0)


main()
