from __future__ import annotations

from core.provider_registry import get_provider, provider_matrix
from core.pack_catalog import packs_for_provider


def matrix() -> dict:
    packs = packs_for_provider("gcp")
    matrix_data = provider_matrix("gcp", packs)
    matrix_data["catalog"] = {
        "service": [pack for pack in packs if pack.get("type") == "service"],
        "tooling": [pack for pack in packs if pack.get("type") == "tooling"],
    }
    return matrix_data


def tool_response(tool: str) -> dict:
    tool = tool.lower()
    provider_info = get_provider("gcp")
    endpoint = "http://127.0.0.1:9000"
    if tool == "gcloud":
        return {
            "provider": "gcp",
            "tool": "gcloud",
            "status": "partial",
            "endpoint": endpoint,
            "help": [
                "Simulated gcloud will point at local Google-style endpoints.",
                "Commands currently translate to compute, storage, sql, pubsub, firestore, functions, api gateway, VPC, and IAM routes.",
            ],
            "notes": "gcloud command-shape adapters are partially implemented and expanding toward full provider coverage.",
            "provider_surface": provider_info.get("surface", {}),
        }
    if tool == "gcutil":
        return {
            "provider": "gcp",
            "tool": "gcutil",
            "status": "partial",
            "endpoint": endpoint,
            "help": [
                "Legacy gcutil compatibility will be simulated locally.",
                "Legacy commands currently resolve to Compute Engine, Cloud Storage, and Pub/Sub routes.",
            ],
            "notes": "gcutil compatibility is partial but now has real command translation coverage.",
            "provider_surface": provider_info.get("surface", {}),
        }
    if tool == "sdk/java":
        return {
            "provider": "gcp",
            "tool": "google-cloud-java",
            "status": "partial",
            "endpoint": endpoint,
            "dependency": "com.google.cloud:*",
            "help": ["Use the simulator endpoint with Google Cloud Java clients.", "Client wrappers are partial, so transport and request shape glue is still expanding."],
            "provider_surface": provider_info.get("surface", {}),
        }
    if tool == "sdk/go":
        return {
            "provider": "gcp",
            "tool": "google-cloud-go",
            "status": "partial",
            "endpoint": endpoint,
            "dependency": "cloud.google.com/go",
            "help": ["Use the simulator endpoint with Google Cloud Go clients.", "Client wrappers are partial, so transport and request shape glue is still expanding."],
            "provider_surface": provider_info.get("surface", {}),
        }
    if tool == "sdk/python":
        return {
            "provider": "gcp",
            "tool": "google-cloud-python",
            "status": "partial",
            "endpoint": endpoint,
            "dependency": "google-cloud-storage (and other google-cloud-* packages)",
            "config": {"STORAGE_EMULATOR_HOST": endpoint, "project": "cloudlearn"},
            "help": ["Set STORAGE_EMULATOR_HOST env var to point Python clients at the simulator.", "Client wrappers are partial, so transport and request shape glue is still expanding."],
            "provider_surface": provider_info.get("surface", {}),
        }
    if tool == "sdk/nodejs":
        return {
            "provider": "gcp",
            "tool": "google-cloud-nodejs",
            "status": "partial",
            "endpoint": endpoint,
            "dependency": "@google-cloud/storage (and other @google-cloud/* packages)",
            "config": {"apiEndpoint": endpoint, "projectId": "cloudlearn"},
            "help": ["Pass apiEndpoint to each client constructor.", "Client wrappers are partial, so transport and request shape glue is still expanding."],
            "provider_surface": provider_info.get("surface", {}),
        }
    raise KeyError(tool)
