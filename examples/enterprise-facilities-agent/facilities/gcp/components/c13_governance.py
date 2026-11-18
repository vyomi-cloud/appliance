"""C13: governance and security: Cloud KMS envelope protection of the ledger payload (with AAD), Cloud Audit Logs read-back of the run."""
import json, time
from google.api_core import exceptions as gex
from ..runtime import NAMES, LANE, Blocked


def run(ctx):
    from google.cloud import kms
    P = f"projects/{ctx.project}"
    c = ctx.rest(kms.KeyManagementServiceClient)

    def key():
        parent = f"{ctx.parent}/keyRings/{NAMES['keyring']}"
        try:
            c.create_key_ring(request={"parent": ctx.parent, "key_ring_id": NAMES["keyring"], "key_ring": {}})
        except gex.AlreadyExists:
            pass
        try:
            k = c.create_crypto_key(request={"parent": parent, "crypto_key_id": NAMES["key"], "crypto_key": {
                "purpose": kms.CryptoKey.CryptoKeyPurpose.ENCRYPT_DECRYPT, "rotation_period": {"seconds": 7776000}, "next_rotation_time": {"seconds": int(time.time()) + 7776000}}}).name
        except gex.AlreadyExists:
            k = f"{parent}/cryptoKeys/{NAMES['key']}"
        ctx.state["kms_key"] = k
        return f"{k} with 90-day rotation"
    ctx.step("kms: key ring facilities + ledger-key (ENCRYPT_DECRYPT, rotation)", key)
    k = ctx.state.get("kms_key")
    if k:
        def seal():
            from cryptography.fernet import Fernet
            aad = f"collection={NAMES['ledger']}".encode()
            wo = ctx.state.get("work_order_id", "WO-000000")
            pt = json.dumps({"work_order": wo, "approved_by": "duty.manager@example.com"}).encode()
            dek = Fernet.generate_key()                                   # envelope: a data key encrypts the record locally, KMS wraps the data key
            blob = Fernet(dek).encrypt(pt)
            wrapped = c.encrypt(request={"name": k, "plaintext": dek, "additional_authenticated_data": aad}).ciphertext
            assert b"duty.manager" not in blob and dek not in wrapped
            back = c.decrypt(request={"name": k, "ciphertext": wrapped, "additional_authenticated_data": aad}).plaintext
            assert json.loads(Fernet(back).decrypt(blob))["work_order"] == wo
            ctx.state["sealed"] = (blob, wrapped)
            return "ledger record sealed with a KMS-wrapped data key; round trip ok"
        ctx.step("kms: envelope-encrypt the approval record (data key wrapped by KMS with AAD)", seal)

        def aad():
            blob, wrapped = ctx.state["sealed"]
            try:
                c.decrypt(request={"name": k, "ciphertext": wrapped, "additional_authenticated_data": b"collection=other"})
            except gex.GoogleAPICallError:
                return "wrong additional_authenticated_data is refused"
            raise Blocked(LANE["core"], "decrypt succeeded with the wrong additional_authenticated_data (the simulator does not enforce AAD)")
        if ctx.state.get("sealed"):
            ctx.step("kms: decrypt with the wrong AAD is refused", aad)

    def audit():
        from google.cloud import logging as gl
        lc = gl.Client(project=ctx.project, credentials=ctx.anon(), _use_grpc=False)
        lc._connection.API_BASE_URL = ctx.endpoint
        names = set()
        for _ in range(10):
            entries = list(lc.list_entries(filter_=f'logName="{P}/logs/cloudaudit.googleapis.com%2Factivity"', page_size=200))
            names = {getattr(e, "payload", {}).get("methodName") if isinstance(getattr(e, "payload", None), dict) else None for e in entries}
            if any("CreateCryptoKey" in (n or "") for n in names):
                break
            time.sleep(0.5)
        want = {"CreateCryptoKey", "CreateTopic"}
        seen = {w for w in want if any(w in (n or "") for n in names)}
        assert seen == want, f"audit methods seen: {sorted(x for x in names if x)}"
        return "admin-activity audit has " + ", ".join(sorted(n.rsplit('.', 1)[-1] for n in names if n))[:150]
    ctx.step("cloud audit logs: admin-activity entries for the run (CreateCryptoKey, CreateTopic ...)", audit, lane=LANE["core"])

    def ledger():
        rows = [d.to_dict() for d in ctx.firestore().collection(NAMES["ledger"]).stream()]
        st = {r["status"] for r in rows}
        assert {"EXECUTED"} <= st, st
        return f"ledger rows: {len(rows)} ({sorted(st)})"
    ctx.step("firestore: approval-ledger is the application-level audit record", ledger)
