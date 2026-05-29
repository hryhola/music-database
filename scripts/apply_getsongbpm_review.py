#!/usr/bin/env python3
"""Apply manual GetSongBPM review decisions to key/miss CSV exports."""

from __future__ import annotations

import argparse
import collections
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fetch_getsongbpm_keys import MISS_FIELDS, OUTPUT_FIELDS, Match, output_row


DEFAULT_NORMALIZED = "data/source/normalized_liked_songs.csv"
DEFAULT_KEYS = "data/work/getsongbpm_matches.csv"
DEFAULT_MISSES = "data/work/getsongbpm_misses.csv"
DEFAULT_DECISIONS = "data/review/getsongbpm_initial_review_decisions.jsonl"
DEFAULT_CACHE = ".cache/getsongbpm"
DEFAULT_MANIFEST = "data/work/key_matching_manifest.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge manual GetSongBPM review decisions.")
    parser.add_argument("--normalized", default=DEFAULT_NORMALIZED, help="Normalized songs CSV.")
    parser.add_argument("--keys", default=DEFAULT_KEYS, help="Matched key/BPM CSV to update.")
    parser.add_argument("--misses", default=DEFAULT_MISSES, help="Misses CSV to update.")
    parser.add_argument("--decisions", default=DEFAULT_DECISIONS, help="Manual review JSONL decisions.")
    parser.add_argument("--cache-dir", default=DEFAULT_CACHE, help="GetSongBPM response cache directory.")
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST, help="Key matching manifest JSON to update.")
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def row_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("source_position", "")), str(row.get("video_id", "")))


def review_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (*row_key(row), str(row.get("best_match_id", "")))


def sort_key(row: dict[str, Any]) -> tuple[int, str]:
    try:
        position = int(str(row.get("source_position", "0")))
    except ValueError:
        position = 0
    return (position, str(row.get("video_id", "")))


def read_latest_decisions(path: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    latest: dict[tuple[str, str, str], dict[str, Any]] = {}
    if not path.exists():
        return latest
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            if isinstance(record, dict):
                latest[review_key(record)] = record
    return latest


def cache_song_index(cache_dir: Path) -> dict[str, dict[str, Any]]:
    songs: dict[str, dict[str, Any]] = {}
    for path in cache_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        search = payload.get("search", [])
        if isinstance(search, dict):
            search = [search]
        for song in search:
            if isinstance(song, dict) and song.get("id"):
                songs.setdefault(str(song["id"]), song)
    return songs


def parse_score(value: object) -> float:
    try:
        return float(str(value or "0"))
    except ValueError:
        return 0.0


def main() -> int:
    args = parse_args()
    normalized_path = Path(args.normalized)
    keys_path = Path(args.keys)
    misses_path = Path(args.misses)
    decisions_path = Path(args.decisions)
    cache_dir = Path(args.cache_dir)
    manifest_path = Path(args.manifest)

    normalized_rows = read_csv(normalized_path)
    normalized_by_key = {row_key(row): row for row in normalized_rows}
    key_rows = read_csv(keys_path)
    miss_rows = read_csv(misses_path)
    decisions = list(read_latest_decisions(decisions_path).values())
    song_index = cache_song_index(cache_dir)

    accepted = [row for row in decisions if row.get("decision") == "accept"]
    rejected = [row for row in decisions if row.get("decision") == "reject"]
    accepted_by_key = {row_key(row): row for row in accepted}
    rejected_by_key = {row_key(row): row for row in rejected}

    merged_keys = {row_key(row): row for row in key_rows}
    missing_sources: list[tuple[str, str]] = []
    missing_songs: list[str] = []

    for decision in accepted:
        key = row_key(decision)
        source = normalized_by_key.get(key)
        if not source:
            missing_sources.append(key)
            continue
        song_id = str(decision.get("best_match_id", ""))
        song = song_index.get(song_id)
        if not song:
            missing_songs.append(song_id)
            continue
        match = Match("manual_accept", parse_score(decision.get("best_match_score")), song)
        merged_keys[key] = output_row(source, match)

    if missing_sources or missing_songs:
        if missing_sources:
            print(f"Missing normalized source rows: {missing_sources[:5]}")
        if missing_songs:
            print(f"Missing cached GetSongBPM songs: {missing_songs[:5]}")
        raise SystemExit(1)

    merged_misses: list[dict[str, Any]] = []
    for row in miss_rows:
        key = row_key(row)
        if key in accepted_by_key:
            continue
        if key in rejected_by_key:
            decision = rejected_by_key[key]
            updated = dict(row)
            updated.update(
                {
                    "reason": "manual_reject",
                    "best_match_score": decision.get("best_match_score", row.get("best_match_score", "")),
                    "best_match_title": decision.get("best_match_title", row.get("best_match_title", "")),
                    "best_match_artist": decision.get("best_match_artist", row.get("best_match_artist", "")),
                    "best_match_id": decision.get("best_match_id", row.get("best_match_id", "")),
                }
            )
            merged_misses.append(updated)
        else:
            merged_misses.append(row)

    matched_rows = sorted(merged_keys.values(), key=sort_key)
    misses = sorted(merged_misses, key=sort_key)
    write_csv(keys_path, OUTPUT_FIELDS, matched_rows)
    write_csv(misses_path, MISS_FIELDS, misses)
    match_statuses = collections.Counter(row.get("match_status", "") for row in matched_rows)
    miss_reasons = collections.Counter(row.get("reason", "") for row in misses)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "normalized_rows": len(normalized_rows),
        "matched_rows": len(matched_rows),
        "miss_rows": len(misses),
        "match_statuses": dict(sorted(match_statuses.items())),
        "miss_reasons": dict(sorted(miss_reasons.items())),
        "manual_decisions": len(decisions),
        "manual_accepts": len(accepted),
        "manual_rejects": len(rejected),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Manual decisions: {len(decisions)}")
    print(f"Accepted into keys: {len(accepted)}")
    print(f"Rejected in misses: {len(rejected)}")
    print(f"Matched rows: {len(key_rows)} -> {len(matched_rows)}")
    print(f"Miss rows: {len(miss_rows)} -> {len(misses)}")
    print(f"Coverage check: {len(matched_rows) + len(misses)} / {len(normalized_rows)}")
    print(f"Manifest: {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
