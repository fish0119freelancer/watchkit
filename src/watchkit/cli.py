"""Command-line interface for watchkit."""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from watchkit.core import (
    FileNotifier,
    StdoutNotifier,
    diff_items,
    load_snapshot,
    load_watchlist_file,
    render_html,
    save_snapshot,
)
from watchkit.watchers.cpsc_recalls import CPSCRecallWatcher
from watchkit.watchers.kev import KEVWatcher

WATCHER_REGISTRY = {
    "kev": KEVWatcher,
    "cpsc_recalls": CPSCRecallWatcher,
    "cpsc": CPSCRecallWatcher,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="watchkit",
        description="Public data watch -> daily HTML report framework",
    )
    subparsers = parser.add_subparsers(dest="command", help="Subcommand to execute")

    run_parser = subparsers.add_parser("run", help="Run a watcher and generate an HTML report")
    run_parser.add_argument(
        "watcher",
        choices=["kev", "cpsc_recalls", "cpsc"],
        help="Name of the watcher to run (e.g. kev, cpsc_recalls)",
    )
    run_parser.add_argument(
        "--watchlist",
        type=Path,
        default=None,
        help="Path to watchlist file (.json or .txt with keywords)",
    )
    run_parser.add_argument(
        "--out",
        type=Path,
        default=Path("report.html"),
        help="Output HTML report path (default: report.html)",
    )
    run_parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path(".watchkit"),
        help="Directory to persist state snapshots (default: .watchkit)",
    )
    run_parser.add_argument(
        "--offline",
        type=Path,
        default=None,
        help="Path to offline JSON fixture (bypasses network for tests/demos)",
    )
    run_parser.add_argument(
        "--notify",
        choices=["stdout", "file", "none"],
        default="stdout",
        help="Notification mode (stdout, file, none; default: stdout)",
    )
    run_parser.add_argument(
        "--notify-file",
        type=Path,
        default=Path("notifications.txt"),
        help="File path when --notify=file is selected",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    if args.command == "run":
        watcher_cls = WATCHER_REGISTRY.get(args.watcher)
        if not watcher_cls:
            sys.stderr.write(f"Unknown watcher: {args.watcher}\n")
            return 1

        watcher = watcher_cls()

        # Step 1: Fetch data (DO NOT open/touch output report before fetch succeeds)
        try:
            raw = watcher.fetch(offline_path=args.offline)
        except Exception as exc:
            sys.stderr.write(f"Fetch failure: {exc}\n")
            return 2

        # Step 2: Parse items
        try:
            items = watcher.parse(raw)
        except Exception as exc:
            sys.stderr.write(f"Parse failure: {exc}\n")
            return 1

        # Step 3: Match against watchlist if provided
        watchlist_rules = []
        if args.watchlist:
            if not args.watchlist.is_file():
                sys.stderr.write(f"Watchlist file not found: {args.watchlist}\n")
                return 1
            watchlist_rules = load_watchlist_file(args.watchlist)

        hits = watcher.match(items, watchlist_rules)

        # Step 4: Diff against snapshot in state-dir
        canonical_name = "cpsc_recalls" if args.watcher == "cpsc" else args.watcher
        state_dir = Path(args.state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = state_dir / f"{canonical_name}_snapshot.json"

        previous_items = load_snapshot(snapshot_path)
        diff = diff_items(items, previous_items)

        out_path = Path(args.out)
        out_part = out_path.with_name(f"{out_path.name}.part")
        snapshot_part = snapshot_path.with_name(f"{snapshot_path.name}.part")

        try:
            # Step 5: Render HTML report
            generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            report_title = f"Watchkit Daily Report - {canonical_name.upper()}"
            html_report = render_html(
                title=report_title,
                hits=hits,
                diff=diff,
                generated_at=generated_at,
            )

            # Step 6: Write output report atomically
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_part.write_text(html_report, encoding="utf-8")
            os.replace(out_part, out_path)

            # Step 7: Save snapshot atomically
            save_snapshot(snapshot_path, items)
        except Exception as exc:
            if out_part.exists():
                try:
                    out_part.unlink()
                except OSError:
                    pass
            if snapshot_part.exists():
                try:
                    snapshot_part.unlink()
                except OSError:
                    pass
            sys.stderr.write(f"Render/write failure: {exc}\n")
            return 3

        # Step 8: Notify
        summary_msg = (
            f"watchkit [{canonical_name}]: {len(hits)} hits, "
            f"+{len(diff.new)} new, ~{len(diff.changed)} changed, "
            f"-{len(diff.removed)} removed -> {out_path}"
        )
        if args.notify == "stdout":
            StdoutNotifier().notify(summary_msg)
        elif args.notify == "file":
            FileNotifier(args.notify_file).notify(summary_msg)

        return 0

    return 0
