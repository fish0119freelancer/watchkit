"""Core framework: Source, Watcher protocol, Diff, HTML rendering, and Notifiers."""
from __future__ import annotations

import html
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

__version__ = "0.1.0"
DEFAULT_USER_AGENT = f"watchkit/{__version__} (+https://github.com/fish0119freelancer/watchkit)"


class FetchError(Exception):
    """Raised when fetching a data source fails after all retries."""


@dataclass
class Item:
    """A single normalized item parsed from a data source."""

    id: str
    title: str
    date: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "date": self.date,
            "data": self.data,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Item:
        return cls(
            id=str(payload.get("id", "")),
            title=str(payload.get("title", "")),
            date=str(payload.get("date", "")),
            data=dict(payload.get("data", {})),
        )


@dataclass
class Hit:
    """A matched item resulting from watchlist filtering."""

    item: Item
    matched_rule: str = ""
    reasons: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.item.id

    @property
    def title(self) -> str:
        return self.item.title

    @property
    def date(self) -> str:
        return self.item.date


@runtime_checkable
class Watcher(Protocol):
    """Protocol for public data watchers."""

    name: str

    def fetch(self, offline_path: Path | None = None) -> Any:
        ...

    def parse(self, raw: Any) -> list[Item]:
        ...

    def match(self, items: list[Item], watchlist: Any) -> list[Hit]:
        ...


@dataclass
class DiffResult:
    """Diff against a previous run's snapshot."""

    new: list[Item] = field(default_factory=list)
    changed: list[Item] = field(default_factory=list)
    removed: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total_changes(self) -> int:
        return len(self.new) + len(self.changed) + len(self.removed)


class Source:
    """Fetch remote data with caching, timeout, and bounded retries."""

    def __init__(
        self,
        url: str,
        cache_path: Path | None = None,
        timeout: float = 60.0,
        max_retries: int = 2,
        backoff_factor: float = 0.5,
        user_agent: str = DEFAULT_USER_AGENT,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.url = url
        self.cache_path = Path(cache_path) if cache_path else None
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.user_agent = user_agent
        self.headers = headers or {}

    def fetch(self, offline_path: Path | None = None) -> str:
        """Fetch remote data, or return an offline fixture when offline_path is set."""
        if offline_path is not None:
            path = Path(offline_path)
            if not path.is_file():
                raise FetchError(f"Offline fixture not found: {offline_path}")
            return path.read_text(encoding="utf-8")

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            **self.headers,
        }
        req = urllib.request.Request(self.url, headers=headers)

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    payload = resp.read().decode("utf-8")
                    if self.cache_path:
                        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                        self.cache_path.write_text(payload, encoding="utf-8")
                    return payload
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    sleep_time = self.backoff_factor * (2**attempt)
                    time.sleep(sleep_time)

        raise FetchError(
            f"Failed to fetch {self.url} after {self.max_retries + 1} attempts: {last_error}"
        ) from last_error


def diff_items(
    current: list[Item],
    previous: list[dict[str, Any]] | dict[str, Any] | None,
) -> DiffResult:
    """Compare current items against a previous run's snapshot."""
    if not previous:
        return DiffResult(new=list(current), changed=[], removed=[])

    prev_items: list[dict[str, Any]] = []
    if isinstance(previous, dict):
        prev_items = previous.get("items", [])
    elif isinstance(previous, list):
        prev_items = previous

    prev_map: dict[str, dict[str, Any]] = {
        str(it.get("id", "")): it for it in prev_items if it.get("id")
    }
    curr_map: dict[str, Item] = {it.id: it for it in current if it.id}

    new_items: list[Item] = []
    changed_items: list[Item] = []
    removed_items: list[dict[str, Any]] = []

    for item_id, item in curr_map.items():
        if item_id not in prev_map:
            new_items.append(item)
        else:
            prev_entry = prev_map[item_id]
            curr_entry = item.to_dict()
            if curr_entry != prev_entry:
                changed_items.append(item)

    for prev_id, prev_entry in prev_map.items():
        if prev_id not in curr_map:
            removed_items.append(prev_entry)

    return DiffResult(new=new_items, changed=changed_items, removed=removed_items)


def load_snapshot(path: Path | str) -> list[dict[str, Any]]:
    """Load items from a state snapshot JSON file."""
    p = Path(path)
    if not p.is_file():
        return []
    try:
        content = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(content, dict):
            return content.get("items", [])
        if isinstance(content, list):
            return content
    except Exception:
        return []
    return []


def save_snapshot(path: Path | str, items: list[Item]) -> None:
    """Save items snapshot into a state JSON file atomically."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "count": len(items),
        "items": [item.to_dict() for item in items],
    }
    part_path = p.with_name(f"{p.name}.part")
    try:
        part_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(part_path, p)
    finally:
        if part_path.exists():
            try:
                part_path.unlink()
            except OSError:
                pass


def load_watchlist_file(path: Path | str) -> list[Any]:
    """Load a watchlist from either JSON or newline-delimited text."""
    p = Path(path)
    if not p.is_file():
        return []
    raw = p.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    if raw.startswith("[") or raw.startswith("{"):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                if "watchlist" in parsed and isinstance(parsed["watchlist"], list):
                    return parsed["watchlist"]
                return [parsed]
        except json.JSONDecodeError:
            pass

    lines: list[str] = []
    for line in raw.splitlines():
        cleaned = line.split("#", 1)[0].strip()
        if cleaned:
            lines.append(cleaned)
    return lines


def render_html(
    title: str,
    hits: list[Hit],
    diff: DiffResult | None = None,
    generated_at: str | None = None,
) -> str:
    """Render a self-contained HTML report with dark mode and zero external JS."""
    gen_time = generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    diff_res = diff or DiffResult()

    cards_html = []
    if hits:
        for hit in hits:
            reasons_html = "".join(f"<li>{html.escape(r)}</li>" for r in hit.reasons)
            reasons_block = f"<ul class='reasons'>{reasons_html}</ul>" if reasons_html else ""
            rule_badge = (
                f"<span class='badge badge-rule'>{html.escape(hit.matched_rule)}</span>"
                if hit.matched_rule
                else ""
            )
            date_line = f"<span class='meta-date'>{html.escape(hit.date)}</span>" if hit.date else ""

            extra_rows = []
            for k, v in hit.extra.items():
                if v and not isinstance(v, (dict, list)):
                    extra_rows.append(
                        f"<div><span class='prop-name'>{html.escape(k)}:</span> "
                        f"<span class='prop-val'>{html.escape(str(v))}</span></div>"
                    )
            extra_block = (
                f"<div class='extra-props'>{''.join(extra_rows)}</div>" if extra_rows else ""
            )

            cards_html.append(
                f"<article class='card hit-card'>"
                f"<div class='card-header'>"
                f"<span class='hit-id'>{html.escape(hit.id)}</span> {rule_badge} {date_line}"
                f"</div>"
                f"<h3 class='hit-title'>{html.escape(hit.title)}</h3>"
                f"{reasons_block}"
                f"{extra_block}"
                f"</article>"
            )
    else:
        cards_html.append("<div class='empty-card'>無命中項目 (No matching items)</div>")

    diff_html = []
    if diff_res.new:
        diff_items_str = "".join(
            f"<li><b>{html.escape(it.id)}</b>: {html.escape(it.title)}</li>" for it in diff_res.new[:10]
        )
        more = f"<li>... 其餘 {len(diff_res.new) - 10} 筆</li>" if len(diff_res.new) > 10 else ""
        diff_html.append(
            f"<div class='diff-block diff-new'>"
            f"<h4>新增項目 (+{len(diff_res.new)})</h4>"
            f"<ul>{diff_items_str}{more}</ul>"
            f"</div>"
        )
    if diff_res.changed:
        diff_items_str = "".join(
            f"<li><b>{html.escape(it.id)}</b>: {html.escape(it.title)}</li>"
            for it in diff_res.changed[:10]
        )
        more = (
            f"<li>... 其餘 {len(diff_res.changed) - 10} 筆</li>"
            if len(diff_res.changed) > 10
            else ""
        )
        diff_html.append(
            f"<div class='diff-block diff-changed'>"
            f"<h4>變更項目 (~{len(diff_res.changed)})</h4>"
            f"<ul>{diff_items_str}{more}</ul>"
            f"</div>"
        )
    if diff_res.removed:
        diff_items_str = "".join(
            f"<li><b>{html.escape(str(it.get('id', '')))}</b>: {html.escape(str(it.get('title', '')))}</li>"
            for it in diff_res.removed[:10]
        )
        more = (
            f"<li>... 其餘 {len(diff_res.removed) - 10} 筆</li>"
            if len(diff_res.removed) > 10
            else ""
        )
        diff_html.append(
            f"<div class='diff-block diff-removed'>"
            f"<h4>移除項目 (-{len(diff_res.removed)})</h4>"
            f"<ul>{diff_items_str}{more}</ul>"
            f"</div>"
        )
    if not diff_html:
        diff_html.append("<div class='empty-card'>無差異變更 (No state changes)</div>")

    return f"""<!doctype html>
<html lang="zh-TW">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --bg: #f8fafc;
      --card-bg: #ffffff;
      --text: #0f172a;
      --muted: #64748b;
      --border: #e2e8f0;
      --accent: #2563eb;
      --tag-bg: #eff6ff;
      --tag-text: #1d4ed8;
      --badge-new: #16a34a;
      --badge-changed: #d97706;
      --badge-removed: #dc2626;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg: #0f172a;
        --card-bg: #1e293b;
        --text: #f8fafc;
        --muted: #94a3b8;
        --border: #334155;
        --accent: #38bdf8;
        --tag-bg: #1e3a8a;
        --tag-text: #bfdbfe;
        --badge-new: #22c55e;
        --badge-changed: #f59e0b;
        --badge-removed: #ef4444;
      }}
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      line-height: 1.6;
    }}
    .container {{
      max-width: 960px;
      margin: 0 auto;
      padding: 24px 16px 64px;
    }}
    header {{
      margin-bottom: 24px;
      border-bottom: 1px solid var(--border);
      padding-bottom: 16px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 1.8rem;
    }}
    .meta {{
      color: var(--muted);
      font-size: 0.9rem;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-bottom: 28px;
    }}
    .metric-card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 14px;
      text-align: center;
    }}
    .metric-value {{
      font-size: 1.8rem;
      font-weight: 700;
      color: var(--accent);
      line-height: 1.2;
    }}
    .metric-label {{
      color: var(--muted);
      font-size: 0.85rem;
      margin-top: 4px;
    }}
    h2 {{
      margin: 32px 0 16px;
      font-size: 1.3rem;
      border-bottom: 2px solid var(--border);
      padding-bottom: 6px;
    }}
    .card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
      margin-bottom: 14px;
    }}
    .hit-card {{
      border-left: 4px solid var(--accent);
    }}
    .card-header {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
      margin-bottom: 6px;
    }}
    .hit-id {{
      font-weight: 700;
      font-family: monospace;
      font-size: 0.95rem;
    }}
    .meta-date {{
      color: var(--muted);
      font-size: 0.85rem;
      margin-left: auto;
    }}
    .hit-title {{
      margin: 6px 0 10px;
      font-size: 1.1rem;
    }}
    .badge {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 4px;
      font-size: 0.75rem;
      font-weight: 600;
    }}
    .badge-rule {{
      background: var(--tag-bg);
      color: var(--tag-text);
    }}
    .reasons {{
      margin: 8px 0;
      padding-left: 20px;
      font-size: 0.9rem;
    }}
    .extra-props {{
      margin-top: 10px;
      padding-top: 10px;
      border-top: 1px dashed var(--border);
      font-size: 0.85rem;
      display: grid;
      gap: 4px;
    }}
    .prop-name {{
      font-weight: 600;
      color: var(--muted);
    }}
    .empty-card {{
      background: var(--card-bg);
      border: 1px dashed var(--border);
      border-radius: 8px;
      padding: 24px;
      text-align: center;
      color: var(--muted);
    }}
    .diff-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 12px;
    }}
    .diff-block {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 14px;
    }}
    .diff-block h4 {{
      margin: 0 0 8px;
      font-size: 0.95rem;
    }}
    .diff-new h4 {{ color: var(--badge-new); }}
    .diff-changed h4 {{ color: var(--badge-changed); }}
    .diff-removed h4 {{ color: var(--badge-removed); }}
    .diff-block ul {{
      margin: 0;
      padding-left: 18px;
      font-size: 0.85rem;
    }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>{html.escape(title)}</h1>
      <div class="meta">產出時間：{html.escape(gen_time)}</div>
    </header>

    <section class="metrics">
      <div class="metric-card">
        <div class="metric-value">{len(hits)}</div>
        <div class="metric-label">命中項目 (Hits)</div>
      </div>
      <div class="metric-card">
        <div class="metric-value">{len(diff_res.new)}</div>
        <div class="metric-label">新發現 (New)</div>
      </div>
      <div class="metric-card">
        <div class="metric-value">{len(diff_res.changed)}</div>
        <div class="metric-label">變更 (Changed)</div>
      </div>
      <div class="metric-card">
        <div class="metric-value">{len(diff_res.removed)}</div>
        <div class="metric-label">移除 (Removed)</div>
      </div>
    </section>

    <section>
      <h2>監控命中清單 (Watchlist Hits)</h2>
      {"".join(cards_html)}
    </section>

    <section>
      <h2>與前次狀態差異 (Diff Summary)</h2>
      <div class="diff-grid">
        {"".join(diff_html)}
      </div>
    </section>
  </div>
</body>
</html>"""


@runtime_checkable
class Notifier(Protocol):
    """Notifier protocol for dispatching summary alerts."""

    def notify(self, message: str, **kwargs: Any) -> None:
        ...


class StdoutNotifier:
    """Print notifications to standard output."""

    def notify(self, message: str, **kwargs: Any) -> None:
        print(message)


class FileNotifier:
    """Append notifications to a designated file."""

    def __init__(self, output_path: Path | str) -> None:
        self.output_path = Path(output_path)

    def notify(self, message: str, **kwargs: Any) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with self.output_path.open("a", encoding="utf-8") as f:
            f.write(message.rstrip("\r\n") + "\n")
