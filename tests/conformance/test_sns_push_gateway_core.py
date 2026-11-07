"""SNS mobile push gateway stub: platform-native payloads, a push inbox, and a real HTTP webhook delivery with
unregistered-token (404/410) endpoint disabling.

Run: PYTHONPATH=. ../s3_simulator/.venv/bin/python tests/conformance/test_sns_push_gateway_core.py
"""
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from core.messaging_store import InMemoryMessagingStore
from core import sns_core as sns

GOT = []
CODE = [200]


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        GOT.append((self.headers.get("x-vyomi-push-platform"), json.loads(self.rfile.read(int(self.headers["content-length"])))))
        self.send_response(CODE[0]); self.end_headers()

    def log_message(self, *a):
        pass


def _check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} {detail}")
    print(f"  ok  {name}")


def _v(xml, tag):
    m = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.S)
    return m.group(1) if m else ""


def main():
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}/push"
    st = InMemoryMessagingStore()
    call = lambda a, **p: sns.dispatch(st, dict(p, Action=a))
    app = _v(call("CreatePlatformApplication", Name="app", Platform="GCM", **{"Attributes.entry.1.key": "PlatformCredential", "Attributes.entry.1.value": "k"}).body, "PlatformApplicationArn")
    ep = _v(call("CreatePlatformEndpoint", PlatformApplicationArn=app, Token="tok1", **{"Attributes.entry.1.key": "VyomiPushWebhook", "Attributes.entry.1.value": url}).body, "EndpointArn")
    r = call("Publish", TargetArn=ep, Message="hello device")
    _check("publish ok", r.status == 200, r.body[:200])
    _check("webhook received platform-native FCM payload", GOT and GOT[0][0] == "GCM" and GOT[0][1]["payload"] == {"data": {"message": "hello device"}}, str(GOT))
    inbox = call("VyomiListPushInbox", EndpointArn=ep).body
    _check("inbox has it, delivered via webhook", "hello device" in inbox and "<Delivery>webhook</Delivery>" in inbox, inbox[:300])
    # APNS payload shape
    appa = _v(call("CreatePlatformApplication", Name="ios", Platform="APNS", **{"Attributes.entry.1.key": "PlatformCredential", "Attributes.entry.1.value": "k"}).body, "PlatformApplicationArn")
    epa = _v(call("CreatePlatformEndpoint", PlatformApplicationArn=appa, Token="tok2").body, "EndpointArn")
    call("Publish", TargetArn=epa, Message="hi ios")
    ib = call("VyomiListPushInbox", EndpointArn=epa).body
    _check("APNS aps.alert payload, inbox-only without a webhook", "aps" in ib and "hi ios" in ib and "<Delivery>inbox</Delivery>" in ib, ib[:300])
    # gateway says token unregistered -> endpoint disabled, next publish fails
    CODE[0] = 410
    call("Publish", TargetArn=ep, Message="gone")
    _check("410 disables the endpoint", "<value>false</value>" in call("GetEndpointAttributes", EndpointArn=ep).body.replace("</entry>", "") or 'Enabled' in call("GetEndpointAttributes", EndpointArn=ep).body and "false" in call("GetEndpointAttributes", EndpointArn=ep).body)
    r = call("Publish", TargetArn=ep, Message="again")
    _check("publish to disabled endpoint -> EndpointDisabled", r.status == 400 and "EndpointDisabled" in r.body)
    srv.shutdown()


if __name__ == "__main__":
    main()
