#!/usr/bin/env bash
# Run or resume the long Paperclip architecture Ralphex loop.
#
# Defaults are tuned for continuing an interrupted run on the current branch:
# - no --worktree, because this Ralphex build requires starting worktrees from production
# - dirty worktree allowed, because a previous run may have failed after editing a task
# - longer idle timeout than the default, because Task 6 previously hit stream idle timeout
#
# Common usage:
#   scripts/run_paperclip_ralphex.sh
#
# Useful overrides:
#   MODE=review scripts/run_paperclip_ralphex.sh
#   MODE=tasks-only scripts/run_paperclip_ralphex.sh
#   USE_WORKTREE=1 scripts/run_paperclip_ralphex.sh   # only from production
#   CLAUDE_ADVICE=0 scripts/run_paperclip_ralphex.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PLAN="${PLAN:-specs/paperclip-architecture-ralphex-plan.md}"
MODE="${MODE:-full}" # full | review | tasks-only | external-only
MAX_ITERATIONS="${MAX_ITERATIONS:-24}"
REVIEW_PATIENCE="${REVIEW_PATIENCE:-2}"
SESSION_TIMEOUT="${SESSION_TIMEOUT:-90m}"
IDLE_TIMEOUT="${IDLE_TIMEOUT:-25m}"
WAIT="${WAIT:-30m}"
USE_WORKTREE="${USE_WORKTREE:-0}"
ALLOW_DIRTY="${ALLOW_DIRTY:-1}"
REQUIRE_CLEAN="${REQUIRE_CLEAN:-0}"
CLAUDE_ADVICE="${CLAUDE_ADVICE:-1}"
CLAUDE_ADVICE_REQUIRED="${CLAUDE_ADVICE_REQUIRED:-0}"
CAFFEINATE="${CAFFEINATE:-1}"

log() {
  printf '[run-paperclip-ralphex] %s\n' "$*"
}

die() {
  printf '[run-paperclip-ralphex] ERROR: %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

scan_dangerous_diff() {
  local changed
  changed="$(git diff --name-only origin/production...HEAD 2>/dev/null; git diff --name-only)"
  if [[ -z "$changed" ]]; then
    return 0
  fi

  local diff
  diff="$(git diff -U0 origin/production...HEAD -- $changed 2>/dev/null; git diff -U0 -- $changed)"

  local found=0
  local patterns=(
    'routine-triggers/public'
    'BEGIN OPENSSH PRIVATE KEY'
    'BOT_TOKEN='
    'PAPERCLIP_API_KEY='
    'PASTE_DATABASE_URL_HERE'
    'postgres://[^$]'
    'postgresql://[^$]'
    '--fail-with-body'
    'Authorization: Bearer [A-Za-z0-9_]'
  )

  for pattern in "${patterns[@]}"; do
    if printf '%s\n' "$diff" | rg -q -- "$pattern"; then
      printf '[run-paperclip-ralphex] dangerous diff pattern matched: %s\n' "$pattern" >&2
      found=1
    fi
  done

  [[ "$found" == "0" ]]
}

run_claude_advice() {
  if [[ "$CLAUDE_ADVICE" != "1" ]]; then
    return 0
  fi
  if ! command -v claude >/dev/null 2>&1; then
    log "Claude Code not found; skipping advice pass."
    return 0
  fi

  mkdir -p .ralphex/advice
  local stamp output
  stamp="$(date '+%Y%m%d-%H%M%S')"
  output=".ralphex/advice/paperclip-ralphex-advice-$stamp.md"

  log "Running Claude Code advice pass (non-blocking unless CLAUDE_ADVICE_REQUIRED=1)."
  set +e
  claude --print --permission-mode plan --output-format text \
    "Review the current ff-backend Paperclip architecture Ralphex run before execution continues.

Context:
- Plan file: $PLAN
- The branch may already contain committed Tasks 0-5 and uncommitted Task 6 edits from an interrupted run.
- We want to avoid over-engineering and focus only on proven blockers that stop agents, create loops, hide false-green states, leak secrets, or leave missing access/tooling unresolved.

Please inspect the current git diff, recent commits, and plan status. Return:
1. Whether continuing Ralphex now is justified.
2. What the next 1-2 tasks should focus on.
3. Any task that should be skipped/deferred as over-engineering.
4. Any safety warning before continuing.

Do not edit files. Do not print secrets. Refer only to env var names." \
    >"$output" 2>&1
  local status=$?
  set -e

  if [[ "$status" != "0" ]]; then
    log "Claude advice failed; output saved to $output"
    if [[ "$CLAUDE_ADVICE_REQUIRED" == "1" ]]; then
      return "$status"
    fi
    return 0
  fi

  log "Claude advice saved to $output"
}

main() {
  require_cmd git
  require_cmd rg
  require_cmd ralphex

  [[ -f "$PLAN" ]] || die "plan file not found: $PLAN"

  if ps -axo pid,command | rg -q "ralphex .*${PLAN}" | rg -vq "rg "; then
    die "a Ralphex process for $PLAN already appears to be running"
  fi

  local branch
  branch="$(git branch --show-current)"
  log "repo: $ROOT"
  log "branch: $branch"
  log "plan: $PLAN"
  log "mode: $MODE"

  if [[ "$USE_WORKTREE" == "1" && "$branch" != "production" ]]; then
    die "USE_WORKTREE=1 requires running from production for this Ralphex build; current branch is $branch"
  fi

  if [[ -n "$(git status --porcelain)" ]]; then
    log "working tree is dirty:"
    git status --short
    if [[ "$REQUIRE_CLEAN" == "1" || "$ALLOW_DIRTY" != "1" ]]; then
      die "dirty working tree; set ALLOW_DIRTY=1 to resume an interrupted task"
    fi
  fi

  git diff --check
  scan_dangerous_diff || die "dangerous diff patterns detected; inspect before continuing"

  if [[ -x scripts/redaction_audit.py ]]; then
    python3 scripts/redaction_audit.py
  fi

  run_claude_advice

  local args=(
    --max-iterations "$MAX_ITERATIONS"
    --review-patience "$REVIEW_PATIENCE"
    --session-timeout "$SESSION_TIMEOUT"
    --idle-timeout "$IDLE_TIMEOUT"
    --wait "$WAIT"
  )

  case "$MODE" in
    full) ;;
    review) args+=(--review) ;;
    tasks-only) args+=(--tasks-only) ;;
    external-only) args+=(--external-only) ;;
    *) die "unknown MODE=$MODE; expected full, review, tasks-only, or external-only" ;;
  esac

  if [[ "$USE_WORKTREE" == "1" ]]; then
    args+=(--worktree)
  fi

  args+=("$PLAN")

  log "starting: ralphex ${args[*]}"
  if [[ "$CAFFEINATE" == "1" && "$(uname -s)" == "Darwin" && -x /usr/bin/caffeinate ]]; then
    exec /usr/bin/caffeinate -i ralphex "${args[@]}"
  fi
  exec ralphex "${args[@]}"
}

main "$@"
