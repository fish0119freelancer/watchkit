"""watchkit: Public data watch -> daily HTML report framework."""
from __future__ import annotations

__version__ = "0.1.0"

from watchkit.core import (
    DiffResult,
    FetchError,
    FileNotifier,
    Hit,
    Item,
    Notifier,
    Source,
    StdoutNotifier,
    Watcher,
    diff_items,
    load_snapshot,
    load_watchlist_file,
    render_html,
    save_snapshot,
)

__all__ = [
    "__version__",
    "DiffResult",
    "FetchError",
    "FileNotifier",
    "Hit",
    "Item",
    "Notifier",
    "Source",
    "StdoutNotifier",
    "Watcher",
    "diff_items",
    "load_snapshot",
    "load_watchlist_file",
    "render_html",
    "save_snapshot",
]
