"""Phase 6 — the unified wire ingress on REAL backends (Pro/Max).

ONE AwsWireRouter, wired to the real appliance backends (MinIO/Postgres/Vault/
NATS), serves AWS + GCP native-wire requests — the same router the Nano relay
uses, only the injected stores differ. Proves the Phase-6 ingress architecture
end-to-end before the legacy per-service handlers are retired. Host-only.
"""
import base64
import json

from core.wire_ingress import build_backed_router


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _sig(service):
    return ("AWS4-HMAC-SHA256 "
            f"Credential=AKIA/20260713/us-east-1/{service}/aws4_request, "
            "SignedHeaders=host, Signature=deadbeef")


def _body(r):
    b = r["body"]
    return b if isinstance(b, (bytes, bytearray)) else str(b).encode()


def run() -> int:
    R = build_backed_router()

    # AWS S3 → MinIO
    R.handle("PUT", "/ingress-s3b", {}, {"Authorization": _sig("s3")}, b"")
    R.handle("PUT", "/ingress-s3b/k.txt", {}, {"Authorization": _sig("s3")}, b"aws-real-bytes")
    g = R.handle("GET", "/ingress-s3b/k.txt", {}, {"Authorization": _sig("s3")}, b"")
    _check("AWS S3 via unified ingress → MinIO round-trips", _body(g) == b"aws-real-bytes")

    # GCP GCS → MinIO
    R.handle("POST", "/storage/v1/b", {}, {}, json.dumps({"name": "ingress-gb"}).encode())
    R.handle("POST", "/upload/storage/v1/b/ingress-gb/o", {"uploadType": "media", "name": "k"},
             {"content-type": "text/plain"}, b"gcp-real-bytes")
    dl = R.handle("GET", "/storage/v1/b/ingress-gb/o/k", {"alt": "media"}, {}, b"")
    _check("GCP GCS via unified ingress → MinIO round-trips", _body(dl) == b"gcp-real-bytes")

    # GCP Cloud KMS → Vault Transit
    P = "/v1/projects/demo/locations/global/keyRings/r/cryptoKeys"
    R.handle("POST", "/v1/projects/demo/locations/global/keyRings", {"keyRingId": "r"}, {}, b"{}")
    R.handle("POST", P, {"cryptoKeyId": "k"}, {}, json.dumps({"purpose": "ENCRYPT_DECRYPT"}).encode())
    enc = json.loads(_body(R.handle("POST", f"{P}/k:encrypt", {}, {},
                     json.dumps({"plaintext": base64.b64encode(b"ingress-crypto").decode()}).encode())))
    dec = json.loads(_body(R.handle("POST", f"{P}/k:decrypt", {}, {},
                     json.dumps({"ciphertext": enc["ciphertext"]}).encode())))
    _check("GCP KMS via unified ingress → Vault decrypts",
           base64.b64decode(dec["plaintext"]) == b"ingress-crypto")

    # GCP Pub/Sub → NATS JetStream
    PP = "/v1/projects/demo"
    R.handle("PUT", f"{PP}/topics/it", {}, {}, b"{}")
    R.handle("PUT", f"{PP}/subscriptions/isub", {}, {}, json.dumps({"topic": "projects/demo/topics/it"}).encode())
    R.handle("POST", f"{PP}/topics/it:publish", {}, {},
             json.dumps({"messages": [{"data": base64.b64encode(b"ingress-msg").decode()}]}).encode())
    pull = json.loads(_body(R.handle("POST", f"{PP}/subscriptions/isub:pull", {}, {},
                     json.dumps({"maxMessages": 10}).encode())))
    ms = pull.get("receivedMessages", [])
    _check("GCP Pub/Sub via unified ingress → NATS delivers",
           ms and base64.b64decode(ms[0]["message"]["data"]) == b"ingress-msg")

    # independent proof the S3 bytes physically live in MinIO
    raw = R.s3._s3.get_object(Bucket="aws-s3-ingress-s3b", Key="k.txt")["Body"].read()
    _check("bytes are real MinIO objects (external client)", raw == b"aws-real-bytes")

    print("\nPHASE 6: ALL GREEN — one unified wire router serves AWS + GCP on real backends "
          "(MinIO + Vault + NATS), the same router the Nano relay uses. Ingress architecture proven.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
