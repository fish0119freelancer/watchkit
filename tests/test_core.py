"""Tests for core module: Source, Diff, HTML rendering, and Notifiers."""
from __future__ import annotations

from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch
import urllib.error

from watchkit.core import (
    DEFAULT_USER_AGENT,
    DiffResult,
    FetchError,
    FileNotifier,
    Hit,
    Item,
    Source,
    StdoutNotifier,
    diff_items,
    load_snapshot,
    render_html,
    save_snapshot,
)


def test_diff_items_new_changed_removed():
    item1 = Item(id="id-1", title="Original Title 1", date="2026-10-01", data={"v": 1})
    item2 = Item(id="id-2", title="Original Title 2", date="2026-10-01", data={"v": 1})
    item3 = Item(id="id-3", title="Original Title 3", date="2026-10-01", data={"v": 1})

    # Initial run: all items are new
    initial_diff = diff_items([item1, item2, item3], previous=None)
    assert len(initial_diff.new) == 3
    assert len(initial_diff.changed) == 0
    assert len(initial_diff.removed) == 0

    # Snapshot of run 1
    snapshot = [item1.to_dict(), item2.to_dict(), item3.to_dict()]

    # Run 2:
    # item1 unchanged
    # item2 modified
    item2_mod = Item(id="id-2", title="Updated Title 2", date="2026-10-02", data={"v": 2})
    # item3 removed (not in current)
    # item4 added
    item4 = Item(id="id-4", title="New Title 4", date="2026-10-02", data={"v": 1})

    current_items = [item1, item2_mod, item4]
    second_diff = diff_items(current_items, previous=snapshot)

    assert [it.id for it in second_diff.new] == ["id-4"]
    assert [it.id for it in second_diff.changed] == ["id-2"]
    assert [it["id"] for it in second_diff.removed] == ["id-3"]
    assert second_diff.total_changes == 3


def test_snapshot_save_and_load(tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    snapshot_file = tmp_path / "state" / "test_snapshot.json"
    items = [
        Item(id="A", title="Alpha", date="2026-10-20", data={"score": 100}),
        Item(id="B", title="Beta", date="2026-10-21", data={"score": 200}),
    ]
    save_snapshot(snapshot_file, items)
    assert snapshot_file.is_file()

    loaded = load_snapshot(snapshot_file)
    assert len(loaded) == 2
    assert loaded[0]["id"] == "A"
    assert loaded[1]["id"] == "B"


def test_html_escaping_and_dark_mode():
    """Ensure hits containing <script> or XSS payloads are safely escaped."""
    malicious_item = Item(
        id="CVE-2026-9999",
        title="Vulnerability with <script>alert('xss')</script> inside",
        date="2026-10-28",
        data={"payload": "<img src=x onerror=alert(1)>"},
    )
    hit = Hit(
        item=malicious_item,
        matched_rule="<script>tag</script>",
        reasons=["Reason with <b>HTML</b> and <script>attack</script>"],
        extra={"note": "<script>alert(2)</script>"},
    )

    diff = DiffResult(new=[malicious_item], changed=[], removed=[])
    html = render_html(
        title="Security Alert <script>title</script>",
        hits=[hit],
        diff=diff,
    )

    # Must contain HTML escaped forms
    assert "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" in html or "&lt;script&gt;" in html
    # Must NOT contain raw unescaped script tags
    assert "<script>" not in html
    assert "</script>" not in html
    assert "onerror=" not in html

    # Dark mode & responsive requirements
    assert 'meta name="viewport"' in html
    assert "prefers-color-scheme: dark" in html
    assert ":root" in html


def test_source_user_agent_format():
    src = Source(url="https://example.invalid/feed.json")
    assert src.user_agent.startswith("watchkit/")
    assert "(+https://github.com/fish0119freelancer/watchkit)" in src.user_agent


def test_source_retries_and_failure():
    src = Source(
        url="https://example.invalid/fail",
        max_retries=2,
        backoff_factor=0.01,
        timeout=1.0,
    )

    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")) as mock_open:
        with pytest.raises(FetchError) as exc_info:
            src.fetch()
        assert "Connection refused" in str(exc_info.value)
        # Initial attempt + 2 retries = 3 attempts total
        assert mock_open.call_count == 3


def test_source_cache_write(tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    cache_file = tmp_path / "cache" / "cached.json"
    src = Source(
        url="https://example.invalid/feed",
        cache_path=cache_file,
    )

    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"status": "ok"}'
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        content = src.fetch()
        assert content == '{"status": "ok"}'
        assert cache_file.is_file()
        assert cache_file.read_text(encoding="utf-8") == '{"status": "ok"}'


def test_notifiers(tmp_path: Path, capsys: pytest.CaptureFixture):
    stdout_notifier = StdoutNotifier()
    stdout_notifier.notify("Hello stdout")
    captured = capsys.readouterr()
    assert "Hello stdout" in captured.out

    out_file = tmp_path / "notifications" / "alerts.txt"
    file_notifier = FileNotifier(out_file)
    file_notifier.notify("Alert line 1")
    file_notifier.notify("Alert line 2")

    content = out_file.read_text(encoding="utf-8")
    assert "Alert line 1\nAlert line 2\n" == content
