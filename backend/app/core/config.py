"""Central configuration.

Reads a project-root .env file if present, then falls back to the real
environment. Nothing secret is ever hardcoded in the repository.
"""

from __future__ import annotations

import os
from pathlib import Path

# backend/app/core/config.py -> core -> app -> backend -> project root
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _load_dotenv() -> None:
    env_file = _PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        # Real environment variables win over the file.
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def require(name: str) -> str:
    """Return an environment variable, or fail loudly at import time."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable {name!r}. "
            "Copy .env.example to .env and fill it in."
        )
    return value


def get(name: str, default: str) -> str:
    return os.environ.get(name) or default
