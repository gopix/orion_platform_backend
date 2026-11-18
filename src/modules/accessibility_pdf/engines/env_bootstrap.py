#!/usr/bin/env python3
"""
env_bootstrap.py
================
Load the repo-root ``.env`` into ``os.environ`` so the accessibility engines can
read their tuning knobs (ORION_ALT_*, orion-claude-*) with a plain
``os.environ.get(...)``.

WHY THIS EXISTS
---------------
The app configures pydantic-settings with ``env_file=".env"``, but that only
populates the Settings *object* — it does NOT export those values into
``os.environ``. Nothing in the app calls ``load_dotenv()``. So variables like
``ORION_ALT_CACHE_DIR`` set in ``.env`` were silently ignored, and the engines
fell back to their built-in defaults (e.g. the relative ``.alt_cache`` cache
dir, which never persisted across runs).

This module fixes that with a dependency-free parser (no python-dotenv needed).
Import it and call ``load_repo_dotenv()`` at the TOP of any engine module,
BEFORE that module reads env-driven constants.

PRECEDENCE
----------
Real process environment variables always win: we use ``setdefault``, so a value
already present in ``os.environ`` is never overwritten by ``.env``.
"""
from __future__ import annotations

import os
from pathlib import Path

_LOADED = False


def _candidate_env_paths():
    paths = []
    try:
        # .../src/modules/accessibility_pdf/engines/env_bootstrap.py
        #   parents[4] == repo root (orion_backend)
        paths.append(Path(__file__).resolve().parents[4] / ".env")
    except Exception:
        pass
    paths.append(Path.cwd() / ".env")
    return paths


def load_repo_dotenv(force: bool = False) -> int:
    """Populate os.environ from the repo-root .env (once per process).

    Returns the number of keys injected. Idempotent: subsequent calls are no-ops
    unless ``force=True``. Never raises — a missing/garbled .env just yields 0.
    """
    global _LOADED
    if _LOADED and not force:
        return 0
    injected = 0
    for p in _candidate_env_paths():
        try:
            if not p.exists():
                continue
            for raw in p.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                # strip inline comments and surrounding quotes
                val = val.split(" #", 1)[0].strip().strip('"').strip("'")
                if not key:
                    continue
                if key not in os.environ:      # real env wins
                    os.environ[key] = val
                    injected += 1
            break  # first existing .env wins
        except Exception:
            continue
    _LOADED = True
    return injected
