#!/usr/bin/env python3
"""Apply broader review decisions to GetSongBPM key/miss CSV exports."""

from __future__ import annotations

import argparse
import collections
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apply_getsongbpm_review import (
    DEFAULT_CACHE,
    DEFAULT_KEYS,
    DEFAULT_MANIFEST,
    DEFAULT_MISSES,
    DEFAULT_NORMALIZED,
    cache_song_index,
    parse_score,
    read_csv,
    row_key,
    sort_key,
    write_csv,
)
from fetch_getsongbpm_keys import MISS_FIELDS, OUTPUT_FIELDS, Match, output_row


DEFAULT_DECISIONS = "data/review/getsongbpm_broader_decisions.jsonl"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge broader GetSongBPM review decisions.")
    parser.add_argument("--normalized", default=DEFAULT_NORMALIZED, help="Normalized songs CSV.")
    parser.add_argument("--keys", default=DEFAULT_KEYS, help="Matched key/BPM CSV to update.")
    parser.add_argument("--misses", default=DEFAULT_MISSES, help="Misses CSV to update.")
    parser.add_argument("--decisions", default=DEFAULT_DECISIONS, help="Broader review JSONL decisions.")
    parser.add_argument("--cache-dir", default=DEFAULT_CACHE, help="GetSongBPM cache directory.")
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST, help="Key matching manifest JSON to update.")
    return parser.parse_args()


def read_latest_broader(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    if not path.exists():
        return latest
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            if isinstance(record, dict):
                latest[row_key(record)] = record
    return latest


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
    decisions = list(read_latest_broader(decisions_path).values())
    song_index = cache_song_index(cache_dir)

    accepted = [row for row in decisions if row.get("decision") == "accept"]
    rejected = [row for row in decisions if row.get("decision") == "reject"]
    manual = [row for row in decisions if row.get("decision") == "manual"]
    accepted_by_key = {row_key(row): row for row in accepted}
    rejected_by_key = {row_key(row): row for row in rejected}
    manual_by_key = {row_key(row): row for row in manual}

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
        match = Match("manual_accept_broader", parse_score(decision.get("best_match_score")), song)
        merged_keys[key] = output_row(source, match)

    for decision in manual:
        key = row_key(decision)
        source = normalized_by_key.get(key)
        if not source:
            missing_sources.append(key)
            continue
        synthetic_song: dict[str, Any] = {
            "id": "",
            "title": "",
            "uri": "",
            "tempo": decision.get("manual_tempo", ""),
            "time_sig": decision.get("manual_time_sig", ""),
            "key_of": decision.get("manual_key", ""),
            "open_key": "",
            "danceability": "",
            "acousticness": "",
            "artist": {"name": ""},
        }
        match = Match("manual_entry", 1.0, synthetic_song)
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
        if key in accepted_by_key or key in manual_by_key:
            continue
        if key in rejected_by_key:
            decision = rejected_by_key[key]
            updated = dict(row)
            updated.update(
                {
                    "reason": "manual_reject_broader",
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

    manifest_payload: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest_payload = {}

    manifest_payload.update(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "normalized_rows": len(normalized_rows),
            "matched_rows": len(matched_rows),
            "miss_rows": len(misses),
            "match_statuses": dict(sorted(match_statuses.items())),
            "miss_reasons": dict(sorted(miss_reasons.items())),
            "broader_decisions": len(decisions),
            "broader_accepts": len(accepted),
            "broader_rejects": len(rejected),
            "broader_manual_entries": len(manual),
        }
    )
    manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Broader decisions: {len(decisions)}")
    print(f"Accepted into keys: {len(accepted)}")
    print(f"Manual entries into keys: {len(manual)}")
    print(f"Rejected in misses: {len(rejected)}")
    print(f"Matched rows: {len(key_rows)} -> {len(matched_rows)}")
    print(f"Miss rows: {len(miss_rows)} -> {len(misses)}")
    print(f"Coverage check: {len(matched_rows) + len(misses)} / {len(normalized_rows)}")
    print(f"Manifest: {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
