"""The Free-tier rate limit must reject SigV4 requests with an AWS-shaped throttle
error, so SDK retryers (Terraform's AWS provider) back off instead of failing."""
from starlette.requests import Request

from core.middleware import _aws_throttle_response


def _req(service: str, headers: dict | None = None) -> Request:
    h = {"authorization": f"AWS4-HMAC-SHA256 Credential=AKIA/20261122/us-east-1/{service}/aws4_request, "
                          "SignedHeaders=host, Signature=x"}
    h.update(headers or {})
    scope = {"type": "http", "method": "POST", "path": "/", "headers": [(k.encode(), v.encode()) for k, v in h.items()]}
    return Request(scope)


def test_s3_is_slowdown_503():
    r = _aws_throttle_response(_req("s3"), 10, 0.2)
    assert r.status_code == 503 and b"<Code>SlowDown</Code>" in r.body
    assert r.headers["retry-after"] == "1"


def test_ec2_uses_ec2_error_envelope():
    r = _aws_throttle_response(_req("ec2"), 10, 0.2)
    assert r.status_code == 503 and b"<Errors><Error><Code>RequestLimitExceeded</Code>" in r.body


def test_query_services_use_throttling_code():
    for svc in ("iam", "rds", "sts"):
        r = _aws_throttle_response(_req(svc), 10, 0.2)
        assert r.status_code == 400 and b"<Code>Throttling</Code>" in r.body, svc


def test_json_target_services_use_throttling_exception():
    r = _aws_throttle_response(_req("dynamodb", {"x-amz-target": "DynamoDB_20120810.GetItem"}), 10, 0.2)
    assert r.status_code == 400 and r.headers["x-amzn-errortype"] == "ThrottlingException"


def test_rest_json_services_use_too_many_requests():
    for svc in ("apigateway", "lambda"):
        r = _aws_throttle_response(_req(svc), 10, 0.2)
        assert r.status_code == 429 and r.headers["x-amzn-errortype"] == "TooManyRequestsException", svc


def test_non_aws_requests_keep_the_plain_429():
    scope = {"type": "http", "method": "GET", "path": "/", "headers": []}
    assert _aws_throttle_response(Request(scope), 10, 0.2) is None
