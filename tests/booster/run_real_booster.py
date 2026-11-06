"""Start the REAL appliance in booster mode for the Nano link smoke (consoles/tests/booster-link-real-smoke.mjs).
   python tests/booster/run_real_booster.py PORT [trial_days_left]   — licence: Pro trial, `sub` = acct-test."""
import os, sys, time, tempfile
port = int(sys.argv[1]); days = float(sys.argv[2]) if len(sys.argv) > 2 else 14
os.environ.setdefault("VYOMI_BOOSTER", "1")
os.environ.setdefault("CLOUDLEARN_STATE_DIR", tempfile.mkdtemp(prefix="booster-state-"))
os.environ.setdefault("VYOMI_BOOSTER_NO_RELAY", "1")
os.environ.setdefault("VYOMI_BOOSTER_EXTRA_ORIGINS", os.environ.get("NANO_ORIGIN", ""))
import server
from core import app_context as ctx
now = int(time.time())
ctx.STATE["license_claims"] = {"tier": "pro", "sub": "acct-test", "trial": True,
                               "sub_expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + days * 86400)), "iat": now}
import uvicorn
uvicorn.run(server.app, host="127.0.0.1", port=port, log_level="warning")
