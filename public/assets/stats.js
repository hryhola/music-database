(function () {
  const chartInstances = [];
  let bubbleZoomState = null;
  let rows = [];

  function countBy(items, getter) {
    const counts = new Map();
    for (const item of items) {
      const key = getter(item);
      counts.set(key, (counts.get(key) || 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }

  function median(values) {
    if (!values.length) {
      return 0;
    }
    const sorted = [...values].sort((a, b) => a - b);
    const middle = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[middle] : Math.round((sorted[middle - 1] + sorted[middle]) / 2);
  }

  function average(values) {
    if (!values.length) {
      return 0;
    }
    return Math.round(values.reduce((sum, value) => sum + value, 0) / values.length);
  }

  function songMeta(song) {
    const parts = [];
    if (song.key_of && song.mode) {
      parts.push(`${song.key_of} ${song.mode}`);
    }
    if (song.tempo_num !== null) {
      parts.push(`${song.tempo_num} BPM`);
    }
    return parts.join(" / ") || "metadata missing";
  }

  function artistMetrics(artist) {
    const keyedSongs = artist.songs.filter((song) => song.key_of && song.mode);
    const tempos = artist.songs.map((song) => song.tempo_num).filter((value) => value !== null);
    const topKeyMode = countBy(keyedSongs, (song) => `${song.key_of} ${song.mode}`)[0];
    return {
      keyCount: keyedSongs.length,
      bpmCount: tempos.length,
      averageBpm: tempos.length ? average(tempos) : "-",
      topKeyMode: topKeyMode ? `${topKeyMode[0]} (${topKeyMode[1]})` : "-",
    };
  }

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function truncateLabel(value, maxCharacters) {
    const label = String(value || "");
    if (label.length <= maxCharacters) {
      return label;
    }
    return `${label.slice(0, Math.max(1, maxCharacters - 3))}...`;
  }

  function bubbleLabelLayout(item, scale) {
    const displayRadius = item.r * scale;
    const labelFont = clamp(displayRadius * 0.26, 8, 18);
    const countFont = clamp(displayRadius * 0.22, 7, 15);
    const maxCharacters = Math.floor((displayRadius * 1.55) / (labelFont * 0.58));
    return {
      countFont,
      displayRadius,
      labelFont,
      maxCharacters,
      showCount: displayRadius >= 58,
      showLabel: displayRadius >= 40 && maxCharacters >= 4,
      strokeWidth: clamp(labelFont * 0.17, 2, 3.4),
    };
  }

  function renderSummary() {
    const tempos = rows.map((row) => row.tempo_num).filter((value) => value !== null);
    const artistCounts = artistData();
    const topArtist = artistCounts[0];
    const items = [
      ["Songs", rows.length],
      ["With key", rows.filter((row) => row.key_of && row.mode).length],
      ["With BPM", tempos.length],
      ["Missing metadata", rows.filter((row) => row.match_status === "missing").length],
      ["Top artist", topArtist ? `${topArtist.name} (${topArtist.count})` : "-"],
      ["Avg / median BPM", `${average(tempos)} / ${median(tempos)}`],
    ];

    document.getElementById("statsSummary").replaceChildren(...items.map(([label, value]) => {
      const card = document.createElement("div");
      card.className = "metric";
      card.innerHTML = `<strong>${MusicData.escapeHtml(MusicData.formatNumber(value))}</strong><span>${MusicData.escapeHtml(label)}</span>`;
      return card;
    }));
  }

  function artistData() {
    const artistMap = new Map();
    for (const row of rows) {
      for (const artist of MusicData.splitArtists(row.normalized_artists)) {
        if (!artistMap.has(artist)) {
          artistMap.set(artist, { name: artist, count: 0, songs: [] });
        }
        const entry = artistMap.get(artist);
        entry.count += 1;
        entry.songs.push(row);
      }
    }
    return [...artistMap.values()].sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
  }

  function renderArtistDetails(artist) {
    const target = document.getElementById("artistDetails");
    if (!artist) {
      target.innerHTML = "<h3>Artists</h3>";
      return;
    }
    const metrics = artistMetrics(artist);
    target.innerHTML = `
      <h3>${MusicData.escapeHtml(artist.name)}</h3>
      <p>${MusicData.formatNumber(artist.count)} songs</p>
      <div class="artist-mini-stats">
        <span><strong>${MusicData.formatNumber(metrics.keyCount)}</strong> with key</span>
        <span><strong>${MusicData.formatNumber(metrics.bpmCount)}</strong> with BPM</span>
        <span><strong>${MusicData.escapeHtml(metrics.averageBpm)}</strong> avg BPM</span>
        <span><strong>${MusicData.escapeHtml(metrics.topKeyMode)}</strong> top key</span>
      </div>
      <ol class="artist-song-list">
        ${artist.songs.slice(0, 12).map((song) => `
          <li>
            <span>${MusicData.escapeHtml(song.normalized_title)}</span>
            <small>${MusicData.escapeHtml(songMeta(song))}</small>
          </li>
        `).join("")}
      </ol>
    `;
  }

  function tooltipHtml(artist) {
    const metrics = artistMetrics(artist);
    return `
      <strong>${MusicData.escapeHtml(artist.name)}</strong>
      <span>${MusicData.formatNumber(artist.count)} songs</span>
      <span>${MusicData.escapeHtml(metrics.topKeyMode)} top key</span>
      <span>${MusicData.escapeHtml(metrics.averageBpm)} avg BPM</span>
      <span>${MusicData.escapeHtml(artist.songs.slice(0, 3).map((song) => song.normalized_title).join(" / "))}</span>
    `;
  }

  function renderArtistBubble() {
    const data = artistData();
    const container = document.getElementById("artistBubble");
    const tooltip = document.getElementById("bubbleTooltip");
    container.replaceChildren();
    renderArtistDetails(data[0]);

    const width = Math.max(320, container.clientWidth);
    const height = Math.max(420, container.clientHeight);
    const root = d3.hierarchy({ name: "artists", children: data })
      .sum((item) => item.count || 0)
      .sort((left, right) => right.value - left.value);
    d3.pack().size([width, height]).padding(3)(root);

    const maxCount = d3.max(data, (item) => item.count) || 1;
    const color = d3.scaleSequential([1, maxCount], d3.interpolateViridis);
    const svg = d3.select(container)
      .append("svg")
      .attr("viewBox", `0 0 ${width} ${height}`)
      .attr("width", "100%")
      .attr("height", "100%")
      .attr("role", "img");
    const viewport = svg.append("g");
    let node = null;
    let selectedArtist = data[0] ? data[0].name : "";
    const updateBubbleLabels = (scale) => {
      if (!node) {
        return;
      }
      node.select(".bubble-label")
        .style("font-size", (item) => `${bubbleLabelLayout(item, scale).labelFont / scale}px`)
        .style("opacity", (item) => bubbleLabelLayout(item, scale).showLabel ? 1 : 0)
        .style("stroke-width", (item) => `${bubbleLabelLayout(item, scale).strokeWidth / scale}px`)
        .text((item) => {
          const layout = bubbleLabelLayout(item, scale);
          return layout.showLabel ? truncateLabel(item.data.name, layout.maxCharacters) : "";
        });
      node.select(".bubble-count")
        .style("font-size", (item) => `${bubbleLabelLayout(item, scale).countFont / scale}px`)
        .style("opacity", (item) => bubbleLabelLayout(item, scale).showCount ? 1 : 0)
        .style("stroke-width", (item) => `${bubbleLabelLayout(item, scale).strokeWidth / scale}px`);
    };
    const selectArtist = (item) => {
      selectedArtist = item.data.name;
      node.classed("selected", (candidate) => candidate.data.name === selectedArtist);
      renderArtistDetails(item.data);
    };
    const focusArtist = (item) => {
      selectArtist(item);
      const nextScale = Math.min(8, Math.max(1.4, Math.min(width, height) / (item.r * 5)));
      const nextTransform = d3.zoomIdentity
        .translate(width / 2 - item.x * nextScale, height / 2 - item.y * nextScale)
        .scale(nextScale);
      svg.transition()
        .duration(420)
        .call(zoom.transform, nextTransform);
    };
    const zoom = d3.zoom()
      .scaleExtent([0.6, 8])
      .on("zoom", (event) => {
        viewport.attr("transform", event.transform);
        updateBubbleLabels(event.transform.k);
      });

    svg.call(zoom);
    bubbleZoomState = { svg, zoom };
    setupBubbleZoomControls();

    node = viewport.selectAll("g")
      .data(root.leaves())
      .enter()
      .append("g")
      .attr("class", "bubble-node")
      .attr("transform", (item) => `translate(${item.x},${item.y})`)
      .on("mouseenter", (event, item) => {
        tooltip.style.display = "block";
        tooltip.innerHTML = tooltipHtml(item.data);
        tooltip.style.left = `${event.clientX + 12}px`;
        tooltip.style.top = `${event.clientY + 12}px`;
      })
      .on("mousemove", (event) => {
        tooltip.style.left = `${event.clientX + 12}px`;
        tooltip.style.top = `${event.clientY + 12}px`;
      })
      .on("mouseleave", () => {
        tooltip.style.display = "none";
      })
      .on("click", (event, item) => {
        event.stopPropagation();
        focusArtist(item);
      });

    node.append("circle")
      .attr("r", (item) => item.r)
      .attr("fill", (item) => color(item.data.count))
      .attr("fill-opacity", 0.92)
      .attr("stroke", "rgba(255,255,255,0.28)")
      .attr("stroke-width", 1);

    node.append("text")
      .attr("class", "bubble-label")
      .attr("dy", "-0.1em");

    node.append("text")
      .attr("class", "bubble-count")
      .attr("dy", "1.15em")
      .text((item) => item.data.count);

    if (data[0]) {
      node.classed("selected", (item) => item.data.name === selectedArtist);
    }
    updateBubbleLabels(1);
  }

  function setupBubbleZoomControls() {
    const zoomIn = document.getElementById("bubbleZoomIn");
    const zoomOut = document.getElementById("bubbleZoomOut");
    const zoomReset = document.getElementById("bubbleZoomReset");
    if (!zoomIn || !zoomOut || !zoomReset) {
      return;
    }

    zoomIn.onclick = () => zoomBubble(1.35);
    zoomOut.onclick = () => zoomBubble(1 / 1.35);
    zoomReset.onclick = () => resetBubbleZoom();
  }

  function zoomBubble(factor) {
    if (!bubbleZoomState) {
      return;
    }
    bubbleZoomState.svg
      .transition()
      .duration(180)
      .call(bubbleZoomState.zoom.scaleBy, factor);
  }

  function resetBubbleZoom() {
    if (!bubbleZoomState) {
      return;
    }
    bubbleZoomState.svg
      .transition()
      .duration(180)
      .call(bubbleZoomState.zoom.transform, d3.zoomIdentity);
  }

  function chart(id, option) {
    const instance = echarts.init(document.getElementById(id), "dark");
    instance.setOption({
      backgroundColor: "transparent",
      textStyle: { color: "#eef5f0" },
      color: ["#43d6b3", "#f7bd55", "#f1789c", "#7aa2ff", "#b58cff", "#73d16d"],
      tooltip: { trigger: "item", backgroundColor: "#0d100f", borderColor: "#46544f", textStyle: { color: "#eef5f0" } },
      grid: { left: 44, right: 18, top: 30, bottom: 42 },
      ...option,
    });
    chartInstances.push(instance);
    return instance;
  }

  function axisStyle() {
    return {
      axisLine: { lineStyle: { color: "#46544f" } },
      axisLabel: { color: "#9ba9a2" },
      splitLine: { lineStyle: { color: "rgba(255,255,255,0.08)" } },
    };
  }

  function renderCharts() {
    const keyCounts = MusicData.KEY_ORDER.map((key) => [key, rows.filter((row) => row.key_of === key).length]);
    chart("keyChart", {
      xAxis: { type: "category", data: keyCounts.map(([key]) => key), ...axisStyle() },
      yAxis: { type: "value", ...axisStyle() },
      series: [{ type: "bar", data: keyCounts.map(([, count]) => count), barMaxWidth: 26 }],
    });

    const modeCounts = [
      { name: "major", value: rows.filter((row) => row.mode === "major").length },
      { name: "minor", value: rows.filter((row) => row.mode === "minor").length },
      { name: "missing", value: rows.filter((row) => !row.mode).length },
    ];
    chart("modeChart", {
      series: [{ type: "pie", radius: ["48%", "72%"], data: modeCounts, label: { color: "#eef5f0" } }],
    });

    const tempos = rows.map((row) => row.tempo_num).filter((value) => value !== null);
    const maxTempo = Math.max(...tempos);
    const bpmBuckets = [];
    for (let start = 40; start <= Math.ceil(maxTempo / 20) * 20; start += 20) {
      bpmBuckets.push([`${start}-${start + 19}`, tempos.filter((tempo) => tempo >= start && tempo <= start + 19).length]);
    }
    chart("bpmChart", {
      xAxis: { type: "category", data: bpmBuckets.map(([bucket]) => bucket), axisLabel: { rotate: 45, color: "#9ba9a2" }, axisLine: { lineStyle: { color: "#46544f" } } },
      yAxis: { type: "value", ...axisStyle() },
      series: [{ type: "bar", data: bpmBuckets.map(([, count]) => count), barMaxWidth: 22 }],
    });

    const topArtists = artistData().slice(0, 20).reverse();
    chart("topArtistsChart", {
      grid: { left: 144, right: 18, top: 20, bottom: 28 },
      xAxis: { type: "value", ...axisStyle() },
      yAxis: { type: "category", data: topArtists.map((item) => item.name), ...axisStyle() },
      series: [{ type: "bar", data: topArtists.map((item) => item.count), barMaxWidth: 14 }],
    });

    chart("coverageChart", {
      series: [{
        type: "pie",
        radius: ["50%", "74%"],
        data: [
          { name: "with metadata", value: rows.filter((row) => row.match_status !== "missing").length },
          { name: "missing", value: rows.filter((row) => row.match_status === "missing").length },
        ],
        label: { color: "#eef5f0" },
      }],
    });
  }

  async function boot() {
    try {
      const loaded = await MusicData.loadCatalog();
      rows = loaded.rows;
      renderSummary();
      renderArtistBubble();
      renderCharts();
      window.addEventListener("resize", () => {
        chartInstances.forEach((instance) => instance.resize());
      });
    } catch (error) {
      document.querySelector(".app-main").innerHTML = `<div class="empty-state">${MusicData.escapeHtml(error.message)}</div>`;
    }
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
