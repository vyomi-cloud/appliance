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
from . import dataplane_adapter as D   # v2.9.0 net-new data planes (Lambda/APIGW/VPC/EventBridge)


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
            # KMS — keys + aliases, via core/kms_core.py
            ("kms", "ListKeys"):    lambda b, a, p: A.kms_list_keys(p),
            ("kms", "CreateKey"):   lambda b, a, p: A.kms_create_key(p),
            ("kms", "GetKey"):      lambda b, a, p: A.kms_get_key(p),
            ("kms", "DeleteKey"):   lambda b, a, p: A.kms_delete_key(p),
            ("kms", "ListAliases"): lambda b, a, p: A.kms_list_aliases(p),
            # Secrets Manager — via core/secrets_core.py
            ("secrets", "ListSecrets"):  lambda b, a, p: A.secrets_list(p),
            ("secrets", "CreateSecret"): lambda b, a, p: A.secrets_create(p),
            ("secrets", "GetSecret"):    lambda b, a, p: A.secrets_get(p),
            ("secrets", "DeleteSecret"): lambda b, a, p: A.secrets_delete(p),
            # SQS — queues + messages, via core/sqs_core.py
            ("sqs", "ListQueues"):  lambda b, a, p: A.sqs_list_queues(p),
            ("sqs", "CreateQueue"): lambda b, a, p: A.sqs_create_queue(p),
            ("sqs", "GetQueue"):    lambda b, a, p: A.sqs_get_queue(p),
            ("sqs", "DeleteQueue"): lambda b, a, p: A.sqs_delete_queue(p),
            ("sqs", "Send"):        lambda b, a, p: A.sqs_send(p),
            ("sqs", "Receive"):     lambda b, a, p: A.sqs_receive(p),
            ("sqs", "Purge"):       lambda b, a, p: A.sqs_purge(p),
            # IAM — users/roles/policies/groups, via core/iam_core.py
            ("iam", "ListUsers"):       lambda b, a, p: A.iam_list_users(p),
            ("iam", "ListRoles"):       lambda b, a, p: A.iam_list_roles(p),
            ("iam", "ListPolicies"):    lambda b, a, p: A.iam_list_policies(p),
            ("iam", "ListGroups"):      lambda b, a, p: A.iam_list_groups(p),
            ("iam", "ListAttachments"): lambda b, a, p: A.iam_list_attachments(p),
            ("iam", "CreateUser"):      lambda b, a, p: A.iam_create_user(p),
            ("iam", "DeleteUser"):      lambda b, a, p: A.iam_delete_user(p),
            ("iam", "DeleteRole"):      lambda b, a, p: A.iam_delete_role(p),
            ("iam", "DeletePolicy"):    lambda b, a, p: A.iam_delete_policy(p),
            # RDS — db instances, via core/rds_core.py
            ("rds", "ListDatabases"):  lambda b, a, p: A.rds_list(p),
            ("rds", "CreateDatabase"): lambda b, a, p: A.rds_create(p),
            ("rds", "GetDatabase"):    lambda b, a, p: A.rds_get(p),
            ("rds", "DeleteDatabase"): lambda b, a, p: A.rds_delete(p),
            ("rds", "Start"):          lambda b, a, p: A.rds_start(p),
            ("rds", "Stop"):           lambda b, a, p: A.rds_stop(p),
            ("rds", "Reboot"):         lambda b, a, p: A.rds_reboot(p),
            ("rds", "Modify"):         lambda b, a, p: A.rds_modify(p),
            ("rds", "Snapshots"):      lambda b, a, p: A.rds_snapshots(p),
            # ── v2.9.0 net-new data planes (real cores via dataplane_adapter) ──
            # Lambda — functions + sandboxed invoke, via core/lambda_core.py
            ("lambda", "ListFunctions"):  lambda b, a, p: D.lambda_list(p),
            ("lambda", "CreateFunction"): lambda b, a, p: D.lambda_create(p),
            ("lambda", "GetFunction"):    lambda b, a, p: D.lambda_get(p),
            ("lambda", "DeleteFunction"): lambda b, a, p: D.lambda_delete(p),
            ("lambda", "Invoke"):         lambda b, a, p: D.lambda_invoke(p),
            # API Gateway — APIs + MOCK/Lambda-proxy + invoke, via core/apigateway_core.py
            ("apigateway", "ListApis"):   lambda b, a, p: D.apigw_list(p),
            ("apigateway", "CreateApi"):  lambda b, a, p: D.apigw_create(p),
            ("apigateway", "DeleteApi"):  lambda b, a, p: D.apigw_delete(p),
            ("apigateway", "Invoke"):     lambda b, a, p: D.apigw_invoke(p),
            # VPC — topology + reachability analyzer, via core/vpc_core.py
            ("vpc", "List"):              lambda b, a, p: D.vpc_list(p),
            ("vpc", "CreateVpc"):         lambda b, a, p: D.vpc_create(p),
            ("vpc", "CreateSubnet"):      lambda b, a, p: D.vpc_create_subnet(p),
            ("vpc", "CreateSecurityGroup"): lambda b, a, p: D.vpc_create_sg(p),
            ("vpc", "Authorize"):         lambda b, a, p: D.vpc_authorize(p),
            ("vpc", "Analyze"):           lambda b, a, p: D.vpc_analyze(p),
            # EventBridge — rules → SQS delivery, via core/eventbridge_core.py
            ("eventbridge", "ListRules"): lambda b, a, p: D.eb_list(p),
            ("eventbridge", "CreateRule"): lambda b, a, p: D.eb_create(p),
            ("eventbridge", "DeleteRule"): lambda b, a, p: D.eb_delete(p),
            ("eventbridge", "PutEvent"):  lambda b, a, p: D.eb_put_event(p),
        }


register(Aws())
