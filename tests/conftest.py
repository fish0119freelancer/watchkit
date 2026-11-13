"""Pytest configuration and test helpers."""
from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

# Ensure watchkit is importable without pip install -e
SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def load_fixture_text(name: str) -> str:
    """Read a test fixture file as text."""
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def load_fixture_json(name: str) -> Any:
    """Read a test fixture file as JSON."""
    return json.loads(load_fixture_text(name))
