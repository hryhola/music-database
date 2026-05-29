# Agent Prompt: GetSongBPM Broader Review Processor

## Context

You are processing a music review queue. Each entry has a "Your Song"
(artist + title) and 0–3 candidate matches sourced from GetSongBPM. Your job is
to decide what to do with each entry: **accept** a candidate, fill in data
**manually** from Tunebat, or **reject** it.

You operate **directly on the data files** — no local HTTP UI. Tunebat is the
only tool that requires a browser, and only when no GetSongBPM candidate fits.

> **Operating modes.** Two modes are supported:
> - **Full review** (default): you can record `accept`, `manual` (via Tunebat),
>   or `reject` decisions.
> - **Candidate-only**: you only ever record `accept` decisions. If no
>   candidate matches, you **skip** the source (no decision written) so it can
>   be picked up by a later Tunebat-enabled pass. Use this mode when Tunebat
>   is unavailable (rate-limited / Cloudflare-blocked) or when you want a
>   reviewable staging file. In this mode you write to a **pending JSONL** via
>   `--decisions data/review/getsongbpm_broader_pending_decisions.jsonl`
>   and pass `--also-check data/review/getsongbpm_broader_decisions.jsonl`
>   so the duplicate guard sees both files.

## Inputs and outputs

| File | Role |
|---|---|
| `data/review/getsongbpm_broader_candidates.csv` | Source rows + their candidates (read-only for you) |
| `data/review/getsongbpm_broader_decisions.jsonl` | Append-only decisions log (one JSON record per line) |

You never write the JSONL by hand. Use the helper CLI (described below), which
locks the file for safe concurrent writes.

## Your two tools

1. **Local CLIs** — read the queue and append decisions:
   - `python scripts/broader_queue.py --start S --end E --format jsonl`
   - `python scripts/record_broader_decision.py …`
2. **Tunebat search** (browser) — only when no candidate matches:
   - `https://tunebat.com/Search?q=ARTIST_NAME+SONG_TITLE`

Do not open any other tabs.

## Per-agent slicing

To avoid agents colliding, every agent is assigned a non-overlapping range of
the **unresolved** queue (the queue already excludes anything decided by the
UI or another agent before you started). Read your slice with:

```bash
python scripts/broader_queue.py --start <YOUR_START> --end <YOUR_END> --format jsonl
```

Each output line is a JSON object describing one source song:

```json
{
  "source_position": "164",
  "video_id": "_Llli2oIIIE",
  "video_url": "https://music.youtube.com/watch?v=_Llli2oIIIE",
  "normalized_artists": "Lian Ross",
  "normalized_title": "Mamy Blue",
  "candidates": [
    { "rank": 1, "score": 0.82,  "getsongbpm_artist": "Céline Dion",  "getsongbpm_title": "Mamy Blue", "key_of": "G",  "mode": "major", "tempo": "109", "getsongbpm_song_id": "68N5BR" },
    { "rank": 2, "score": 0.811, "getsongbpm_artist": "Mathys Roets", "getsongbpm_title": "Mamy Blue", "key_of": "C",  "mode": "major", "tempo": "114", "getsongbpm_song_id": "xG6r2z" },
    { "rank": 3, "score": 0.784, "getsongbpm_artist": "Lara Fabian",  "getsongbpm_title": "Mamy Blue", "key_of": "Dm", "mode": "minor", "tempo": "60",  "getsongbpm_song_id": "g52Jv9" }
  ]
}
```

## Decision protocol (execute in order for each source)

### Step 1 — Read "Your Song"

Note the exact `normalized_artists` and `normalized_title`.

### Step 2 — Evaluate candidates

For each candidate, check whether **both** `getsongbpm_artist` AND
`getsongbpm_title` match "Your Song".

Acceptable, non-essential differences:
- punctuation (hyphens, parentheses, brackets, apostrophes, commas)
- capitalization
- `feat.` / `ft.` / `featuring` variations
- accent / diacritic differences

**Not acceptable** — these are different songs:
- a different artist with the same title
- a `Remastered`, `Live`, `Radio Edit`, `Acoustic`, `Instrumental`, etc. suffix
  when "Your Song" doesn't have it (and vice versa)

### Step 3 — If a matching candidate exists → accept it

```bash
python scripts/record_broader_decision.py \
  --source-position <POS> --video-id <VID> \
  --decision accept --candidate-rank <N> \
  --source-label "agent-<id>" \
  --notes "<short rationale>"
```

Then move to the next source.

### Step 4 — If no candidate matches → search Tunebat

Open `https://tunebat.com/Search?q=ARTIST_NAME+SONG_TITLE` (URL-encode spaces
as `+`). Read **all** visible results. Find the row where both artist and
title match "Your Song" using the same matching rules as Step 2.

### Step 5 — Tunebat result handling

| Situation | Action |
|---|---|
| Single unambiguous match found | Record manual entry with the Tunebat Key and BPM |
| Two or more entries with the **exact** same artist AND title but different Key/BPM | **STOP — escalate to the user** |
| Two or more entries with same artist+title and same Key+BPM (only popularity differs) | Use either — proceed automatically |
| No match found on Tunebat | Record reject |

Manual entry:

```bash
python scripts/record_broader_decision.py \
  --source-position <POS> --video-id <VID> \
  --decision manual --manual-key "<KEY>" --manual-tempo <BPM> \
  --source-label "agent-<id>" \
  --notes "tunebat: <artist> - <title>"
```

Notes on `--manual-key` formatting: use what Tunebat shows verbatim (e.g.
`"G"`, `"G major"`, `"Cm"`, `"F# minor"`). Do **not** populate
`--manual-time-sig` (Tunebat doesn't expose it reliably).

Reject:

```bash
python scripts/record_broader_decision.py \
  --source-position <POS> --video-id <VID> \
  --decision reject \
  --source-label "agent-<id>" \
  --notes "tunebat: not found"
```

### Step 6 — Repeat for the next source.

## Candidate-only mode addendum

When the orchestrator tells you "candidate-only mode":

1. **Never query Tunebat.** Skip Step 4 and Step 5 entirely.
2. For Step 3 (accept), pass `--decisions` and `--also-check` so writes go to
   the pending file but the duplicate guard still considers the main log:
   ```bash
   .venv/bin/python scripts/record_broader_decision.py \
       --source-position <POS> --video-id <VID> \
       --decision accept --candidate-rank <N> \
       --source-label "agent-<id>" \
       --notes "<short rationale>" \
       --decisions data/review/getsongbpm_broader_pending_decisions.jsonl \
       --also-check data/review/getsongbpm_broader_decisions.jsonl
   ```
3. If no candidate matches, **skip silently** — print a `SKIP:` log line but do
   not call the CLI:
   ```
   SKIP: [POS] ARTIST – TITLE → deferred for Tunebat pass
   ```
4. Your final summary must include `skipped: <N>` alongside the accept count.
   `manual` and `reject` counts will always be 0.

## Rules & edge cases

- **Time sig**: never set it. Leave `--manual-time-sig` unused.
- **Never invent values.** Only enter a key/BPM if Tunebat (or a candidate)
  clearly provides it for the *exact* song.
- **Reject** = the song has no usable data source.
- **Duplicate guard**: `scripts/record_broader_decision.py` refuses to overwrite an
  existing decision for a source. If you see that error, you tried to act on
  a source that another agent (or the UI) already decided — skip it and move
  on. Do **not** pass `--allow-duplicate`.
- **Output**: after each decision, log one line to stdout:

  ```
  [POS] ARTIST – TITLE → ACTION (key, bpm) | source: candidate#N | tunebat | rejected
  ```

  Example: `[164] Lian Ross – Mamy Blue → manual: G major, 109 BPM | source: tunebat`

## Blockers — stop and ask the user if:

- Tunebat shows exact duplicate entries (same artist + same title char-by-char)
  with different Key or BPM values.
- You are genuinely unsure whether an artist name matches
  (e.g., "The Beatles" vs "Beatles", aliases, mononyms).
- Any unexpected page state, error, or rate-limit appears on Tunebat.

In those cases, record nothing for that source and report the source_position +
video_id to the user.
