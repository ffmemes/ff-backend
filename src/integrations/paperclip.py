"""
Paperclip integration — webhook proxy and notification helpers.

Sentry and Coolify cannot send custom Authorization headers, but Paperclip
triggers require Bearer token auth. This module provides:
  1. A FastAPI router with a secured webhook proxy endpoint that external
     services (Sentry, Coolify) can POST to. The proxy verifies the caller's
     identity and forwards the request to Paperclip's QA trigger with the
     correct Bearer token.
  2. A helper function for notifying Paperclip from Python code (used by
     Prefect flow hooks).

Security:
  - Sentry webhooks: verified via HMAC-SHA256 signature (Sentry-Hook-Signature
    header checked against SENTRY_CLIENT_SECRET).
  - Coolify / other sources: verified via shared secret in query parameter
    (?secret=WEBHOOK_PROXY_SECRET).
  - Requests failing both checks get 403.

Env vars required:
  PAPERCLIP_QA_TRIGGER_URL    — Paperclip trigger fire URL
  PAPERCLIP_QA_TRIGGER_SECRET — Bearer token for the trigger
  SENTRY_CLIENT_SECRET        — Sentry Internal Integration client secret (for HMAC)
  WEBHOOK_PROXY_SECRET        — Shared secret for non-Sentry callers
"""

import hashlib
import hmac
import logging

import httpx
from fastapi import APIRouter, Request, Response

from src.config import settings

logger = logging.getLogger(__name__)

# Coolify UUID for ff-backend app — used to filter deploy webhooks
FFMEMES_APP_UUID = "v0kkssccwoswgwwscws4kscc"

router = APIRouter()


def _verify_sentry_signature(body: bytes, signature: str) -> bool:
    """Verify Sentry webhook HMAC-SHA256 signature."""
    secret = settings.SENTRY_CLIENT_SECRET
    if not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _verify_shared_secret(provided: str | None) -> bool:
    """Verify shared secret from query parameter."""
    expected = settings.WEBHOOK_PROXY_SECRET
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected, provided)


@router.post("/webhooks/qa-alert")
async def webhook_proxy_qa(request: Request) -> Response:
    """Proxy webhook from Sentry/Coolify to Paperclip QA trigger.

    Authentication (one must pass):
      1. Sentry: Sentry-Hook-Signature header (HMAC-SHA256)
      2. Others: ?secret=<WEBHOOK_PROXY_SECRET> query parameter
    """
    trigger_url = settings.PAPERCLIP_QA_TRIGGER_URL
    trigger_secret = settings.PAPERCLIP_QA_TRIGGER_SECRET

    if not trigger_url or not trigger_secret:
        logger.warning("Paperclip QA trigger not configured, skipping proxy")
        return Response(status_code=200, content="ok (not configured)")

    # Read raw body for signature verification
    body_bytes = await request.body()

    # Auth check: Sentry signature OR shared secret
    sentry_sig = request.headers.get("Sentry-Hook-Signature", "")
    query_secret = request.query_params.get("secret")

    is_sentry = bool(sentry_sig)
    authenticated = False

    if is_sentry:
        authenticated = _verify_sentry_signature(body_bytes, sentry_sig)
    else:
        authenticated = _verify_shared_secret(query_secret)

    if not authenticated:
        logger.warning(
            "Webhook proxy auth failed (sentry=%s, has_secret=%s)",
            is_sentry,
            bool(query_secret),
        )
        return Response(status_code=403, content="forbidden")

    # Parse payload
    try:
        import json

        body = json.loads(body_bytes)
    except Exception:
        body = {}

    # Identify source
    source = "sentry" if is_sentry else "coolify"
    sentry_resource = request.headers.get("Sentry-Hook-Resource")
    if sentry_resource:
        source = f"sentry_{sentry_resource}"

    # Coolify fires for ALL apps. Only forward events for ff-backend.
    if source == "coolify":
        body_str = body_bytes.decode("utf-8", errors="replace")
        if FFMEMES_APP_UUID not in body_str:
            logger.info("Coolify webhook ignored (not ff-backend app)")
            return Response(status_code=200, content="ok (filtered)")

    payload = {
        "event": f"webhook_proxy_{source}",
        "body": body,
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                trigger_url,
                headers={"Authorization": f"Bearer {trigger_secret}"},
                json=payload,
                timeout=10,
            )
            logger.info("Paperclip QA trigger fired: %s", resp.status_code)
            if resp.status_code >= 300:
                logger.error(
                    "Paperclip QA trigger returned non-2xx: %s", resp.status_code
                )
                return Response(status_code=502, content="bad gateway")
    except Exception as e:
        logger.error("Failed to proxy to Paperclip QA: %s", e)
        return Response(status_code=502, content="bad gateway")

    return Response(status_code=200, content="ok")


def notify_qa_sync(flow_name: str, run_name: str, error_msg: str) -> None:
    """Fire the Paperclip QA trigger synchronously (for Prefect hooks)."""
    trigger_url = settings.PAPERCLIP_QA_TRIGGER_URL
    trigger_secret = settings.PAPERCLIP_QA_TRIGGER_SECRET

    if not trigger_url or not trigger_secret:
        return

    try:
        resp = httpx.post(
            trigger_url,
            headers={"Authorization": f"Bearer {trigger_secret}"},
            json={
                "event": "prefect_flow_failure",
                "flow": flow_name,
                "run": run_name,
                "error": error_msg[:500],
            },
            timeout=10,
        )
        resp.raise_for_status()
    except Exception as e:
        logger.error("Failed to notify Paperclip QA: %s", e)
