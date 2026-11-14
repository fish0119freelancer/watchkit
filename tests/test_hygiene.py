"""Generic package hygiene tests."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from watchkit.core import DEFAULT_USER_AGENT, Source

WATCHKIT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
REPOSITORY_URL = "https://github.com/fish0119freelancer/watchkit"

EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}\b"
)
GITHUB_NOREPLY_PATTERN = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@users\.noreply\.github\.com$",
    re.IGNORECASE,
)
HOME_PATH_PATTERNS = (
    re.compile(r"/users/", re.IGNORECASE),
    re.compile(r"/home/[^/\s]+/", re.IGNORECASE),
    re.compile(r"[A-Za-z]:\\+users(?:\\|/|$)", re.IGNORECASE),
)
TOKEN_PREFIX_PATTERN = re.compile(
    r"(?:ghp_|gho_|github_pat_|sk-|akia)",
    re.IGNORECASE,
)
FINMIND_PATTERN = re.compile(r"\bFINMIND_TOKEN\s*=\s*['\"]?([^'\"\s]+)['\"]?")
DIGIT_PATTERN = re.compile(r"\d{9,}")
PRIVATE_NETWORK_PATTERN = re.compile(r"\.(?:local|home|lan)\b", re.IGNORECASE)
PUBLIC_TEXT_DIRS = (WATCHKIT_ROOT / "examples", WATCHKIT_ROOT / "docs")
TEXT_SUFFIXES = {".md", ".sh", ".txt"}
PNG_MAX_BYTES = 1_000_000


def _load_extra_tokens() -> tuple[str, ...]:
    """Load optional maintainer-provided values for this test run only."""
    raw_values = os.environ.get("WATCHKIT_HYGIENE_EXTRA", "")
    return tuple(
        value.strip().casefold()
        for value in raw_values.split(",")
        if value.strip()
    )


def _is_allowed_public_email(file_path: Path, email: str) -> bool:
    """Allow GitHub noreply addresses in the package's public docs."""
    name = file_path.name.upper()
    is_public_doc = name == "LICENSE" or name.startswith("README")
    return is_public_doc and bool(GITHUB_NOREPLY_PATTERN.fullmatch(email))


def test_user_agent_hygiene() -> None:
    """Verify the User-Agent has package metadata and no email address."""
    ua = DEFAULT_USER_AGENT
    assert "watchkit/" in ua
    assert REPOSITORY_URL in ua
    assert "@" not in ua

    source = Source("https://example.invalid")
    assert source.user_agent == ua


def test_no_hardcoded_paths_or_personal_identifiers() -> None:
    """Scan package text files for generic secret and path patterns.

    Maintainers can add private identifiers via an environment variable at test
    time. Values are comma-separated and are never committed to the package.

    Fixtures are excluded from the email and 9+ digit rules because sample
    data can contain public contact fields and long product identifiers.
    """
    extra_tokens = _load_extra_tokens()
    ignore_dirs = {".git", "__pycache__", ".pytest_cache", ".watchkit", "build", "dist"}
    test_file = Path(__file__).resolve()
    violations: list[str] = []

    for file_path in WATCHKIT_ROOT.rglob("*"):
        if not file_path.is_file():
            continue

        # Pattern definitions in this test necessarily contain the patterns
        # being checked; source-level review covers this file itself.
        if file_path.resolve() == test_file:
            continue

        if any(part in ignore_dirs or part.endswith(".egg-info") for part in file_path.parts):
            continue

        try:
            content = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            continue

        is_fixture = FIXTURES_DIR in file_path.parents
        relative_path = file_path.relative_to(WATCHKIT_ROOT)

        for line_no, line in enumerate(content.splitlines(), start=1):
            for pattern in HOME_PATH_PATTERNS:
                if pattern.search(line):
                    violations.append(f"{relative_path}:{line_no}: contains an absolute home path")

            if TOKEN_PREFIX_PATTERN.search(line):
                violations.append(f"{relative_path}:{line_no}: contains a token prefix")

            if FINMIND_PATTERN.search(line):
                violations.append(f"{relative_path}:{line_no}: contains FINMIND_TOKEN with a value")

            if PRIVATE_NETWORK_PATTERN.search(line):
                violations.append(f"{relative_path}:{line_no}: contains a private-network hostname")

            if extra_tokens and any(token in line.casefold() for token in extra_tokens):
                violations.append(f"{relative_path}:{line_no}: contains a maintainer-provided identifier")

            if not is_fixture:
                for email in EMAIL_PATTERN.findall(line):
                    if not _is_allowed_public_email(file_path, email):
                        violations.append(f"{relative_path}:{line_no}: contains an email address")

                if DIGIT_PATTERN.search(line):
                    violations.append(f"{relative_path}:{line_no}: contains a 9+ digit run")

    assert not violations, "Found hygiene violations:\n" + "\n".join(violations)


def test_examples_and_docs_text_files_are_in_hygiene_scope() -> None:
    """Ensure public example and documentation text files are scanned."""
    scanned_files = {
        path
        for path in WATCHKIT_ROOT.rglob("*")
        if path.is_file() and path.suffix.casefold() in TEXT_SUFFIXES
    }

    for directory in PUBLIC_TEXT_DIRS:
        text_files = [
            path
            for path in directory.rglob("*")
            if path.is_file() and path.suffix.casefold() in TEXT_SUFFIXES
        ]
        assert text_files, f"Expected public text files under {directory.name}/"
        assert set(text_files) <= scanned_files


def test_png_files_are_not_larger_than_one_megabyte() -> None:
    """Keep committed screenshots small enough for the public package."""
    oversized = [
        f"{path.relative_to(WATCHKIT_ROOT)} ({path.stat().st_size} bytes)"
        for path in WATCHKIT_ROOT.rglob("*")
        if path.is_file()
        and path.suffix.casefold() == ".png"
        and path.stat().st_size > PNG_MAX_BYTES
    ]

    assert not oversized, "PNG files exceed the 1 MB limit: " + ", ".join(oversized)


def test_offline_demo_python_command_runs_in_tmp_dir(tmp_path: Path) -> None:
    """Run the README demo command without writing to the tracked example output."""
    report_path = tmp_path / "kev-report.html"
    state_dir = tmp_path / ".state"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = "src"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "watchkit",
            "run",
            "kev",
            "--watchlist",
            "examples/watchlist.txt",
            "--offline",
            "tests/fixtures/kev_sample.json",
            "--out",
            str(report_path),
            "--state-dir",
            str(state_dir),
        ],
        cwd=WATCHKIT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    report = report_path.read_text(encoding="utf-8")
    assert report.count("class='card hit-card'") >= 2
