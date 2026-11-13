"""Tests for the watchkit CLI end-to-end and failure handling."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from watchkit.cli import main
from conftest import FIXTURES_DIR


def test_cli_offline_run_end_to_end_kev(tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    fixture_path = FIXTURES_DIR / "kev_sample.json"
    watchlist_path = tmp_path / "wl.txt"
    watchlist_path.write_text("Microsoft: Windows 11\nSynology\n", encoding="utf-8")

    out_report = tmp_path / "report.html"
    state_dir = tmp_path / ".watchkit"

    argv = [
        "run",
        "kev",
        "--offline",
        str(fixture_path),
        "--watchlist",
        str(watchlist_path),
        "--out",
        str(out_report),
        "--state-dir",
        str(state_dir),
    ]

    ret = main(argv)
    assert ret == 0

    assert out_report.is_file()
    html_content = out_report.read_text(encoding="utf-8")
    assert "CVE-2026-10001" in html_content
    assert "CVE-2026-10002" in html_content

    # Non-matching item should not be in hits section
    hits_section = html_content.split("監控命中清單 (Watchlist Hits)")[1].split("與前次狀態差異 (Diff Summary)")[0]
    assert "CVE-2026-10005" not in hits_section

    # State dir snapshot check
    snapshot_path = state_dir / "kev_snapshot.json"
    assert snapshot_path.is_file()


def test_cli_offline_run_end_to_end_cpsc(tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    fixture_path = FIXTURES_DIR / "cpsc_sample.json"
    watchlist_path = tmp_path / "wl.json"
    watchlist_path.write_text('[{"products": ["power bank"], "manufacturers": ["China"]}]', encoding="utf-8")

    out_report = tmp_path / "cpsc_report.html"
    state_dir = tmp_path / ".watchkit"

    argv = [
        "run",
        "cpsc_recalls",
        "--offline",
        str(fixture_path),
        "--watchlist",
        str(watchlist_path),
        "--out",
        str(out_report),
        "--state-dir",
        str(state_dir),
    ]

    ret = main(argv)
    assert ret == 0

    assert out_report.is_file()
    html_content = out_report.read_text(encoding="utf-8")
    hits_section = html_content.split("監控命中清單 (Watchlist Hits)")[1].split("與前次狀態差異 (Diff Summary)")[0]
    assert "26-001" in hits_section
    assert "26-003" not in hits_section


def test_cli_fetch_failure_keeps_previous_report(tmp_path: Path):
    """When fetch fails, exit code must be 2, and previous report must NOT be overwritten."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    out_report = tmp_path / "report.html"
    initial_content = "<!doctype html><html><body>PREVIOUS_GOOD_REPORT_CONTENTS</body></html>"
    out_report.write_text(initial_content, encoding="utf-8")

    # Offline path pointing to a non-existent file triggers a fetch error
    non_existent = tmp_path / "missing_feed.json"

    argv = [
        "run",
        "kev",
        "--offline",
        str(non_existent),
        "--out",
        str(out_report),
    ]

    ret = main(argv)
    assert ret == 2

    # The report must remain completely intact
    assert out_report.is_file()
    assert out_report.read_text(encoding="utf-8") == initial_content


def test_cli_fetch_failure_network_keeps_previous_report(tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    out_report = tmp_path / "report.html"
    initial_content = "ORIGINAL_REPORT_DATA"
    out_report.write_text(initial_content, encoding="utf-8")

    argv = [
        "run",
        "kev",
        "--out",
        str(out_report),
    ]

    with patch("urllib.request.urlopen", side_effect=OSError("Network down")):
        ret = main(argv)
        assert ret == 2

    assert out_report.read_text(encoding="utf-8") == initial_content


def test_cli_render_failure_preserves_previous_report_and_snapshot(tmp_path: Path):
    """When render_html raises, exit code must be 3, previous report and snapshot must remain unchanged, and no .part files exist."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    fixture_path = FIXTURES_DIR / "kev_sample.json"
    watchlist_path = tmp_path / "wl.txt"
    watchlist_path.write_text("Microsoft\n", encoding="utf-8")

    out_report = tmp_path / "report.html"
    initial_report_bytes = b"<html>PREVIOUS_REPORT_BYTES</html>"
    out_report.write_bytes(initial_report_bytes)

    state_dir = tmp_path / ".watchkit"
    state_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = state_dir / "kev_snapshot.json"
    initial_snapshot_bytes = b'{"version": 1, "items": [{"id": "OLD_ITEM", "title": "Old"}]}'
    snapshot_path.write_bytes(initial_snapshot_bytes)

    argv = [
        "run",
        "kev",
        "--offline",
        str(fixture_path),
        "--watchlist",
        str(watchlist_path),
        "--out",
        str(out_report),
        "--state-dir",
        str(state_dir),
    ]

    with patch("watchkit.cli.render_html", side_effect=RuntimeError("Template rendering error")):
        ret = main(argv)

    assert ret == 3
    assert out_report.read_bytes() == initial_report_bytes
    assert snapshot_path.read_bytes() == initial_snapshot_bytes

    part_files = list(tmp_path.rglob("*.part"))
    assert part_files == []


def test_cli_successful_run_leaves_no_part_files(tmp_path: Path):
    """Successful run must create report and snapshot, leaving zero .part files."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    fixture_path = FIXTURES_DIR / "kev_sample.json"

    out_report = tmp_path / "report.html"
    state_dir = tmp_path / ".watchkit"

    argv = [
        "run",
        "kev",
        "--offline",
        str(fixture_path),
        "--out",
        str(out_report),
        "--state-dir",
        str(state_dir),
    ]

    ret = main(argv)
    assert ret == 0
    assert out_report.is_file()
    assert (state_dir / "kev_snapshot.json").is_file()

    part_files = list(tmp_path.rglob("*.part"))
    assert part_files == []


def test_cli_second_run_reports_zero_new_items(tmp_path: Path, capsys):
    """Second run with the same fixture reports +0 new (snapshot persisted)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    fixture_path = FIXTURES_DIR / "kev_sample.json"

    out_report = tmp_path / "report.html"
    state_dir = tmp_path / ".watchkit"

    argv = [
        "run",
        "kev",
        "--offline",
        str(fixture_path),
        "--out",
        str(out_report),
        "--state-dir",
        str(state_dir),
        "--notify",
        "stdout",
    ]

    # First run: snapshot created, items detected as new
    ret1 = main(argv)
    assert ret1 == 0
    out1 = capsys.readouterr().out
    assert "+5 new" in out1

    # Second run: snapshot already exists, zero new items reported
    ret2 = main(argv)
    assert ret2 == 0
    out2 = capsys.readouterr().out
    assert "+0 new" in out2

    # Verify no .part files leftover after both runs
    part_files = list(tmp_path.rglob("*.part"))
    assert part_files == []
