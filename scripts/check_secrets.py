"""Fail if a credential looks committed.

A database password reached this repository's history and was pushed. Moving
it to an environment variable stops it recurring in new code; this stops it
recurring in new commits, which is the part a person forgets.

    python scripts/check_secrets.py

Exits non-zero on a hit. Wired into CI.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("hardcoded password kwarg", re.compile(r"""password\s*=\s*["'][^"'{}$][^"']{5,}["']""", re.I)),
    ("hardcoded secret/key", re.compile(r"""(secret|api[_-]?key|token)\s*=\s*["'][A-Za-z0-9/+_-]{12,}["']""", re.I)),
    ("connection string", re.compile(r"""(postgres|postgresql|mysql|mongodb)://[^\s:"']+:[^\s@"']+@""", re.I)),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
]

# Paths where a match is expected or harmless.
SKIP_DIRS = {".git", "node_modules", "archive", "dist", "screenshots", "__pycache__", "models"}
SKIP_FILES = {".env.example", "check_secrets.py", "SECURITY.md"}
SKIP_SUFFIX = {".pkl", ".pt", ".db", ".png", ".jpg", ".pdf", ".lock", ".csv", ".json"}

# Values that look like secrets but are placeholders or documentation.
ALLOW = re.compile(r"(os\.environ|os\.getenv|process\.env|require\(|<[^>]+>|change-me|your[-_])", re.I)


def tracked_files() -> list[Path]:
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout
        return [ROOT / line for line in out.splitlines() if line]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return [p for p in ROOT.rglob("*") if p.is_file()]


def main() -> int:
    hits: list[str] = []
    for path in tracked_files():
        rel = path.relative_to(ROOT)
        if set(rel.parts) & SKIP_DIRS or rel.name in SKIP_FILES or path.suffix in SKIP_SUFFIX:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if ALLOW.search(line):
                continue
            for label, pattern in PATTERNS:
                if pattern.search(line):
                    hits.append(f"  {rel}:{lineno}  {label}\n      {line.strip()[:100]}")
                    break

    if hits:
        print(f"Possible credentials in {len(hits)} place(s):\n")
        print("\n".join(hits))
        print("\nMove the value to an environment variable and read it via "
              "backend/app/core/config.py, then re-run.")
        return 1

    print(f"No credentials found in {len(tracked_files())} tracked files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
