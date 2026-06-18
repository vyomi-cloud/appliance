"""Runtime bundles, deployments, and service-action router.

Extracted from server.py — contains the /api/runtime/bundles,
/api/deployments, and /api/actions route handlers.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request

from core import app_context as ctx
from core.models import DeploymentRequest, ServiceActionRequest, IAMUserRequest

# Aliases
STATE = ctx.STATE
_id = ctx.id_gen
_now = ctx.now
_record_usage = ctx.record_usage
runtime_state = ctx.runtime_state


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register(app: FastAPI) -> None:
    """Mount /api/runtime/bundles, /api/deployments, and /api/actions routes."""

    @app.get("/api/runtime/bundles")
    def api_runtime_bundles():
        return {"bundles": list(runtime_state["bundles"].values()), "count": len(runtime_state["bundles"])}

    @app.post("/api/deployments")
    def api_create_deployment(req: DeploymentRequest):
        deployment_id = _id("deploy")
        source_dir = Path(os.environ.get("CLOUDLEARN_DEPLOY_DIR", Path(__file__).resolve().parent / "deployments")) / deployment_id
        source_dir.mkdir(parents=True, exist_ok=True)
        deployment = {
            "deployment_id": deployment_id,
            "name": req.name,
            "source_url": req.source_url,
            "runtime": req.runtime,
            "command": req.command,
            "branch": req.branch,
            "repo": req.repo,
            "status": "created",
            "workdir": str(source_dir),
            "created": _now(),
        }
        if req.source_url.startswith("https://github.com/") or req.source_url.endswith(".git"):
            try:
                import subprocess
                subprocess.run(["git", "clone", "--depth", "1", req.source_url, str(source_dir)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                deployment["status"] = "cloned"
            except Exception as e:
                deployment["status"] = "clone_failed"
                deployment["error"] = str(e)
        STATE["deployments"][deployment_id] = deployment
        _record_usage("deploy.create", deployment)
        return deployment

    @app.post("/api/actions")
    def api_action_router(payload: ServiceActionRequest):
        service = payload.payload.get("service", "")
        action = payload.action.lower()
        if service == "s3":
            return {"message": "Use S3 REST or /api/s3 endpoints for S3 actions."}
        if service == "iam" and action == "createuser":
            from providers import aws_iam as provider_aws_iam
            return provider_aws_iam.api_iam_create_user(IAMUserRequest(**payload.payload))
        raise HTTPException(400, detail="UnsupportedAction")

    # ── v2.0.6 (#420): version + update-check endpoints ───────────────────
    # The SPA polls /api/runtime/update-check every page load and shows a
    # top banner if the latest GitHub release is ahead of the running
    # image's VERSION file. The CLI's `vyomi upgrade` hits the same
    # endpoint to decide whether to pull a new image at all.

    @app.post("/api/runtime/community-click")
    async def api_runtime_community_click(request: Request):
        """v2.0.6 (#426): counter for GitHub-community modal clicks.
        Lets us measure which CTAs (star / watch / discussions / source
        / issues / contributing / modal_open) actually convert, so we
        can A/B test copy + placement without analytics dependencies.

        Stores rolling per-action counts on STATE["runtime"]["community"]
        with hourly buckets so we can plot trends. No PII — just the
        action name + (optional) the page that triggered it.
        Idempotent: a flood of clicks just increments the counter.

        Returns the current per-action totals so the SPA could in
        principle show "joined by X others today" microcopy later.
        """
        import time as _time
        # Parse JSON body manually — FastAPI's auto-binding `payload: dict`
        # tries to read query params for non-Pydantic dict types, which
        # leaves the body unread (same gotcha as routes/aws_extras.py).
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        payload = payload if isinstance(payload, dict) else {}
        action = str(payload.get("action") or "").strip().lower()[:32]
        where = str(payload.get("where") or "").strip().lower()[:32]
        if not action:
            raise HTTPException(status_code=400, detail="action required")
        # Whitelist actions to avoid an attacker spamming arbitrary keys
        # into our STATE dict. New actions need a one-line update here.
        allowed = {
            "modal_open", "star", "watch", "discussions",
            "source", "issues", "contributing",
        }
        if action not in allowed:
            raise HTTPException(status_code=400, detail=f"unknown action: {action}")
        community = STATE.setdefault("runtime", {}).setdefault("community", {
            "actions": {},
            "hourly":  {},
            "first_seen_at": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
        })
        # All-time per-action counter
        community.setdefault("actions", {})[action] = int(community["actions"].get(action, 0)) + 1
        # Hourly bucket — lets us plot trend lines later. Keep at most
        # 24*7=168 buckets (1 week) to bound state growth.
        hour_key = _time.strftime("%Y-%m-%dT%H", _time.gmtime())
        hbucket = community.setdefault("hourly", {}).setdefault(hour_key, {})
        hbucket[action] = int(hbucket.get(action, 0)) + 1
        if len(community["hourly"]) > 168:
            for old in sorted(community["hourly"].keys())[: len(community["hourly"]) - 168]:
                community["hourly"].pop(old, None)
        community["last_action"] = action
        community["last_where"]  = where or None
        community["last_seen_at"] = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
        try:
            ctx.persist_state()
        except Exception:
            pass
        return {"ok": True, "action": action, "totals": community["actions"]}

    @app.get("/api/runtime/readiness")
    def api_runtime_readiness():
        """v2.0.7 (#425): backend-readiness probe for the
        "Appliance is getting ready" banner on the launch page.
        Returns each tracked backend's TCP-probe state + a weighted
        overall percentage so the user sees progress proportional to
        bytes-downloaded, not just container count.

        See core/appliance_readiness.py for the probe list + design
        rationale. Safe to call every few seconds — each probe is a
        sub-300ms TCP connect.
        """
        from core import appliance_readiness as _ar
        return _ar.probe_all()

    @app.get("/api/runtime/install-id")
    def api_runtime_install_id():
        """Return the appliance's stable install identifier.

        Used by:
          - packaging/common/phone-home.{sh,ps1} during a `brew upgrade`
            / `apt upgrade` / `dnf upgrade` flow on an EXISTING install.
            The package-manager script probes this endpoint before
            generating a random id, so an existing customer's appliance
            keeps the same install_id across CLI upgrades. Without this
            probe, the postinst would mint a new random id and the
            portal's install-funnel row would split in two.
          - scripts/cloud-learn launcher as a post-`up` backfill, to
            seed $HOME/.vyomi/install_id when the CLI was installed by
            a method that DIDN'T write the marker file (tarball, source
            clone, docker-compose-direct).

        Public-ish: returns just the install_id — no PII, no license
        details. The id is already sent in every phone-home POST that
        leaves the appliance, so exposing it on the local LAN to a
        process running as the same user is not a leak.
        """
        from core import license_remote
        return {"install_id": license_remote.get_or_create_install_id(STATE)}

    @app.get("/api/runtime/version")
    def api_runtime_version():
        """Current appliance version — read from the VERSION file baked
        into the image at /app/VERSION. Falls back to "unknown" if the
        file is missing (e.g. dev runs from a checkout without one)."""
        try:
            v = Path("/app/VERSION").read_text(encoding="ascii").strip()
        except Exception:
            try:
                # Dev fallback — read the repo's VERSION file relative
                # to this module.
                v = (Path(__file__).resolve().parent.parent / "VERSION").read_text(encoding="ascii").strip()
            except Exception:
                v = "unknown"
        return {"version": v}

    @app.get("/api/runtime/update-check")
    def api_runtime_update_check():
        """Compare local VERSION to the latest GitHub release tag.
        Cached 15 min in module-local memory to avoid hammering the
        GitHub anonymous rate limit (60 req/hr).

        Returns:
          { current: "2.0.5", latest: "2.0.6", update_available: true,
            release_url: "https://github.com/vyomi-cloud/appliance/...",
            release_notes_url: same, checked_at: ISO8601 }

        Errors are surfaced as `{ error: "...", current: "..." }` so
        the SPA banner can degrade gracefully instead of crashing.
        Set CLOUDLEARN_UPDATE_CHECK_DISABLED=1 to opt out (returns
        update_available=false unconditionally).
        """
        import json as _json
        import time as _time
        import urllib.error as _ue
        import urllib.request as _ur

        # Opt-out
        if str(os.environ.get("CLOUDLEARN_UPDATE_CHECK_DISABLED", "")).strip().lower() in ("1", "true", "yes"):
            return {"update_available": False, "disabled": True}

        # Resolve current version
        try:
            current = Path("/app/VERSION").read_text(encoding="ascii").strip()
        except Exception:
            try:
                current = (Path(__file__).resolve().parent.parent / "VERSION").read_text(encoding="ascii").strip()
            except Exception:
                current = "unknown"

        # Cache — 15 min TTL, stored on the module's runtime state.
        now = _time.time()
        cache = runtime_state.setdefault("update_check_cache", {})
        if cache.get("expires_at", 0) > now and cache.get("payload"):
            payload = dict(cache["payload"])
            payload["current"] = current
            payload["update_available"] = _semver_lt(current, payload.get("latest", "0.0.0"))
            payload["cached"] = True
            return payload

        # Live fetch
        repo = os.environ.get("CLOUDLEARN_GITHUB_REPO") or os.environ.get(
            "VYOMI_GITHUB_REPO") or "vyomi-cloud/appliance"
        url = f"https://api.github.com/repos/{repo}/releases/latest"
        try:
            req = _ur.Request(url, headers={"Accept": "application/vnd.github+json",
                                             "User-Agent": "vyomi-update-check/1.0"})
            with _ur.urlopen(req, timeout=5) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
            latest_tag = str(data.get("tag_name") or "")
            latest = latest_tag.lstrip("v")
            release_url = data.get("html_url") or f"https://github.com/{repo}/releases/tag/{latest_tag}"
            payload = {
                "current":           current,
                "latest":            latest,
                "latest_tag":        latest_tag,
                "update_available":  _semver_lt(current, latest),
                "release_url":       release_url,
                "release_notes_url": release_url,
                "checked_at":        _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime(now)),
                "cached":            False,
            }
            cache["payload"] = payload
            cache["expires_at"] = now + 15 * 60   # 15 min
            return payload
        except (_ue.URLError, Exception) as e:
            # Stale cache wins over a hard error — surface the error
            # but keep the SPA banner working.
            if cache.get("payload"):
                payload = dict(cache["payload"])
                payload["current"] = current
                payload["update_available"] = _semver_lt(current, payload.get("latest", "0.0.0"))
                payload["error"] = f"{type(e).__name__}: {e}"
                payload["served_from"] = "stale_cache"
                return payload
            return {
                "current":          current,
                "latest":           current,  # don't ever falsely advertise an upgrade on error
                "update_available": False,
                "error":            f"{type(e).__name__}: {e}",
            }


def _semver_lt(a: str, b: str) -> bool:
    """True if `a` is strictly less than `b` under loose semver
    (handles 2/3/4-segment versions like 2.0.5 vs 2.0.5.1)."""
    def parse(v):
        try:
            return tuple(int(x) for x in v.lstrip("v").split(".") if x.isdigit())
        except Exception:
            return ()
    return parse(a) < parse(b)
