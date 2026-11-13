"""Tests for CISA KEV watcher: parse and match."""
from __future__ import annotations

from watchkit.watchers.kev import KEVWatcher
from conftest import load_fixture_json, load_fixture_text


def test_kev_parse():
    watcher = KEVWatcher()
    raw = load_fixture_text("kev_sample.json")
    items = watcher.parse(raw)

    assert len(items) == 5
    ids = [item.id for item in items]
    assert "CVE-2026-10001" in ids
    assert "CVE-2026-10002" in ids
    assert "CVE-2026-10003" in ids
    assert "CVE-2026-10004" in ids
    assert "CVE-2026-10005" in ids

    first = items[0]
    assert first.data["vendor"] == "Microsoft Corp."
    assert first.data["product"] == "Microsoft Windows 11"
    assert first.data["ransomware"] == "Known"
    assert first.date == "2026-10-28"


def test_kev_match_vendor_and_product():
    watcher = KEVWatcher()
    items = watcher.parse(load_fixture_text("kev_sample.json"))

    # Watchlist: Microsoft Windows 11, Synology all products
    watchlist = [
        {"vendor": "Microsoft", "products": ["Windows 11"]},
        {"vendor": "Synology", "products": "*"},
    ]
    hits = watcher.match(items, watchlist)
    hit_ids = {h.id for h in hits}

    assert "CVE-2026-10001" in hit_ids  # Microsoft Windows 11
    assert "CVE-2026-10002" in hit_ids  # Synology DiskStation Manager
    assert "CVE-2026-10003" not in hit_ids  # Adobe Inc
    assert "CVE-2026-10004" not in hit_ids  # Micro (should not match Microsoft)
    assert "CVE-2026-10005" not in hit_ids  # Unwatched Vendor


def test_kev_match_no_partial_vendor_confusion():
    """Ensure 'Micro' vendor rule does not match 'Microsoft Corp.' and vice versa."""
    watcher = KEVWatcher()
    items = watcher.parse(load_fixture_text("kev_sample.json"))

    watchlist = [{"vendor": "Micro", "products": "*"}]
    hits = watcher.match(items, watchlist)
    hit_ids = {h.id for h in hits}

    assert "CVE-2026-10004" in hit_ids  # Vendor is Micro
    assert "CVE-2026-10001" not in hit_ids  # Vendor is Microsoft Corp.


def test_kev_match_text_format():
    watcher = KEVWatcher()
    items = watcher.parse(load_fixture_text("kev_sample.json"))

    text_watchlist = [
        "Microsoft: Windows 11",
        "Synology",
    ]
    hits = watcher.match(items, text_watchlist)
    hit_ids = {h.id for h in hits}

    assert "CVE-2026-10001" in hit_ids
    assert "CVE-2026-10002" in hit_ids
    assert len(hits) == 2
