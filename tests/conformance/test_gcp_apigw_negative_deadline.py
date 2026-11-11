"""#519: negative x-google-backend deadlines are NOT rejected for OpenAPI 2.0 (deprecation withdrawn 2026-11-04)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from core.gcp_console_tabs import openapi_routes


def test_negative_deadline_accepted():
    doc = {"swagger": "2.0", "info": {"title": "t"},
           "x-google-backend": {"address": "https://example.com", "deadline": -1},
           "paths": {"/a": {"get": {"operationId": "a",
                                    "x-google-backend": {"address": "https://example.com", "deadline": -5}}}}}
    routes = openapi_routes(doc)
    assert routes and routes[0]["operationId"] == "a"
