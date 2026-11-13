"""Tests for CPSC Recall watcher: parse, privacy, and match."""
from __future__ import annotations

from watchkit.watchers.cpsc_recalls import CPSCRecallWatcher
from conftest import load_fixture_text


def test_cpsc_parse_and_privacy():
    watcher = CPSCRecallWatcher()
    raw = load_fixture_text("cpsc_sample.json")
    items = watcher.parse(raw)

    assert len(items) == 4
    ids = [item.id for item in items]
    assert "26-001" in ids
    assert "26-002" in ids
    assert "26-003" in ids
    assert "26-004" in ids

    # Check privacy: ConsumerContact and narrative injuries must not leak
    for item in items:
        assert "ConsumerContact" not in item.data
        assert "@" not in str(item.data)
        assert "A named consumer" not in str(item.data)


def test_cpsc_match_product_and_manufacturer():
    watcher = CPSCRecallWatcher()
    items = watcher.parse(load_fixture_text("cpsc_sample.json"))

    # Watchlist: power bank / charger from China
    watchlist = [
        {"products": ["power bank", "charger"], "manufacturers": ["China"]},
    ]
    hits = watcher.match(items, watchlist)
    hit_ids = {h.id for h in hits}

    assert "26-001" in hit_ids
    assert "26-002" not in hit_ids
    assert "26-003" not in hit_ids
    assert "26-004" not in hit_ids


def test_cpsc_match_text_format():
    watcher = CPSCRecallWatcher()
    items = watcher.parse(load_fixture_text("cpsc_sample.json"))

    text_watchlist = [
        "product: toy | manufacturer: Vietnam",
        "lamp",
    ]
    hits = watcher.match(items, text_watchlist)
    hit_ids = {h.id for h in hits}

    assert "26-002" in hit_ids  # toy blocks from Vietnam
    assert "26-003" in hit_ids  # desk lamp
    assert "26-001" not in hit_ids
    assert "26-004" not in hit_ids
