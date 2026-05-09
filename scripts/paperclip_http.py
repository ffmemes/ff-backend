"""Shared Paperclip HTTP client for deploy/audit scripts.

Centralizes URL handling, bearer auth, JSON encoding, pagination, timeouts,
secret redaction, and error reporting so `agents/_sync_config.py`,
`scripts/paperclip_routine_audit.py`, `scripts/paperclip_outcome_audit.py`,
and `scripts/paperclip_execution_audit.py` no longer carry near-duplicate
copies of the same boilerplate.

No live Paperclip access is required to import this module — it only depends
on the standard library. Tests stub `urllib.request.urlopen` (or pass a fake
`opener`) to exercise behavior without network.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

# Single source of truth for log/body redaction. Mirrors what the per-script
# `SENSITIVE_PATTERNS` previously held; keep new patterns additive so audit
# stderr never echoes a secret a Paperclip API call surfaced.
SENSITIVE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\b(bearer\s+)[a-z0-9._~+/=-]{20,}"), r"\1[REDACTED]"),
    (re.compile(r"(https?://)[^@\s/:]+:[^@\s@]+@"), r"\1[REDACTED]@"),
    (
        re.compile(
            r"(?i)\b([a-z0-9_]*(?:token|secret|api_key|auth)[a-z0-9_]*\s*[:=]\s*)"
            r"([^\s,;]+)"
        ),
        r"\1[REDACTED]",
    ),
)


def redact(body: str, limit: int = 240) -> str:
    """Collapse whitespace, mask secrets, and truncate to `limit` chars."""
    body = " ".join(body.split())
    for pattern, replacement in SENSITIVE_PATTERNS:
        body = pattern.sub(replacement, body)
    if len(body) <= limit:
        return body
    return body[: max(1, limit - 1)] + "…"


class PaperclipAPIError(Exception):
    """HTTP / transport / decode failure from a Paperclip API call.

    `__str__` preserves the legacy `"HTTP {code} for {path}: {body}"` shape so
    existing audits can keep using `message.startswith("HTTP 404 for ")` to
    distinguish "not found" from "degraded".
    """

    def __init__(
        self,
        *,
        method: str,
        path: str,
        body: str,
        code: int | None = None,
        kind: str = "http",
    ) -> None:
        self.method = method
        self.path = path
        self.body = body
        self.code = code
        self.kind = kind
        if kind == "http" and code is not None:
            super().__init__(f"HTTP {code} for {path}: {body}")
        else:
            super().__init__(f"transport/decode failure for {path}: {body}")


def paperclip_base_url(env: dict[str, str] | None = None) -> str | None:
    """Resolve the API base URL from env, stripping a trailing `/api` segment.

    The `/api` strip lets callers paste either form (the audit scripts always
    re-add explicit `/api/...` paths, so a doubled prefix would break
    silently).
    """
    env = os.environ if env is None else env
    raw = env.get("PAPERCLIP_API_URL") or env.get("PAPERCLIP_URL")
    if not raw:
        return None
    trimmed = raw.rstrip("/")
    if trimmed.endswith("/api"):
        trimmed = trimmed[:-4]
    return trimmed


def parse_ts(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp (with `Z` accepted) into UTC-aware datetime.

    A single garbage timestamp from the API used to crash whole audits via
    uncaught `ValueError`. Mirror that defensive behavior here so callers
    don't reimplement it.
    """
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        print(f"warning: parse_ts unparseable value {value!r}", file=sys.stderr)
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# Type alias for the urlopen-shaped callable tests inject. Not enforced with
# typing.Protocol because the stdlib signature is loose enough that a stricter
# protocol would just cause friction.
OpenerFn = Callable[..., Any]


class PaperclipClient:
    """Thin Paperclip API wrapper: bearer auth, JSON, redacted error reporting.

    `opener` exists to let unit tests inject a fake without monkeypatching
    `urllib.request.urlopen` globally.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        user_agent: str = "ffmemes-paperclip-client/1.0",
        timeout: int = 30,
        opener: OpenerFn | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.user_agent = user_agent
        self.timeout = timeout
        self._opener = opener or urllib.request.urlopen

    def _build_url(self, path: str, query: dict[str, str] | None) -> str:
        url = self.base_url + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        return url

    def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        body: Any = None,
    ) -> Any:
        url = self._build_url(path, query)
        req = urllib.request.Request(url, method=method)
        # Cloudflare in front of org.ffmemes.com blocks the default
        # `Python-urllib/x.y` User-Agent (CF error 1010), so callers must
        # always pick a UA. Don't drop this header.
        req.add_header("Authorization", f"Bearer {self.api_key}")
        req.add_header("User-Agent", self.user_agent)
        data: bytes | None = None
        if body is not None:
            req.add_header("Content-Type", "application/json")
            data = json.dumps(body).encode()
        try:
            with self._opener(req, data=data, timeout=self.timeout) as resp:
                payload = resp.read()
        except urllib.error.HTTPError as exc:
            err_body = redact(exc.read().decode("utf-8", errors="replace"), limit=500)
            raise PaperclipAPIError(
                method=method, path=path, body=err_body, code=exc.code, kind="http"
            ) from exc
        except urllib.error.URLError as exc:
            raise PaperclipAPIError(
                method=method, path=path, body=str(exc.reason), kind="transport"
            ) from exc
        except (TimeoutError, OSError) as exc:
            raise PaperclipAPIError(
                method=method, path=path, body=str(exc), kind="transport"
            ) from exc
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise PaperclipAPIError(
                method=method, path=path, body=str(exc), kind="transport"
            ) from exc

    def get(self, path: str, query: dict[str, str] | None = None) -> Any:
        return self.request("GET", path, query=query)

    def post(self, path: str, body: Any = None) -> Any:
        return self.request("POST", path, body=body)

    def patch(self, path: str, body: Any = None) -> Any:
        return self.request("PATCH", path, body=body)

    def paginate(
        self,
        path: str,
        *,
        query: dict[str, str] | None = None,
        limit: int,
        page_size: int = 200,
        dedupe_key: str = "id",
        offset_param: str = "offset",
        limit_param: str = "limit",
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Page through a list endpoint and return `(items, truncation)`.

        Stop conditions:
        - Empty page (clean end of data).
        - Duplicate-only page (server ignores `offset` or has a hidden cap).
        - Non-list / non-dict / missing-id responses (shape drift).
        - Hitting `limit` rows; on the boundary we probe one extra row so an
          exact-fit dataset isn't reported as truncated.

        `truncation` keys: `truncated` (bool), `reason` (str | None),
        `atOffset` (int | None).
        """
        collected: list[dict[str, Any]] = []
        seen: set[Any] = set()
        offset = 0
        truncation: dict[str, Any] = {"truncated": False, "reason": None, "atOffset": None}
        base_query = dict(query or {})
        while len(collected) < limit:
            page_request_size = min(page_size, limit - len(collected))
            page_query = dict(base_query)
            page_query[limit_param] = str(page_request_size)
            page_query[offset_param] = str(offset)
            try:
                page = self.get(path, page_query)
            except PaperclipAPIError as exc:
                # Treat a per-page failure as truncation rather than killing
                # the whole audit; callers still get whatever rows arrived.
                print(
                    f"warning: paginate {path} page at offset={offset} failed: {exc}; "
                    f"treating as truncated",
                    file=sys.stderr,
                )
                truncation = {
                    "truncated": True,
                    "reason": "page_request_failed",
                    "atOffset": offset,
                }
                break
            if not isinstance(page, list):
                print(
                    f"warning: paginate {path} got unexpected response shape "
                    f"{type(page).__name__} at offset={offset}; treating as degraded",
                    file=sys.stderr,
                )
                truncation = {
                    "truncated": True,
                    "reason": "unexpected_response_shape",
                    "atOffset": offset,
                }
                break
            if not page:
                break
            dict_page = [item for item in page if isinstance(item, dict)]
            if len(dict_page) != len(page):
                print(
                    f"warning: paginate {path} page at offset={offset} contained "
                    f"{len(page) - len(dict_page)} non-dict element(s); treating as degraded",
                    file=sys.stderr,
                )
                truncation = {
                    "truncated": True,
                    "reason": "unexpected_response_shape",
                    "atOffset": offset,
                }
                break
            items_with_id = [item for item in dict_page if item.get(dedupe_key)]
            if len(items_with_id) != len(dict_page):
                print(
                    f"warning: paginate {path} page at offset={offset} contained "
                    f"{len(dict_page) - len(items_with_id)} dict element(s) missing "
                    f"`{dedupe_key}`; treating as degraded",
                    file=sys.stderr,
                )
                truncation = {
                    "truncated": True,
                    "reason": "unexpected_response_shape",
                    "atOffset": offset,
                }
                break
            new_items = [item for item in items_with_id if item[dedupe_key] not in seen]
            if not new_items:
                print(
                    f"warning: paginate {path} stalled at offset={offset} "
                    f"(page of duplicates); API likely ignores `{offset_param}` "
                    f"or has a server-side cap; results may be truncated",
                    file=sys.stderr,
                )
                truncation = {
                    "truncated": True,
                    "reason": "duplicate_page_offset_ignored",
                    "atOffset": offset,
                }
                break
            for item in new_items:
                seen.add(item[dedupe_key])
                collected.append(item)
            offset += len(page)
        if not truncation["truncated"] and len(collected) >= limit:
            try:
                probe_query = dict(base_query)
                probe_query[limit_param] = "1"
                probe_query[offset_param] = str(len(collected))
                probe = self.get(path, probe_query)
            except PaperclipAPIError as exc:
                print(
                    f"warning: paginate {path} ceiling probe failed at limit={limit}: {exc}; "
                    f"treating as truncated",
                    file=sys.stderr,
                )
                truncation = {
                    "truncated": True,
                    "reason": "hit_limit_ceiling_probe_failed",
                    "atOffset": len(collected),
                }
            else:
                if isinstance(probe, list) and not probe:
                    pass  # exactly `limit` rows existed; not truncated.
                else:
                    print(
                        f"warning: paginate {path} hit ceiling limit={limit}; "
                        f"results may be truncated",
                        file=sys.stderr,
                    )
                    truncation = {
                        "truncated": True,
                        "reason": "hit_limit_ceiling",
                        "atOffset": len(collected),
                    }
        return collected, truncation


def require_credentials(env: dict[str, str] | None = None) -> tuple[str, str] | None:
    """Return `(base_url, api_key)` if both env vars are set, else `None`.

    Helper so the audit `main()` functions don't all reimplement the same
    "Set PAPERCLIP_API_URL... and PAPERCLIP_API_KEY" check.
    """
    env = os.environ if env is None else env
    base_url = paperclip_base_url(env)
    api_key = env.get("PAPERCLIP_API_KEY")
    if not base_url or not api_key:
        return None
    return base_url, api_key


def fold_text(parts: Iterable[str | None]) -> str:
    """Join non-None text fragments with newlines for keyword scanning."""
    return "\n".join(p for p in parts if p)
