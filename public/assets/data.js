(function () {
  const SCRIPT_URL = new URL(document.currentScript.src);
  const DATA_URL = new URL("../data/music_catalog.csv", SCRIPT_URL).href;
  const MANIFEST_URL = new URL("../data/music_catalog_manifest.json", SCRIPT_URL).href;
  const KEY_ORDER = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
  const EXPORT_FIELDS = [
    "source_position",
    "video_id",
    "video_url",
    "normalized_artists",
    "normalized_title",
    "original_artists",
    "original_title",
    "album",
    "duration_seconds",
    "key_of",
    "mode",
    "tempo",
    "time_sig",
    "open_key",
    "match_status",
    "match_score",
    "match_reason",
    "metadata_source",
    "getsongbpm_song_id",
    "getsongbpm_title",
    "getsongbpm_artist",
    "getsongbpm_uri",
    "danceability",
    "acousticness",
  ];

  function numberOrNull(value) {
    if (value === null || value === undefined || String(value).trim() === "") {
      return null;
    }
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function normalizeRow(row) {
    const tempo = numberOrNull(row.tempo);
    const duration = numberOrNull(row.duration_seconds);
    const key = row.key_of || "";
    const mode = row.mode || "";
    return {
      ...row,
      tempo_num: tempo,
      duration_num: duration,
      key_mode: key && mode ? `${key} ${mode}` : "",
      bpm_band: tempo === null ? "" : `${Math.floor(tempo / 10) * 10}-${Math.floor(tempo / 10) * 10 + 9}`,
      searchable: [
        row.normalized_artists,
        row.normalized_title,
        row.album,
        row.original_artists,
        row.original_title,
        row.video_id,
      ].join(" ").toLowerCase(),
    };
  }

  function loadCsv(url) {
    return new Promise((resolve, reject) => {
      Papa.parse(url, {
        download: true,
        header: true,
        skipEmptyLines: true,
        complete: (result) => {
          if (result.errors && result.errors.length) {
            reject(new Error(result.errors[0].message));
            return;
          }
          resolve(result.data.map(normalizeRow));
        },
        error: reject,
      });
    });
  }

  async function loadCatalog() {
    const [rows, manifestResponse] = await Promise.all([
      loadCsv(DATA_URL),
      fetch(MANIFEST_URL).catch(() => null),
    ]);
    const manifest = manifestResponse && manifestResponse.ok ? await manifestResponse.json() : null;
    return { rows, manifest };
  }

  function formatNumber(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed.toLocaleString() : String(value || "");
  }

  function formatDuration(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value <= 0) {
      return "";
    }
    const minutes = Math.floor(value / 60);
    const remainder = Math.round(value % 60);
    return `${minutes}:${String(remainder).padStart(2, "0")}`;
  }

  function formatDate(value) {
    if (!value) {
      return "-";
    }
    return String(value).replace("T", " ").slice(0, 16);
  }

  function splitArtists(value) {
    return String(value || "")
      .split(";")
      .map((artist) => artist.trim())
      .filter(Boolean);
  }

  function publicRow(row) {
    return Object.fromEntries(EXPORT_FIELDS.map((field) => [field, row[field] || ""]));
  }

  function downloadCsv(filename, rows) {
    const csv = Papa.unparse(rows.map(publicRow), { columns: EXPORT_FIELDS });
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  function escapeHtml(value) {
    return String(value || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  window.MusicData = {
    DATA_URL,
    MANIFEST_URL,
    KEY_ORDER,
    EXPORT_FIELDS,
    loadCatalog,
    formatNumber,
    formatDuration,
    formatDate,
    splitArtists,
    downloadCsv,
    escapeHtml,
  };
})();
