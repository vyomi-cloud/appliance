"""AWS environment for vyomilabs.labrun: a clean in-process simulator + test LLM stub. start() -> (endpoint, env) where env is what each lab command runs with."""
import os
import sys

from . import ROOT, ensure_reference_on_path


def start(endpoint=None):
    ensure_reference_on_path()
    for k, v in (("AWS_ACCESS_KEY_ID", "test"), ("AWS_SECRET_ACCESS_KEY", "test"), ("AWS_DEFAULT_REGION", "us-east-1"), ("CLOUDLEARN_TIER_ENFORCE", "0")):
        os.environ.setdefault(k, v)
    if not endpoint:
        sys.path.insert(0, os.path.join(ROOT, "tools", "llm_stub"))
        import stub_llm_server
        os.environ.setdefault("VYOMI_LLM_ENDPOINT", stub_llm_server.start())
        from facilities.server import start_in_process
        endpoint = start_in_process()
        if os.environ.get("VYOMILABS_HAS_RUNTIME") == "1":
            import routes.aws_lambda_unified  # noqa: F401  installs the appliance's real Lambda runner (separate Python process per invoke)
    return endpoint, dict(os.environ, AWS_ENDPOINT_URL=endpoint)
