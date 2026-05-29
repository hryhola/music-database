(function () {
  const state = {
    query: "",
    keys: new Set(),
    mode: "",
    bpmTarget: "",
    bpmMargin: "0",
    group: "",
  };

  let table = null;
  let rows = [];
  let manifest = null;

  function el(id) {
    return document.getElementById(id);
  }

  function setText(id, value) {
    el(id).textContent = value;
  }

  function renderKeyFilter() {
    const container = el("keyFilter");
    container.replaceChildren(...MusicData.KEY_ORDER.map((key) => {
      const label = document.createElement("label");
      label.className = "key-chip";
      label.innerHTML = `
        <input type="checkbox" value="${key}">
        <span>${key}</span>
      `;
      label.querySelector("input").addEventListener("change", (event) => {
        if (event.target.checked) {
          state.keys.add(key);
        } else {
          state.keys.delete(key);
        }
        applyTableState();
      });
      return label;
    }));
  }

  function normalizeBpmFilter() {
    const target = Number(state.bpmTarget);
    const margin = Number(state.bpmMargin || 0);
    return {
      enabled: state.bpmTarget !== "" && Number.isFinite(target),
      target,
      margin: Number.isFinite(margin) && margin >= 0 ? margin : 0,
    };
  }

  function catalogFilter(data) {
    if (state.query && !data.searchable.includes(state.query)) {
      return false;
    }

    if (state.keys.size && !state.keys.has(data.key_of)) {
      return false;
    }

    if (state.mode === "missing") {
      if (data.mode) {
        return false;
      }
    } else if (state.mode && data.mode !== state.mode) {
      return false;
    }

    const bpm = normalizeBpmFilter();
    if (bpm.enabled) {
      if (data.tempo_num === null) {
        return false;
      }
      if (Math.abs(data.tempo_num - bpm.target) > bpm.margin) {
        return false;
      }
    }

    return true;
  }

  function groupValue(data) {
    if (state.group === "artist") {
      return data.normalized_artists || "Missing artist";
    }
    if (state.group === "key") {
      return data.key_of || "Missing key";
    }
    if (state.group === "mode") {
      return data.mode || "Missing mode";
    }
    if (state.group === "key_mode") {
      return data.key_mode || "Missing key/mode";
    }
    if (state.group === "bpm_band") {
      return data.bpm_band || "Missing BPM";
    }
    return "";
  }

  function applyTableState() {
    if (!table) {
      return;
    }
    table.setFilter(catalogFilter);
    table.setGroupBy(state.group ? groupValue : false);
  }

  function updateMetrics(activeRows) {
    const visibleRows = activeRows ? activeRows.map((row) => row.getData()) : table.getData("active");
    setText("totalCount", MusicData.formatNumber(rows.length));
    setText("visibleCount", MusicData.formatNumber(visibleRows.length));
    setText("keyCount", MusicData.formatNumber(visibleRows.filter((row) => row.key_of && row.mode).length));
    setText("tempoCount", MusicData.formatNumber(visibleRows.filter((row) => row.tempo).length));
  }

  function textFormatter(field) {
    return (cell) => MusicData.escapeHtml(cell.getData()[field] || "");
  }

  function keyFormatter(cell) {
    const value = cell.getValue();
    return value ? MusicData.escapeHtml(value) : '<span class="muted">-</span>';
  }

  function modeFormatter(cell) {
    const value = cell.getValue();
    return value ? MusicData.escapeHtml(value) : '<span class="muted">-</span>';
  }

  function bpmFormatter(cell) {
    const value = cell.getValue();
    return value ? `${MusicData.escapeHtml(value)} BPM` : '<span class="muted">-</span>';
  }

  function durationFormatter(cell) {
    return MusicData.formatDuration(cell.getValue()) || '<span class="muted">-</span>';
  }

  function actionsFormatter(cell) {
    const data = cell.getData();
    const youtubeAction = data.video_url
      ? `<a class="icon-link-button youtube-action" href="${MusicData.escapeHtml(data.video_url)}" target="_blank" rel="noreferrer" aria-label="Open in YouTube Music" title="Open in YouTube Music"><span class="youtube-glyph" aria-hidden="true"></span></a>`
      : '<span class="icon-link-button disabled" aria-hidden="true">-</span>';
    return `
      <div class="actions-cell">
        ${youtubeAction}
        <button class="details-button" type="button">Details</button>
      </div>
    `;
  }

  function showDetails(row) {
    const dialog = el("detailsDialog");
    const title = el("detailsTitle");
    const artist = el("detailsArtist");
    const body = el("detailsBody");
    const detailRows = [
      ["Original artist", row.original_artists],
      ["Original title", row.original_title],
      ["Source position", row.source_position],
      ["Video ID", row.video_id],
      ["YouTube Music", row.video_url],
      ["Metadata source", row.metadata_source],
      ["Match status", row.match_status],
      ["Match reason", row.match_reason],
      ["Match score", row.match_score],
      ["GetSongBPM artist", row.getsongbpm_artist],
      ["GetSongBPM title", row.getsongbpm_title],
      ["GetSongBPM song ID", row.getsongbpm_song_id],
      ["GetSongBPM URL", row.getsongbpm_uri],
      ["Open key", row.open_key],
      ["Time signature", row.time_sig],
      ["Danceability", row.danceability],
      ["Acousticness", row.acousticness],
      ["Duration", MusicData.formatDuration(row.duration_seconds)],
    ];

    artist.textContent = row.normalized_artists || "Unknown artist";
    title.textContent = row.normalized_title || "Untitled";
    body.innerHTML = `<dl class="details-grid">${detailRows.map(([label, value]) => {
      const renderedValue = value && String(value).startsWith("http")
        ? `<a href="${MusicData.escapeHtml(value)}" target="_blank" rel="noreferrer">${MusicData.escapeHtml(value)}</a>`
        : MusicData.escapeHtml(value || "-");
      return `<div class="detail-item"><dt>${MusicData.escapeHtml(label)}</dt><dd>${renderedValue}</dd></div>`;
    }).join("")}</dl>`;

    if (typeof dialog.showModal === "function") {
      dialog.showModal();
    } else {
      dialog.setAttribute("open", "");
    }
  }

  function setupTable() {
    table = new Tabulator("#catalogTable", {
      data: rows,
      layout: "fitColumns",
      placeholder: "No rows match the current filters.",
      initialSort: [{ column: "source_position", dir: "asc" }],
      groupHeader: (value, count) => `${MusicData.escapeHtml(value)} <span class="muted">(${count})</span>`,
      columns: [
        { title: "Artist", field: "normalized_artists", minWidth: 160, formatter: textFormatter("normalized_artists") },
        { title: "Title", field: "normalized_title", minWidth: 200, formatter: textFormatter("normalized_title") },
        { title: "Key", field: "key_of", width: 76, hozAlign: "center", formatter: keyFormatter },
        { title: "Mode", field: "mode", width: 96, hozAlign: "center", formatter: modeFormatter },
        { title: "BPM", field: "tempo_num", width: 82, hozAlign: "right", sorter: "number", formatter: bpmFormatter },
        { title: "Album", field: "album", minWidth: 150, formatter: textFormatter("album") },
        { title: "Duration", field: "duration_num", width: 94, hozAlign: "right", sorter: "number", formatter: durationFormatter },
        {
          title: "Actions",
          field: "actions",
          width: 136,
          hozAlign: "center",
          formatter: actionsFormatter,
          headerSort: false,
          cellClick: (event, cell) => {
            if (event.target.closest(".details-button")) {
              showDetails(cell.getRow().getData());
            }
          },
        },
      ],
    });

    table.on("dataFiltered", (_filters, activeRows) => updateMetrics(activeRows));
    table.on("dataLoaded", () => updateMetrics());
    table.on("tableBuilt", () => {
      applyTableState();
      updateMetrics();
    });
  }

  function setupControls() {
    el("searchInput").addEventListener("input", (event) => {
      state.query = event.target.value.trim().toLowerCase();
      applyTableState();
    });

    el("groupSelect").addEventListener("change", (event) => {
      state.group = event.target.value;
      applyTableState();
    });

    el("bpmTarget").addEventListener("input", (event) => {
      state.bpmTarget = event.target.value.trim();
      applyTableState();
    });

    el("bpmMargin").addEventListener("input", (event) => {
      state.bpmMargin = event.target.value.trim();
      applyTableState();
    });

    el("modeFilter").addEventListener("click", (event) => {
      const button = event.target.closest("button[data-mode]");
      if (!button) {
        return;
      }
      state.mode = button.dataset.mode;
      el("modeFilter").querySelectorAll("button").forEach((item) => {
        item.classList.toggle("active", item === button);
      });
      applyTableState();
    });

    el("clearFilters").addEventListener("click", () => {
      state.query = "";
      state.keys.clear();
      state.mode = "";
      state.bpmTarget = "";
      state.bpmMargin = "0";
      state.group = "";
      el("searchInput").value = "";
      el("bpmTarget").value = "";
      el("bpmMargin").value = "0";
      el("groupSelect").value = "";
      el("keyFilter").querySelectorAll("input").forEach((input) => {
        input.checked = false;
      });
      el("modeFilter").querySelectorAll("button").forEach((button) => {
        button.classList.toggle("active", button.dataset.mode === "");
      });
      applyTableState();
    });

    el("downloadFiltered").addEventListener("click", () => {
      MusicData.downloadCsv("music_catalog_filtered.csv", table.getData("active"));
    });

    el("closeDetails").addEventListener("click", () => el("detailsDialog").close());
    el("detailsDialog").addEventListener("click", (event) => {
      if (event.target === el("detailsDialog")) {
        el("detailsDialog").close();
      }
    });
  }

  async function boot() {
    try {
      const loaded = await MusicData.loadCatalog();
      rows = loaded.rows;
      manifest = loaded.manifest;
      document.title = manifest ? `Music Database (${MusicData.formatNumber(manifest.total_rows)})` : "Music Database";
      renderKeyFilter();
      setupControls();
      setupTable();
    } catch (error) {
      document.querySelector(".table-panel").innerHTML = `<div class="empty-state">${MusicData.escapeHtml(error.message)}</div>`;
    }
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
