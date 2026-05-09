#!/usr/bin/env python3
"""Staff Engineer PR review contract.

Codifies the decision logic that lived as imperative shell snippets in
`agents/staff-engineer/AGENTS.md` so the prompt can shrink to role +
decision criteria + helper invocation, and so each branch is covered by
a fixture test instead of being reverified by a fresh agent every wake.

Pure module: takes already-fetched PR metadata + review state in, returns
decisions out. No `gh`, `curl`, Paperclip API, or env reads inside the
helpers themselves — only the `--dry-run` CLI driver reads JSON from
stdin/file. Tests in `tests/test_paperclip_pr_review.py`.

Contract surface
----------------

- `pr_issue_slug(pr_number)`  →  `"[pr:NNN]"`
- `cto_followup_title(pr_number)`  →  `"[pr:NNN] address review changes"`
- `is_internal_pr(meta)`  →  bool, mirrors the Staff-Engineer rule:
  internal = `IS_FORK == false` AND
  (`author == "ohld"` OR `head_branch` matches an internal branch prefix).
- `pr_state_decision(meta)`  →  enum-like string, one of:
  `"already_resolved"`, `"missing_payload"`, `"review"`.
- `review_outcome(review)`  →  enum-like string, one of:
  `"approved"`, `"changes_requested"`, `"blocked"`.
- `merge_preflight(meta, review, repo)`  →  `MergePreflight` describing
  whether the auto-merge command should fire and why.
- `terminal_checklist(meta, review, post_actions)`  →  list of
  unsatisfied terminal-checklist items (empty list = OK to close).

The dry-run CLI prints these decisions for a hand-supplied PR snapshot
so an operator can verify the contract without firing `gh` or wakeing an
agent.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

INTERNAL_BRANCH_PREFIXES: tuple[str, ...] = (
    "agent/",
    "cto/",
    "staff-engineer/",
    "release-engineer/",
    "localize-",
    "fix/FFM-",
    "feat/agent-",
)

INTERNAL_AUTHORS: frozenset[str] = frozenset({"ohld"})

CI_FAILURE_STATES: frozenset[str] = frozenset({"FAILURE", "ERROR", "CANCELLED"})

REVIEW_OUTCOMES: tuple[str, ...] = ("approved", "changes_requested", "blocked")
PR_STATE_DECISIONS: tuple[str, ...] = ("already_resolved", "missing_payload", "review")


def pr_issue_slug(pr_number: int | str) -> str:
    """Stable issue prefix Paperclip uses to dedupe review handoffs."""
    return f"[pr:{int(pr_number)}]"


def cto_followup_title(pr_number: int | str) -> str:
    return f"{pr_issue_slug(pr_number)} address review changes"


def _matches_internal_branch(head_branch: str | None) -> bool:
    if not head_branch:
        return False
    return any(head_branch.startswith(p) for p in INTERNAL_BRANCH_PREFIXES)


def is_internal_pr(meta: Mapping[str, Any]) -> bool:
    """Internal-author rule from `agents/staff-engineer/AGENTS.md` step 1.

    Fork PRs are ALWAYS external regardless of author/branch — a fork can
    name its branch anything and would otherwise spoof the in-repo
    branch-prefix allowlist. The in-repo author/branch check only fires
    when `isCrossRepository == false`.
    """
    if meta.get("isCrossRepository") is True:
        return False
    author = (
        (meta.get("author") or {}).get("login")
        if isinstance(meta.get("author"), Mapping)
        else meta.get("author")
    )
    if isinstance(author, str) and author in INTERNAL_AUTHORS:
        return True
    return _matches_internal_branch(meta.get("headRefName"))


def pr_state_decision(meta: Mapping[str, Any]) -> str:
    """Idempotency check (step 0).

    Returns:
      `"already_resolved"` — `state in {MERGED, CLOSED}`. Skip review,
      close the execution issue with that summary.
      `"missing_payload"`  — caller could not derive a PR number. Comment
      and mark blocked; do not guess from "most recently updated PR".
      `"review"`           — proceed with the standard review flow.
    """
    if meta.get("pr_number") in (None, "", 0):
        return "missing_payload"
    state = (meta.get("state") or "").upper()
    if state in {"MERGED", "CLOSED"}:
        return "already_resolved"
    return "review"


def review_outcome(review: Mapping[str, Any]) -> str:
    """Map a structural-review payload to an enum-like outcome.

    Expected keys (all optional, defaults are conservative):
      `structural_pass`     — bool from `/review`
      `codex_pass`          — bool from `/codex review`
      `cso_required`        — bool, did the diff touch sensitive surfaces
      `cso_pass`            — bool, only consulted when `cso_required`
      `paranoia_violations` — list of project-specific findings
                              (`candidates.py` SQL interpolation, blender
                              weight invariants, secret leak)

    Decision rules:
      - any `paranoia_violations` → `"changes_requested"`
      - `structural_pass is False` or `codex_pass is False` →
        `"changes_requested"`
      - `cso_required and cso_pass is False` → `"changes_requested"`
      - any required signal still `None` → `"blocked"` (don't ship a
        review without evidence)
      - everything green → `"approved"`
    """
    if review.get("paranoia_violations"):
        return "changes_requested"
    structural = review.get("structural_pass")
    codex = review.get("codex_pass")
    if structural is False or codex is False:
        return "changes_requested"
    if review.get("cso_required") and review.get("cso_pass") is False:
        return "changes_requested"
    if structural is None or codex is None:
        return "blocked"
    if review.get("cso_required") and review.get("cso_pass") is None:
        return "blocked"
    return "approved"


@dataclass(frozen=True)
class MergePreflight:
    """Result of the three-check preflight from step 8.

    `should_merge` is True only when (a) the review approved, (b) the
    author is internal, (c) CI is not red, and (d) repo-level auto-merge
    is enabled. Any False answer surfaces in `reasons` so the caller can
    leave a precise GitHub comment instead of a generic "blocked".
    """

    should_merge: bool
    reasons: tuple[str, ...]
    skip_reasons: tuple[str, ...] = ()


def _checks_failed(checks: Sequence[Mapping[str, Any]] | None) -> bool:
    if not checks:
        return False
    return any((c.get("state") or "").upper() in CI_FAILURE_STATES for c in checks)


def merge_preflight(
    meta: Mapping[str, Any],
    review: Mapping[str, Any],
    repo: Mapping[str, Any] | None = None,
) -> MergePreflight:
    """Decide whether `gh pr merge --squash --auto` is safe to fire.

    `meta` is a `gh pr view` JSON. `review` is the same payload accepted
    by `review_outcome`; it must already have `outcome` set to one of
    `REVIEW_OUTCOMES` (the caller normally derives it via
    `review_outcome(review)` first). `repo` is `gh api repos/<o>/<r>`
    JSON, needed for the `allow_auto_merge` precheck.
    """
    skip: list[str] = []

    outcome = review.get("outcome") or review_outcome(review)
    if outcome != "approved":
        skip.append(f"review_outcome={outcome}")

    if not is_internal_pr(meta):
        skip.append("external_author")

    if _checks_failed(meta.get("statusCheckRollup")):
        skip.append("ci_red")

    if repo is not None and repo.get("allow_auto_merge") is not True:
        skip.append("auto_merge_disabled")

    return MergePreflight(
        should_merge=not skip,
        reasons=tuple(skip),
        skip_reasons=tuple(skip),
    )


@dataclass(frozen=True)
class TerminalIssue:
    code: str
    message: str


def terminal_checklist(
    meta: Mapping[str, Any],
    review: Mapping[str, Any],
    post_actions: Mapping[str, Any] | None = None,
) -> list[TerminalIssue]:
    """Verify each Staff-Engineer terminal-checklist item.

    `post_actions` is a flat mapping of side effects the run claims to
    have performed:
      `review_signal_posted`        — bool. True when either a real
                                       formal review or the
                                       `STAFF ENGINEER REVIEW: ...`
                                       comment fallback was published.
      `auto_merge_cancelled`        — bool. Required on
                                       changes-requested for ohld PRs
                                       so a queued merge from a prior
                                       wake doesn't fire mid-fix.
      `cto_followup_created`        — bool. Required on
                                       changes-requested with internal
                                       author.
      `merge_state`                 — `"merged"` | `"queued"` |
                                       `"blocked"` | `"skipped"`.
      `block_comment_posted`        — bool. Required on
                                       `merge_state == "blocked"`.

    Returns a list of unsatisfied checklist items (empty list = OK to
    close `done`).
    """
    post_actions = post_actions or {}
    issues: list[TerminalIssue] = []

    outcome = review.get("outcome") or review_outcome(review)

    if not post_actions.get("review_signal_posted"):
        issues.append(TerminalIssue("missing_review_signal", "No GitHub review signal posted"))

    is_internal = is_internal_pr(meta)

    if outcome == "changes_requested":
        if is_internal and not post_actions.get("cto_followup_created"):
            issues.append(
                TerminalIssue(
                    "missing_cto_followup",
                    "Internal changes-requested PR has no [pr:NNN] address review changes child",
                )
            )
        if not post_actions.get("auto_merge_cancelled"):
            issues.append(
                TerminalIssue(
                    "auto_merge_not_cancelled",
                    "auto-merge from a prior wake was not disabled before posting changes",
                )
            )

    if outcome == "approved":
        merge_state = post_actions.get("merge_state")
        # External-author approvals never reach the merge step; a
        # `merge_state == "skipped"` with `external_author` reason is a
        # clean terminal state.
        if not is_internal:
            if merge_state not in {"skipped", None}:
                issues.append(
                    TerminalIssue(
                        "external_unexpected_merge",
                        (
                            "External PR has a non-skipped merge_state — "
                            "should never auto-merge from this agent"
                        ),
                    )
                )
        else:
            if merge_state not in {"merged", "queued", "blocked"}:
                issues.append(
                    TerminalIssue(
                        "missing_merge_state",
                        "Internal approved PR has no merge_state (merged|queued|blocked)",
                    )
                )
            if merge_state == "blocked" and not post_actions.get("block_comment_posted"):
                issues.append(
                    TerminalIssue(
                        "missing_block_comment",
                        "Blocked merge state without a GitHub comment naming the blocker",
                    )
                )

    return issues


def render_decision_summary(
    meta: Mapping[str, Any],
    review: Mapping[str, Any],
    repo: Mapping[str, Any] | None,
    post_actions: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Bundle every contract decision so the dry-run CLI emits one JSON
    object. The shape is the public ledger format consumers diff across
    runs."""
    pr_number = meta.get("pr_number") or meta.get("number")
    state_decision = pr_state_decision(meta)
    outcome = review_outcome(review)
    review_with_outcome = dict(review)
    review_with_outcome.setdefault("outcome", outcome)
    preflight = merge_preflight(meta, review_with_outcome, repo)
    checklist = terminal_checklist(meta, review_with_outcome, post_actions)
    return {
        "pr_number": pr_number,
        "issue_slug": pr_issue_slug(pr_number) if pr_number else None,
        "state_decision": state_decision,
        "is_internal": is_internal_pr(meta),
        "review_outcome": outcome,
        "merge_preflight": {
            "should_merge": preflight.should_merge,
            "skip_reasons": list(preflight.skip_reasons),
        },
        "terminal_unsatisfied": [
            {"code": item.code, "message": item.message} for item in checklist
        ],
        "cto_followup_title": cto_followup_title(pr_number) if pr_number else None,
    }


def _load_json(path: str | None, fallback: dict[str, Any]) -> dict[str, Any]:
    if path is None:
        return dict(fallback)
    if path == "-":
        return json.load(sys.stdin)
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run helper for the Staff Engineer PR-review contract. "
            "Reads PR metadata + review evidence as JSON and prints the "
            "decision a real wake would make."
        )
    )
    parser.add_argument("--meta", help="Path to PR metadata JSON, or '-' for stdin")
    parser.add_argument("--review", help="Path to review evidence JSON, or '-' for stdin")
    parser.add_argument("--repo", help="Path to repo settings JSON (gh api repos/<o>/<r>)")
    parser.add_argument("--post-actions", help="Path to post-actions JSON")
    parser.add_argument("--json", action="store_true", help="JSON output (default: pretty)")
    args = parser.parse_args(argv)

    meta = _load_json(args.meta, {})
    review = _load_json(args.review, {})
    repo = _load_json(args.repo, {}) if args.repo else None
    post_actions = _load_json(args.post_actions, {}) if args.post_actions else None

    summary = render_decision_summary(meta, review, repo, post_actions)
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
