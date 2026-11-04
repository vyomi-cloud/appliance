"""AWS-13 SNS SMS: sandbox verification code lands in the simulated handset inbox; verifying with it works; Publish to the verified phone
shows up in the inbox. Via AwsWireRouter (Query protocol, signing name sns). Run: PYTHONPATH=. python3 tests/conformance/test_sns_sms_inbox.py
"""
import re
import urllib.parse

from core.aws_wire_router import AwsWireRouter

AUTH = "AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/sns/aws4_request, SignedHeaders=host, Signature=0"


def q(r, action, **p):
    body = urllib.parse.urlencode({"Action": action, "Version": "2010-03-31", **p}).encode()
    out = r.handle("POST", "/", {}, {"authorization": AUTH, "content-type": "application/x-www-form-urlencoded"}, body)
    return out["status"], out["body"].decode()


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


PH = "+15551230001"


def main():
    r = AwsWireRouter()
    st, x = q(r, "VyomiListSimulatedSMS")
    _check("inbox starts empty", st == 200 and "<member>" not in x)
    st, x = q(r, "CreateSMSSandboxPhoneNumber", PhoneNumber=PH)
    _check("CreateSMSSandboxPhoneNumber", st == 200)
    st, x = q(r, "VyomiListSimulatedSMS", PhoneNumber=PH)
    m = re.search(r"Your verification code is (\d{6})", x)
    _check("verification code is delivered to the simulated handset", st == 200 and m and "SMSSandboxVerification" in x)
    st, x = q(r, "VyomiListSimulatedSMS", PhoneNumber="+15559998888")
    _check("inbox is per phone number", "<member>" not in x)
    st, x = q(r, "Publish", PhoneNumber=PH, Message="hi")
    _check("publish to unverified phone fails", st == 400)
    st, x = q(r, "VerifySMSSandboxPhoneNumber", PhoneNumber=PH, OneTimePassword="000000")
    _check("wrong code -> VerificationException", st == 400 and "VerificationException" in x)
    st, x = q(r, "VerifySMSSandboxPhoneNumber", PhoneNumber=PH, OneTimePassword=m.group(1))
    _check("the code read from the inbox verifies the phone", st == 200)
    st, x = q(r, "Publish", PhoneNumber=PH, Message="order shipped")
    _check("publish to verified phone", st == 200)
    st, x = q(r, "VyomiListSimulatedSMS", PhoneNumber=PH)
    _check("published SMS appears in the inbox, newest first", x.index("order shipped") < x.index("verification code"))
    print("PASS sns sms inbox")


if __name__ == "__main__":
    main()
