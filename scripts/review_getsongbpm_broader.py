#!/usr/bin/env python3
"""Local UI for approving broader title-only candidate matches."""

from __future__ import annotations

import argparse
import csv
import html
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode


DEFAULT_CANDIDATES = "data/review/getsongbpm_broader_candidates.csv"
DEFAULT_DECISIONS = "data/review/getsongbpm_broader_decisions.jsonl"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Approve broader GetSongBPM candidate matches.")
    parser.add_argument("--candidates", default=DEFAULT_CANDIDATES, help="Broader candidates CSV.")
    parser.add_argument("--decisions", default=DEFAULT_DECISIONS, help="Decision JSONL output.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument("--port", type=int, default=8768, help="Port to bind.")
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


def source_key(record: dict) -> tuple[str, str]:
    return (str(record.get("source_position", "")), str(record.get("video_id", "")))


def latest_decisions(path: Path) -> dict[tuple[str, str], dict]:
    return {source_key(record): record for record in read_jsonl(path)}


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def group_sources(candidate_rows: list[dict[str, str]]) -> list[dict]:
    by_key: dict[tuple[str, str], dict] = {}
    order: list[tuple[str, str]] = []
    for row in candidate_rows:
        key = source_key(row)
        if key not in by_key:
            by_key[key] = {
                "source_position": row.get("source_position", ""),
                "video_id": row.get("video_id", ""),
                "video_url": row.get("video_url", ""),
                "normalized_artists": row.get("normalized_artists", ""),
                "normalized_title": row.get("normalized_title", ""),
                "candidates": [],
            }
            order.append(key)
        by_key[key]["candidates"].append(row)
    for key in order:
        by_key[key]["candidates"].sort(key=lambda r: int(r.get("candidate_rank", "0") or "0"))
    return [by_key[key] for key in order]


class ReviewApp:
    def __init__(self, candidates_path: Path, decisions_path: Path):
        self.candidates_path = candidates_path
        self.decisions_path = decisions_path

    def queue(self) -> list[dict]:
        sources = group_sources(read_csv(self.candidates_path))
        decided = latest_decisions(self.decisions_path)
        return [s for s in sources if (s["source_position"], s["video_id"]) not in decided]

    def append_decision(self, payload: dict) -> None:
        self.decisions_path.parent.mkdir(parents=True, exist_ok=True)
        with self.decisions_path.open("a", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")

    def progress(self) -> tuple[int, int]:
        total = len(group_sources(read_csv(self.candidates_path)))
        decided = len(latest_decisions(self.decisions_path))
        return decided, total

    def render(self, index: int = 0) -> bytes:
        queue = self.queue()
        decided, total = self.progress()
        if not queue:
            return self.page(
                "Review complete",
                f"""
                <main class="done">
                  <h1>Broader review complete</h1>
                  <p>{decided} of {total} sources decided. No unresolved sources remain.</p>
                </main>
                """,
            )

        index = max(0, min(index, len(queue) - 1))
        source = queue[index]
        candidates_html = "".join(self.candidate_card(c) for c in source["candidates"])
        accept_buttons = "".join(
            f'<button name="decision" value="accept_{c.get("candidate_rank")}" type="submit">Accept #{esc(c.get("candidate_rank"))}</button>'
            for c in source["candidates"]
        )

        candidate_inputs = "".join(
            f'<input type="hidden" name="candidate_{c.get("candidate_rank")}_id" value="{esc(c.get("getsongbpm_song_id"))}">'
            f'<input type="hidden" name="candidate_{c.get("candidate_rank")}_artist" value="{esc(c.get("getsongbpm_artist"))}">'
            f'<input type="hidden" name="candidate_{c.get("candidate_rank")}_title" value="{esc(c.get("getsongbpm_title"))}">'
            f'<input type="hidden" name="candidate_{c.get("candidate_rank")}_score" value="{esc(c.get("candidate_score"))}">'
            f'<input type="hidden" name="candidate_{c.get("candidate_rank")}_variant" value="{esc(c.get("candidate_variant"))}">'
            for c in source["candidates"]
        )

        body = f"""
        <main>
          <header>
            <div>
              <h1>GetSongBPM Broader Review</h1>
              <p>{index + 1} of {len(queue)} unresolved sources &middot; {decided} of {total} decided overall</p>
            </div>
            <nav>
              <a href="/?{urlencode({'index': max(0, index - 1)})}">Previous</a>
              <a href="/?{urlencode({'index': min(len(queue) - 1, index + 1)})}">Next</a>
            </nav>
          </header>

          <section class="source">
            <h2>Your Song</h2>
            <dl>
              <dt>Artist</dt><dd>{esc(source['normalized_artists'])}</dd>
              <dt>Title</dt><dd>{esc(source['normalized_title'])}</dd>
              <dt>YouTube</dt><dd><a href="{esc(source['video_url'])}" target="_blank" rel="noreferrer">{esc(source['video_id'])}</a></dd>
            </dl>
          </section>

          <section class="candidates">
            {candidates_html}
          </section>

          <form method="POST" action="/decision">
            <input type="hidden" name="source_position" value="{esc(source['source_position'])}">
            <input type="hidden" name="video_id" value="{esc(source['video_id'])}">
            <input type="hidden" name="normalized_artists" value="{esc(source['normalized_artists'])}">
            <input type="hidden" name="normalized_title" value="{esc(source['normalized_title'])}">
            <input type="hidden" name="index" value="{esc(index)}">
            {candidate_inputs}
            <label>Notes
              <textarea name="notes" placeholder="Optional"></textarea>
            </label>
            <fieldset class="manual">
              <legend>Manual entry &mdash; use when no candidate fits but you know the values</legend>
              <div class="manual-grid">
                <label>Key
                  <input type="text" name="manual_key" placeholder="e.g., Cm, F#, Bb major" autocomplete="off">
                </label>
                <label>BPM
                  <input type="text" name="manual_tempo" inputmode="decimal" placeholder="e.g., 120" autocomplete="off">
                </label>
                <label>Time sig
                  <input type="text" name="manual_time_sig" placeholder="e.g., 4/4" autocomplete="off">
                </label>
              </div>
              <button name="decision" value="manual" type="submit" class="manual-submit">Save manual entry</button>
            </fieldset>
            <div class="actions">
              {accept_buttons}
              <button name="decision" value="reject" type="submit" class="danger">Reject all</button>
              <button name="decision" value="skip" type="submit" class="ghost">Skip</button>
            </div>
          </form>
        </main>
        """
        return self.page("GetSongBPM Broader Review", body)

    def candidate_card(self, candidate: dict) -> str:
        return f"""
        <article>
          <h3>Candidate #{esc(candidate.get('candidate_rank'))} &middot; score {esc(candidate.get('candidate_score'))}</h3>
          <p class="variant">via {esc(candidate.get('candidate_variant'))}</p>
          <dl>
            <dt>Artist</dt><dd>{esc(candidate.get('getsongbpm_artist'))}</dd>
            <dt>Title</dt><dd>{esc(candidate.get('getsongbpm_title'))}</dd>
            <dt>Key</dt><dd>{esc(candidate.get('key_of'))} {esc(candidate.get('mode'))}</dd>
            <dt>Tempo</dt><dd>{esc(candidate.get('tempo'))} BPM</dd>
            <dt>Open key</dt><dd>{esc(candidate.get('open_key'))}</dd>
            <dt>Time sig</dt><dd>{esc(candidate.get('time_sig'))}</dd>
            <dt>GetSongBPM</dt><dd><a href="{esc(candidate.get('getsongbpm_uri'))}" target="_blank" rel="noreferrer">{esc(candidate.get('getsongbpm_song_id'))}</a></dd>
          </dl>
        </article>
        """

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
            main {{ max-width: 1280px; margin: 0 auto; padding: 28px; }}
            header {{ display: flex; justify-content: space-between; gap: 16px; align-items: center; margin-bottom: 20px; }}
            h1 {{ margin: 0; font-size: 28px; }}
            h2 {{ margin: 0 0 14px; font-size: 17px; }}
            h3 {{ margin: 0 0 6px; font-size: 16px; }}
            p {{ color: #5a666a; margin: 6px 0 0; }}
            a {{ color: #0f766e; }}
            nav {{ display: flex; gap: 8px; }}
            nav a, button {{ border: 1px solid #c9d0cf; background: white; color: #1f282b; border-radius: 6px; padding: 9px 14px; text-decoration: none; cursor: pointer; font: inherit; }}
            section.source, article, form {{ background: white; border: 1px solid #d8dddc; border-radius: 8px; padding: 18px; margin-bottom: 16px; }}
            section.candidates {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(0, 1fr)); gap: 14px; margin-bottom: 16px; }}
            section.candidates article {{ margin: 0; }}
            dl {{ display: grid; grid-template-columns: 110px minmax(0, 1fr); gap: 7px 12px; margin: 0; }}
            dt {{ font-weight: 700; color: #4c585c; }}
            dd {{ margin: 0; overflow-wrap: anywhere; }}
            textarea {{ width: 100%; min-height: 64px; box-sizing: border-box; border: 1px solid #c9d0cf; border-radius: 6px; padding: 10px; font: inherit; }}
            label {{ display: grid; gap: 6px; font-weight: 700; color: #4c585c; }}
            .actions {{ display: flex; gap: 10px; margin-top: 14px; flex-wrap: wrap; }}
            .actions button {{ background: #0f766e; color: white; border-color: #0f766e; }}
            .actions button.danger {{ background: #b91c1c; border-color: #b91c1c; }}
            .actions button.ghost {{ background: white; color: #1f282b; border-color: #c9d0cf; }}
            fieldset.manual {{ border: 1px solid #d8dddc; border-radius: 8px; padding: 12px 16px 14px; margin: 14px 0 0; background: #fbfaf4; }}
            fieldset.manual legend {{ font-weight: 700; color: #4c585c; padding: 0 6px; font-size: 13px; }}
            .manual-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-bottom: 10px; }}
            .manual-grid label {{ display: grid; gap: 4px; font-weight: 700; color: #4c585c; font-size: 13px; }}
            .manual-grid input {{ width: 100%; padding: 8px 10px; border: 1px solid #c9d0cf; border-radius: 6px; font: inherit; box-sizing: border-box; }}
            .manual-submit {{ background: #ca8a04; color: white; border-color: #ca8a04; }}
            .variant {{ font-size: 12px; color: #5a666a; margin: 0 0 8px; }}
            .done {{ max-width: 680px; }}
            @media (max-width: 900px) {{
              section.candidates {{ grid-template-columns: 1fr; }}
              dl {{ grid-template-columns: 1fr; }}
              .manual-grid {{ grid-template-columns: 1fr; }}
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
            decision = payload.get("decision", ["skip"])[0]
            try:
                index = int(payload.get("index", ["0"])[0])
            except ValueError:
                index = 0

            if decision == "skip":
                self.redirect(index + 1)
                return

            record = {
                "stage": "broader",
                "source_position": payload.get("source_position", [""])[0],
                "video_id": payload.get("video_id", [""])[0],
                "normalized_artists": payload.get("normalized_artists", [""])[0],
                "normalized_title": payload.get("normalized_title", [""])[0],
                "notes": payload.get("notes", [""])[0].strip(),
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
            }

            if decision == "reject":
                record["decision"] = "reject"
                record["best_match_id"] = ""
                record["best_match_artist"] = ""
                record["best_match_title"] = ""
                record["best_match_score"] = ""
                record["candidate_rank"] = ""
                record["candidate_variant"] = ""
            elif decision == "manual":
                manual_key = payload.get("manual_key", [""])[0].strip()
                manual_tempo = payload.get("manual_tempo", [""])[0].strip()
                manual_time_sig = payload.get("manual_time_sig", [""])[0].strip()
                if not manual_key and not manual_tempo:
                    self.respond(400, b"Enter at least a key or a BPM before saving.", "text/plain")
                    return
                if manual_tempo:
                    try:
                        if float(manual_tempo) <= 0:
                            raise ValueError
                    except ValueError:
                        self.respond(400, b"BPM must be a positive number.", "text/plain")
                        return
                record["decision"] = "manual"
                record["manual_key"] = manual_key
                record["manual_tempo"] = manual_tempo
                record["manual_time_sig"] = manual_time_sig
            elif decision.startswith("accept_"):
                rank = decision.split("_", 1)[1]
                record["decision"] = "accept"
                record["best_match_id"] = payload.get(f"candidate_{rank}_id", [""])[0]
                record["best_match_artist"] = payload.get(f"candidate_{rank}_artist", [""])[0]
                record["best_match_title"] = payload.get(f"candidate_{rank}_title", [""])[0]
                record["best_match_score"] = payload.get(f"candidate_{rank}_score", [""])[0]
                record["candidate_rank"] = rank
                record["candidate_variant"] = payload.get(f"candidate_{rank}_variant", [""])[0]
                if not record["best_match_id"]:
                    self.respond(400, b"Missing candidate id", "text/plain")
                    return
            else:
                self.respond(400, b"Unknown decision", "text/plain")
                return

            app.append_decision(record)
            self.redirect(index)

        def redirect(self, index: int) -> None:
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
        Path(args.candidates).expanduser(),
        Path(args.decisions).expanduser(),
    )
    server = ThreadingHTTPServer((args.host, args.port), make_handler(app))
    print(f"GetSongBPM broader review UI: http://{args.host}:{args.port}")
    print("Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
