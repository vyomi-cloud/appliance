"""/api/providers/gcp/* — the gcloud/gcutil + SDK connection guides the GCP console's 'Connect' dialogs read."""
import os
import sys

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
failed = False


def check(name, ok):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    failed = failed or not ok


def get(path):
    return requests.get(f"{BASE}/api/providers/gcp/{path}", timeout=30).json()


def post(path, command):
    return requests.post(f"{BASE}/api/providers/gcp/{path}", json={"command": command}, timeout=30).json()


def main():
    for tool in ("gcloud", "gcutil"):
        g = get(tool)
        check(f"{tool} guide is for gcp/{tool} with an endpoint",
              g.get("provider") == "gcp" and g.get("tool") == tool and str(g.get("endpoint", "")).startswith("http"))
    for lang, tool in (("java", "google-cloud-java"), ("go", "google-cloud-go"),
                       ("python", "google-cloud-python"), ("nodejs", "google-cloud-nodejs")):
        g = get(f"sdk/{lang}")
        check(f"sdk/{lang} guide is {tool} with an endpoint", g.get("tool") == tool and bool(g.get("endpoint")))
        s = get(f"sdk/{lang}/snippet")
        check(f"sdk/{lang} snippet is non-empty, names the endpoint",
              s.get("language") == lang and bool(s.get("snippet")) and s.get("endpoint", "x") in s["snippet"])
    r = post("gcloud/resolve", "gcloud compute instances list")
    check("gcloud/resolve maps 'compute instances list' to compute instances.list",
          r.get("service") == "compute" and r.get("operation") == "instances.list" and "GET" in r.get("route", ""))
    r = post("gcloud/resolve", "gcloud pubsub topics list")
    check("gcloud/resolve maps 'pubsub topics list' to pubsub topics.list",
          r.get("service") == "pubsub" and r.get("operation") == "topics.list")
    r = post("gcloud/resolve", "aws s3 ls")
    check("gcloud/resolve rejects a non-gcloud command", "must start with" in str(r.get("notes", "")))
    r = post("gcutil/resolve", "gcutil listinstances")
    check("gcutil/resolve maps 'listinstances' to compute instances.list",
          r.get("service") == "compute" and r.get("operation") == "instances.list")
    r = post("gcutil/resolve", "gcloud compute instances list")
    check("gcutil/resolve rejects a non-gcutil command", "must start with" in str(r.get("notes", "")))
    sys.exit(1 if failed else 0)


main()
