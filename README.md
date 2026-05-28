# Music Database

A small static music-library database built from a normalized YouTube Music liked-songs export.

The public page shows the cleaned artist/title catalog and keeps provenance links back to YouTube Music videos. Private auth files, cookies, raw browser exports, and API keys are not stored here.

Tempo and key metadata powered by [GetSongBPM](https://getsongbpm.com/).

## GitHub Pages

This repo includes a GitHub Actions workflow that publishes the root directory to GitHub Pages.

After pushing to GitHub, enable Pages for the repository and choose **GitHub Actions** as the Pages source if GitHub does not enable it automatically.

Expected public URL:

```text
https://hryhola.github.io/music-database/
```
