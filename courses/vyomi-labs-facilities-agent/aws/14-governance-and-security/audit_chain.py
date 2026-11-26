import hashlib
import json

import boto3

ddb, kms, s3 = boto3.client("dynamodb"), boto3.client("kms"), boto3.client("s3")
rows = [{k: list(v.values())[0] for k, v in i.items() if k != "task_token"} for i in ddb.scan(TableName="approval-ledger")["Items"]]
rows.sort(key=lambda r: (r.get("ts", "0"), r["request_id"]))
if len(rows) < 2:
    raise SystemExit("missing prerequisite: the ledger needs at least two decisions (run chapter 5: approve.py, reject.py)")


def chain(entries):
    out, prev = [], "0" * 64
    for e in entries:
        body = json.dumps(e, sort_keys=True)
        prev = hashlib.sha256((prev + body).encode()).hexdigest()
        out.append({"entry": e, "hash": prev})
    return out


def first_break(links):
    """Index of the first entry whose hash does not follow from the entries before it, or None."""
    prev = "0" * 64
    for i, l in enumerate(links):
        prev = hashlib.sha256((prev + json.dumps(l["entry"], sort_keys=True)).encode()).hexdigest()
        if prev != l["hash"]:
            return i
    return None


try:
    mac_key = kms.describe_key(KeyId="alias/audit-anchor")["KeyMetadata"]["KeyId"]
except kms.exceptions.NotFoundException:
    mac_key = kms.create_key(KeySpec="HMAC_256", KeyUsage="GENERATE_VERIFY_MAC", Description="signs the audit chain head")["KeyMetadata"]["KeyId"]
    kms.create_alias(AliasName="alias/audit-anchor", TargetKeyId=mac_key)


def anchor(links):
    return kms.generate_mac(KeyId=mac_key, Message=links[-1]["hash"].encode(), MacAlgorithm="HMAC_SHA_256")["Mac"]


def anchor_ok(links, mac):
    try:
        return kms.verify_mac(KeyId=mac_key, Message=links[-1]["hash"].encode(), MacAlgorithm="HMAC_SHA_256", Mac=mac)["MacValid"]
    except Exception:
        return False


links = chain(rows)
mac = anchor(links)
s3.put_object(Bucket="facilities-docs", Key="audit/chain.json", Body=json.dumps(links).encode())
assert first_break(links) is None and anchor_ok(links, mac)
print("chain of", len(links), "decisions written and signed; verifies clean")

# Attack 1: edit one entry in the middle.
t = json.loads(json.dumps(links))
t[0]["entry"]["status"] = "EXECUTED" if t[0]["entry"].get("status") != "EXECUTED" else "REJECTED"
assert first_break(t) == 0, "an edited entry must break the chain at that entry"
print("edit entry 0: chain breaks at index", first_break(t))

# Attack 2: delete the newest entry (the chain still looks internally valid, the signed head no longer matches).
t = json.loads(json.dumps(links))[:-1]
assert first_break(t) is None and not anchor_ok(t, mac), "a truncated chain must fail the signed anchor"
print("delete the last entry: hashes still chain, signed anchor rejects it")

# Attack 3: rewrite the whole chain after editing (the attacker can recompute hashes but cannot sign).
t = json.loads(json.dumps(links))
t[-1]["entry"]["status"] = "FORGED"
forged = chain([l["entry"] for l in t])
assert first_break(forged) is None and not anchor_ok(forged, mac), "a recomputed chain must fail the signed anchor"
print("rewrite the chain: hashes recompute, signed anchor rejects it")
print("tamper evidence verified")
