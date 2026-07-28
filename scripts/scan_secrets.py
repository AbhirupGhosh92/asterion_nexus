#!/usr/bin/env python3
"""
Secret scanner — runs as a pre-commit hook and in CI.

Two modes:
  --staged   what you're about to commit (added lines + new file paths)
  --all      every tracked file (CI, so a --no-verify commit can't sneak past)

Design notes:

- **Only added lines are scanned** in --staged mode. Rewriting history to
  purge an old secret is a separate job; failing every commit until then
  would just teach you to pass --no-verify reflexively.
- **Filename rules come first.** `backend/.env` is a finding whatever is
  inside it, because the danger is the file class, not the byte pattern.
- **Patterns are high-signal only.** A scanner that cries wolf gets disabled,
  so this looks for shapes that are almost never anything else: real key
  material, provider-specific ids, and assignments whose *value* looks
  random rather than whose *name* sounds secret.

Escape hatches: append `pragma: allowlist secret` to a line, or commit with
`--no-verify`. CI still scans the tree either way.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

ALLOW_MARKER = "pragma: allowlist secret"

# Files that must never be committed regardless of content.
BLOCKED_PATHS = [
    (re.compile(r"(^|/)\.env(\.|$)(?!example)"), "environment file"),
    (re.compile(r"(^|/)\.env$"), "environment file"),
    (re.compile(r"(^|/)CLAUDE\.local\.md$"), "local deployment notes"),
    (re.compile(r"(^|/)deploy\.config$"), "deployment config"),
    (re.compile(r"\.(pem|p12|pfx|keystore|jks)$"), "key material"),
    (re.compile(r"(^|/)id_(rsa|dsa|ecdsa|ed25519)$"), "private ssh key"),
    (re.compile(r"(service[-_]?account|-sa)[-_.\w]*\.json$"), "service account key"),
    (re.compile(r"(^|/)\.npmrc$|(^|/)\.pypirc$"), "package registry credentials"),
]

# Paths where matches are expected and meaningless (templates, this scanner).
IGNORED_PATHS = re.compile(
    r"(\.example$|\.example\.|(^|/)scripts/scan_secrets\.py$|(^|/)\.githooks/|"
    r"(^|/)package-lock\.json$|(^|/)\.git/)"
)

PATTERNS: list[tuple[str, re.Pattern]] = [
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("GCP service-account key", re.compile(r'"type"\s*:\s*"service_account"')),
    # Alternations stay NON-capturing: a capturing group here would make the
    # code treat the literal prefix ("AKIA") as the secret's value and then
    # dismiss it as an identifier — silently disarming the rule.
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35,}")),
    ("AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[0-9A-Za-z]{36,}\b")),
    ("Slack token", re.compile(r"\bxox[abprs]-[0-9A-Za-z-]{10,}\b")),
    ("Stripe secret key", re.compile(r"\b[sr]k_live_[0-9A-Za-z]{20,}\b")),
    ("OpenAI/Anthropic key", re.compile(r"\b(?:sk-ant-|sk-proj-|sk-)[0-9A-Za-z_\-]{24,}\b")),
    ("PEM certificate body", re.compile(r"-----BEGIN OPENSSH PRIVATE KEY-----")),
    # Assignment whose value looks random: >=16 chars of key-ish alphabet with
    # no spaces. Placeholders (`xxx`, `your-…`, `<…>`, `changeme`) are excluded
    # below, which is what keeps .env.example-style docs quiet.
    (
        "hardcoded credential",
        re.compile(
            r"""(?ix)
            \b (?:password|passwd|secret|token|api[_-]?key|access[_-]?key|
                  client[_-]?secret|auth[_-]?token|credential)
            \s* [:=] \s* ["']? (?P<value>[A-Za-z0-9+/=_\-]{16,}) ["']?
            """
        ),
    ),
]

PLACEHOLDER = re.compile(
    r"(?i)^(x{3,}|y{3,}|your[-_]|my[-_]|example|placeholder|changeme|todo|"
    r"replace|dummy|test|sample|none|null|true|false|\$\{|<|\.\.\.)"
)

# snake_case / SCREAMING_CASE words — how code refers to a secret, not how a
# secret looks. `secret = google_secret_manager_secret.secrets[...]` is a
# Terraform reference; treating it as a finding is how scanners get muted.
IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z_]*(_[A-Za-z]+)*$")


def _looks_random(value: str) -> bool:
    """Real key material mixes character classes; identifiers don't."""
    if IDENTIFIER.match(value):
        return False
    has_digit = any(c.isdigit() for c in value)
    has_upper = any(c.isupper() for c in value)
    has_lower = any(c.islower() for c in value)
    has_b64 = any(c in "+/=" for c in value)
    return has_b64 or has_digit or (has_upper and has_lower)


def _redact(value: str) -> str:
    return value[:4] + "…" + value[-2:] if len(value) > 8 else "…"


def scan_line(path: str, lineno: int, line: str) -> list[str]:
    if ALLOW_MARKER in line:
        return []
    findings = []
    for label, rx in PATTERNS:
        m = rx.search(line)
        if not m:
            continue
        # Only the generic rule extracts a value to judge; provider-specific
        # shapes are self-evidently secrets and are reported as matched.
        value = m.groupdict().get("value")
        if value is not None and (PLACEHOLDER.match(value) or not _looks_random(value)):
            continue  # a template or a code reference, not a credential
        findings.append(f"{path}:{lineno}  {label}  ({_redact(value or m.group(0))})")
    return findings


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout


def scan_staged() -> list[str]:
    findings = []

    staged = [p for p in _git("diff", "--cached", "--name-only",
                              "--diff-filter=ACMR").splitlines() if p]
    for path in staged:
        if IGNORED_PATHS.search(path):
            continue
        for rx, why in BLOCKED_PATHS:
            if rx.search(path):
                findings.append(f"{path}  blocked file  ({why} — should be gitignored)")
                break

    # -U0 so only changed lines are considered, with hunk headers for numbers.
    diff = _git("diff", "--cached", "-U0", "--diff-filter=ACMR")
    path, lineno = "", 0
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            path, lineno = line[6:], 0
            continue
        if line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            lineno = int(m.group(1)) if m else 0
            continue
        if line.startswith("+") and not line.startswith("+++"):
            if path and not IGNORED_PATHS.search(path):
                findings += scan_line(path, lineno, line[1:])
            lineno += 1
    return findings


def scan_all() -> list[str]:
    findings = []
    for path in _git("ls-files").splitlines():
        if not path or IGNORED_PATHS.search(path):
            continue
        for rx, why in BLOCKED_PATHS:
            if rx.search(path):
                findings.append(f"{path}  blocked file  ({why} — should be gitignored)")
                break
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                for i, line in enumerate(fh, 1):
                    findings += scan_line(path, i, line)
        except (OSError, UnicodeError):
            continue
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--all", action="store_true", help="scan every tracked file")
    args = ap.parse_args()

    findings = scan_all() if args.all else scan_staged()
    if not findings:
        return 0

    where = "the repository" if args.all else "this commit"
    print(f"\n\033[1;31m✖ possible secrets in {where}:\033[0m\n", file=sys.stderr)
    for f in findings:
        print(f"    {f}", file=sys.stderr)
    print(
        "\nIf one of these is a false positive, append "
        f"`{ALLOW_MARKER}` to that line.\n"
        "To bypass entirely: git commit --no-verify "
        "(CI runs the same scan, so it will still be caught).\n",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
