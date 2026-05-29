#!/usr/bin/env python3
"""Promote agent-staged decisions from the pending JSONL into the main decisions log.

Pending entries are written by review agents in candidate-only mode. After a
human verifies them via scripts/view_pending_decisions.py, this script appends them
into data/review/getsongbpm_broader_decisions.jsonl. Entries that already
exist in the main log (same source_position + video_id) are skipped.

By default the pending file is left intact so it can be inspected post-merge.
Pass --clear to truncate it once the merge succeeds, or --only to merge a
specific subset.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import sys
from pathlib import Path


DEFAULT_PENDING = "data/review/getsongbpm_broader_pending_decisions.jsonl"
DEFAULT_MAIN = "data/review/getsongbpm_broader_decisions.jsonl"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge pending decisions into the main log.")
    parser.add_argument("--pending", default=DEFAULT_PENDING, help="Pending JSONL (source).")
    parser.add_argument("--main", default=DEFAULT_MAIN, help="Main decisions JSONL (destination).")
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="Restrict merge to specific 'source_position:video_id' keys (repeatable).",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Exclude specific 'source_position:video_id' keys from merge (repeatable).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be merged without writing.",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Truncate the pending file after a successful merge.",
    )
    return parser.parse_args()


def load_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                out.append(record)
    return out


def keyset(records: list[dict]) -> set[tuple[str, str]]:
    return {(str(r.get("source_position", "")), str(r.get("video_id", ""))) for r in records}


def parse_key_filter(values: list[str]) -> set[tuple[str, str]]:
    parsed: set[tuple[str, str]] = set()
    for item in values:
        if ":" not in item:
            sys.stderr.write(f"Skipping bad --only/--exclude value (need 'pos:vid'): {item}\n")
            continue
        pos, vid = item.split(":", 1)
        parsed.add((pos.strip(), vid.strip()))
    return parsed


def append_locked(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            for line in lines:
                handle.write(line)
                if not line.endswith("\n"):
                    handle.write("\n")
            handle.flush()
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def main() -> int:
    args = parse_args()
    pending_path = Path(args.pending).expanduser()
    main_path = Path(args.main).expanduser()

    pending = load_records(pending_path)
    main_records = load_records(main_path)
    already = keyset(main_records)

    only = parse_key_filter(args.only)
    exclude = parse_key_filter(args.exclude)

    to_merge: list[dict] = []
    skipped_duplicate = 0
    skipped_filter = 0
    for record in pending:
        key = (str(record.get("source_position", "")), str(record.get("video_id", "")))
        if only and key not in only:
            skipped_filter += 1
            continue
        if key in exclude:
            skipped_filter += 1
            continue
        if key in already:
            skipped_duplicate += 1
            continue
        to_merge.append(record)
        already.add(key)

    print(f"Pending records:    {len(pending)}")
    print(f"Already in main:    {skipped_duplicate}")
    print(f"Filtered out:       {skipped_filter}")
    print(f"To merge:           {len(to_merge)}")

    if args.dry_run:
        for record in to_merge[:5]:
            print(
                f"  + [{record.get('source_position')}] "
                f"{record.get('normalized_artists', '')} - {record.get('normalized_title', '')} "
                f"→ {record.get('decision')}"
            )
        if len(to_merge) > 5:
            print(f"  ... and {len(to_merge) - 5} more")
        return 0

    if to_merge:
        lines = [json.dumps(record, ensure_ascii=False, sort_keys=True) for record in to_merge]
        append_locked(main_path, lines)

    if args.clear:
        pending_path.write_text("", encoding="utf-8")
        print("Pending file truncated.")

    print(f"Merged {len(to_merge)} records into {args.main}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
