#!/usr/bin/env python3
"""Local UI for accepting or rejecting suggested GetSongBPM matches."""

from __future__ import annotations

import argparse
import csv
import html
import json
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode


DEFAULT_QUEUE = "data/review/getsongbpm_initial_review_queue.csv"
DEFAULT_DECISIONS = "data/review/getsongbpm_initial_review_decisions.jsonl"
DEFAULT_CACHE = ".cache/getsongbpm"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review suggested GetSongBPM matches.")
    parser.add_argument("--queue", default=DEFAULT_QUEUE, help="Manual review CSV.")
    parser.add_argument("--decisions", default=DEFAULT_DECISIONS, help="Decision JSONL output.")
    parser.add_argument("--cache-dir", default=DEFAULT_CACHE, help="GetSongBPM cache directory.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument("--port", type=int, default=8766, help="Port to bind.")
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                payload = json.loads(line)
                if isinstance(payload, dict):
                    records.append(payload)
    return records


def record_key(record: dict) -> tuple[str, str, str]:
    return (
        str(record.get("source_position", "")),
        str(record.get("video_id", "")),
        str(record.get("best_match_id", "")),
    )


def latest_decisions(path: Path) -> dict[tuple[str, str, str], dict]:
    return {record_key(record): record for record in read_jsonl(path)}


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def find_song_in_cache(cache_dir: Path, song_id: str) -> dict:
    if not song_id or not cache_dir.exists():
        return {}
    for path in cache_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        search = payload.get("search", [])
        if isinstance(search, dict):
            search = [search]
        for song in search:
            if isinstance(song, dict) and str(song.get("id", "")) == song_id:
                return song
    return {}


def artist_name(song: dict) -> str:
    artist = song.get("artist")
    if isinstance(artist, dict):
        return str(artist.get("name", ""))
    return ""


class ReviewApp:
    def __init__(self, queue_path: Path, decisions_path: Path, cache_dir: Path):
        self.queue_path = queue_path
        self.decisions_path = decisions_path
        self.cache_dir = cache_dir

    def queue(self) -> list[dict[str, str]]:
        decisions = latest_decisions(self.decisions_path)
        return [row for row in read_csv(self.queue_path) if record_key(row) not in decisions]

    def append_decision(self, payload: dict) -> None:
        self.decisions_path.parent.mkdir(parents=True, exist_ok=True)
        with self.decisions_path.open("a", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")

    def render(self, index: int = 0) -> bytes:
        queue = self.queue()
        total = len(queue)
        if total == 0:
            return self.page(
                "Review complete",
                """
                <main class="done">
                  <h1>Review complete</h1>
                  <p>No unresolved suggested matches remain.</p>
                </main>
                """,
            )

        index = max(0, min(index, total - 1))
        row = queue[index]
        song = find_song_in_cache(self.cache_dir, row.get("best_match_id", ""))
        title = song.get("title") or row.get("best_match_title", "")
        artist = artist_name(song) or row.get("best_match_artist", "")
        body = f"""
        <main>
          <header>
            <div>
              <h1>GetSongBPM Match Review</h1>
              <p>{index + 1} of {total} unresolved suggestions</p>
            </div>
            <nav>
              <a href="/?{urlencode({'index': max(0, index - 1)})}">Previous</a>
              <a href="/?{urlencode({'index': min(total - 1, index + 1)})}">Next</a>
            </nav>
          </header>

          <section class="grid">
            <article>
              <h2>Your Song</h2>
              <dl>
                <dt>Artist</dt><dd>{esc(row.get('normalized_artists'))}</dd>
                <dt>Title</dt><dd>{esc(row.get('normalized_title'))}</dd>
                <dt>Reason</dt><dd>{esc(row.get('reason'))}</dd>
                <dt>Score</dt><dd>{esc(row.get('best_match_score'))}</dd>
                <dt>YouTube</dt><dd><a href="{esc(row.get('video_url'))}" target="_blank" rel="noreferrer">{esc(row.get('video_id'))}</a></dd>
              </dl>
            </article>

            <article>
              <h2>Suggested Match</h2>
              <dl>
                <dt>Artist</dt><dd>{esc(artist)}</dd>
                <dt>Title</dt><dd>{esc(title)}</dd>
                <dt>Key</dt><dd>{esc(song.get('key_of', ''))}</dd>
                <dt>Tempo</dt><dd>{esc(song.get('tempo', ''))} BPM</dd>
                <dt>Open key</dt><dd>{esc(song.get('open_key', ''))}</dd>
                <dt>Time signature</dt><dd>{esc(song.get('time_sig', ''))}</dd>
                <dt>GetSongBPM</dt><dd><a href="{esc(song.get('uri', ''))}" target="_blank" rel="noreferrer">{esc(row.get('best_match_id'))}</a></dd>
              </dl>
            </article>

            <form method="POST" action="/decision">
              <h2>Decision</h2>
              <input type="hidden" name="source_position" value="{esc(row.get('source_position'))}">
              <input type="hidden" name="video_id" value="{esc(row.get('video_id'))}">
              <input type="hidden" name="best_match_id" value="{esc(row.get('best_match_id'))}">
              <input type="hidden" name="index" value="{esc(index)}">
              <input type="hidden" name="normalized_artists" value="{esc(row.get('normalized_artists'))}">
              <input type="hidden" name="normalized_title" value="{esc(row.get('normalized_title'))}">
              <input type="hidden" name="best_match_artist" value="{esc(artist)}">
              <input type="hidden" name="best_match_title" value="{esc(title)}">
              <input type="hidden" name="best_match_score" value="{esc(row.get('best_match_score'))}">
              <label>Notes
                <textarea name="notes" placeholder="Optional"></textarea>
              </label>
              <div class="actions">
                <button name="decision" value="accept" type="submit">Accept</button>
                <button name="decision" value="reject" type="submit">Reject</button>
                <button name="decision" value="later" type="submit">Review Later</button>
              </div>
            </form>
          </section>
        </main>
        """
        return self.page("GetSongBPM Match Review", body)

    def page(self, title: str, body: str) -> bytes:
        document = f"""<!doctype html>
        <html lang="en">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>{esc(title)}</title>
          <style>
            :root {{ color-scheme: light; font-family: Inter, system-ui, -apple-system, sans-serif; }}
            body {{ margin: 0; background: #f4f6f4; color: #1f282b; }}
            main {{ max-width: 1160px; margin: 0 auto; padding: 28px; }}
            header {{ display: flex; justify-content: space-between; gap: 16px; align-items: center; margin-bottom: 20px; }}
            h1 {{ margin: 0; font-size: 30px; }}
            h2 {{ margin: 0 0 14px; font-size: 18px; }}
            p {{ color: #5a666a; margin: 6px 0 0; }}
            a {{ color: #0f766e; }}
            nav {{ display: flex; gap: 8px; }}
            nav a, button {{ border: 1px solid #c9d0cf; background: white; color: #1f282b; border-radius: 6px; padding: 10px 14px; text-decoration: none; cursor: pointer; }}
            .grid {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 16px; align-items: start; }}
            article, form {{ background: white; border: 1px solid #d8dddc; border-radius: 8px; padding: 18px; }}
            form {{ grid-column: 1 / -1; }}
            dl {{ display: grid; grid-template-columns: 140px minmax(0, 1fr); gap: 9px 14px; margin: 0; }}
            dt {{ font-weight: 700; color: #4c585c; }}
            dd {{ margin: 0; overflow-wrap: anywhere; }}
            textarea {{ width: 100%; min-height: 80px; box-sizing: border-box; border: 1px solid #c9d0cf; border-radius: 6px; padding: 10px; font: inherit; }}
            label {{ display: grid; gap: 6px; font-weight: 700; color: #4c585c; }}
            .actions {{ display: flex; gap: 10px; margin-top: 14px; flex-wrap: wrap; }}
            .actions button:first-child {{ background: #0f766e; color: white; border-color: #0f766e; }}
            .done {{ max-width: 680px; }}
            @media (max-width: 800px) {{
              main {{ padding: 18px; }}
              header, .grid {{ display: block; }}
              nav, form, article + article {{ margin-top: 14px; }}
              dl {{ grid-template-columns: 1fr; }}
            }}
          </style>
        </head>
        <body>{body}</body>
        </html>"""
        return document.encode("utf-8")


def make_handler(app: ReviewApp) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_HEAD(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()

        def do_GET(self) -> None:
            query = ""
            if "?" in self.path:
                _, query = self.path.split("?", 1)
            params = parse_qs(query)
            try:
                index = int(params.get("index", ["0"])[0])
            except ValueError:
                index = 0
            self.respond(200, app.render(index))

        def do_POST(self) -> None:
            if self.path != "/decision":
                self.respond(404, b"Not found", "text/plain")
                return
            length = int(self.headers.get("content-length", "0"))
            payload = parse_qs(self.rfile.read(length).decode("utf-8"))
            decision = payload.get("decision", ["later"])[0]
            if decision == "later":
                self.redirect_next(payload.get("index", ["0"])[0])
                return
            record = {
                "decision": decision,
                "source_position": payload.get("source_position", [""])[0],
                "video_id": payload.get("video_id", [""])[0],
                "best_match_id": payload.get("best_match_id", [""])[0],
                "normalized_artists": payload.get("normalized_artists", [""])[0],
                "normalized_title": payload.get("normalized_title", [""])[0],
                "best_match_artist": payload.get("best_match_artist", [""])[0],
                "best_match_title": payload.get("best_match_title", [""])[0],
                "best_match_score": payload.get("best_match_score", [""])[0],
                "notes": payload.get("notes", [""])[0].strip(),
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
            }
            app.append_decision(record)
            self.redirect(payload.get("index", ["0"])[0])

        def redirect_next(self, index: str) -> None:
            try:
                next_index = int(index) + 1
            except ValueError:
                next_index = 0
            self.redirect(str(next_index))

        def redirect(self, index: str) -> None:
            self.send_response(303)
            self.send_header("Location", f"/?{urlencode({'index': index})}")
            self.end_headers()

        def respond(self, status: int, body: bytes, content_type: str = "text/html; charset=utf-8") -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: object) -> None:
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    return Handler


def main() -> int:
    args = parse_args()
    app = ReviewApp(
        Path(args.queue).expanduser(),
        Path(args.decisions).expanduser(),
        Path(args.cache_dir).expanduser(),
    )
    server = ThreadingHTTPServer((args.host, args.port), make_handler(app))
    print(f"GetSongBPM review UI: http://{args.host}:{args.port}")
    print("Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
