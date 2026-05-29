#!/usr/bin/env python3
"""Normalize key_of/mode columns in generated CSV exports."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from key_normalization import normalize_key_fields


DEFAULT_INPUT = "data/work/getsongbpm_matches.csv"
DEFAULT_MANIFEST = "data/work/key_matching_manifest.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize musical key notation in CSV exports.")
    parser.add_argument("paths", nargs="*", default=[DEFAULT_INPUT], help="CSV files with key_of/mode columns.")
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST, help="Manifest JSON to annotate when normalizing main CSV.")
    return parser.parse_args()


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def normalize_file(path: Path) -> dict[str, int]:
    fieldnames, rows = read_csv(path)
    if "key_of" not in fieldnames or "mode" not in fieldnames:
        raise SystemExit(f"{path} does not contain key_of and mode columns")

    changed_rows = 0
    missing_key_rows = 0
    moved_tempo_rows = 0
    for row in rows:
        before = (row.get("key_of", ""), row.get("mode", ""), row.get("tempo", ""))
        normalized = normalize_key_fields(row.get("key_of", ""), row.get("mode", ""), row.get("tempo", ""))
        row["key_of"] = normalized.key_of
        row["mode"] = normalized.mode
        if "tempo" in fieldnames:
            row["tempo"] = normalized.tempo
        after = (row.get("key_of", ""), row.get("mode", ""), row.get("tempo", ""))
        if before != after:
            changed_rows += 1
        if not normalized.key_of:
            missing_key_rows += 1
        if before[2] != after[2]:
            moved_tempo_rows += 1

    write_csv(path, fieldnames, rows)
    return {
        "rows": len(rows),
        "changed_rows": changed_rows,
        "missing_key_rows": missing_key_rows,
        "moved_tempo_rows": moved_tempo_rows,
    }


def update_manifest(path: Path, stats: dict[str, int]) -> None:
    payload: dict[str, Any] = {}
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
    payload.update(
        {
            "key_normalized_at": datetime.now(timezone.utc).isoformat(),
            "key_normalized_rows": stats["rows"],
            "key_normalized_changed_rows": stats["changed_rows"],
            "key_normalized_missing_key_rows": stats["missing_key_rows"],
        }
    )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    manifest_path = Path(args.manifest)
    for raw_path in args.paths:
        path = Path(raw_path)
        stats = normalize_file(path)
        print(
            f"{path}: {stats['rows']} rows, {stats['changed_rows']} changed, "
            f"{stats['missing_key_rows']} missing keys, {stats['moved_tempo_rows']} tempos moved from key text"
        )
        if path == Path(DEFAULT_INPUT):
            update_manifest(manifest_path, stats)
            print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
