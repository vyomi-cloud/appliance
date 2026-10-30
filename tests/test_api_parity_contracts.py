from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from core.terraform_export import export_space_to_terraform_json
from core.terraform_workflow import stage_workflow_bundle, terraform_import_bundle


_TEST_DIR = Path(tempfile.mkdtemp(prefix="cloudlearn-parity-"))
os.environ["CLOUDLEARN_STATE_FILE"] = str(_TEST_DIR / "state.sqlite3")
os.environ["CLOUDLEARN_LEGACY_STATE_FILE"] = str(_TEST_DIR / "state.pkl")


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class ApiParityContractsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.port = _free_port()
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        env = os.environ.copy()
        env["CLOUDLEARN_STATE_FILE"] = os.environ["CLOUDLEARN_STATE_FILE"]
        env["CLOUDLEARN_LEGACY_STATE_FILE"] = os.environ["CLOUDLEARN_LEGACY_STATE_FILE"]
        env["PYTHONUNBUFFERED"] = "1"
        cls.proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "server:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(cls.port),
                "--log-level",
                "warning",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        deadline = time.time() + 30
        last_error = ""
        while time.time() < deadline:
            try:
                status, _, body = cls._request("GET", "/healthz")
                if status == 200:
                    payload = json.loads(body.decode("utf-8"))
                    if payload.get("status") == "ok":
                        return
            except Exception as exc:
                last_error = str(exc)
            time.sleep(0.25)
        stderr = ""
        if cls.proc.stderr is not None:
            try:
                stderr = cls.proc.stderr.read() or ""
            except Exception:
                stderr = ""
        raise RuntimeError(f"CloudLearn test server did not start: {last_error}\n{stderr}")

    @classmethod
    def tearDownClass(cls) -> None:
        if getattr(cls, "proc", None) and cls.proc.poll() is None:
            cls.proc.terminate()
            try:
                cls.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                cls.proc.kill()
                cls.proc.wait(timeout=10)
        shutil.rmtree(_TEST_DIR, ignore_errors=True)

    @classmethod
    def _request(cls, method: str, path: str, *, params: dict | None = None, body: dict | None = None, headers: dict | None = None):
        url = cls.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        data = None
        req_headers = {"Accept": "application/json"}
        if headers:
            req_headers.update(headers)
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers, exc.read()

    def request_json(self, method: str, path: str, *, params: dict | None = None, body: dict | None = None, headers: dict | None = None):
        status, resp_headers, raw = self._request(method, path, params=params, body=body, headers=headers)
        content_type = str(resp_headers.get("content-type", "")).lower()
        parsed = None
        if raw and "json" in content_type:
            parsed = json.loads(raw.decode("utf-8"))
        elif raw:
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except Exception:
                parsed = raw.decode("utf-8")
        return status, parsed, raw, resp_headers

    def request_text(self, method: str, path: str, *, params: dict | None = None, body: dict | None = None, headers: dict | None = None):
        status, _, raw = self._request(method, path, params=params, body=body, headers=headers)
        return status, raw.decode("utf-8")

    def assertJsonContains(self, response: dict, key: str) -> None:
        self.assertIn(key, response)

    def test_provider_catalog_matches_current_matrix(self) -> None:
        status, aws_caps, _, _ = self.request_json("GET", "/api/providers/aws/capabilities")
        self.assertEqual(status, 200)
        self.assertEqual(aws_caps["service_counts"]["total"], 9)
        self.assertEqual(aws_caps["service_counts"]["integrated"], 9)

        status, gcp_caps, _, _ = self.request_json("GET", "/api/providers/gcp/capabilities")
        self.assertEqual(status, 200)
        self.assertEqual(gcp_caps["service_counts"]["total"], 9)
        self.assertEqual(gcp_caps["service_counts"]["integrated"], 9)

        status, aws_services, _, _ = self.request_json("GET", "/api/providers/aws/services")
        self.assertEqual(status, 200)
        self.assertEqual(aws_services["count"], 9)
        self.assertTrue(all(service["status"] == "integrated" for service in aws_services["services"]))

        status, gcp_services, _, _ = self.request_json("GET", "/api/providers/gcp/services")
        self.assertEqual(status, 200)
        self.assertEqual(gcp_services["count"], 9)
        self.assertTrue(all(service["status"] == "integrated" for service in gcp_services["services"]))

    def test_aws_api_parity_contracts(self) -> None:
        bucket = _unique("aws-bucket")
        user_name = _unique("aws-user")
        queue_name = _unique("aws-queue")
        table_name = _unique("aws-table")
        function_name = _unique("aws-fn")
        api_name = _unique("aws-api")
        vpc_name = _unique("aws-vpc")
        created_lambda_dir = Path("lambda_functions") / function_name

        try:
            status, text = self.request_text("GET", "/ec2", params={"Action": "DescribeInstances", "Version": "2016-11-15"})
            self.assertEqual(status, 200)
            self.assertIn("DescribeInstancesResponse", text)

            status, created_bucket, _, _ = self.request_json("POST", f"/api/s3/buckets/{bucket}", params={"region": "us-east-1"})
            self.assertEqual(status, 200)
            self.assertEqual(created_bucket["message"], f"Bucket '{bucket}' created")
            status, s3_list, _, _ = self.request_json("GET", "/api/s3/buckets")
            self.assertEqual(status, 200)
            self.assertIn(bucket, [item["name"] for item in s3_list["buckets"]])

            status, created_user, _, _ = self.request_json("POST", "/api/iam/users", body={"user_name": user_name})
            self.assertEqual(status, 200)
            self.assertEqual(created_user["user_name"], user_name)
            status, user_list, _, _ = self.request_json("GET", "/api/iam/users")
            self.assertEqual(status, 200)
            self.assertIn(created_user["user_id"], [item["user_id"] for item in user_list["users"]])

            status, created_queue, _, _ = self.request_json("POST", "/api/sqs/queues", body={"queue_name": queue_name, "tags": {"env": "test"}})
            self.assertEqual(status, 200)
            self.assertEqual(created_queue["queue_name"], queue_name)
            status, _, _, _ = self.request_json("POST", f"/api/sqs/queues/{queue_name}/messages", body={"message_body": "hello parity"})
            self.assertEqual(status, 200)
            status, received, _, _ = self.request_json("POST", f"/api/sqs/queues/{queue_name}/receive", body={"max_number_of_messages": 1})
            self.assertEqual(status, 200)
            self.assertGreaterEqual(received["count"], 1)

            status, created_table, _, _ = self.request_json("POST", "/api/dynamodb/tables", body={"table_name": table_name, "partition_key_name": "id", "partition_key_type": "S"})
            self.assertEqual(status, 200)
            self.assertEqual(created_table["table"]["table_name"], table_name)
            status, _, _, _ = self.request_json("POST", f"/api/dynamodb/tables/{table_name}/items", body={"item": {"id": {"S": "1"}, "title": {"S": "hello"}}})
            self.assertEqual(status, 200)
            status, query, _, _ = self.request_json("POST", f"/api/dynamodb/tables/{table_name}/query", body={"partition_key_value": "1"})
            self.assertEqual(status, 200)
            self.assertGreaterEqual(query["count"], 1)

            status, created_fn, _, _ = self.request_json("POST", "/api/lambda/functions", body={"function_name": function_name})
            self.assertEqual(status, 200)
            self.assertEqual(created_fn["function_name"], function_name)
            status, invocation, _, _ = self.request_json("POST", f"/api/lambda/functions/{function_name}/invoke", body={"payload": {"ping": True}})
            self.assertEqual(status, 200)
            self.assertEqual(invocation["status"], "success")
            self.assertEqual(invocation["payload"]["message"], "Hello from Lambda")

            status, created_api, _, _ = self.request_json("POST", "/api/apigateway/apis", body={"name": api_name, "description": "parity"})
            self.assertEqual(status, 200)
            self.assertEqual(created_api["name"], api_name)
            status, api_list, _, _ = self.request_json("GET", "/api/apigateway/apis")
            self.assertEqual(status, 200)
            self.assertIn(api_name, [item["name"] for item in api_list["apis"]])

            status, created_vpc, _, _ = self.request_json("POST", "/api/vpc/vpcs", body={"name": vpc_name, "cidr_block": "10.50.0.0/16"})
            self.assertEqual(status, 200)
            self.assertTrue(created_vpc["vpc_id"].startswith("vpc-"))
            status, vpc_list, _, _ = self.request_json("GET", "/api/vpc/vpcs")
            self.assertEqual(status, 200)
            self.assertIn(created_vpc["vpc_id"], [item["vpc_id"] for item in vpc_list["vpcs"]])
        finally:
            self.request_json("DELETE", f"/api/vpc/vpcs/{created_vpc['vpc_id']}" if "created_vpc" in locals() else f"/api/vpc/vpcs/{vpc_name}")
            self.request_json("DELETE", f"/api/apigateway/apis/{api_name}")
            self.request_json("DELETE", f"/api/lambda/functions/{function_name}")
            self.request_json("DELETE", f"/api/dynamodb/tables/{table_name}")
            self.request_json("DELETE", f"/api/sqs/queues/{queue_name}")
            self.request_json("DELETE", f"/api/iam/users/{created_user['user_id']}" if "created_user" in locals() else f"/api/iam/users/{user_name}")
            self.request_json("DELETE", f"/api/s3/buckets/{bucket}")
            if created_lambda_dir.exists():
                shutil.rmtree(created_lambda_dir, ignore_errors=True)

    def test_gcp_api_parity_contracts(self) -> None:
        project = "cloudlearn"
        bucket = _unique("gcp-bucket")
        object_name = "hello.txt"
        sa_id = _unique("sa")
        iam_user_name = _unique("gcp-user")
        topic = _unique("gcp-topic")
        subscription = f"{topic}-sub"
        collection = "parity"
        doc_id = _unique("doc")
        fn_name = _unique("gcp-fn")
        api_name = _unique("gcp-api")
        api_cfg = _unique("gcp-cfg")
        gateway_name = _unique("gcp-gw")
        network_name = _unique("gcp-net")

        status, caps, _, _ = self.request_json("GET", "/api/providers/gcp/capabilities")
        self.assertEqual(status, 200)
        self.assertEqual(caps["service_counts"]["total"], 9)

        try:
            status, created_bucket, _, _ = self.request_json("POST", "/storage/v1/b", params={"project": project}, body={"name": bucket})
            self.assertEqual(status, 200)
            self.assertEqual(created_bucket["name"], bucket)
            status, storage_list, _, _ = self.request_json("GET", "/storage/v1/b", params={"project": project})
            self.assertEqual(status, 200)
            self.assertIn(bucket, [item["name"] for item in storage_list["items"]])
            status, _, _, _ = self.request_json("POST", f"/storage/v1/b/{bucket}/o", params={"project": project}, body={"name": object_name, "data": "hello cloud"})
            self.assertEqual(status, 200)
            status, objects, _, _ = self.request_json("GET", f"/storage/v1/b/{bucket}/o", params={"project": project})
            self.assertEqual(status, 200)
            self.assertIn(object_name, [item["name"].split("/")[-1] for item in objects["items"]])

            status, created_sa, _, _ = self.request_json("POST", f"/v1/projects/{project}/serviceAccounts", body={"accountId": sa_id, "displayName": "Service Account"})
            self.assertEqual(status, 200)
            self.assertIn(sa_id, created_sa["email"])
            status, sa_list, _, _ = self.request_json("GET", f"/v1/projects/{project}/serviceAccounts")
            self.assertEqual(status, 200)
            self.assertIn(sa_id, [item["name"] for item in sa_list["accounts"]])
            status, created_gcp_user, _, _ = self.request_json("POST", "/api/gcp/iam/users", body={"user_name": iam_user_name})
            self.assertEqual(status, 200)
            self.assertEqual(created_gcp_user["user_name"], iam_user_name)
            status, gcp_users, _, _ = self.request_json("GET", "/api/gcp/iam/users")
            self.assertEqual(status, 200)
            self.assertIn(created_gcp_user["user_id"], [item["user_id"] for item in gcp_users["users"]])

            status, created_topic, _, _ = self.request_json("POST", f"/v1/projects/{project}/topics", body={"topicId": topic, "subscriptionId": subscription})
            self.assertEqual(status, 200)
            self.assertTrue(created_topic["name"].endswith(f"/topics/{topic}"))
            status, topic_list, _, _ = self.request_json("GET", f"/v1/projects/{project}/topics")
            self.assertEqual(status, 200)
            self.assertIn(topic, [item["name"].split("/")[-1] for item in topic_list["topics"]])
            status, _, _, _ = self.request_json("POST", f"/v1/projects/{project}/topics/{topic}:publish", body={"messages": [{"data": "aGVsbG8="}]})
            self.assertEqual(status, 200)
            status, sub_pull, _, _ = self.request_json("POST", f"/v1/projects/{project}/subscriptions/{subscription}:pull", body={"maxMessages": 1})
            self.assertEqual(status, 200)
            self.assertGreaterEqual(len(sub_pull["receivedMessages"]), 1)

            status, created_doc, _, _ = self.request_json("POST", f"/firestore/v1/projects/{project}/databases/(default)/documents/{collection}", body={"name": doc_id, "fields": {"title": {"stringValue": "hello"}}})
            self.assertEqual(status, 200)
            self.assertIn("title", created_doc["fields"])
            status, docs, _, _ = self.request_json("GET", f"/firestore/v1/projects/{project}/databases/(default)/documents/{collection}")
            self.assertEqual(status, 200)
            self.assertIn(doc_id, [item["name"].split("/")[-1] for item in docs["documents"]])
            status, query, _, _ = self.request_json("POST", f"/firestore/v1/projects/{project}/databases/(default)/documents:runQuery", body={"structuredQuery": {"from": [{"collectionId": collection}], "where": {"fieldFilter": {"field": {"fieldPath": "title"}, "op": "EQUAL", "value": {"stringValue": "hello"}}}}})
            self.assertEqual(status, 200)
            self.assertGreaterEqual(len(query), 1)

            status, created_fn, _, _ = self.request_json("POST", f"/v1/projects/{project}/locations/us-central1/functions", body={"name": fn_name, "runtime": "python311", "entryPoint": "handler"})
            self.assertEqual(status, 200)
            self.assertTrue(created_fn["name"].endswith(f"/functions/{fn_name}"))
            status, fn_list, _, _ = self.request_json("GET", f"/v1/projects/{project}/locations/us-central1/functions")
            self.assertEqual(status, 200)
            self.assertIn(fn_name, [item["name"].split("/")[-1] for item in fn_list["functions"]])
            status, fn_call, _, _ = self.request_json("POST", f"/v1/projects/{project}/locations/us-central1/functions/{fn_name}:call", body={"data": {"ping": True}})
            self.assertEqual(status, 200)
            self.assertTrue(fn_call["result"]["ok"])

            status, created_api, _, _ = self.request_json("POST", f"/v1/projects/{project}/locations/global/apis", body={"name": api_name, "displayName": "Parity API"})
            self.assertEqual(status, 200)
            self.assertTrue(created_api["name"].endswith(f"/apis/{api_name}"))
            status, created_cfg, _, _ = self.request_json("POST", f"/v1/projects/{project}/locations/global/apiConfigs", body={"name": api_cfg, "api": api_name, "path_part": "hello", "http_method": "GET", "response_body": "{\"message\":\"hello\"}"})
            self.assertEqual(status, 200)
            self.assertTrue(created_cfg["name"].endswith(f"/apiConfigs/{api_cfg}"))
            status, created_gw, _, _ = self.request_json("POST", f"/v1/projects/{project}/locations/global/gateways", body={"name": gateway_name, "apiConfig": api_cfg, "stage_name": "prod"})
            self.assertEqual(status, 200)
            self.assertTrue(created_gw["name"].endswith(f"/gateways/{gateway_name}"))

            status, created_net, _, _ = self.request_json("POST", f"/compute/v1/projects/{project}/global/networks", body={"name": network_name, "autoCreateSubnetworks": True})
            self.assertEqual(status, 200)
            # v4 C0d: insert returns a (completed) Operation, as real Compute Engine does
            self.assertTrue(created_net["targetLink"].endswith(f"/global/networks/{network_name}"))
            status, net_list, _, _ = self.request_json("GET", f"/compute/v1/projects/{project}/global/networks")
            self.assertEqual(status, 200)
            self.assertIn(network_name, [item["name"] for item in net_list["items"]])

            status, created_subnet, _, _ = self.request_json("POST", f"/compute/v1/projects/{project}/regions/us-central1/subnetworks", body={"name": f"{network_name}-subnet", "network": network_name, "ipCidrRange": "10.0.0.0/24"})
            self.assertEqual(status, 200)
            self.assertEqual(created_subnet["kind"], "compute#operation")
            self.assertTrue(created_subnet["targetLink"].endswith(f"/subnetworks/{network_name}-subnet"))
            status, created_fw, _, _ = self.request_json("POST", f"/compute/v1/projects/{project}/global/firewalls", body={"name": f"{network_name}-fw", "network": network_name, "direction": "INGRESS", "allowed": [{"IPProtocol": "tcp", "ports": ["80"]}]})
            self.assertEqual(status, 200)
            self.assertTrue(created_fw["targetLink"].endswith(f"/global/firewalls/{network_name}-fw"))
        finally:
            self.request_json("DELETE", f"/compute/v1/projects/{project}/global/firewalls/{network_name}-fw")
            self.request_json("DELETE", f"/compute/v1/projects/{project}/regions/us-central1/subnetworks/{network_name}-subnet")
            self.request_json("DELETE", f"/compute/v1/projects/{project}/global/networks/{network_name}")
            self.request_json("DELETE", f"/v1/projects/{project}/locations/global/apis/{api_name}")
            self.request_json("DELETE", f"/v1/projects/{project}/locations/us-central1/functions/{fn_name}")
            self.request_json("DELETE", f"/firestore/v1/projects/{project}/databases/(default)/documents/{collection}/{doc_id}")
            self.request_json("DELETE", f"/v1/projects/{project}/subscriptions/{subscription}")
            self.request_json("DELETE", f"/v1/projects/{project}/topics/{topic}")
            self.request_json("DELETE", f"/api/gcp/iam/users/{created_gcp_user['user_id']}" if "created_gcp_user" in locals() else f"/api/gcp/iam/users/{iam_user_name}")
            self.request_json("DELETE", f"/v1/projects/{project}/serviceAccounts/{created_sa['email']}" if "created_sa" in locals() else f"/v1/projects/{project}/serviceAccounts/{sa_id}@{project}.iam.gserviceaccount.com")
            self.request_json("DELETE", f"/storage/v1/b/{bucket}")

    def test_terraform_round_trip_contract(self) -> None:
        space = {
            "space_id": "space-roundtrip",
            "name": "roundtrip",
            "provider": "aws",
            "active_region": "us-east-1",
            "active_account": "cloudlearn",
            "service_states": {},
        }
        terraform_json = {
            "resource": {
                "aws_instance": {
                    "app": {
                        "ami": "ami-ubuntu2404",
                        "instance_type": "t3.micro",
                        "tags": {"Name": "app"},
                    }
                },
                "google_compute_instance": {
                    "vm": {
                        "name": "vm",
                        "zone": "us-central1-a",
                        "machine_type": "e2-micro",
                    }
                },
            }
        }

        imported = terraform_import_bundle({"terraform_json": terraform_json}, space)
        self.assertEqual(imported["supported_resources"], 2)
        self.assertIn("ec2", imported["service_state_updates"])
        self.assertIn("gcp_compute", imported["service_state_updates"])

        space["service_states"] = imported["service_state_updates"]
        space["resources"] = {"nodes": imported["nodes"]}

        exported = export_space_to_terraform_json(space)
        self.assertGreaterEqual(exported["summary"]["supported_resources"], 2)
        self.assertIn("aws_instance", exported["terraform_json"]["resource"])
        self.assertIn("google_compute_instance", exported["terraform_json"]["resource"])
        self.assertIn("terraform_hcl", exported)
        self.assertIn("versions.tf", exported["terraform_hcl"])
        self.assertIn("providers.tf", exported["terraform_hcl"])
        self.assertIn("main.tf", exported["terraform_hcl"])
        self.assertIn('resource "aws_instance" "app"', exported["terraform_hcl"]["main.tf"])
        self.assertIn('resource "google_compute_instance" "vm"', exported["terraform_hcl"]["main.tf"])
        self.assertEqual(exported["summary"]["hcl_files"], 3)

        old_terraform_dir = os.environ.get("CLOUDLEARN_TERRAFORM_DIR")
        with tempfile.TemporaryDirectory(prefix="cloudlearn-terraform-") as tf_root:
            os.environ["CLOUDLEARN_TERRAFORM_DIR"] = tf_root
            try:
                staged = stage_workflow_bundle(exported, "workflow-test", "plan", exported["summary"])
            finally:
                if old_terraform_dir is None:
                    os.environ.pop("CLOUDLEARN_TERRAFORM_DIR", None)
                else:
                    os.environ["CLOUDLEARN_TERRAFORM_DIR"] = old_terraform_dir

        hcl_dir = Path(staged["hcl_dir"])
        self.assertTrue((hcl_dir / "versions.tf").exists())
        self.assertTrue((hcl_dir / "providers.tf").exists())
        self.assertTrue((hcl_dir / "main.tf").exists())
        self.assertIn('resource "aws_instance" "app"', (hcl_dir / "main.tf").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
