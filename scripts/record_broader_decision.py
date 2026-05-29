#!/usr/bin/env python3
"""Record a single broader-review decision into the decisions JSONL.

Designed for use by review agents working directly with data files (no HTTP UI).
Uses POSIX `fcntl.flock` so multiple agents can append concurrently without
interleaving lines. Validates inputs, looks up candidate metadata when
accepting, and refuses duplicate decisions for the same source by default.

Examples:
  Accept candidate #2 for source:
    scripts/record_broader_decision.py --source-position 5 --video-id eIp2 \\
        --decision accept --candidate-rank 2 --notes "matches Static-X discography"

  Manual entry from Tunebat:
    scripts/record_broader_decision.py --source-position 41 --video-id Zm_G \\
        --decision manual --manual-key "G major" --manual-tempo 109 \\
        --notes "tunebat: Lian Ross - Mamy Blue"

  Reject (no usable data source):
    scripts/record_broader_decision.py --source-position 200 --video-id Q-xX \\
        --decision reject --notes "tunebat: not found"
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_CANDIDATES = "data/review/getsongbpm_broader_candidates.csv"
DEFAULT_DECISIONS = "data/review/getsongbpm_broader_decisions.jsonl"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Append a single broader-review decision.")
    parser.add_argument("--source-position", required=True, help="source_position of the song.")
    parser.add_argument("--video-id", required=True, help="video_id of the song.")
    parser.add_argument(
        "--decision",
        required=True,
        choices=["accept", "manual", "reject"],
        help="Decision type.",
    )
    parser.add_argument("--candidate-rank", type=int, help="1-3. Required when --decision=accept.")
    parser.add_argument("--manual-key", default="", help="Key string for --decision=manual (e.g. 'Cm', 'G major').")
    parser.add_argument("--manual-tempo", default="", help="BPM for --decision=manual (positive number).")
    parser.add_argument("--manual-time-sig", default="", help="Optional time signature for --decision=manual.")
    parser.add_argument("--notes", default="", help="Optional reviewer notes.")
    parser.add_argument("--candidates", default=DEFAULT_CANDIDATES, help="Candidates CSV (for accept lookup).")
    parser.add_argument("--decisions", default=DEFAULT_DECISIONS, help="Decisions JSONL to append to.")
    parser.add_argument(
        "--also-check",
        action="append",
        default=[],
        help="Additional JSONL paths to scan for duplicate detection (repeatable).",
    )
    parser.add_argument(
        "--allow-duplicate",
        action="store_true",
        help="Append even if this source already has a decision (default: refuse).",
    )
    parser.add_argument(
        "--source-label",
        default="",
        help="Optional free-form label recorded with the decision (e.g. 'agent-2', 'tunebat').",
    )
    return parser.parse_args()


def fail(message: str, code: int = 2) -> "int":
    sys.stderr.write(message.rstrip() + "\n")
    return code


def load_existing_decisions(path: Path) -> set[tuple[str, str]]:
    decided: set[tuple[str, str]] = set()
    if not path.exists():
        return decided
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
                decided.add(
                    (str(record.get("source_position", "")), str(record.get("video_id", "")))
                )
    return decided


def find_candidate(candidates_path: Path, source_position: str, video_id: str, rank: int) -> dict | None:
    if not candidates_path.exists():
        return None
    with candidates_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if (
                row.get("source_position") == source_position
                and row.get("video_id") == video_id
                and str(row.get("candidate_rank", "")) == str(rank)
            ):
                return row
    return None


def find_source_meta(candidates_path: Path, source_position: str, video_id: str) -> dict | None:
    if not candidates_path.exists():
        return None
    with candidates_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("source_position") == source_position and row.get("video_id") == video_id:
                return row
    return None


def build_record(args: argparse.Namespace, candidates_path: Path) -> dict:
    record: dict = {
        "stage": "broader",
        "source_position": str(args.source_position),
        "video_id": str(args.video_id),
        "notes": (args.notes or "").strip(),
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }
    if args.source_label:
        record["source_label"] = args.source_label.strip()

    source_meta = find_source_meta(candidates_path, args.source_position, args.video_id)
    if source_meta:
        record["normalized_artists"] = source_meta.get("normalized_artists", "")
        record["normalized_title"] = source_meta.get("normalized_title", "")
    else:
        record["normalized_artists"] = ""
        record["normalized_title"] = ""

    if args.decision == "accept":
        if not args.candidate_rank:
            raise SystemExit(fail("--candidate-rank is required with --decision=accept"))
        candidate = find_candidate(candidates_path, args.source_position, args.video_id, args.candidate_rank)
        if not candidate:
            raise SystemExit(
                fail(
                    f"No candidate rank {args.candidate_rank} found for source_position="
                    f"{args.source_position!r} video_id={args.video_id!r}"
                )
            )
        record["decision"] = "accept"
        record["best_match_id"] = candidate.get("getsongbpm_song_id", "")
        record["best_match_artist"] = candidate.get("getsongbpm_artist", "")
        record["best_match_title"] = candidate.get("getsongbpm_title", "")
        record["best_match_score"] = candidate.get("candidate_score", "")
        record["candidate_rank"] = str(args.candidate_rank)
        record["candidate_variant"] = candidate.get("candidate_variant", "")
        if not record["best_match_id"]:
            raise SystemExit(fail("Candidate is missing getsongbpm_song_id; cannot accept."))

    elif args.decision == "manual":
        manual_key = (args.manual_key or "").strip()
        manual_tempo = (args.manual_tempo or "").strip()
        manual_time_sig = (args.manual_time_sig or "").strip()
        if not manual_key and not manual_tempo:
            raise SystemExit(fail("Provide --manual-key, --manual-tempo, or both."))
        if manual_tempo:
            try:
                if float(manual_tempo) <= 0:
                    raise ValueError
            except ValueError:
                raise SystemExit(fail("--manual-tempo must be a positive number."))
        record["decision"] = "manual"
        record["manual_key"] = manual_key
        record["manual_tempo"] = manual_tempo
        record["manual_time_sig"] = manual_time_sig

    else:  # reject
        record["decision"] = "reject"
        record["best_match_id"] = ""
        record["best_match_artist"] = ""
        record["best_match_title"] = ""
        record["best_match_score"] = ""
        record["candidate_rank"] = ""
        record["candidate_variant"] = ""

    return record


def append_locked(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.write(line)
            if not line.endswith("\n"):
                handle.write("\n")
            handle.flush()
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def main() -> int:
    args = parse_args()
    candidates_path = Path(args.candidates).expanduser()
    decisions_path = Path(args.decisions).expanduser()

    if not args.allow_duplicate:
        decided = load_existing_decisions(decisions_path)
        for extra in args.also_check:
            decided.update(load_existing_decisions(Path(extra).expanduser()))
        if (str(args.source_position), str(args.video_id)) in decided:
            return fail(
                f"source_position={args.source_position!r} video_id={args.video_id!r} already has a decision. "
                "Pass --allow-duplicate to override."
            )

    record = build_record(args, candidates_path)
    serialized = json.dumps(record, ensure_ascii=False, sort_keys=True)
    append_locked(decisions_path, serialized)
    print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
