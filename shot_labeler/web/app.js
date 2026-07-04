const state = {
  videos: [],
  currentIndex: 0,
  shots: [],
  notes: "",
  pendingRelease: null,
};

const els = {
  datasetPath: document.getElementById("datasetPath"),
  videoCount: document.getElementById("videoCount"),
  labeledCount: document.getElementById("labeledCount"),
  videoList: document.getElementById("videoList"),
  title: document.getElementById("currentTitle"),
  meta: document.getElementById("currentMeta"),
  status: document.getElementById("statusLine"),
  video: document.getElementById("videoPlayer"),
  shotRows: document.getElementById("shotRows"),
  shotTotal: document.getElementById("shotTotal"),
  makeTotal: document.getElementById("makeTotal"),
  missTotal: document.getElementById("missTotal"),
  pendingRelease: document.getElementById("pendingRelease"),
  notes: document.getElementById("notesInput"),
  exportButton: document.getElementById("exportButton"),
};

const MISS_TYPES = [
  "",
  "rim_hit",
  "backboard_miss",
  "airball",
  "blocked",
  "under_basket_interference",
];

function fmt(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return Number(value).toFixed(2);
}

function currentVideo() {
  return state.videos[state.currentIndex] || null;
}

async function loadVideos() {
  const res = await fetch("/api/videos");
  const data = await res.json();
  state.videos = data.videos || [];
  els.datasetPath.textContent = data.labels_path || "";
  renderVideoList();
  if (state.videos.length > 0) {
    loadVideo(0);
  } else {
    setStatus("No videos found in video root.");
  }
}

function renderVideoList() {
  const labeled = state.videos.filter((v) => v.labeled).length;
  els.videoCount.textContent = `${state.videos.length} videos`;
  els.labeledCount.textContent = `${labeled} labeled`;
  els.videoList.innerHTML = "";
  state.videos.forEach((video, index) => {
    const button = document.createElement("button");
    button.className = `video-row ${index === state.currentIndex ? "active" : ""}`;
    button.innerHTML = `
      <span>
        <strong>${escapeHtml(video.video_id)}</strong>
        <small>${escapeHtml(video.scene_type)} · ${video.fps || 30} fps</small>
      </span>
      <span class="badge ${video.labeled ? "done" : ""}">${video.shots?.length || 0}</span>
    `;
    button.addEventListener("click", () => loadVideo(index));
    els.videoList.appendChild(button);
  });
}

function loadVideo(index) {
  const video = state.videos[index];
  if (!video) return;
  state.currentIndex = index;
  state.shots = cloneShots(video.shots || []);
  state.notes = video.notes || "";
  state.pendingRelease = null;
  els.video.src = video.media_url;
  els.video.load();
  els.notes.value = state.notes;
  els.title.textContent = video.video_id;
  els.meta.textContent = `${video.scene_type} · ${video.fps || 30} fps`;
  renderVideoList();
  renderShots();
  setStatus("Loaded.");
}

function cloneShots(shots) {
  return shots
    .filter((shot) => shot && (shot.result === "make" || shot.result === "miss"))
    .map((shot, index) => ({
      attempt: index + 1,
      time_s: Number(shot.time_s),
      result_time_s: Number(shot.result_time_s ?? shot.time_s),
      release_time_s: shot.release_time_s === undefined ? undefined : Number(shot.release_time_s),
      result: shot.result,
      miss_type: shot.miss_type || "",
      notes: shot.notes || "",
    }))
    .sort((a, b) => a.time_s - b.time_s)
    .map((shot, index) => ({ ...shot, attempt: index + 1 }));
}

function renderShots() {
  els.pendingRelease.textContent = fmt(state.pendingRelease);
  const makes = state.shots.filter((shot) => shot.result === "make").length;
  const misses = state.shots.filter((shot) => shot.result === "miss").length;
  els.shotTotal.textContent = `${state.shots.length} shots`;
  els.makeTotal.textContent = `${makes} make`;
  els.missTotal.textContent = `${misses} miss`;

  els.shotRows.innerHTML = "";
  if (state.shots.length === 0) {
    const row = document.createElement("tr");
    row.innerHTML = `<td class="empty-row" colspan="6">No shots labeled.</td>`;
    els.shotRows.appendChild(row);
    return;
  }

  state.shots.forEach((shot, index) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${index + 1}</td>
      <td class="result-${shot.result}">${shot.result}</td>
      <td>${fmt(shot.time_s)}s</td>
      <td>${shot.release_time_s === undefined ? "-" : `${fmt(shot.release_time_s)}s`}</td>
      <td>${typeCell(shot, index)}</td>
      <td><button data-remove="${index}" title="Remove this shot">Remove</button></td>
    `;
    els.shotRows.appendChild(row);
  });
  els.shotRows.querySelectorAll("select[data-type-index]").forEach((select) => {
    select.addEventListener("change", () => {
      const index = Number(select.dataset.typeIndex);
      if (!state.shots[index]) return;
      state.shots[index].miss_type = select.value;
      setStatus(`Updated miss type for shot #${index + 1}.`);
    });
  });
  els.shotRows.querySelectorAll("button[data-remove]").forEach((button) => {
    button.addEventListener("click", () => {
      state.shots.splice(Number(button.dataset.remove), 1);
      renumberShots();
      renderShots();
      setStatus("Shot removed.");
    });
  });
}

function typeCell(shot, index) {
  if (shot.result !== "miss") return `<span class="muted-cell">-</span>`;
  const options = MISS_TYPES.map((value) => {
    const label = value || "none";
    const selected = value === (shot.miss_type || "") ? "selected" : "";
    return `<option value="${escapeHtml(value)}" ${selected}>${escapeHtml(label)}</option>`;
  }).join("");
  return `<select class="type-select" data-type-index="${index}">${options}</select>`;
}

function addShot(result) {
  const time = roundTime(els.video.currentTime || 0);
  const shot = {
    attempt: state.shots.length + 1,
    time_s: time,
    result_time_s: time,
    result,
  };
  if (state.pendingRelease !== null) {
    shot.release_time_s = state.pendingRelease;
  }
  state.shots.push(shot);
  state.shots = cloneShots(state.shots);
  state.pendingRelease = null;
  renderShots();
  setStatus(`Added ${result} at ${fmt(time)}s.`);
}

function markRelease() {
  state.pendingRelease = roundTime(els.video.currentTime || 0);
  renderShots();
  setStatus(`Release marked at ${fmt(state.pendingRelease)}s.`);
}

function clearRelease() {
  state.pendingRelease = null;
  renderShots();
  setStatus("Release marker cleared.");
}

function undoShot() {
  if (state.shots.length === 0) {
    setStatus("No shot to undo.");
    return;
  }
  state.shots.pop();
  renumberShots();
  renderShots();
  setStatus("Last shot removed.");
}

function renumberShots() {
  state.shots = state.shots.map((shot, index) => ({ ...shot, attempt: index + 1 }));
}

async function saveLabels(moveNext = false) {
  const video = currentVideo();
  if (!video) return false;
  const payload = {
    video_index: video.index,
    shots: state.shots,
    notes: els.notes.value,
  };
  const res = await fetch("/api/label", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!data.ok) {
    setStatus(data.error || "Save failed.");
    return false;
  }
  video.shots = cloneShots(data.label.shots || []);
  video.notes = data.label.notes || "";
  video.labeled = video.shots.length > 0;
  renderVideoList();
  setStatus("Saved.");
  if (moveNext) {
    loadVideo(Math.min(state.currentIndex + 1, state.videos.length - 1));
  }
  return true;
}

async function exportJson() {
  const saved = await saveLabels(false);
  if (!saved) return;
  const res = await fetch("/api/export");
  if (!res.ok) {
    setStatus("Export failed.");
    return;
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "labels.json";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  setStatus("Exported labels.json.");
}

function seekBy(seconds) {
  els.video.currentTime = Math.max(0, Math.min((els.video.duration || Infinity), els.video.currentTime + seconds));
}

function frameStep(direction) {
  const video = currentVideo();
  const fps = Number(video?.fps || 30);
  seekBy(direction / Math.max(fps, 1));
}

function roundTime(value) {
  return Math.round(Number(value) * 100) / 100;
}

function setStatus(message) {
  els.status.textContent = message;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function bindControls() {
  document.getElementById("back5Button").addEventListener("click", () => seekBy(-5));
  document.getElementById("back1Button").addEventListener("click", () => seekBy(-1));
  document.getElementById("prevFrameButton").addEventListener("click", () => frameStep(-1));
  document.getElementById("releaseButton").addEventListener("click", markRelease);
  document.getElementById("makeButton").addEventListener("click", () => addShot("make"));
  document.getElementById("missButton").addEventListener("click", () => addShot("miss"));
  document.getElementById("nextFrameButton").addEventListener("click", () => frameStep(1));
  document.getElementById("forward1Button").addEventListener("click", () => seekBy(1));
  document.getElementById("forward5Button").addEventListener("click", () => seekBy(5));
  document.getElementById("undoButton").addEventListener("click", undoShot);
  document.getElementById("clearReleaseButton").addEventListener("click", clearRelease);
  document.getElementById("saveButton").addEventListener("click", () => saveLabels(false));
  document.getElementById("saveNextButton").addEventListener("click", () => saveLabels(true));
  els.exportButton.addEventListener("click", exportJson);

  document.addEventListener("keydown", (event) => {
    const active = document.activeElement;
    if (active && ["TEXTAREA", "INPUT", "SELECT"].includes(active.tagName)) return;
    const key = event.key.toLowerCase();
    if (key === " ") {
      event.preventDefault();
      if (els.video.paused) els.video.play();
      else els.video.pause();
    } else if (key === "a") frameStep(-1);
    else if (key === "d") frameStep(1);
    else if (key === "j") seekBy(-1);
    else if (key === "l") seekBy(1);
    else if (key === "[") seekBy(-5);
    else if (key === "]") seekBy(5);
    else if (key === "s") markRelease();
    else if (key === "m") addShot("make");
    else if (key === "x") addShot("miss");
    else if (key === "u") undoShot();
    else if (key === "c") clearRelease();
    else if (key === "n") saveLabels(true);
    else if (key === "q") saveLabels(false);
  });
}

bindControls();
loadVideos().catch((error) => setStatus(error.message || String(error)));
