"""Measured metrics: the request recorder's series maths, and no synthetic charts in the AWS consoles."""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from core import request_metrics as rm  # noqa: E402


def setup_function(_):
    rm.clear()


def test_series_counts_errors_and_zero_fills():
    now = 1_800_000_000.0
    rm.record("aws", "vpc", "GET", "/api/vpc/vpcs/vpc-1", 200, 10, ts=now - 5)
    rm.record("aws", "vpc", "GET", "/api/vpc/vpcs/vpc-1", 200, 30, ts=now - 4)
    rm.record("aws", "vpc", "GET", "/api/vpc/vpcs/vpc-1/x", 404, 20, ts=now - 3)
    rm.record("aws", "vpc", "GET", "/api/vpc/vpcs/vpc-2", 200, 5, ts=now - 2)
    s = rm.series("aws", "vpc", "vpc-1", minutes=5, step=60, now=now)
    assert len(s["points"]) == 5
    assert s["total_requests"] == 3 and s["total_errors"] == 1
    assert rm.series("aws", "vpc", "vpc-2", 5, 60, now)["total_requests"] == 1
    assert rm.series("aws", "vpc", "vpc-9", 5, 60, now)["total_requests"] == 0
    assert rm.series("gcp", "vpc", "", 5, 60, now)["total_requests"] == 0


def test_old_requests_fall_out_of_the_window():
    now = 1_800_000_000.0
    rm.record("aws", "sqs", "POST", "/", 200, 5, ts=now - 7200)
    assert rm.series("aws", "sqs", "", 60, 60, now)["total_requests"] == 0


def test_classify_console_and_wire_paths():
    assert rm.classify("/api/aws/kms/keys") == ("aws", "kms")
    assert rm.classify("/api/vpc/vpcs") == ("aws", "vpc")
    assert rm.classify("/api/spaces") == ("", "")
    assert rm.classify("/", ("aws", "sqs")) == ("aws", "sqs")


def test_aws_consoles_draw_no_synthetic_series():
    for f in ("static/aws-console.html", "wasm/aws-console.html"):
        src = open(os.path.join(ROOT, f), encoding="utf-8").read()
        assert "buildSparkline" not in src, f
        assert not re.search(r"seed\s*\*\s*1103515245", src), f
