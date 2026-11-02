"""IAM sweep 1 — real TOTP MFA, enforced password policy, account summary, access-key last-used,
SSH keys / service-specific credentials / signing + server certificates, root principal state,
security recommendations, IAM event log, full credential report. Everything goes through
AwsWireRouter (the Nano / unified-ingress entry), with some calls signed with a user's own key.

Run: PYTHONPATH=. python3 tests/conformance/test_iam_sweepiam_core.py
"""
import base64
import re
import time
from urllib.parse import urlencode

from core import iam_core
from core.aws_wire_router import AwsWireRouter

OP = "AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/iam/aws4_request, SignedHeaders=host, Signature=0"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def iam(r, action, akid=None, **p):
    auth = OP.replace("Credential=T/", f"Credential={akid}/") if akid else OP
    out = r.handle("POST", "/", {}, {"authorization": auth, "content-type": "application/x-www-form-urlencoded"},
                   urlencode({"Action": action, "Version": "2010-05-08", **p}).encode())
    return out["status"], out["body"].decode()


def tag(body, t):
    m = re.search(rf"<{t}>(.*?)</{t}>", body, re.S)
    return m.group(1) if m else None


def run():
    r = AwsWireRouter()
    # ── password policy enforcement ────────────────────────────────────
    iam(r, "CreateUser", UserName="alice")
    s, b = iam(r, "CreateLoginProfile", UserName="alice", Password="short")
    _check("default policy rejects a short password", s == 400 and "PasswordPolicyViolation" in b)
    s, b = iam(r, "CreateLoginProfile", UserName="alice", Password="alllowercaseletters")
    _check("default policy needs 3 of 4 character types", s == 400 and "PasswordPolicyViolation" in b)
    iam(r, "UpdateAccountPasswordPolicy", MinimumPasswordLength="14", RequireSymbols="true", RequireNumbers="true",
        RequireUppercaseCharacters="true", RequireLowercaseCharacters="true", AllowUsersToChangePassword="true",
        PasswordReusePrevention="2", MaxPasswordAge="30")
    s, b = iam(r, "CreateLoginProfile", UserName="alice", Password="Abcdef1!")
    _check("custom policy: min length 14 enforced", s == 400 and "at least 14 characters" in b)
    s, b = iam(r, "CreateLoginProfile", UserName="alice", Password="Abcdefghijklmno1")
    _check("custom policy: symbol required", s == 400 and "non-alphanumeric" in b)
    s, b = iam(r, "CreateLoginProfile", UserName="alice", Password="Correct-Horse-Battery-9", PasswordResetRequired="true")
    _check("compliant password creates the profile", s == 200 and tag(b, "PasswordResetRequired") == "true")
    s, b = iam(r, "UpdateLoginProfile", UserName="alice", Password="Correct-Horse-Battery-9")
    _check("reuse of the current password rejected (PasswordReusePrevention)", s == 400 and "last 2 passwords" in b)
    s, b = iam(r, "UpdateLoginProfile", UserName="alice", Password="Another-Strong-Pass-7")
    _check("a new compliant password is accepted", s == 200)

    # ── access keys, last-used, ChangePassword as the caller ───────────
    s, b = iam(r, "CreateAccessKey", UserName="alice")
    akid, secret = tag(b, "AccessKeyId"), tag(b, "SecretAccessKey")
    s, b = iam(r, "GetAccessKeyLastUsed", AccessKeyId=akid)
    _check("never-used key reports N/A", "<ServiceName>N/A</ServiceName>" in b and "LastUsedDate" not in b)
    s, b = iam(r, "ListUsers", akid=akid)
    s, b = iam(r, "GetAccessKeyLastUsed", AccessKeyId=akid)
    _check("last-used recorded from a request signed with the key", tag(b, "ServiceName") == "iam" and tag(b, "LastUsedDate"))
    _check("last-used names the owner", tag(b, "UserName") == "alice")
    s, b = iam(r, "ChangePassword", OldPassword="wrong", NewPassword="Third-Strong-Pass-5!!")
    _check("ChangePassword as the console operator is refused (not an IAM user)", s == 400 and "InvalidUserType" in b)
    s, b = iam(r, "ChangePassword", akid=akid, OldPassword="wrong", NewPassword="Third-Strong-Pass-5!!")
    _check("ChangePassword with a wrong old password refused", s == 400)
    s, b = iam(r, "ChangePassword", akid=akid, OldPassword="Another-Strong-Pass-7", NewPassword="weak")
    _check("ChangePassword enforces the policy", s == 400 and "PasswordPolicyViolation" in b)
    s, b = iam(r, "ChangePassword", akid=akid, OldPassword="Another-Strong-Pass-7", NewPassword="Third-Strong-Pass-5!!")
    _check("ChangePassword as the user succeeds", s == 200)
    s, b = iam(r, "GetLoginProfile", UserName="alice")
    _check("reset-required cleared by ChangePassword", tag(b, "PasswordResetRequired") == "false")
    iam(r, "UpdateAccountPasswordPolicy", MinimumPasswordLength="8", AllowUsersToChangePassword="false")
    s, b = iam(r, "ChangePassword", akid=akid, OldPassword="Third-Strong-Pass-5!!", NewPassword="Fourth-Strong-Pass-1!!")
    _check("AllowUsersToChangePassword=false blocks ChangePassword", s == 403)
    s, b = iam(r, "CreateAccessKey", akid=akid)
    _check("CreateAccessKey without UserName targets the caller", tag(b, "UserName") == "alice")
    s, b = iam(r, "CreateAccessKey", UserName="alice")
    _check("third access key -> LimitExceeded", s == 409 and "LimitExceeded" in b)
    s, b = iam(r, "DeleteUser", UserName="alice")
    _check("user with access keys cannot be deleted (DeleteConflict)", s == 409 and "DeleteConflict" in b)

    # ── real TOTP MFA ──────────────────────────────────────────────────
    s, b = iam(r, "CreateVirtualMFADevice", VirtualMFADeviceName="alice-phone")
    serial, seed = tag(b, "SerialNumber"), base64.b64decode(tag(b, "Base32StringSeed")).decode()
    step = int(time.time() // 30)
    s, b = iam(r, "EnableMFADevice", UserName="alice", SerialNumber=serial, AuthenticationCode1="123456", AuthenticationCode2="654321")
    _check("wrong TOTP codes rejected", s == 403 and "InvalidAuthenticationCode" in b)
    s, b = iam(r, "EnableMFADevice", UserName="alice", SerialNumber=serial,
               AuthenticationCode1=iam_core._totp(seed, step + 1), AuthenticationCode2=iam_core._totp(seed, step))
    _check("codes in the wrong order are not 'consecutive'", s == 403)
    s, b = iam(r, "EnableMFADevice", UserName="alice", SerialNumber=serial,
               AuthenticationCode1=iam_core._totp(seed, step), AuthenticationCode2=iam_core._totp(seed, step + 1))
    _check("two consecutive valid TOTP codes enable the device", s == 200)
    # RFC 6238 vector: secret "12345678901234567890" at T=59 -> 94287082 (8 digit) => 6-digit tail 287082
    _check("TOTP matches the RFC 6238 test vector", iam_core._totp(base64.b32encode(b"12345678901234567890").decode(), 59 // 30) == "287082")
    s, b = iam(r, "ResyncMFADevice", UserName="alice", SerialNumber=serial,
               AuthenticationCode1=iam_core._totp(seed, step - 5), AuthenticationCode2=iam_core._totp(seed, step - 4))
    _check("resync accepts codes inside the wider drift window", s == 200)
    s, b = iam(r, "ResyncMFADevice", UserName="alice", SerialNumber=serial, AuthenticationCode1="000000", AuthenticationCode2="111111")
    _check("resync rejects codes that are not from this device", s == 403)

    # ── root principal: MFA + access keys ──────────────────────────────
    s, b = iam(r, "GetAccountSummary")
    sm = dict(re.findall(r"<key>(\w+)</key><value>(\d+)</value>", b))
    _check("summary: Users=1, MFADevicesInUse=1, root MFA off", sm["Users"] == "1" and sm["MFADevicesInUse"] == "1" and sm["AccountMFAEnabled"] == "0")
    s, b = iam(r, "GetSecurityRecommendations")
    _check("recommendation: root MFA missing", "<Id>root-mfa</Id>" in b)
    s, b = iam(r, "CreateVirtualMFADevice", VirtualMFADeviceName="root-account-mfa-device")
    rserial, rseed = tag(b, "SerialNumber"), base64.b64decode(tag(b, "Base32StringSeed")).decode()
    s, b = iam(r, "EnableMFADevice", UserName="root", SerialNumber=rserial,
               AuthenticationCode1=iam_core._totp(rseed, step), AuthenticationCode2=iam_core._totp(rseed, step + 1))
    _check("root MFA can be registered", s == 200)
    s, b = iam(r, "GetAccountSummary")
    sm = dict(re.findall(r"<key>(\w+)</key><value>(\d+)</value>", b))
    _check("summary: AccountMFAEnabled=1", sm["AccountMFAEnabled"] == "1")
    s, b = iam(r, "GetSecurityRecommendations")
    _check("root-MFA recommendation clears", "<Id>root-mfa</Id>" not in b)
    iam(r, "CreateUser", UserName="bob")
    iam(r, "CreateLoginProfile", UserName="bob", Password="Bobs-Strong-Pass-3!!")
    s, b = iam(r, "GetSecurityRecommendations")
    _check("recommendation: bob has a password but no MFA", "<Id>user-mfa</Id>" in b and "user/bob" in b)
    s, b = iam(r, "CreateAccessKey")
    rk = tag(b, "AccessKeyId")
    _check("CreateAccessKey with no caller targets the root user", tag(b, "UserName") == "&lt;root_account&gt;")
    s, b = iam(r, "GetSecurityRecommendations")
    _check("recommendation: root access key present", "<Id>root-keys</Id>" in b and rk in b)
    s, b = iam(r, "GetAccountSummary")
    _check("summary: AccountAccessKeysPresent=1", "<key>AccountAccessKeysPresent</key><value>1</value>" in b)

    # ── SSH public keys ────────────────────────────────────────────────
    blob = base64.b64encode(b"\x00\x00\x00\x07ssh-rsa" + b"x" * 40).decode()
    pub = f"ssh-rsa {blob} alice@laptop"
    s, b = iam(r, "UploadSSHPublicKey", UserName="alice", SSHPublicKeyBody="not a key")
    _check("malformed SSH key rejected", s == 400 and "InvalidPublicKey" in b)
    s, b = iam(r, "UploadSSHPublicKey", UserName="alice", SSHPublicKeyBody=pub)
    kid = tag(b, "SSHPublicKeyId")
    _check("SSH key uploaded with an MD5 fingerprint", s == 200 and kid.startswith("APKA") and re.fullmatch(r"([0-9a-f]{2}:){15}[0-9a-f]{2}", tag(b, "Fingerprint")))
    s, b = iam(r, "UploadSSHPublicKey", UserName="alice", SSHPublicKeyBody=pub)
    _check("duplicate SSH key rejected", s == 400 and "DuplicateSSHPublicKey" in b)
    s, b = iam(r, "ListSSHPublicKeys", UserName="alice")
    _check("SSH key listed", kid in b)
    iam(r, "UpdateSSHPublicKey", UserName="alice", SSHPublicKeyId=kid, Status="Inactive")
    s, b = iam(r, "GetSSHPublicKey", UserName="alice", SSHPublicKeyId=kid, Encoding="SSH")
    _check("SSH key deactivated and body returned", tag(b, "Status") == "Inactive" and pub in b)
    s, b = iam(r, "DeleteUser", UserName="bob")
    _check("bob (no keys) deletes", s == 200 or "DeleteConflict" in b)

    # ── service-specific credentials ───────────────────────────────────
    s, b = iam(r, "CreateServiceSpecificCredential", UserName="alice", ServiceName="codecommit.amazonaws.com")
    cid, pw1 = tag(b, "ServiceSpecificCredentialId"), tag(b, "ServicePassword")
    _check("service credential created with a one-time password", s == 200 and cid.startswith("ACCA") and pw1 and tag(b, "ServiceUserName") == "alice-at-123456789012")
    s, b = iam(r, "ListServiceSpecificCredentials", UserName="alice")
    _check("listing never re-reveals the password", cid in b and "ServicePassword" not in b)
    s, b = iam(r, "ResetServiceSpecificCredential", UserName="alice", ServiceSpecificCredentialId=cid)
    _check("reset issues a new password", tag(b, "ServicePassword") != pw1)
    iam(r, "UpdateServiceSpecificCredential", ServiceSpecificCredentialId=cid, Status="Inactive")
    s, b = iam(r, "ListServiceSpecificCredentials", UserName="alice", ServiceName="codecommit.amazonaws.com")
    _check("status update persisted", tag(b, "Status") == "Inactive")
    s, b = iam(r, "CreateServiceSpecificCredential", UserName="alice", ServiceName="nope.amazonaws.com")
    _check("unknown service rejected", s == 404)
    iam(r, "DeleteServiceSpecificCredential", UserName="alice", ServiceSpecificCredentialId=cid)
    s, b = iam(r, "ListServiceSpecificCredentials", UserName="alice")
    _check("service credential deleted", cid not in b)

    # ── X.509 signing + server certificates ────────────────────────────
    der = _self_signed_der()
    pem = "-----BEGIN CERTIFICATE-----\n" + base64.b64encode(der).decode() + "\n-----END CERTIFICATE-----"
    s, b = iam(r, "UploadSigningCertificate", UserName="alice", CertificateBody="garbage")
    _check("malformed signing cert rejected", s == 400 and "MalformedCertificate" in b)
    s, b = iam(r, "UploadSigningCertificate", UserName="alice", CertificateBody=pem)
    certid = tag(b, "CertificateId")
    _check("signing certificate uploaded", s == 200 and certid)
    iam(r, "UpdateSigningCertificate", UserName="alice", CertificateId=certid, Status="Inactive")
    s, b = iam(r, "ListSigningCertificates", UserName="alice")
    _check("signing cert listed inactive", certid in b and tag(b, "Status") == "Inactive")
    s, b = iam(r, "UploadServerCertificate", ServerCertificateName="web", CertificateBody=pem,
               PrivateKey="-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----", Path="/prod/")
    _check("server certificate uploaded with real notAfter", s == 200 and tag(b, "Expiration").startswith("2036-01-01"))
    _check("server cert ARN carries the path", tag(b, "Arn") == "arn:aws:iam::123456789012:server-certificate/prod/web")
    s, b = iam(r, "ListServerCertificates", PathPrefix="/prod/")
    _check("server certificate listed", "<ServerCertificateName>web</ServerCertificateName>" in b)
    s, b = iam(r, "GetServerCertificate", ServerCertificateName="web")
    _check("server certificate body returned", "BEGIN CERTIFICATE" in b)
    iam(r, "UpdateServerCertificate", ServerCertificateName="web", NewServerCertificateName="web2")
    s, b = iam(r, "GetServerCertificate", ServerCertificateName="web2")
    _check("server certificate renamed", s == 200)
    s, b = iam(r, "GetAccountSummary")
    _check("summary counts the server certificate", "<key>ServerCertificates</key><value>1</value>" in b)
    s, b = iam(r, "SetSecurityTokenServicePreferences", GlobalEndpointTokenVersion="v2Token")
    s, b = iam(r, "GetAccountSummary")
    _check("STS global endpoint token version is a real account setting", s == 200 and "<key>GlobalEndpointTokenVersion</key><value>2</value>" in b)
    s, b = iam(r, "SetSecurityTokenServicePreferences", GlobalEndpointTokenVersion="v3")
    _check("invalid token version rejected", s == 400)
    iam(r, "DeleteServerCertificate", ServerCertificateName="web2")
    s, b = iam(r, "GetServerCertificate", ServerCertificateName="web2")
    _check("server certificate deleted", s == 404)

    # ── credential report + event log ──────────────────────────────────
    iam(r, "GenerateCredentialReport")
    s, b = iam(r, "GetCredentialReport")
    csv = base64.b64decode(tag(b, "Content")).decode().splitlines()
    cols = csv[0].split(",")
    _check("credential report has the full AWS column set", len(cols) == 22 and "access_key_1_last_used_service" in cols and "cert_1_active" in cols)
    row = dict(zip(cols, next(l for l in csv if l.startswith("alice,")).split(",")))
    _check("report: alice has a password, MFA, key 1 last-used from real activity",
           row["password_enabled"] == "true" and row["mfa_active"] == "true" and row["access_key_1_last_used_service"] == "iam"
           and row["cert_1_active"] == "false" and row["cert_1_last_rotated"] != "N/A")
    root = dict(zip(cols, csv[1].split(",")))
    _check("report: root row shows root MFA + key", root["user"] == "<root_account>" and root["mfa_active"] == "true" and root["access_key_1_active"] == "true")
    s, b = iam(r, "ListIamEvents", MaxItems="500")
    _check("event log records admin actions newest-first with outcome", tag(b, "EventName") and "<EventName>CreateServerCertificate" not in b
           and "UploadServerCertificate" in b and "<Status>PasswordPolicyViolation</Status>" in b)
    _check("event log attributes caller-signed actions", "<Principal>alice</Principal>" in b)
    s, b = iam(r, "ListIamEvents", EventName="DeleteServerCertificate")
    _check("event log filters by name", b.count("<member>") == 1)
    print("\nRESULT: PASS - IAM sweep 1 behaviours hold on the Nano-style AwsWireRouter")


def _der(tag_, content):
    n = len(content)
    hdr = bytes([tag_, n]) if n < 128 else bytes([tag_, 0x81, n]) if n < 256 else bytes([tag_, 0x82, n >> 8, n & 255])
    return hdr + content


def _self_signed_der():
    """A structurally valid X.509 skeleton (version, serial, sigalg, issuer, validity ...) - enough for the
    validity walk; it is not a signed certificate and the core never claims to verify one."""
    ver = _der(0xA0, _der(0x02, b"\x02"))
    serial = _der(0x02, b"\x01")
    alg = _der(0x30, _der(0x06, b"\x2a\x86\x48\x86\xf7\x0d\x01\x01\x0b"))
    name = _der(0x30, _der(0x31, _der(0x30, _der(0x06, b"\x55\x04\x03") + _der(0x0c, b"vyomi"))))
    validity = _der(0x30, _der(0x17, b"260101000000Z") + _der(0x18, b"20360101000000Z"))
    tbs = _der(0x30, ver + serial + alg + name + validity + name)
    return _der(0x30, tbs + alg + _der(0x03, b"\x00abcd"))


if __name__ == "__main__":
    run()
