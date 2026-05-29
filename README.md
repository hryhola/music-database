# Music Database

Static music-library catalog built from a normalized YouTube Music liked-songs export.

The public site is intentionally small: it reads one primary CSV, `public/data/music_catalog.csv`, and shows artist/title, provenance, musical key, mode, and tempo where available.

Tempo and key metadata are powered by [GetSongBPM](https://getsongbpm.com/) plus manual Tunebat lookups for songs that could not be matched cleanly through the API.

## Repo Layout

- `public/`: deployable static site.
- `public/data/music_catalog.csv`: primary catalog data file. Use this first.
- `public/data/music_catalog_manifest.json`: public row counts and generation timestamp.
- `data/source/`: source-level normalized YouTube Music data.
- `data/work/`: reproducible pipeline outputs and manifests.
- `data/review/`: review queues, decisions, and audit trails.
- `scripts/`: fetch, review, merge, normalization, and catalog build tools.
- `tests/`: unit tests for matching and key normalization.

## Current Data

- Total catalog rows: 1,995
- Rows with matched/manual metadata: 1,192
- Rows with complete normalized key + mode: 1,171
- Rows still missing key/BPM metadata: 803

Canonical key format:

- `key_of`: pitch class only, using sharps (`C`, `C#`, `D`, ...)
- `mode`: `major` or `minor`
- bare keys from sources are treated as major

## Local Preview

```bash
cd public
python3 -m http.server 8765
```

Open `http://127.0.0.1:8765/`.

## Rebuild Public Data

After changing anything in `data/source`, `data/work`, or `data/review`, rebuild the public catalog:

```bash
.venv/bin/python scripts/build_public_catalog.py
```

## Useful Pipeline Commands

Initial GetSongBPM fetch:

```bash
GETSONGBPM_API_KEY=... .venv/bin/python scripts/fetch_getsongbpm_keys.py
```

Apply manual review decisions:

```bash
.venv/bin/python scripts/apply_getsongbpm_review.py
.venv/bin/python scripts/apply_getsongbpm_broader.py
.venv/bin/python scripts/normalize_key_columns.py data/work/getsongbpm_matches.csv data/review/getsongbpm_broader_candidates.csv
.venv/bin/python scripts/build_public_catalog.py
```

Run tests:

```bash
.venv/bin/python -m unittest discover tests
```

## GitHub Pages

GitHub Actions deploys the `public/` directory to Pages.

Expected public URL:

```text
https://hryhola.github.io/music-database/
```
