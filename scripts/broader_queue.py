#!/usr/bin/env python3
"""Emit the broader-review queue (sources + candidates) as JSON for agent processing.

Each source object contains the normalized song metadata and up to 3 candidates
(rank-ordered). Sources that already have a recorded decision are filtered out
by default. Supports index slicing for parallel agent assignment.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path


DEFAULT_CANDIDATES = "data/review/getsongbpm_broader_candidates.csv"
DEFAULT_DECISIONS = "data/review/getsongbpm_broader_decisions.jsonl"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Emit broader review queue as JSON.")
    parser.add_argument("--candidates", default=DEFAULT_CANDIDATES, help="Broader candidates CSV.")
    parser.add_argument("--decisions", default=DEFAULT_DECISIONS, help="Decisions JSONL to filter against.")
    parser.add_argument("--start", type=int, default=None, help="Start index (inclusive, 0-based) into the unresolved queue.")
    parser.add_argument("--end", type=int, default=None, help="End index (exclusive) into the unresolved queue.")
    parser.add_argument(
        "--include-decided",
        action="store_true",
        help="Include sources that already have a recorded decision (default: filter out).",
    )
    parser.add_argument(
        "--format",
        choices=["json", "jsonl", "summary"],
        default="json",
        help="Output format. 'json' = JSON array; 'jsonl' = one object per line; 'summary' = counts only.",
    )
    return parser.parse_args()


def decided_keys(path: Path) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    if not path.exists():
        return keys
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
                keys.add((str(record.get("source_position", "")), str(record.get("video_id", ""))))
    return keys


def build_queue(candidates_path: Path) -> list[dict]:
    by_source: dict[tuple[str, str], dict] = {}
    order: list[tuple[str, str]] = []
    with candidates_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            key = (row.get("source_position", ""), row.get("video_id", ""))
            entry = by_source.get(key)
            if entry is None:
                entry = {
                    "source_position": row.get("source_position", ""),
                    "video_id": row.get("video_id", ""),
                    "video_url": row.get("video_url", ""),
                    "normalized_artists": row.get("normalized_artists", ""),
                    "normalized_title": row.get("normalized_title", ""),
                    "candidates": [],
                }
                by_source[key] = entry
                order.append(key)
            entry["candidates"].append(
                {
                    "rank": int(row.get("candidate_rank", "0") or "0"),
                    "score": float(row.get("candidate_score", "0") or "0"),
                    "variant": row.get("candidate_variant", ""),
                    "getsongbpm_song_id": row.get("getsongbpm_song_id", ""),
                    "getsongbpm_title": row.get("getsongbpm_title", ""),
                    "getsongbpm_artist": row.get("getsongbpm_artist", ""),
                    "getsongbpm_uri": row.get("getsongbpm_uri", ""),
                    "key_of": row.get("key_of", ""),
                    "mode": row.get("mode", ""),
                    "tempo": row.get("tempo", ""),
                    "time_sig": row.get("time_sig", ""),
                    "open_key": row.get("open_key", ""),
                    "danceability": row.get("danceability", ""),
                    "acousticness": row.get("acousticness", ""),
                }
            )
    for key in order:
        by_source[key]["candidates"].sort(key=lambda c: c["rank"])
    return [by_source[key] for key in order]


def main() -> int:
    args = parse_args()
    candidates_path = Path(args.candidates).expanduser()
    decisions_path = Path(args.decisions).expanduser()

    queue = build_queue(candidates_path)
    decided = decided_keys(decisions_path)

    if not args.include_decided:
        queue = [s for s in queue if (s["source_position"], s["video_id"]) not in decided]

    total = len(queue)
    start = max(0, args.start or 0)
    end = total if args.end is None else min(total, args.end)
    sliced = queue[start:end]

    if args.format == "summary":
        print(
            json.dumps(
                {
                    "queue_total": total,
                    "decided_total": len(decided),
                    "slice_start": start,
                    "slice_end": end,
                    "slice_size": len(sliced),
                },
                indent=2,
            )
        )
    elif args.format == "jsonl":
        for source in sliced:
            json.dump(source, sys.stdout, ensure_ascii=False)
            sys.stdout.write("\n")
    else:
        json.dump(sliced, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
