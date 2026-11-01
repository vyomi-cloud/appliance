"""Console Home setup: switch to <cloud>'s space and create one priced resource through the
cloud's native API (same helpers as hourly/savings_check.py), so the Home cost card has
something to show.   python3 home_setup.py aws|gcp|azure"""
import os
import sys
import uuid

os.environ["ENDPOINT"] = os.environ.get("VYOMI_BASE_URL") or os.environ.get("ENDPOINT") or "http://localhost:9000"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hourly"))
import savings_check as sc  # noqa: E402

cloud = sys.argv[1]
label, create, mkname = sc.CLOUDS[cloud]
if not sc.switch_to(cloud):
    sys.exit(1)
try:
    create(mkname())
except Exception as e:  # noqa: BLE001  e.g. Azure blob step needs Azurite; the ARM account is already counted
    print(f"home setup: {label} created, data-plane step skipped ({type(e).__name__})")
print(f"home setup: {cloud} space active, {label} created")
