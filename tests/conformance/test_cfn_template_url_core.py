"""CloudFormation TemplateURL accepts every real S3 URL form, incl. the global endpoint the console's own placeholder shows."""
try:
    from core import cloudformation_core as c
except ImportError:  # pragma: no cover
    import cloudformation_core as c  # type: ignore

OK = ["https://s3.amazonaws.com/b/k.json", "https://s3.us-east-1.amazonaws.com/b/k.json", "https://s3-us-west-2.amazonaws.com/b/p/k.yaml",
      "https://b.s3.amazonaws.com/k.json", "https://b.s3.us-east-1.amazonaws.com/k.json", "http://s3.amazonaws.com/b/k"]
BAD = ["https://example.com/b/k.json", "https://s3.amazonaws.com.evil.com/b/k.json", "https://amazonaws.com/b/k"]


def run():
    for u in OK:
        assert c._S3_URL_RE.match(u), f"should accept {u}"
        print(f"[PASS] accepts {u}")
    for u in BAD:
        assert not c._S3_URL_RE.match(u), f"should reject {u}"
        print(f"[PASS] rejects {u}")
    print("CFN TEMPLATE URL OK")


if __name__ == "__main__":
    run()
