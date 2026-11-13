"""Built-in watchers for public data sources."""
from __future__ import annotations

from watchkit.watchers.cpsc_recalls import CPSCRecallWatcher
from watchkit.watchers.kev import KEVWatcher

__all__ = ["KEVWatcher", "CPSCRecallWatcher"]
