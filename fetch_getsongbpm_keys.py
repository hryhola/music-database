#!/usr/bin/env python3
"""Fetch key/BPM metadata from the GetSongBPM API for normalized songs."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import string
import sys
import time
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import requests


BASE_URL = "https://api.getsong.co"
API_KEY_ENV = "GETSONGBPM_API_KEY"
DEFAULT_INPUT = "data/normalized_liked_songs.csv"
DEFAULT_OUTPUT = "data/song_keys_getsongbpm.csv"
DEFAULT_MISSES = "data/song_keys_getsongbpm_misses.csv"
DEFAULT_CACHE_DIR = ".cache/getsongbpm"
DEFAULT_LIMIT = 5
DEFAULT_MATCH_THRESHOLD = 0.86
DEFAULT_SLEEP_SECONDS = 1.25
DEFAULT_RETRIES = 4

PUNCT_TRANSLATION = str.maketrans("", "", string.punctuation + "’‘“”«»„")
FEAT_RE = re.compile(r"(?i)\b(feat\.?|ft\.?|featuring)\b.*$")
PAREN_META_RE = re.compile(r"\s*[\[(](?:feat\.?|ft\.?|featuring).*?[\])]", re.I)

OUTPUT_FIELDS = [
    "normalized_artists",
    "normalized_title",
    "source_position",
    "video_id",
    "video_url",
    "original_artists",
    "original_title",
    "album",
    "duration_seconds",
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
    "match_score",
    "match_status",
]

MISS_FIELDS = [
    "normalized_artists",
    "normalized_title",
    "source_position",
    "video_id",
    "video_url",
    "reason",
    "best_match_score",
    "best_match_title",
    "best_match_artist",
    "best_match_id",
]


@dataclass(frozen=True)
class Match:
    status: str
    score: float
    song: dict[str, Any] | None


@dataclass(frozen=True)
class QueryVariant:
    name: str
    title: str
    artist: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch GetSongBPM key/BPM data for normalized songs.")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="Normalized songs CSV.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Matched output CSV.")
    parser.add_argument("--misses", default=DEFAULT_MISSES, help="Miss/ambiguous output CSV.")
    parser.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR, help="Directory for cached search responses.")
    parser.add_argument("--api-key", default=os.environ.get(API_KEY_ENV), help=f"API key. Defaults to {API_KEY_ENV}.")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="GetSongBPM search result limit per song.")
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_MATCH_THRESHOLD,
        help="Minimum match score to accept.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=DEFAULT_SLEEP_SECONDS,
        help="Delay between uncached API calls. Default stays below 3000/hour.",
    )
    parser.add_argument("--max-rows", type=int, default=None, help="Process only the first N input rows.")
    parser.add_argument("--force", action="store_true", help="Ignore cached search responses.")
    parser.add_argument("--dry-run", action="store_true", help="Do not call the API; validate inputs and cache state only.")
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES, help="Retries for transient API/network errors.")
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def compact(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def strip_accents(value: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKD", value or "") if not unicodedata.combining(char)
    )


def comparable(value: str) -> str:
    value = strip_accents(value).casefold()
    value = PAREN_META_RE.sub("", value)
    value = FEAT_RE.sub("", value)
    value = value.replace("&", " and ")
    value = value.translate(PUNCT_TRANSLATION)
    value = re.sub(r"\b(the|official|topic)\b", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def first_artist(artists: str) -> str:
    artists = re.split(r"\s*;\s*", artists or "", maxsplit=1)[0]
    artists = re.split(r"\s*,\s*", artists, maxsplit=1)[0]
    return compact(artists)


def artist_name(song: dict[str, Any]) -> str:
    artist = song.get("artist")
    if isinstance(artist, dict):
        return str(artist.get("name", ""))
    if isinstance(artist, list) and artist:
        first = artist[0]
        if isinstance(first, dict):
            return str(first.get("name", ""))
    return ""


def cache_key(row: dict[str, str], limit: int, variant: QueryVariant | None = None) -> str:
    variant = variant or QueryVariant("primary", row.get("normalized_title", ""), first_artist(row.get("normalized_artists", "")))
    artist = comparable(variant.artist) or "unknown_artist"
    title = comparable(variant.title) or "unknown_title"
    raw = f"{artist}__{title}__limit_{limit}"
    if variant.name != "primary":
        raw += f"__{variant.name}"
    raw = re.sub(r"[^a-z0-9]+", "_", raw)
    return raw.strip("_")[:180] + ".json"


def simplify_query_title(title: str) -> str:
    title = compact(title)
    title = PAREN_META_RE.sub("", title)
    title = FEAT_RE.sub("", title)
    title = re.sub(r"\s*[\[(]\d{1,4}(?:[./-]\d{1,4}){1,2}[\])]\s*", " ", title)
    title = re.sub(r"\s*[\[(](?:album|single|remastered|explicit).*?[\])]\s*", " ", title, flags=re.I)
    return compact(title)


def query_variants(row: dict[str, str]) -> list[QueryVariant]:
    primary = QueryVariant(
        "primary",
        compact(row.get("normalized_title", "")),
        first_artist(row.get("normalized_artists", "")),
    )
    variants = [primary]
    simplified = simplify_query_title(primary.title)
    if simplified and simplified.casefold() != primary.title.casefold():
        variants.append(QueryVariant("simplified_title", simplified, primary.artist))
    return variants


def search_url(variant: QueryVariant, limit: int) -> str:
    title = compact(variant.title)
    artist = compact(variant.artist)
    lookup = f"song:{title} artist:{artist}"
    return f"{BASE_URL}/search/?type=both&lookup={quote_plus(lookup)}&limit={limit}"


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
) -> dict[str, Any]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / cache_key(row, limit, variant)
    if path.exists() and not force:
        return json.loads(path.read_text(encoding="utf-8"))

    if dry_run:
        return {"search": [], "_dry_run": True}

    url = search_url(variant, limit)
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
        raise RuntimeError("GetSongBPM rate limit reached. Re-run later; cached responses are preserved.")
    if response.status_code >= 400:
        raise RuntimeError(f"GetSongBPM API error {response.status_code}: {response.text[:300]}")

    payload = response.json()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def result_songs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    search = payload.get("search", [])
    if isinstance(search, dict):
        search = [search]
    return [item for item in search if isinstance(item, dict) and item.get("title")]


def unique_songs(songs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for song in songs:
        key = str(song.get("id") or song.get("uri") or song.get("title"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(song)
    return unique


def similarity(left: str, right: str) -> float:
    left_c = comparable(left)
    right_c = comparable(right)
    if not left_c or not right_c:
        return 0.0
    if left_c == right_c:
        return 1.0
    if left_c in right_c or right_c in left_c:
        shorter = min(len(left_c), len(right_c))
        longer = max(len(left_c), len(right_c))
        return max(0.88, shorter / longer)
    return SequenceMatcher(None, left_c, right_c).ratio()


def score_song(row: dict[str, str], song: dict[str, Any]) -> float:
    title_score = similarity(row.get("normalized_title", ""), str(song.get("title", "")))
    artist_score = similarity(first_artist(row.get("normalized_artists", "")), artist_name(song))
    album_score = 0.0
    album = song.get("album")
    if isinstance(album, dict) and row.get("album"):
        album_score = similarity(row.get("album", ""), str(album.get("title", "")))
    if album_score:
        return round(title_score * 0.58 + artist_score * 0.34 + album_score * 0.08, 4)
    return round(title_score * 0.64 + artist_score * 0.36, 4)


def choose_match(row: dict[str, str], songs: list[dict[str, Any]], threshold: float) -> Match:
    if not songs:
        return Match("not_found", 0.0, None)

    scored = sorted(((score_song(row, song), song) for song in songs), key=lambda item: item[0], reverse=True)
    best_score, best_song = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0
    if best_score < threshold:
        return Match("low_confidence", best_score, best_song)
    if second_score >= threshold and best_score - second_score < 0.03:
        return Match("ambiguous", best_score, best_song)
    return Match("matched", best_score, best_song)


def mode_from_key(key_of: str) -> str:
    key = compact(key_of)
    if not key:
        return ""
    lowered = key.casefold()
    if lowered.endswith("m") or lowered.endswith(" minor"):
        return "minor"
    if lowered.endswith(" major"):
        return "major"
    return "major"


def output_row(row: dict[str, str], match: Match) -> dict[str, Any]:
    song = match.song or {}
    key_of = str(song.get("key_of", "") or "")
    return {
        **{field: row.get(field, "") for field in OUTPUT_FIELDS if field in row},
        "getsongbpm_song_id": song.get("id", ""),
        "getsongbpm_title": song.get("title", ""),
        "getsongbpm_artist": artist_name(song),
        "getsongbpm_uri": song.get("uri", ""),
        "tempo": song.get("tempo", ""),
        "time_sig": song.get("time_sig", ""),
        "key_of": key_of,
        "mode": mode_from_key(key_of),
        "open_key": song.get("open_key", ""),
        "danceability": song.get("danceability", ""),
        "acousticness": song.get("acousticness", ""),
        "match_score": f"{match.score:.4f}",
        "match_status": match.status,
    }


def miss_row(row: dict[str, str], match: Match) -> dict[str, Any]:
    song = match.song or {}
    return {
        "normalized_artists": row.get("normalized_artists", ""),
        "normalized_title": row.get("normalized_title", ""),
        "source_position": row.get("source_position", ""),
        "video_id": row.get("video_id", ""),
        "video_url": row.get("video_url", ""),
        "reason": match.status,
        "best_match_score": f"{match.score:.4f}",
        "best_match_title": song.get("title", ""),
        "best_match_artist": artist_name(song),
        "best_match_id": song.get("id", ""),
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

    rows = read_csv(Path(args.input).expanduser())
    if args.max_rows is not None:
        rows = rows[: args.max_rows]

    cache_dir = Path(args.cache_dir).expanduser()
    session = requests.Session()
    matched_rows: list[dict[str, Any]] = []
    miss_rows: list[dict[str, Any]] = []
    uncached_calls = 0

    for index, row in enumerate(rows, start=1):
        songs: list[dict[str, Any]] = []
        match = Match("not_found", 0.0, None)
        for variant in query_variants(row):
            cache_path = cache_dir / cache_key(row, args.limit, variant)
            was_cached = cache_path.exists() and not args.force
            payload = fetch_search(
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
            if not was_cached and not args.dry_run:
                uncached_calls += 1
            songs = unique_songs([*songs, *result_songs(payload)])
            match = choose_match(row, songs, args.threshold)
            if match.status == "matched":
                break

        if match.status == "matched":
            matched_rows.append(output_row(row, match))
        else:
            miss_rows.append(miss_row(row, match))

        if not was_cached and not args.dry_run and index < len(rows):
            time.sleep(max(0.0, args.sleep))

    write_csv(Path(args.output).expanduser(), OUTPUT_FIELDS, matched_rows)
    write_csv(Path(args.misses).expanduser(), MISS_FIELDS, miss_rows)

    print(f"Processed {len(rows)} normalized songs")
    print(f"Matched: {len(matched_rows)}")
    print(f"Misses/ambiguous: {len(miss_rows)}")
    print(f"Uncached API calls: {uncached_calls}")
    print(f"Output: {args.output}")
    print(f"Misses: {args.misses}")
    print(f"Cache: {args.cache_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
