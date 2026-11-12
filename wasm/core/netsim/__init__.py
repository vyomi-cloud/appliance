# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""netsim — one cloud-neutral network engine for AWS VPC, GCP VPC and Azure VNet.

model.py      pure topology model (runs in Pyodide)
evaluate.py   reach() — the single reachability evaluator (Nano behaviour + every analyzer)
from_aws/gcp/azure.py   read-only translators from the existing cores
enforce.py    offline: Docker network per subnet + nftables table per space (via netd sidecar)
flowlogs.py   nft per-flow counters → AWS / GCP / Azure flow-log records
"""
