"""Shared issue / outcome / routine contracts for the Paperclip audits.

Centralizes the definitions that previously lived inline in each audit
script so prompts and audits read from one source of truth:

- `[slug:...]` issue prefixes and the canonical class names they map to.
- Structured `experiments/log.jsonl` action names that count as decisions
  vs outcomes — including the legacy `daily_post` alias that drifted away
  from the canonical `daily_channel_post` / `post_published` names.
- Routine outcome contracts (terminal markers, intermediate approval
  markers, stale-draft markers, missing-access markers).
- Nested-state derivation that surfaces `published`,
  `approved_unpublished`, `pending_approval`, `stale_draft`,
  `blocked_without_access`, `missing_smoke`, and `merged_without_close`
  so a routine cannot be reported green while a child is non-terminal.

Pure module: no I/O, no Paperclip client, no env reads. Tested in
`tests/test_paperclip_contracts.py`.
"""

from __future__ import annotations

import re
from typing import Iterable, Mapping, Sequence

ISSUE_SLUG_RE = re.compile(r"^\[([a-z0-9_-]+):([^\]]+)\]")

# `[<slug>: ...]` prefix → audit category. The class name is the value
# audit consumers (outcome audit, dashboards, prompts) should reference.
ISSUE_CLASSES: Mapping[str, str] = {
    "pr": "pr_review",
    "post": "comms_post",
    "deploy": "deploy",
    "incident": "incident",
    "maintenance": "maintenance",
    "report": "analyst_report",
    "experiment": "experiment",
    "scan": "qa_scan",
    "strategy": "strategy",
}

# All categories the outcome audit knows about. `ceo_routing` and `other`
# are derived (creator-based / fallback) and don't have a slug prefix, so
# they're listed separately.
ALLOWED_ISSUE_CLASSES: frozenset[str] = frozenset(
    list(ISSUE_CLASSES.values()) + ["ceo_routing", "other"]
)

# Categories whose backlog churn dominates "execution" share — used by
# `paperclip_outcome_audit` to flag `execution_heavy_week`.
EXECUTION_CATEGORIES: frozenset[str] = frozenset(
    {"pr_review", "incident", "deploy", "qa_scan", "maintenance", "analyst_report"}
)


def parse_bracket_slug(title: str) -> tuple[str, str] | None:
    """Return `(slug, ident)` for `[slug:ident] title…`, else `None`."""
    if not title:
        return None
    match = ISSUE_SLUG_RE.match(title.lower())
    if not match:
        return None
    return match.group(1), match.group(2)


def issue_slug(title: str) -> str | None:
    parsed = parse_bracket_slug(title)
    return parsed[0] if parsed else None


# Structured `experiments/log.jsonl` `action` values that count as
# product decisions. Strict enumeration so audits don't silently start
# accepting new names without a contract update.
DECISION_ACTIONS: frozenset[str] = frozenset(
    {
        "experiment_created",
        "experiment_completed",
        "experiment_cancelled",
        "experiment_archived",
        "weekly_outcome_review",
    }
)

# Outcome actions are decisions plus the canonical "something shipped"
# events. `daily_channel_post` and `post_published` are both canonical:
# Comms Manager logs `daily_channel_post` once per anomaly-driven post,
# and the underlying publish event itself uses `post_published`. Both
# count toward outcome yield.
OUTCOME_ACTIONS: frozenset[str] = DECISION_ACTIONS | frozenset(
    {
        "daily_channel_post",
        "post_published",
        "bug_fixed",
    }
)

# Legacy / typo aliases. Audits resolve these to the canonical name so
# historical rows continue to count without rewriting old ledger entries.
# Keep this map small: every entry should preserve a known historical meaning.
OUTCOME_ALIASES: Mapping[str, str] = {
    "daily_post": "daily_channel_post",
}


def canonical_action(action: str | None) -> str | None:
    """Map a logged action name to its canonical form, or `None` if it
    is neither a known outcome nor a known alias."""
    if not action:
        return None
    if action in OUTCOME_ACTIONS:
        return action
    return OUTCOME_ALIASES.get(action)


def is_outcome_action(action: str | None) -> bool:
    return canonical_action(action) is not None


def is_decision_action(action: str | None) -> bool:
    return canonical_action(action) in DECISION_ACTIONS


# Regexes that mark text as evidence of a routine outcome. Used by the
# execution audit to satisfy `outcome_gap` and by the routine audit to
# detect `published` nested state.
PUBLISHED_MARKERS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\boutcome\s*=\s*published\b", re.IGNORECASE),
    re.compile(r"\b(?:editorial_post_id|editorial post id)\b", re.IGNORECASE),
    re.compile(r"\b(?:telegram_message_id|telegram message id)\b", re.IGNORECASE),
)

# Intermediate approval signals. `APPROVED_TO_PUBLISH` is legacy fallback
# (still permitted for old drafts per `agents/comms-manager/AGENTS.md`)
# but `accepted` confirmation cards are the authoritative path.
APPROVAL_MARKERS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\boutcome\s*=\s*draft_created\b", re.IGNORECASE),
    re.compile(r"\bAPPROVED_TO_PUBLISH\b"),
    re.compile(r"\bapproved\b", re.IGNORECASE),
)

STALE_DRAFT_MARKERS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\boutcome\s*=\s*stale_draft\b", re.IGNORECASE),
)

# Comment phrasings that mean the run actually surfaced an access gap
# (env var / token / role missing). Distinct from
# `paperclip_execution_audit.MISSING_ACCESS_MARKERS` which carries a
# broader set; keep this tight so we don't promote noisy "permission"
# discussions to a nested blocked state.
BLOCKED_ACCESS_MARKERS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\boutcome\s*=\s*blocked_without_access\b", re.IGNORECASE),
    re.compile(r"\bmissing\s+(?:env|secret|token|access)\b", re.IGNORECASE),
    re.compile(r"\bblocked_without_access\b", re.IGNORECASE),
)

MISSING_SMOKE_MARKERS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bmissing_smoke\b", re.IGNORECASE),
    re.compile(r"\bsmoke\s+check\s+(?:not\s+run|skipped|missing)\b", re.IGNORECASE),
)

MERGED_WITHOUT_CLOSE_MARKERS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bmerged_without_close\b", re.IGNORECASE),
    re.compile(r"\bpr\s+merged\b.+\bissue\s+still\s+open\b", re.IGNORECASE | re.DOTALL),
)

# Order matters: the first matching state wins. `published` and
# `merged_without_close` are terminal; the rest describe non-terminal
# parents that callers must surface as "child non-terminal" so a routine
# does not report green while a child is still pending.
NESTED_STATES: tuple[str, ...] = (
    "published",
    "merged_without_close",
    "stale_draft",
    "blocked_without_access",
    "missing_smoke",
    "approved_unpublished",
    "pending_approval",
    "unknown",
)

TERMINAL_NESTED_STATES: frozenset[str] = frozenset({"published", "merged_without_close"})


def _any(patterns: Iterable[re.Pattern[str]], text: str) -> bool:
    return any(p.search(text) for p in patterns)


def _all(patterns: Iterable[re.Pattern[str]], text: str) -> bool:
    return all(p.search(text) for p in patterns)


def nested_state(text: str, *, slug: str | None = None) -> str:
    """Classify a child issue's text into one of `NESTED_STATES`.

    The function is biased toward "did this finish?" rather than "what
    failed?": absent strong signals it returns `pending_approval` for
    `[post:...]` issues and `unknown` otherwise. That keeps the
    parent-cannot-be-green-with-non-terminal-child rule conservative.
    """
    if _all(PUBLISHED_MARKERS, text):
        return "published"
    if _any(MERGED_WITHOUT_CLOSE_MARKERS, text):
        return "merged_without_close"
    if _any(STALE_DRAFT_MARKERS, text):
        return "stale_draft"
    if _any(BLOCKED_ACCESS_MARKERS, text):
        return "blocked_without_access"
    if _any(MISSING_SMOKE_MARKERS, text):
        return "missing_smoke"
    if _any(APPROVAL_MARKERS, text):
        return "approved_unpublished"
    if slug == "post":
        return "pending_approval"
    return "unknown"


def is_terminal_nested_state(state: str) -> bool:
    return state in TERMINAL_NESTED_STATES


def parent_child_status_violation(
    parent_status: str | None,
    children: Sequence[Mapping[str, object]],
) -> list[str]:
    """Return identifiers of children that are non-terminal while the
    parent is closed.

    `children` items must carry `identifier`, `status`, and either
    `nestedState` or enough text to classify. The caller (routine audit)
    is responsible for materializing the nested state.
    """
    if parent_status not in {"done", "cancelled"}:
        return []
    bad: list[str] = []
    for ref in children:
        ident = ref.get("identifier")
        status = ref.get("status")
        nested = ref.get("nestedState")
        if status in {"done", "cancelled"}:
            continue
        if isinstance(nested, str) and is_terminal_nested_state(nested):
            continue
        if isinstance(ident, str):
            bad.append(ident)
    return bad


# Paperclip agent workflow hardening contracts. These are intentionally pure
# text classifiers so docs, prompts, routines, and doctor checks can reuse the
# same "do not teach agents the wrong path" rules without a live Paperclip API.
AGENT_WORKFLOW_INVARIANT_PATTERNS: Mapping[str, tuple[re.Pattern[str], ...]] = {
    "ssh_default_path": (
        re.compile(r"\bssh\b.+\b(?:default|first|primary|normal)\s+path\b", re.IGNORECASE),
        re.compile(r"\b(?:start|begin|first)\s+with\s+ssh\b", re.IGNORECASE),
    ),
    "secret_recovery_prompt": (
        re.compile(
            r"\b(?:recover|find|search|grep)\b.+\b(?:secret|token|api[_ -]?key)\b", re.IGNORECASE
        ),
        re.compile(
            r"\b(?:secret|token|api[_ -]?key)\b.+\b(?:logs?|machine|filesystem)\b", re.IGNORECASE
        ),
    ),
    "missing_paperclip_first_path": (
        re.compile(
            r"\b(?:paperclip\s+(?:mcp|api)|paperclipai)\b.+\b(?:unavailable|missing|broken)\b"
            r".+\b(?:blocker|blocked|cannot\s+continue)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
}

AGENT_WORKFLOW_INVARIANTS: tuple[str, ...] = tuple(AGENT_WORKFLOW_INVARIANT_PATTERNS)


def agent_workflow_invariant_violations(text: str) -> tuple[str, ...]:
    """Return workflow-hardening invariants violated by `text`.

    The rules stay narrow on purpose: they target high-risk agent prompts that
    normalize SSH/manual secret hunting or make missing Paperclip access a hard
    blocker instead of a capability gap to report.
    """
    if not text:
        return ()
    violations = [
        name for name, patterns in AGENT_WORKFLOW_INVARIANT_PATTERNS.items() if _any(patterns, text)
    ]
    return tuple(violations)
