"""Azure Table wire in the simulator's OWN core (flag off), driven by the unmodified azure-data-tables SDK:
PATCH/MERGE + PUT verbs, OData $filter, $select/$top + continuation paging, ETag/If-Match -> 412, upsert modes,
submit_transaction ($batch). Starts the real appliance app (server.py) in-process.
Run: PYTHONPATH=. python3 tests/conformance/test_azure_table_wire_sdk.py   (skips when azure-data-tables is absent)"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from azure.data.tables import TableServiceClient
except ImportError:
    print("[SKIP] azure-data-tables not installed")
    sys.exit(0)
import _az_inproc as h
import _az_table_scenario as sc

if __name__ == "__main__":
    os.environ.pop("VYOMI_AZURE_REAL_BACKENDS", None)
    base = h.start_sim()
    sc.run(TableServiceClient.from_connection_string(h.table_cs(base)), "own-core: ")
    print(f"\n{len(h.FAILS)} failure(s)" if h.FAILS else "\nAll PASS")
    sys.exit(1 if h.FAILS else 0)
