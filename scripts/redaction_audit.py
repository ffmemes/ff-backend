#!/usr/bin/env python3
"""Public-repo redaction audit.

Scans tracked files for secret values and live trigger material that must
never land in this public repo. Allowed: env var names, redacted issue
slugs, public dashboard hostnames. Forbidden: API keys, full DB URLs with
real passwords, Telegram bot tokens, raw bearer auth headers, Telethon
session strings, and private keys.

Exit code 0 == clean. Exit code 1 == at least one finding (or error).

Usage:
    python3 scripts/redaction_audit.py            # scan tracked files
    python3 scripts/redaction_audit.py path/...   # scan named paths
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlsplit

REPO_ROOT = Path(__file__).resolve().parent.parent

PLACEHOLDER_TOKENS = {
    "changeme",
    "REDACTED",
    "<your",
    "<password>",
    "<token>",
    "<api-key>",
    "<api_key>",
    "<secret>",
    "your-",
    "example",
    "EXAMPLE",
    "xxxxxxxx",
    "XXXX",
    "myStrongPassword",
    "app:app@",
    "postgres:postgres@",
    "@localhost",
    "@db:",
    "@app_db:",
}

DB_CREDENTIAL_PLACEHOLDER_TOKENS = {
    "changeme",
    "redacted",
    "<password>",
    "<token>",
    "<secret>",
    "example",
    "xxxxxxxx",
    "mystrongpassword",
}

DB_CREDENTIAL_PLACEHOLDER_PAIRS = {
    ("app", "app"),
    ("postgres", "postgres"),
}


@dataclass(frozen=True)
class Pattern:
    name: str
    regex: re.Pattern[str]
    description: str


PATTERNS: tuple[Pattern, ...] = (
    Pattern(
        name="legacy_public_trigger_path",
        regex=re.compile(r"routine-triggers/public/[A-Za-z0-9_-]{8,}"),
        description="Legacy routine trigger URL whose public id acts as a shared secret.",
    ),
    Pattern(
        name="bearer_literal",
        regex=re.compile(
            r"""(?ix)
            Bearer\s+
            (?![\$<>{])               # not an env-var ref like $VAR / ${VAR} / <token>
            [A-Za-z0-9_\-.]{20,}
            """,
        ),
        description="Authorization: Bearer <literal>. Use $VAR_NAME instead.",
    ),
    Pattern(
        name="db_url_with_password",
        regex=re.compile(
            r"""(?x)
            postgres(?:ql)?(?:\+\w+)?://
            [^\s:'"$<{]+               # username, no env-var ref
            :
            [^\s@/'"$<{]+              # password, no env-var ref
            @
            [^\s/'"$<{]+               # host
            """,
        ),
        description="postgres URL with a literal password. Use $DATABASE_URL or .env.",
    ),
    Pattern(
        name="openai_api_key",
        regex=re.compile(r"\bsk-[A-Za-z0-9_\-]{30,}\b"),
        description="OpenAI / Anthropic style API key.",
    ),
    Pattern(
        name="aws_access_key",
        regex=re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        description="AWS access key id.",
    ),
    Pattern(
        name="slack_bot_token",
        regex=re.compile(r"\bxox[bp]-[A-Za-z0-9\-]{20,}\b"),
        description="Slack bot/user token.",
    ),
    Pattern(
        name="telegram_bot_token",
        regex=re.compile(r"\b[0-9]{8,12}:[A-Za-z0-9_-]{35,}\b"),
        description="Telegram Bot API token (digits:base64).",
    ),
    Pattern(
        name="telethon_session_string",
        regex=re.compile(r"\b1[A-Za-z][A-Za-z0-9+/=_-]{80,}\b"),
        description="Telethon string-session blob.",
    ),
    Pattern(
        name="private_key_block",
        regex=re.compile(r"-----BEGIN (?:RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----"),
        description="Inlined private key.",
    ),
)

# Files where the patterns themselves must appear: the audit code, the
# rule documentation, and any test fixtures. Allowlist by repo-relative path.
ALLOWLIST_PATHS: frozenset[str] = frozenset(
    {
        "scripts/redaction_audit.py",
        "scripts/pre-commit-secrets-check.sh",
        "tests/test_redaction_audit.py",
        "docs/public-repo-rule.md",
    }
)

# Files that legitimately contain placeholder credentials (clearly safe).
PLACEHOLDER_PATHS: frozenset[str] = frozenset({".env.example"})

# Extensions we never scan (binary, lock files, large generated assets).
SKIP_SUFFIXES: frozenset[str] = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".pdf",
        ".zip",
        ".gz",
        ".tar",
        ".bin",
        ".lock",
        ".onnx",
        ".pkl",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
    }
)

# Top-level directories we never scan even if tracked.
SKIP_DIR_PREFIXES: tuple[str, ...] = (
    ".ralphex/",
    ".worktrees/",
)


@dataclass
class Finding:
    path: str
    line_no: int
    column: int
    pattern: str
    snippet: str

    def format(self) -> str:
        return f"{self.path}:{self.line_no}:{self.column}: {self.pattern} :: {self.snippet}"


def is_placeholder(match_text: str) -> bool:
    lower = match_text.lower()
    for token in PLACEHOLDER_TOKENS:
        if token.lower() in lower:
            return True
    return False


def is_db_url_placeholder(match_text: str) -> bool:
    parsed = urlsplit(match_text)
    username = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    if not username or not password:
        return False

    lowered_pair = (username.lower(), password.lower())
    if lowered_pair in DB_CREDENTIAL_PLACEHOLDER_PAIRS:
        return True

    credential_text = f"{username}:{password}".lower()
    for token in DB_CREDENTIAL_PLACEHOLDER_TOKENS:
        if token in credential_text:
            return True
    return False


def list_tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def should_skip(rel_path: str) -> bool:
    if rel_path in ALLOWLIST_PATHS:
        return True
    for prefix in SKIP_DIR_PREFIXES:
        if rel_path.startswith(prefix):
            return True
    suffix = Path(rel_path).suffix.lower()
    if suffix in SKIP_SUFFIXES:
        return True
    return False


def scan_file(rel_path: str) -> list[Finding]:
    abs_path = REPO_ROOT / rel_path
    if not abs_path.is_file():
        return []
    try:
        text = abs_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    findings: list[Finding] = []
    is_placeholder_file = rel_path in PLACEHOLDER_PATHS
    for pattern in PATTERNS:
        for match in pattern.regex.finditer(text):
            matched = match.group(0)
            if pattern.name == "db_url_with_password":
                is_placeholder_match = is_db_url_placeholder(matched)
            else:
                is_placeholder_match = is_placeholder(matched)
            if is_placeholder_file and is_placeholder_match:
                continue
            if is_placeholder_match:
                # heuristic for non-env files too: if the value clearly
                # contains a placeholder marker, skip.
                continue
            line_no = text.count("\n", 0, match.start()) + 1
            line_start = text.rfind("\n", 0, match.start()) + 1
            column = match.start() - line_start + 1
            snippet = matched
            if len(snippet) > 80:
                snippet = snippet[:40] + "..." + snippet[-20:]
            findings.append(
                Finding(
                    path=rel_path,
                    line_no=line_no,
                    column=column,
                    pattern=pattern.name,
                    snippet=snippet,
                )
            )
    return findings


def scan(paths: Iterable[str]) -> list[Finding]:
    findings: list[Finding] = []
    for rel in paths:
        if should_skip(rel):
            continue
        findings.extend(scan_file(rel))
    return findings


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        help="Paths to scan. Defaults to all tracked files.",
    )
    parser.add_argument(
        "--list-patterns",
        action="store_true",
        help="Print pattern names + descriptions and exit.",
    )
    args = parser.parse_args(argv)

    if args.list_patterns:
        for pattern in PATTERNS:
            print(f"{pattern.name}: {pattern.description}")
        return 0

    if args.paths:
        paths = args.paths
    else:
        paths = list_tracked_files()

    findings = scan(paths)
    if not findings:
        print(f"redaction-audit: clean ({len(list(paths))} files scanned)")
        return 0

    print(f"redaction-audit: {len(findings)} finding(s):")
    for f in findings:
        print(f"  {f.format()}")
    print()
    print("Forbidden material in tracked files. See docs/public-repo-rule.md.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
