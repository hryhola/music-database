#!/usr/bin/env python3
"""Broader candidate search for selected miss rows using title-only queries."""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import requests

from fetch_getsongbpm_keys import (
    API_KEY_ENV,
    BASE_URL,
    DEFAULT_CACHE_DIR,
    DEFAULT_RETRIES,
    DEFAULT_SLEEP_SECONDS,
    QueryVariant,
    artist_name,
    cache_key,
    compact,
    result_songs,
    score_song,
    simplify_query_title,
)
from key_normalization import normalize_key_fields


DEFAULT_INPUT = "data/review/getsongbpm_miss_filter_selected.csv"
DEFAULT_CANDIDATES = "data/review/getsongbpm_broader_candidates.csv"
DEFAULT_NO_CANDIDATES = "data/review/getsongbpm_broader_no_candidates.csv"
DEFAULT_MANIFEST = "data/work/getsongbpm_broader_manifest.json"
DEFAULT_LIMIT = 10
DEFAULT_TOP_N = 3
DEFAULT_MIN_SCORE = 0.55


CANDIDATE_FIELDS = [
    "normalized_artists",
    "normalized_title",
    "source_position",
    "video_id",
    "video_url",
    "candidate_rank",
    "candidate_score",
    "candidate_variant",
    "getsongbpm_song_id",
    "getsongbpm_title",
    "getsongbpm_artist",
    "getsongbpm_uri",
    "tempo",
    "time_sig",
    "key_of",
    "mode",
    "open_key",
    "danceability",
    "acousticness",
]


NO_CANDIDATE_FIELDS = [
    "normalized_artists",
    "normalized_title",
    "source_position",
    "video_id",
    "video_url",
    "raw_candidate_count",
    "best_score",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Title-only broader candidate search across selected miss rows.",
    )
    parser.add_argument("--input", default=DEFAULT_INPUT, help="Selected miss rows CSV.")
    parser.add_argument("--candidates", default=DEFAULT_CANDIDATES, help="Candidate CSV output.")
    parser.add_argument("--no-candidates", default=DEFAULT_NO_CANDIDATES, help="No-candidate CSV output.")
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST, help="Run manifest JSON output.")
    parser.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR, help="GetSongBPM response cache.")
    parser.add_argument(
        "--api-key",
        default=os.environ.get(API_KEY_ENV),
        help=f"API key (defaults to {API_KEY_ENV}).",
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="GetSongBPM result limit per query.")
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N, help="Top candidates per source to retain.")
    parser.add_argument(
        "--min-score",
        type=float,
        default=DEFAULT_MIN_SCORE,
        help="Minimum combined score (title 0.64 + artist 0.36) to surface a candidate.",
    )
    parser.add_argument("--sleep", type=float, default=DEFAULT_SLEEP_SECONDS, help="Delay between uncached calls.")
    parser.add_argument("--max-rows", type=int, default=None, help="Only process first N input rows.")
    parser.add_argument("--force", action="store_true", help="Ignore cached responses.")
    parser.add_argument("--dry-run", action="store_true", help="Skip API calls; validate setup only.")
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES, help="Retries for transient errors.")
    parser.add_argument(
        "--include-truncated",
        action="store_true",
        help=(
            "Also fetch first-3-word and first-2-word title variants for sources whose "
            "simplified title is 4+ words long. Helps recover long titles GetSongBPM does "
            "not index verbatim."
        ),
    )
    parser.add_argument(
        "--truncated-min-words",
        type=int,
        default=4,
        help="Minimum simplified-title word count required to emit truncated variants.",
    )
    return parser.parse_args()


def variants_for(
    row: dict[str, str],
    include_truncated: bool = False,
    truncated_min_words: int = 4,
) -> list[QueryVariant]:
    title = compact(row.get("normalized_title", ""))
    if not title:
        return []
    variants = [QueryVariant("title_only", title, "")]
    simplified = simplify_query_title(title)
    if simplified and simplified.casefold() != title.casefold():
        variants.append(QueryVariant("simplified_title_only", simplified, ""))
    if include_truncated:
        base = simplified or title
        tokens = base.split()
        if len(tokens) >= truncated_min_words:
            seen = {v.title.casefold() for v in variants}
            first3 = " ".join(tokens[:3])
            if first3.casefold() not in seen:
                variants.append(QueryVariant("title_first3", first3, ""))
                seen.add(first3.casefold())
            first2 = " ".join(tokens[:2])
            if first2.casefold() not in seen:
                variants.append(QueryVariant("title_first2", first2, ""))
    return variants


def search_url_title_only(variant: QueryVariant, limit: int) -> str:
    title = compact(variant.title)
    return f"{BASE_URL}/search/?type=song&lookup={quote_plus(title)}&limit={limit}"


def fetch_search(
    session: requests.Session,
    row: dict[str, str],
    variant: QueryVariant,
    api_key: str,
    cache_dir: Path,
    limit: int,
    force: bool,
    dry_run: bool,
    retries: int,
) -> tuple[dict[str, Any], bool]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / cache_key(row, limit, variant)
    cached = path.exists() and not force
    if cached:
        return json.loads(path.read_text(encoding="utf-8")), True
    if dry_run:
        return {"search": [], "_dry_run": True}, False

    url = search_url_title_only(variant, limit)
    response = None
    for attempt in range(retries + 1):
        try:
            response = session.get(
                url,
                headers={"X-API-KEY": api_key},
                params={"api_key": api_key},
                timeout=30,
            )
            break
        except requests.exceptions.RequestException as exc:
            if attempt >= retries:
                raise RuntimeError(f"GetSongBPM request failed after {retries + 1} attempts: {exc}") from exc
            time.sleep(min(30.0, 2.0 * (attempt + 1)))

    if response is None:
        raise RuntimeError("GetSongBPM request failed before receiving a response.")
    if response.status_code == 429:
        raise RuntimeError("GetSongBPM rate limit reached. Re-run later; cached responses preserved.")
    if response.status_code >= 400:
        raise RuntimeError(f"GetSongBPM API error {response.status_code}: {response.text[:300]}")

    payload = response.json()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload, False


def song_id(song: dict[str, Any]) -> str:
    return str(song.get("id") or song.get("uri") or song.get("title") or "")


def collect_candidates(
    row: dict[str, str],
    variants: list[QueryVariant],
    fetch: Any,
) -> tuple[list[dict[str, Any]], dict[str, str], int, int]:
    """Returns (unique_songs, variant_by_id, raw_count, fresh_calls)."""
    raw_count = 0
    fresh_calls = 0
    unique: list[dict[str, Any]] = []
    variant_by_id: dict[str, str] = {}
    for variant in variants:
        payload, cached = fetch(variant)
        if not cached:
            fresh_calls += 1
        songs = result_songs(payload)
        raw_count += len(songs)
        for song in songs:
            sid = song_id(song)
            if not sid or sid in variant_by_id:
                continue
            variant_by_id[sid] = variant.name
            unique.append(song)
    return unique, variant_by_id, raw_count, fresh_calls


def select_top(
    row: dict[str, str],
    songs: list[dict[str, Any]],
    top_n: int,
    min_score: float,
) -> list[tuple[float, dict[str, Any]]]:
    scored = sorted(
        ((score_song(row, song), song) for song in songs),
        key=lambda item: item[0],
        reverse=True,
    )
    return [(score, song) for score, song in scored if score >= min_score][:top_n]


def candidate_row(
    row: dict[str, str],
    song: dict[str, Any],
    score: float,
    rank: int,
    variant_name: str,
) -> dict[str, Any]:
    key_of = str(song.get("key_of", "") or "")
    normalized_key = normalize_key_fields(key_of, tempo=song.get("tempo", ""))
    return {
        "normalized_artists": row.get("normalized_artists", ""),
        "normalized_title": row.get("normalized_title", ""),
        "source_position": row.get("source_position", ""),
        "video_id": row.get("video_id", ""),
        "video_url": row.get("video_url", ""),
        "candidate_rank": rank,
        "candidate_score": f"{score:.4f}",
        "candidate_variant": variant_name,
        "getsongbpm_song_id": song.get("id", ""),
        "getsongbpm_title": song.get("title", ""),
        "getsongbpm_artist": artist_name(song),
        "getsongbpm_uri": song.get("uri", ""),
        "tempo": normalized_key.tempo,
        "time_sig": song.get("time_sig", ""),
        "key_of": normalized_key.key_of,
        "mode": normalized_key.mode,
        "open_key": song.get("open_key", ""),
        "danceability": song.get("danceability", ""),
        "acousticness": song.get("acousticness", ""),
    }


def no_candidate_row(
    row: dict[str, str],
    raw_count: int,
    best_score: float,
) -> dict[str, Any]:
    return {
        "normalized_artists": row.get("normalized_artists", ""),
        "normalized_title": row.get("normalized_title", ""),
        "source_position": row.get("source_position", ""),
        "video_id": row.get("video_id", ""),
        "video_url": row.get("video_url", ""),
        "raw_candidate_count": raw_count,
        "best_score": f"{best_score:.4f}",
    }


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    if not args.api_key and not args.dry_run:
        raise SystemExit(
            f"Missing API key. Set {API_KEY_ENV} or pass --api-key. "
            "Use --dry-run to validate setup without API calls."
        )

    input_path = Path(args.input).expanduser()
    with input_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if args.max_rows is not None:
        rows = rows[: args.max_rows]

    cache_dir = Path(args.cache_dir).expanduser()
    session = requests.Session()
    candidate_rows: list[dict[str, Any]] = []
    no_candidate_rows: list[dict[str, Any]] = []
    uncached_calls = 0

    for index, row in enumerate(rows, start=1):
        variants = variants_for(
            row,
            include_truncated=args.include_truncated,
            truncated_min_words=args.truncated_min_words,
        )
        if not variants:
            no_candidate_rows.append(no_candidate_row(row, 0, 0.0))
            continue

        def fetch(variant: QueryVariant) -> tuple[dict[str, Any], bool]:
            return fetch_search(
                session=session,
                row=row,
                variant=variant,
                api_key=args.api_key or "",
                cache_dir=cache_dir,
                limit=args.limit,
                force=args.force,
                dry_run=args.dry_run,
                retries=args.retries,
            )

        unique, variant_by_id, raw_count, fresh = collect_candidates(row, variants, fetch)
        if not args.dry_run:
            uncached_calls += fresh
        kept = select_top(row, unique, args.top_n, args.min_score)

        if kept:
            for rank, (score, song) in enumerate(kept, start=1):
                candidate_rows.append(
                    candidate_row(
                        row,
                        song,
                        score,
                        rank,
                        variant_by_id.get(song_id(song), variants[0].name),
                    )
                )
        else:
            best = 0.0
            if unique:
                best = max(score_song(row, song) for song in unique)
            no_candidate_rows.append(no_candidate_row(row, raw_count, best))

        if fresh and not args.dry_run and index < len(rows):
            time.sleep(max(0.0, args.sleep))

    write_csv(Path(args.candidates).expanduser(), CANDIDATE_FIELDS, candidate_rows)
    write_csv(Path(args.no_candidates).expanduser(), NO_CANDIDATE_FIELDS, no_candidate_rows)

    sources_with_candidates = len({(r["source_position"], r["video_id"]) for r in candidate_rows})
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input": args.input,
        "input_count": len(rows),
        "candidate_rows": len(candidate_rows),
        "sources_with_candidates": sources_with_candidates,
        "sources_without_candidates": len(no_candidate_rows),
        "top_n": args.top_n,
        "min_score": args.min_score,
        "limit": args.limit,
        "uncached_calls": uncached_calls,
        "include_truncated": args.include_truncated,
        "truncated_min_words": args.truncated_min_words,
    }
    Path(args.manifest).expanduser().write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Sources processed: {len(rows)}")
    print(f"Sources with candidates: {sources_with_candidates}")
    print(f"Sources without candidates: {len(no_candidate_rows)}")
    print(f"Candidate rows written: {len(candidate_rows)}")
    print(f"Uncached API calls: {uncached_calls}")
    print(f"Output: {args.candidates}")
    print(f"No candidates: {args.no_candidates}")
    print(f"Manifest: {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
