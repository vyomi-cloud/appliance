"""C5b: can the approval path run on the REAL Google Pub/Sub + Firestore emulators (image already in the local Docker store; nothing is pulled)?
(a) the loop with the official gRPC clients straight against the emulators, (b) is the emulator the simulator's data plane when PUBSUB_EMULATOR_HOST / FIRESTORE_EMULATOR_HOST are set?
Containers are named ref-probe-*-<tag> and only those exact names are removed."""
from _common import *
import json, subprocess, time, socket

s = Step()
IMG = "gcr.io/google.com/cloudsdktool/google-cloud-cli:emulators"
names = [f"ref-probe-pubsub-{TAG}", f"ref-probe-firestore-{TAG}"]


def freeport():
    k = socket.socket(); k.bind(("127.0.0.1", 0)); p = k.getsockname()[1]; k.close(); return p


def sh(*a):
    return subprocess.run(a, capture_output=True, text=True, timeout=120)


def start():
    if sh("docker", "info").returncode != 0:
        raise Blocked("docker daemon not running")
    if sh("docker", "image", "inspect", IMG).returncode != 0:
        raise Blocked(f"image {IMG} not present locally (not pulling 1.5 GB)")
    s.pp, s.fp = freeport(), freeport()
    r1 = sh("docker", "run", "-d", "--rm", "--name", names[0], "-p", f"127.0.0.1:{s.pp}:8085", IMG, "gcloud", "beta", "emulators", "pubsub", "start", "--host-port=0.0.0.0:8085", f"--project={PROJECT}")
    r2 = sh("docker", "run", "-d", "--rm", "--name", names[1], "-p", f"127.0.0.1:{s.fp}:8080", IMG, "gcloud", "emulators", "firestore", "start", "--host-port=0.0.0.0:8080")
    assert r1.returncode == 0 and r2.returncode == 0, (r1.stderr, r2.stderr)
    import requests
    for port in (s.pp, s.fp):
        for _ in range(90):
            try:
                requests.get(f"http://127.0.0.1:{port}/", timeout=2)
                break
            except Exception:
                time.sleep(1)
        else:
            raise AssertionError(f"emulator on {port} did not come up: " + sh("docker", "logs", "--tail", "5", names[0 if port == s.pp else 1]).stdout[-300:])
    s.up = True
    return f"pubsub emulator :{s.pp}, firestore emulator :{s.fp}"


def loop_real():
    os.environ["PUBSUB_EMULATOR_HOST"] = f"127.0.0.1:{s.pp}"
    os.environ["FIRESTORE_EMULATOR_HOST"] = f"127.0.0.1:{s.fp}"
    from google.cloud import pubsub_v1, firestore
    pub, sub = pubsub_v1.PublisherClient(), pubsub_v1.SubscriberClient()
    topic, sn = f"projects/{PROJECT}/topics/real-{TAG}", f"projects/{PROJECT}/subscriptions/real-{TAG}"
    pub.create_topic(request={"name": topic}); sub.create_subscription(request={"name": sn, "topic": topic})
    db = firestore.Client(project=PROJECT)
    db.collection("ledger").document("r1").set({"status": "PENDING"})
    pub.publish(topic, b'{"request_id":"r1"}').result(timeout=20)
    m = sub.pull(request={"subscription": sn, "max_messages": 1}, timeout=20).received_messages
    assert len(m) == 1
    db.collection("ledger").document("r1").set({"status": "APPROVED"})
    sub.acknowledge(request={"subscription": sn, "ack_ids": [m[0].ack_id]})
    assert db.collection("ledger").document("r1").get().to_dict()["status"] == "APPROVED"
    return "full approval loop on the real emulators with the high-level gRPC clients"


def sim_data_plane():
    """With the emulator env vars set, publish/firestore writes through the simulator's own wire front door: do they land in the emulator?"""
    topic = f"projects/{PROJECT}/topics/viasim-{TAG}"
    call("PUT", f"/v1/{topic}", {})      # raw REST: with PUBSUB_EMULATOR_HOST set the SDK forces its gRPC channel, so the REST client cannot be built
    from google.cloud import pubsub_v1
    real = pubsub_v1.PublisherClient()
    names_ = [t.name for t in real.list_topics(request={"project": f"projects/{PROJECT}"})]
    assert topic in names_, f"topic created through the simulator is NOT in the real Pub/Sub emulator (emulator has {names_})"
    return "simulator delegates Pub/Sub to the emulator"


def sim_firestore_data_plane():
    fs = firestore_rest()
    fs_set(fs, "viasim", "d1", {"v": 1})
    from google.cloud import firestore
    doc = firestore.Client(project=PROJECT).collection("viasim").document("d1").get()
    assert doc.exists, "document written through the simulator is NOT in the real Firestore emulator"
    return "simulator delegates Firestore to the emulator"


try:
    s("start real Pub/Sub + Firestore emulator containers (local image)", start)
    if getattr(s, "up", False):
        s("(a) approval loop on the real emulators with official high-level gRPC clients", loop_real)
        s("(b) Pub/Sub through the simulator front door lands in the real emulator", sim_data_plane)
        s("(b) Firestore through the simulator front door lands in the real emulator", sim_firestore_data_plane)
finally:
    for n in names:
        sh("docker", "rm", "-f", n)
s.finish()
