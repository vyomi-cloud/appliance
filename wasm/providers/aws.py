"""AWS provider plugin (WASM substrate).

S3 + DynamoDB are served by the PROVEN conformance cores (core/s3_object_core.py,
core/dynamodb_core.py) via aws_core_adapter — the SAME logic the conformance
suite asserts on host CPython AND Pyodide, not a stub. Every (service, op) below
is a thin call into that adapter. Adding more AWS services = more entries here;
new data-plane semantics belong in a core + its conformance suite, never inline.
"""
from __future__ import annotations

from .registry import CloudProvider, register
from . import aws_core_adapter as A


class Aws(CloudProvider):
    id = "aws"
    label = "Amazon Web Services"
    match_hosts = (".amazonaws.com",)

    def handlers(self):
        # Each handler is (backends, account, params) -> dict; S3/DynamoDB ignore
        # the generic `backends` bundle and use the cores' own stores (adapter).
        return {
            # S3 — buckets + objects, all via core/s3_object_core.py
            ("s3", "ListBuckets"):   lambda b, a, p: A.s3_list_buckets(p),
            ("s3", "CreateBucket"):  lambda b, a, p: A.s3_create_bucket(p),
            ("s3", "GetBucket"):     lambda b, a, p: A.s3_get_bucket(p),
            ("s3", "DeleteBucket"):  lambda b, a, p: A.s3_delete_bucket(p),
            ("s3", "PutVersioning"): lambda b, a, p: A.s3_set_versioning(p),
            ("s3", "ListObjects"):   lambda b, a, p: A.s3_list_objects(p),
            ("s3", "PutObject"):     lambda b, a, p: A.s3_put_object(p),
            ("s3", "GetObject"):     lambda b, a, p: A.s3_get_object(p),
            ("s3", "DeleteObject"):  lambda b, a, p: A.s3_delete_object(p),
            # DynamoDB — tables + items, all via core/dynamodb_core.py
            ("dynamodb", "ListTables"):  lambda b, a, p: A.ddb_list_tables(p),
            ("dynamodb", "CreateTable"): lambda b, a, p: A.ddb_create_table(p),
            ("dynamodb", "GetTable"):    lambda b, a, p: A.ddb_get_table(p),
            ("dynamodb", "DeleteTable"): lambda b, a, p: A.ddb_delete_table(p),
            ("dynamodb", "ListItems"):   lambda b, a, p: A.ddb_list_items(p),
            ("dynamodb", "PutItem"):     lambda b, a, p: A.ddb_put_item(p),
            ("dynamodb", "Query"):       lambda b, a, p: A.ddb_query(p),
            ("dynamodb", "Scan"):        lambda b, a, p: A.ddb_scan(p),
        }


register(Aws())
