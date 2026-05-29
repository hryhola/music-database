#!/usr/bin/env python3
"""Build the published one-file music catalog from pipeline outputs."""

from __future__ import annotations

import argparse
import collections
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_SOURCE = "data/source/normalized_liked_songs.csv"
DEFAULT_KEYS = "data/work/getsongbpm_matches.csv"
DEFAULT_MISSES = "data/work/getsongbpm_misses.csv"
DEFAULT_OUTPUT = "public/data/music_catalog.csv"
DEFAULT_MANIFEST = "public/data/music_catalog_manifest.json"

CATALOG_FIELDS = [
    "source_position",
    "video_id",
    "video_url",
    "normalized_artists",
    "normalized_title",
    "original_artists",
    "original_title",
    "album",
    "duration_seconds",
    "key_of",
    "mode",
    "tempo",
    "time_sig",
    "open_key",
    "match_status",
    "match_score",
    "match_reason",
    "metadata_source",
    "getsongbpm_song_id",
    "getsongbpm_title",
    "getsongbpm_artist",
    "getsongbpm_uri",
    "danceability",
    "acousticness",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build public/data/music_catalog.csv.")
    parser.add_argument("--source", default=DEFAULT_SOURCE, help="Normalized all-songs source CSV.")
    parser.add_argument("--keys", default=DEFAULT_KEYS, help="Matched key/BPM CSV.")
    parser.add_argument("--misses", default=DEFAULT_MISSES, help="Unmatched/missed rows CSV.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Public catalog CSV output.")
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST, help="Public manifest JSON output.")
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CATALOG_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def row_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("source_position", "")), str(row.get("video_id", "")))


def sort_key(row: dict[str, Any]) -> tuple[int, str]:
    try:
        position = int(str(row.get("source_position", "0")))
    except ValueError:
        position = 0
    return (position, str(row.get("video_id", "")))


def metadata_source(match_status: str) -> str:
    if match_status == "manual_entry":
        return "manual"
    if match_status:
        return "GetSongBPM"
    return ""


def build_catalog(
    source_rows: list[dict[str, str]],
    key_rows: list[dict[str, str]],
    miss_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    keys_by_id = {row_key(row): row for row in key_rows}
    misses_by_id = {row_key(row): row for row in miss_rows}
    catalog: list[dict[str, str]] = []

    for source in sorted(source_rows, key=sort_key):
        key = row_key(source)
        matched = keys_by_id.get(key)
        missed = misses_by_id.get(key)
        row = {field: "" for field in CATALOG_FIELDS}
        for field in (
            "source_position",
            "video_id",
            "video_url",
            "normalized_artists",
            "normalized_title",
            "original_artists",
            "original_title",
            "album",
            "duration_seconds",
        ):
            row[field] = source.get(field, "")

        if matched:
            for field in CATALOG_FIELDS:
                row[field] = matched.get(field, row.get(field, ""))
            row["match_reason"] = ""
            row["metadata_source"] = metadata_source(row.get("match_status", ""))
        else:
            row["match_status"] = "missing"
            row["match_reason"] = missed.get("reason", "not_found") if missed else "not_found"
            row["metadata_source"] = ""

        catalog.append(row)

    return catalog


def write_manifest(path: Path, catalog: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    statuses = collections.Counter(row.get("match_status", "") for row in catalog)
    reasons = collections.Counter(row.get("match_reason", "") for row in catalog if row.get("match_reason"))
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "primary_csv": "music_catalog.csv",
        "total_rows": len(catalog),
        "rows_with_key": sum(1 for row in catalog if row.get("key_of") and row.get("mode")),
        "rows_with_metadata": sum(1 for row in catalog if row.get("match_status") != "missing"),
        "match_statuses": dict(sorted(statuses.items())),
        "miss_reasons": dict(sorted(reasons.items())),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    source_rows = read_csv(Path(args.source))
    key_rows = read_csv(Path(args.keys))
    miss_rows = read_csv(Path(args.misses))
    catalog = build_catalog(source_rows, key_rows, miss_rows)

    key_set = {row_key(row) for row in key_rows}
    miss_set = {row_key(row) for row in miss_rows}
    source_set = {row_key(row) for row in source_rows}
    if len(catalog) != len(source_rows) or key_set & miss_set or (key_set | miss_set) != source_set:
        raise SystemExit("Catalog coverage check failed.")

    write_csv(Path(args.output), catalog)
    write_manifest(Path(args.manifest), catalog)
    print(f"Catalog rows: {len(catalog)}")
    print(f"Rows with key/mode: {sum(1 for row in catalog if row.get('key_of') and row.get('mode'))}")
    print(f"Output: {args.output}")
    print(f"Manifest: {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
