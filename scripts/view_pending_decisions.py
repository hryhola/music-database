#!/usr/bin/env python3
"""Render a pending agent-decisions JSONL as a verifiable table.

The pending file is the staging area written by review agents in candidate-only
mode. This script joins each decision against the broader candidates CSV so a
human can sanity-check what the agent accepted before merging into the main
decisions log.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path


DEFAULT_PENDING = "data/review/getsongbpm_broader_pending_decisions.jsonl"
DEFAULT_CANDIDATES = "data/review/getsongbpm_broader_candidates.csv"
DEFAULT_CSV_OUT = "data/review/getsongbpm_broader_pending_decisions.csv"


CSV_FIELDS = [
    "source_position",
    "video_id",
    "decision",
    "candidate_rank",
    "source_label",
    "normalized_artists",
    "normalized_title",
    "best_match_artist",
    "best_match_title",
    "best_match_score",
    "manual_key",
    "manual_tempo",
    "manual_time_sig",
    "notes",
    "reviewed_at",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect pending agent decisions.")
    parser.add_argument("--pending", default=DEFAULT_PENDING, help="Pending decisions JSONL.")
    parser.add_argument("--candidates", default=DEFAULT_CANDIDATES, help="Candidates CSV for context.")
    parser.add_argument(
        "--format",
        choices=["table", "csv", "summary"],
        default="table",
        help="table = aligned text; csv = write CSV to --csv-out; summary = counts only.",
    )
    parser.add_argument("--csv-out", default=DEFAULT_CSV_OUT, help="Output CSV path when --format=csv.")
    parser.add_argument("--filter-label", default=None, help="Show only decisions with this source_label.")
    return parser.parse_args()


def load_decisions(path: Path) -> list[dict]:
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


def load_candidate_index(path: Path) -> dict[tuple[str, str, str], dict]:
    index: dict[tuple[str, str, str], dict] = {}
    if not path.exists():
        return index
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            key = (
                row.get("source_position", ""),
                row.get("video_id", ""),
                str(row.get("candidate_rank", "")),
            )
            index[key] = row
    return index


def truncate(value: str, width: int) -> str:
    value = value or ""
    if len(value) <= width:
        return value
    return value[: max(0, width - 1)] + "…"


def render_table(records: list[dict]) -> None:
    columns = [
        ("pos", 5),
        ("video_id", 11),
        ("dec", 7),
        ("rank", 4),
        ("agent", 8),
        ("artist", 26),
        ("title", 34),
        ("match_artist", 26),
        ("match_title", 26),
        ("key", 8),
        ("bpm", 5),
        ("score", 6),
        ("notes", 30),
    ]
    header = " | ".join(f"{name:<{width}}" for name, width in columns)
    print(header)
    print("-" * len(header))
    for record in records:
        manual_key = record.get("manual_key", "") or ""
        manual_bpm = record.get("manual_tempo", "") or ""
        if record.get("decision") == "accept":
            match_key = "(via candidate)"
            match_bpm = "(via candidate)"
        else:
            match_key = manual_key
            match_bpm = manual_bpm
        row = [
            truncate(str(record.get("source_position", "")), columns[0][1]),
            truncate(str(record.get("video_id", "")), columns[1][1]),
            truncate(str(record.get("decision", "")), columns[2][1]),
            truncate(str(record.get("candidate_rank", "") or ""), columns[3][1]),
            truncate(str(record.get("source_label", "") or ""), columns[4][1]),
            truncate(record.get("normalized_artists", ""), columns[5][1]),
            truncate(record.get("normalized_title", ""), columns[6][1]),
            truncate(record.get("best_match_artist", ""), columns[7][1]),
            truncate(record.get("best_match_title", ""), columns[8][1]),
            truncate(match_key, columns[9][1]),
            truncate(match_bpm, columns[10][1]),
            truncate(str(record.get("best_match_score", "") or ""), columns[11][1]),
            truncate(record.get("notes", ""), columns[12][1]),
        ]
        print(" | ".join(f"{value:<{width}}" for value, (_, width) in zip(row, columns)))


def render_csv(records: list[dict], candidates: dict[tuple[str, str, str], dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for record in records:
            writer.writerow({field: record.get(field, "") for field in CSV_FIELDS})


def render_summary(records: list[dict]) -> None:
    print(f"Pending decisions: {len(records)}")
    print(f"By decision: {dict(Counter(r.get('decision', '') for r in records))}")
    print(f"By source_label: {dict(Counter(r.get('source_label', '') or '(none)' for r in records))}")
    if records:
        manuals = [r for r in records if r.get('decision') == 'manual']
        if manuals:
            keys = Counter((r.get('manual_key', '') or '').split()[0] if r.get('manual_key') else '' for r in manuals)
            print(f"Manual key prefixes (top 8): {dict(keys.most_common(8))}")


def main() -> int:
    args = parse_args()
    records = load_decisions(Path(args.pending).expanduser())
    if args.filter_label:
        records = [r for r in records if r.get("source_label") == args.filter_label]

    if args.format == "summary":
        render_summary(records)
        return 0

    candidates = load_candidate_index(Path(args.candidates).expanduser())

    if args.format == "csv":
        render_csv(records, candidates, Path(args.csv_out).expanduser())
        print(f"Wrote {len(records)} rows to {args.csv_out}")
        return 0

    render_table(records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
