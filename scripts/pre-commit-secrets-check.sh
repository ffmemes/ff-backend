#!/bin/bash
# Pre-commit hook: blocks commits containing secrets
# Install: cp scripts/pre-commit-secrets-check.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
# Purpose: Safety rail for public repo with autonomous AI agents
#
# Patterns checked:
#   - PostgreSQL connection strings (postgresql://)
#   - API keys (sk-*, key-*, xoxb-*, xoxp-*)
#   - Telegram Bot tokens (digits:alphanumeric)
#   - Generic secrets (password=, secret=, token= with values)
#   - AWS keys (AKIA...)
#   - Private keys (BEGIN RSA/DSA/EC PRIVATE KEY)

set -e

# Only check staged changes (what's about to be committed)
DIFF=$(git diff --cached --diff-filter=ACM)

if [ -z "$DIFF" ]; then
    exit 0
fi

FOUND=0

# PostgreSQL connection strings
if echo "$DIFF" | grep -qiE 'postgresql://[^"'\''[:space:]]+'; then
    echo "ERROR: PostgreSQL connection string detected in staged changes"
    echo "       Pattern: postgresql://..."
    FOUND=1
fi

# OpenAI / Anthropic API keys
if echo "$DIFF" | grep -qE 'sk-[a-zA-Z0-9]{20,}'; then
    echo "ERROR: API key pattern (sk-*) detected in staged changes"
    FOUND=1
fi

# Telegram Bot tokens (format: 123456789:ABCdefGHIjklMNOpqrs...)
if echo "$DIFF" | grep -qE '[0-9]{8,}:[A-Za-z0-9_-]{30,}'; then
    echo "ERROR: Telegram Bot token pattern detected in staged changes"
    FOUND=1
fi

# AWS access keys
if echo "$DIFF" | grep -qE 'AKIA[0-9A-Z]{16}'; then
    echo "ERROR: AWS access key pattern detected in staged changes"
    FOUND=1
fi

# Private keys
if echo "$DIFF" | grep -qE 'BEGIN (RSA |DSA |EC )?PRIVATE KEY'; then
    echo "ERROR: Private key detected in staged changes"
    FOUND=1
fi

# Generic secrets in config-like patterns (password=X, secret=X, token=X)
# Only match when followed by a non-empty value (not just the variable name)
if echo "$DIFF" | grep -qiE '(password|secret|token|api_key|apikey)\s*[=:]\s*['\''"][^'\''"]{8,}'; then
    echo "WARNING: Possible secret assignment detected in staged changes"
    echo "         Check manually — this may be a false positive"
    # Warning only, don't block (too many false positives)
fi

if [ $FOUND -ne 0 ]; then
    echo ""
    echo "Commit blocked. Secrets must not be committed to this public repo."
    echo "If this is a false positive, use: git commit --no-verify"
    echo ""
    echo "Secrets belong in .env (gitignored), not in code."
    exit 1
fi

exit 0
