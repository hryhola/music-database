#!/usr/bin/env python3
"""Local UI for choosing which GetSongBPM misses are worth chasing further."""

from __future__ import annotations

import argparse
import csv
import html
import json
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote_plus, urlparse

from fetch_getsongbpm_keys import MISS_FIELDS


DEFAULT_MISSES = "data/work/getsongbpm_misses.csv"
DEFAULT_STATE = "data/review/getsongbpm_miss_filter_state.json"
DEFAULT_SELECTED = "data/review/getsongbpm_miss_filter_selected.csv"
DEFAULT_REJECTED = "data/review/getsongbpm_miss_filter_rejected.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Filter GetSongBPM misses before deeper search.")
    parser.add_argument("--misses", default=DEFAULT_MISSES, help="Misses CSV to review.")
    parser.add_argument("--state", default=DEFAULT_STATE, help="Saved triage state JSON.")
    parser.add_argument("--selected", default=DEFAULT_SELECTED, help="Selected misses CSV output.")
    parser.add_argument("--rejected", default=DEFAULT_REJECTED, help="Unselected misses CSV output.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument("--port", type=int, default=8767, help="Port to bind.")
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MISS_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def row_key(row: dict[str, str]) -> str:
    return f"{row.get('source_position', '')}::{row.get('video_id', '')}"


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def json_for_script(value: object) -> str:
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c").replace("&", "\\u0026")


class MissFilterApp:
    def __init__(self, misses_path: Path, state_path: Path, selected_path: Path, rejected_path: Path):
        self.misses_path = misses_path
        self.state_path = state_path
        self.selected_path = selected_path
        self.rejected_path = rejected_path

    def rows(self) -> list[dict[str, str]]:
        return read_csv(self.misses_path)

    def state(self, rows: list[dict[str, str]]) -> dict:
        all_keys = [row_key(row) for row in rows]
        if not self.state_path.exists():
            selected = all_keys
        else:
            try:
                payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {}
            all_key_set = set(all_keys)
            selected = [key for key in payload.get("selected_keys", all_keys) if key in all_key_set]
        selected_set = set(selected)
        return {
            "selected_keys": selected,
            "selected_count": len(selected_set),
            "rejected_count": len(all_keys) - len(selected_set),
            "total_count": len(all_keys),
        }

    def save(self, selected_keys: list[str]) -> dict:
        rows = self.rows()
        rows_by_key = {row_key(row): row for row in rows}
        valid_selected = [key for key in selected_keys if key in rows_by_key]
        selected_set = set(valid_selected)
        selected_rows = [row for row in rows if row_key(row) in selected_set]
        rejected_rows = [row for row in rows if row_key(row) not in selected_set]

        write_csv(self.selected_path, selected_rows)
        write_csv(self.rejected_path, rejected_rows)

        state = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": str(self.misses_path),
            "source_count": len(rows),
            "selected_count": len(selected_rows),
            "rejected_count": len(rejected_rows),
            "selected_csv": str(self.selected_path),
            "rejected_csv": str(self.rejected_path),
            "selected_keys": [row_key(row) for row in selected_rows],
            "rejected_keys": [row_key(row) for row in rejected_rows],
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return state

    def render(self) -> bytes:
        rows = self.rows()
        state = self.state(rows)
        payload_rows = [
            {
                **row,
                "key": row_key(row),
                "search_url": "https://getsongbpm.com/search?q="
                + quote_plus(f"{row.get('normalized_artists', '')} {row.get('normalized_title', '')}"),
            }
            for row in rows
        ]
        body = f"""<!doctype html>
        <html lang="en">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>GetSongBPM Miss Triage</title>
          <style>
            :root {{
              color-scheme: light;
              font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
              --bg: #f5f7f4;
              --ink: #182225;
              --muted: #5c6a70;
              --line: #d9dfdd;
              --panel: #fff;
              --accent: #0f766e;
            }}
            * {{ box-sizing: border-box; }}
            body {{ margin: 0; background: var(--bg); color: var(--ink); }}
            header {{ position: sticky; top: 0; z-index: 4; background: var(--panel); border-bottom: 1px solid var(--line); }}
            main, .top {{ width: min(1280px, calc(100% - 28px)); margin: 0 auto; }}
            .top {{ padding: 18px 0; display: grid; gap: 14px; }}
            h1 {{ margin: 0; font-size: 28px; letter-spacing: 0; }}
            p {{ margin: 4px 0 0; color: var(--muted); line-height: 1.45; }}
            .toolbar {{ display: grid; grid-template-columns: minmax(260px, 1fr) 180px auto auto auto auto; gap: 8px; align-items: center; }}
            input, select, button {{ min-height: 40px; border: 1px solid var(--line); border-radius: 6px; background: #fff; color: var(--ink); font: inherit; padding: 8px 10px; }}
            button {{ cursor: pointer; white-space: nowrap; }}
            button.primary {{ background: var(--accent); border-color: var(--accent); color: #fff; }}
            button.secondary {{ background: #eef3f0; }}
            .stats {{ display: flex; gap: 8px; flex-wrap: wrap; }}
            .stat {{ background: #eef3f0; border: 1px solid var(--line); border-radius: 6px; padding: 8px 10px; color: var(--muted); }}
            .stat strong {{ color: var(--ink); }}
            main {{ padding: 16px 0 28px; }}
            .notice {{ min-height: 22px; color: var(--accent); margin-bottom: 10px; }}
            .table-shell {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; overflow: auto; }}
            table {{ width: 100%; border-collapse: collapse; table-layout: fixed; min-width: 980px; }}
            th, td {{ text-align: left; border-bottom: 1px solid var(--line); padding: 9px 10px; vertical-align: top; overflow-wrap: anywhere; }}
            th {{ position: sticky; top: 0; background: #eef3f0; color: #354246; font-size: 13px; z-index: 2; }}
            tr.off {{ color: #7d888c; background: #fbfbfa; }}
            tr.off td.title, tr.off td.artist {{ text-decoration: line-through; }}
            tr:hover {{ background: #f9fbfa; }}
            .keep {{ width: 70px; text-align: center; }}
            .artist {{ width: 20%; }}
            .title {{ width: 26%; }}
            .reason {{ width: 13%; }}
            .suggestion {{ width: 23%; }}
            .links {{ width: 18%; }}
            .links a {{ color: var(--accent); display: inline-block; margin-right: 10px; }}
            .empty {{ padding: 28px; color: var(--muted); }}
            @media (max-width: 920px) {{
              .toolbar {{ grid-template-columns: 1fr 1fr; }}
              .toolbar button.primary {{ grid-column: 1 / -1; }}
            }}
          </style>
        </head>
        <body>
          <header>
            <div class="top">
              <div>
                <h1>GetSongBPM Miss Triage</h1>
                <p>All misses start selected. Unselect rows you do not want to spend more search effort on, then save.</p>
              </div>
              <div class="stats">
                <span class="stat"><strong id="selected-count">0</strong> selected</span>
                <span class="stat"><strong id="unselected-count">0</strong> unselected</span>
                <span class="stat"><strong id="visible-count">0</strong> visible</span>
                <span class="stat"><strong>{len(rows)}</strong> total</span>
              </div>
              <div class="toolbar">
                <input id="search" type="search" placeholder="Search artist, title, suggestion, or video id" autocomplete="off">
                <select id="reason"></select>
                <button id="select-visible" class="secondary" type="button">Select Visible</button>
                <button id="unselect-visible" class="secondary" type="button">Unselect Visible</button>
                <button id="reset" class="secondary" type="button">Reset All</button>
                <button id="save" class="primary" type="button">Save Selection</button>
              </div>
            </div>
          </header>
          <main>
            <div id="notice" class="notice"></div>
            <section class="table-shell" aria-live="polite">
              <table>
                <thead>
                  <tr>
                    <th class="keep">Keep</th>
                    <th class="artist">Artist</th>
                    <th class="title">Title</th>
                    <th class="reason">Reason</th>
                    <th class="suggestion">Current Candidate</th>
                    <th class="links">Links</th>
                  </tr>
                </thead>
                <tbody id="rows"></tbody>
              </table>
            </section>
          </main>
          <script>
            const rows = {json_for_script(payload_rows)};
            const initialSelected = new Set({json_for_script(state["selected_keys"])});
            const selected = new Set(initialSelected);
            let visible = [];

            function text(value) {{
              return String(value || "");
            }}

            function escapeHtml(value) {{
              return text(value)
                .replaceAll("&", "&amp;")
                .replaceAll("<", "&lt;")
                .replaceAll(">", "&gt;")
                .replaceAll('"', "&quot;")
                .replaceAll("'", "&#039;");
            }}

            function escapeAttr(value) {{
              return escapeHtml(value).replaceAll("`", "&#096;");
            }}

            function rowMatches(row) {{
              const query = document.getElementById("search").value.trim().toLowerCase();
              const reason = document.getElementById("reason").value;
              const haystack = [
                row.normalized_artists,
                row.normalized_title,
                row.reason,
                row.best_match_artist,
                row.best_match_title,
                row.video_id
              ].join(" ").toLowerCase();
              return (!query || haystack.includes(query)) && (!reason || row.reason === reason);
            }}

            function renderReasons() {{
              const select = document.getElementById("reason");
              const reasons = [...new Set(rows.map((row) => row.reason).filter(Boolean))].sort();
              select.replaceChildren(
                Object.assign(document.createElement("option"), {{ value: "", textContent: "All reasons" }}),
                ...reasons.map((reason) => Object.assign(document.createElement("option"), {{
                  value: reason,
                  textContent: reason.replaceAll("_", " ")
                }}))
              );
            }}

            function renderStats() {{
              document.getElementById("selected-count").textContent = selected.size.toLocaleString();
              document.getElementById("unselected-count").textContent = (rows.length - selected.size).toLocaleString();
              document.getElementById("visible-count").textContent = visible.length.toLocaleString();
            }}

            function renderRows() {{
              visible = rows.filter(rowMatches);
              renderStats();
              const body = document.getElementById("rows");
              if (!visible.length) {{
                body.innerHTML = '<tr><td colspan="6" class="empty">No rows match the current filters.</td></tr>';
                return;
              }}
              body.replaceChildren(...visible.map((row) => {{
                const checked = selected.has(row.key);
                const tr = document.createElement("tr");
                tr.className = checked ? "" : "off";
                tr.innerHTML = `
                  <td class="keep"><input type="checkbox" data-key="${{escapeAttr(row.key)}}" ${{checked ? "checked" : ""}} aria-label="Keep ${{escapeAttr(row.normalized_artists)}} - ${{escapeAttr(row.normalized_title)}}"></td>
                  <td class="artist">${{escapeHtml(row.normalized_artists)}}</td>
                  <td class="title">${{escapeHtml(row.normalized_title)}}</td>
                  <td class="reason">${{escapeHtml(row.reason.replaceAll("_", " "))}}<br>${{escapeHtml(row.best_match_score || "")}}</td>
                  <td class="suggestion">${{escapeHtml(row.best_match_artist || "-")}}<br>${{escapeHtml(row.best_match_title || "")}}</td>
                  <td class="links">
                    <a href="${{escapeAttr(row.video_url)}}" target="_blank" rel="noreferrer">YouTube</a>
                    <a href="${{escapeAttr(row.search_url)}}" target="_blank" rel="noreferrer">Search</a>
                  </td>
                `;
                return tr;
              }}));
            }}

            function syncRenderedSelection() {{
              document.querySelectorAll('#rows input[type=checkbox][data-key]').forEach((checkbox) => {{
                const checked = selected.has(checkbox.dataset.key);
                checkbox.checked = checked;
                const tr = checkbox.closest('tr');
                if (tr) tr.className = checked ? '' : 'off';
              }});
              renderStats();
            }}

            function preserveScroll(callback) {{
              const scrollX = window.scrollX;
              const scrollY = window.scrollY;
              callback();
              requestAnimationFrame(() => window.scrollTo(scrollX, scrollY));
            }}

            function updateVisibleSelection(shouldSelect) {{
              preserveScroll(() => {{
                for (const row of visible) {{
                  if (shouldSelect) selected.add(row.key);
                  else selected.delete(row.key);
                }}
                syncRenderedSelection();
              }});
            }}

            async function saveSelection() {{
              const button = document.getElementById("save");
              const notice = document.getElementById("notice");
              button.disabled = true;
              notice.textContent = "Saving...";
              try {{
                const response = await fetch("/save", {{
                  method: "POST",
                  headers: {{ "content-type": "application/json" }},
                  body: JSON.stringify({{ selected_keys: [...selected] }})
                }});
                if (!response.ok) throw new Error(await response.text());
                const state = await response.json();
                notice.textContent = `Saved ${{state.selected_count.toLocaleString()}} selected and ${{state.rejected_count.toLocaleString()}} unselected.`;
              }} catch (error) {{
                notice.textContent = `Save failed: ${{error.message}}`;
              }} finally {{
                button.disabled = false;
              }}
            }}

            document.getElementById("rows").addEventListener("change", (event) => {{
              const checkbox = event.target.closest("input[type=checkbox][data-key]");
              if (!checkbox) return;
              preserveScroll(() => {{
                if (checkbox.checked) selected.add(checkbox.dataset.key);
                else selected.delete(checkbox.dataset.key);
                const tr = checkbox.closest('tr');
                if (tr) tr.className = checkbox.checked ? '' : 'off';
                renderStats();
              }});
            }});
            document.getElementById("search").addEventListener("input", renderRows);
            document.getElementById("reason").addEventListener("change", renderRows);
            document.getElementById("select-visible").addEventListener("click", () => updateVisibleSelection(true));
            document.getElementById("unselect-visible").addEventListener("click", () => updateVisibleSelection(false));
            document.getElementById("reset").addEventListener("click", () => {{
              preserveScroll(() => {{
                selected.clear();
                for (const row of rows) selected.add(row.key);
                syncRenderedSelection();
              }});
            }});
            document.getElementById("save").addEventListener("click", saveSelection);

            renderReasons();
            renderRows();
          </script>
        </body>
        </html>"""
        return body.encode("utf-8")


def make_handler(app: MissFilterApp) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_HEAD(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path not in {"/", "/index.html"}:
                self.respond(404, b"Not found", "text/plain; charset=utf-8")
                return
            self.respond(200, app.render())

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path != "/save":
                self.respond(404, b"Not found", "text/plain; charset=utf-8")
                return
            try:
                length = int(self.headers.get("content-length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                selected_keys = payload.get("selected_keys", [])
                if not isinstance(selected_keys, list):
                    raise ValueError("selected_keys must be a list")
                state = app.save([str(key) for key in selected_keys])
            except (json.JSONDecodeError, ValueError) as exc:
                self.respond(400, str(exc).encode("utf-8"), "text/plain; charset=utf-8")
                return
            self.respond(200, json.dumps(state, ensure_ascii=False).encode("utf-8"), "application/json")

        def respond(self, status: int, body: bytes, content_type: str = "text/html; charset=utf-8") -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def log_message(self, fmt: str, *args: object) -> None:
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    return Handler


def main() -> int:
    args = parse_args()
    app = MissFilterApp(
        Path(args.misses).expanduser(),
        Path(args.state).expanduser(),
        Path(args.selected).expanduser(),
        Path(args.rejected).expanduser(),
    )
    server = ThreadingHTTPServer((args.host, args.port), make_handler(app))
    print(f"GetSongBPM miss triage UI: http://{args.host}:{args.port}")
    print("Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
