const $ = (selector) => document.querySelector(selector);
const tabs = [...document.querySelectorAll(".tab")];
const panes = { upload: $("#uploadPane"), url: $("#urlPane") };
const fileInput = $("#videoFile");
const urlInput = $("#videoUrl");
const processButton = $("#processButton");
const clearButton = $("#clearButton");
const preview = $("#videoPreview");
const previewEmpty = $("#videoEmpty");
const searchInput = $("#transcriptSearch");
const actionButtons = [$("#copyButton"), ...document.querySelectorAll(".download-button")];

let state = "idle";
let activeTab = "upload";
let selectedFile = null;
let objectUrl = null;
let currentJobId = null;
let requestGeneration = 0;
let highestProgress = 0;
let transcriptSegments = [];
let segmentElements = [];
let activeSegmentIndex = -1;
let searchTimer = null;
let feedbackTimer = null;

function formatTimestamp(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  const base = `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  return hours ? `${String(hours).padStart(2, "0")}:${base}` : base;
}

function languageName(code) {
  return ({ bn: "Bengali", en: "English" })[code] || (code ? code.toUpperCase() : "Unknown");
}

function isActive() { return ["submitting", "queued", "validating", "detecting_faces", "extracting_audio", "transcribing"].includes(state); }
function hasSource() { return activeTab === "upload" ? Boolean(selectedFile) : Boolean(urlInput.value.trim()); }
function refreshControls() {
  processButton.disabled = isActive() || !hasSource();
  const hasTranscript = !isActive() && transcriptSegments.length > 0 && Boolean(currentJobId);
  actionButtons.forEach((button) => { button.disabled = !hasTranscript; });
  searchInput.disabled = !hasTranscript;
  $("#clearSearchButton").disabled = !hasTranscript || !searchInput.value;
}

function showBanner(kind, message) {
  const target = kind === "error" ? $("#errorBanner") : $("#warningBanner");
  target.textContent = message; target.hidden = !message;
}
function clearBanners() { showBanner("error", ""); showBanner("warning", ""); }
function showFeedback(message, isError = false) {
  clearTimeout(feedbackTimer);
  const feedback = $("#actionFeedback");
  feedback.textContent = message; feedback.classList.toggle("feedback-error", isError);
  feedbackTimer = setTimeout(() => { feedback.textContent = ""; }, 3000);
}
function setProgress(progress, stage) {
  highestProgress = Math.max(highestProgress, Math.min(100, Number(progress) || 0));
  $("#progressValue").textContent = `${highestProgress}%`;
  $("#progressBar").style.width = `${highestProgress}%`;
  $("#progressStage").textContent = stage;
  $(".progress-track").setAttribute("aria-valuenow", String(highestProgress));
}

function revokeObjectUrl() { if (objectUrl) { URL.revokeObjectURL(objectUrl); objectUrl = null; } }
function setPreview(source, isLocal = false) {
  if (!isLocal) revokeObjectUrl();
  preview.pause(); preview.removeAttribute("src"); preview.load();
  if (source) { preview.src = source; preview.hidden = false; previewEmpty.hidden = true; }
  else { preview.hidden = true; previewEmpty.hidden = false; }
  $("#previewMessage").hidden = true;
}
function chooseFile(file) {
  selectedFile = file || null; clearBanners(); revokeObjectUrl();
  if (selectedFile) { objectUrl = URL.createObjectURL(selectedFile); setPreview(objectUrl, true); state = "source_selected"; }
  else { setPreview(""); state = "idle"; }
  refreshControls();
}
function previewPublicUrl() {
  const url = urlInput.value.trim();
  if (url) { setPreview(url); state = "source_selected"; }
  else { setPreview(""); state = "idle"; }
  refreshControls();
}
preview.addEventListener("error", () => {
  if (activeTab === "url" && urlInput.value.trim()) {
    $("#previewMessage").textContent = "This public URL cannot be previewed by the browser. Timestamps remain available, but seeking requires a playable preview.";
    $("#previewMessage").hidden = false; preview.hidden = true; previewEmpty.hidden = false;
    showBanner("warning", "Browser preview is unavailable for this public URL.");
  }
});

tabs.forEach((tab) => tab.addEventListener("click", () => activateTab(tab.dataset.tab)));
tabs.forEach((tab) => tab.addEventListener("keydown", (event) => {
  if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
  event.preventDefault(); activateTab(activeTab === "upload" ? "url" : "upload", true);
}));
function activateTab(name, focus = false) {
  activeTab = name;
  tabs.forEach((tab) => { const active = tab.dataset.tab === name; tab.classList.toggle("active", active); tab.setAttribute("aria-selected", String(active)); if (focus && active) tab.focus(); });
  Object.entries(panes).forEach(([key, pane]) => { const active = key === name; pane.classList.toggle("active", active); pane.hidden = !active; });
  if (name === "upload" && objectUrl) setPreview(objectUrl, true); else if (name === "url") previewPublicUrl(); else if (!selectedFile) setPreview("");
  refreshControls();
}

function createHighlightedText(text, query) {
  const fragment = document.createDocumentFragment();
  if (!query) { fragment.append(document.createTextNode(text)); return fragment; }
  const foldedText = text.toLocaleLowerCase(); const foldedQuery = query.toLocaleLowerCase();
  let cursor = 0; let match;
  while ((match = foldedText.indexOf(foldedQuery, cursor)) !== -1) {
    fragment.append(document.createTextNode(text.slice(cursor, match)));
    const mark = document.createElement("mark"); mark.textContent = text.slice(match, match + query.length); fragment.append(mark);
    cursor = match + query.length;
  }
  fragment.append(document.createTextNode(text.slice(cursor))); return fragment;
}
function applySearch() {
  const query = searchInput.value.trim(); let matches = 0;
  segmentElements.forEach((article, index) => {
    const text = String(transcriptSegments[index].text || "");
    const matched = !query || text.toLocaleLowerCase().includes(query.toLocaleLowerCase());
    article.classList.toggle("search-dimmed", Boolean(query) && !matched);
    if (query && matched) matches += 1;
    const paragraph = article.querySelector(".chat-text"); paragraph.replaceChildren(createHighlightedText(text, query));
  });
  const count = query ? matches : transcriptSegments.length;
  $("#searchResultCount").textContent = `${count} matching segment${count === 1 ? "" : "s"}`;
  $("#searchEmpty").hidden = !query || matches > 0;
  $("#clearSearchButton").disabled = !query || !transcriptSegments.length;
}
searchInput.addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(applySearch, 180); refreshControls(); });
$("#clearSearchButton").addEventListener("click", () => { searchInput.value = ""; applySearch(); searchInput.focus(); });

async function seekToSegment(segment, index) {
  if (!preview.src || preview.hidden) { showBanner("warning", "Seeking requires a playable video preview."); return; }
  if (preview.readyState < 1) await new Promise((resolve) => preview.addEventListener("loadedmetadata", resolve, { once: true }));
  const duration = Number.isFinite(preview.duration) ? preview.duration : Number(segment.start);
  preview.currentTime = Math.min(Math.max(0, Number(segment.start) || 0), Math.max(0, duration));
  setActiveSegment(index, true);
  try { await preview.play(); } catch { showBanner("warning", "Playback was blocked by the browser. Press play to continue from the selected timestamp."); }
}
function setActiveSegment(index, scroll = false) {
  if (index === activeSegmentIndex) return;
  segmentElements.forEach((element, position) => element.classList.toggle("active-segment", position === index));
  activeSegmentIndex = index;
  if (scroll && index >= 0) segmentElements[index].scrollIntoView({ block: "nearest", behavior: "smooth" });
}
preview.addEventListener("timeupdate", () => {
  const time = preview.currentTime;
  let index = -1;
  for (let position = 0; position < transcriptSegments.length; position += 1) {
    const segment = transcriptSegments[position];
    if (time >= Number(segment.start) && time < Number(segment.end)) { index = position; break; }
  }
  setActiveSegment(index, index >= 0);
});

function renderTranscript(job) {
  const chat = $("#transcriptChat"); const notice = $("#transcriptionNotice");
  transcriptSegments = Array.isArray(job.transcript_json) ? job.transcript_json : [];
  segmentElements = []; activeSegmentIndex = -1; chat.replaceChildren(); searchInput.value = "";
  if (!transcriptSegments.length) {
    chat.hidden = true; notice.hidden = false;
    const title = notice.querySelector("strong"); const detail = notice.querySelector("p");
    if (job.transcription_status === "skipped") title.textContent = "Transcription skipped";
    else if (job.transcription_status === "unavailable") title.textContent = "Transcription unavailable";
    else if (job.transcription_status === "failed") title.textContent = "Transcription failed";
    else title.textContent = "No speech was detected in this video.";
    detail.textContent = job.transcription_warning || "No valid speech segments were produced.";
  } else {
    notice.hidden = true; chat.hidden = false;
    transcriptSegments.forEach((segment, index) => {
      const article = document.createElement("article"); article.className = "chat-message"; article.tabIndex = 0;
      const meta = document.createElement("div"); meta.className = "chat-meta";
      const timestamp = document.createElement("button"); timestamp.type = "button"; timestamp.className = "timestamp-button";
      timestamp.textContent = formatTimestamp(segment.start); timestamp.setAttribute("aria-label", `Seek video to ${formatTimestamp(segment.start)}`);
      timestamp.addEventListener("click", () => seekToSegment(segment, index));
      const end = document.createElement("span"); end.className = "chat-end"; end.textContent = `to ${formatTimestamp(segment.end)}`;
      const speaker = document.createElement("span"); speaker.className = "chat-speaker"; speaker.textContent = "Person 1";
      const text = document.createElement("p"); text.className = "chat-text"; text.textContent = segment.text;
      meta.append(timestamp, end, speaker); article.append(meta, text); chat.append(article); segmentElements.push(article);
    });
  }
  applySearch(); refreshControls();
}

function updateResults(job) {
  $("#faceResult").textContent = job.face_detected ? "Human face detected: Yes" : "Human face detected: No";
  $("#maximumFaces").textContent = job.maximum_face_count ?? "—"; $("#sampledFrames").textContent = job.sampled_frame_count ?? "—";
  $("#averageConfidence").textContent = job.average_detection_confidence == null ? "—" : `${(job.average_detection_confidence * 100).toFixed(1)}%`;
  $("#bestConfidence").textContent = job.best_detection_confidence == null ? "—" : `${(job.best_detection_confidence * 100).toFixed(1)}%`;
  $("#inferenceDevice").textContent = job.inference_device ?? "—"; $("#transcriptionDevice").textContent = job.transcription_device ?? "—";
  $("#detectedLanguage").textContent = job.detected_language ? languageName(job.detected_language) : "—";
  $("#segmentCount").textContent = job.transcription_segment_count ?? 0; $("#identityResult").textContent = "Unknown";
  if (job.video_duration != null) { $(".duration").textContent = formatTimestamp(job.video_duration); $("#resultDuration").textContent = formatTimestamp(job.video_duration); }
  if (job.transcription_warning) showBanner("warning", job.transcription_warning);
  renderTranscript(job);
}
function stageState(job) {
  const stage = String(job.current_stage || "").toLowerCase();
  if (stage.includes("face")) return "detecting_faces"; if (stage.includes("extract")) return "extracting_audio"; if (stage.includes("transcri") || stage.includes("model")) return "transcribing"; if (stage.includes("metadata") || stage.includes("video")) return "validating"; return job.status;
}
async function parseError(response) { try { const body = await response.json(); return body.error?.message || "The request could not be completed."; } catch { return "The request could not be completed."; } }
const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
async function pollJob(pollUrl, generation) {
  for (;;) {
    let response;
    try { response = await fetch(pollUrl, { headers: { Accept: "application/json" } }); }
    catch { if (generation !== requestGeneration) return; throw new Error("Network connection was interrupted. You can safely retry."); }
    if (generation !== requestGeneration) return;
    if (!response.ok) throw new Error(await parseError(response));
    const job = await response.json(); if (generation !== requestGeneration || job.job_id !== currentJobId) return;
    state = stageState(job); setProgress(job.progress, job.current_stage);
    if (job.face_detected != null) updateResults(job);
    if (job.status === "failed") { state = "failed"; throw new Error(job.error_message || "Video processing failed."); }
    if (job.status === "completed") { state = job.transcription_warning ? "completed_with_warning" : "completed"; updateResults(job); refreshControls(); return; }
    await wait(1000);
  }
}

processButton.addEventListener("click", async () => {
  if (isActive() || !hasSource()) return;
  const generation = ++requestGeneration; currentJobId = null; transcriptSegments = []; clearBanners(); renderTranscript({ transcript_json: [], transcription_status: "pending" });
  state = "submitting"; highestProgress = 0; setProgress(2, "Submitting video"); refreshControls();
  try {
    let response;
    if (activeTab === "upload") { const form = new FormData(); form.append("video", selectedFile); response = await fetch("/api/jobs/upload", { method: "POST", body: form }); }
    else { response = await fetch("/api/jobs/url", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url: urlInput.value.trim() }) }); }
    if (generation !== requestGeneration) return;
    if (!response.ok) throw new Error(await parseError(response));
    const accepted = await response.json(); currentJobId = accepted.job_id; state = "queued"; await pollJob(accepted.poll_url, generation);
  } catch (error) { if (generation === requestGeneration) { state = "failed"; showBanner("error", error.message || "The request could not be completed."); } }
  finally { if (generation === requestGeneration) refreshControls(); }
});

function transcriptText() {
  const lines = [`Detected language: ${$("#detectedLanguage").textContent}`, "Identity: Unknown", ""];
  transcriptSegments.forEach((segment) => lines.push(`${formatTimestamp(segment.start)} — Person 1: ${segment.text}`)); return lines.join("\n");
}
async function copyTranscript() {
  const text = transcriptText();
  let area = null;
  try {
    if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(text);
    else { area = document.createElement("textarea"); area.value = text; area.setAttribute("readonly", ""); area.className = "clipboard-fallback"; document.body.append(area); area.select(); if (!document.execCommand("copy")) throw new Error("copy failed"); }
    showFeedback("Transcript copied");
  } catch { showFeedback("Transcript could not be copied. Check clipboard permission.", true); }
  finally { if (area) area.remove(); }
}
$("#copyButton").addEventListener("click", copyTranscript);
document.querySelectorAll(".download-button").forEach((button) => button.addEventListener("click", async () => {
  if (!currentJobId || button.disabled) return; button.disabled = true; showFeedback(`Preparing ${button.dataset.format.toUpperCase()} download…`);
  try {
    const response = await fetch(`/api/jobs/${encodeURIComponent(currentJobId)}/transcript.${button.dataset.format}`);
    if (!response.ok) throw new Error(await parseError(response));
    const blob = await response.blob(); const disposition = response.headers.get("Content-Disposition") || "";
    const filename = disposition.match(/filename="([^"]+)"/)?.[1] || `visionscribe-transcript.${button.dataset.format}`;
    const url = URL.createObjectURL(blob); const anchor = document.createElement("a"); anchor.href = url; anchor.download = filename; document.body.append(anchor); anchor.click(); anchor.remove(); URL.revokeObjectURL(url); showFeedback(`${button.dataset.format.toUpperCase()} downloaded`);
  } catch (error) { showFeedback(error.message || "Download failed.", true); }
  finally { refreshControls(); }
}));

function resetResults() {
  const values = { faceResult: "Not processed", maximumFaces: "—", sampledFrames: "—", averageConfidence: "—", bestConfidence: "—", inferenceDevice: "—", detectedLanguage: "—", transcriptionDevice: "—", segmentCount: "—", resultDuration: "—", identityResult: "Unknown" };
  Object.entries(values).forEach(([id, value]) => { $(`#${id}`).textContent = value; }); $(".duration").textContent = "00:00";
}
function clearWorkflow() {
  requestGeneration += 1; state = "cleared"; currentJobId = null; selectedFile = null; transcriptSegments = []; segmentElements = []; activeSegmentIndex = -1; highestProgress = 0;
  fileInput.value = ""; urlInput.value = ""; searchInput.value = ""; revokeObjectUrl(); setPreview(""); clearBanners(); showFeedback(""); resetResults();
  const notice = $("#transcriptionNotice"); notice.hidden = false; notice.querySelector("strong").textContent = "No transcript yet"; notice.querySelector("p").textContent = "Process a video to detect speech.";
  $("#transcriptChat").replaceChildren(); $("#transcriptChat").hidden = true; $("#searchEmpty").hidden = true; $("#searchResultCount").textContent = "0 matching segments";
  setProgress(0, "Waiting for a video"); activateTab("upload"); state = "idle"; refreshControls();
}
clearButton.addEventListener("click", clearWorkflow);
fileInput.addEventListener("change", () => chooseFile(fileInput.files[0]));
urlInput.addEventListener("input", previewPublicUrl);
const dropzone = $(".dropzone");
["dragenter", "dragover"].forEach((name) => dropzone.addEventListener(name, (event) => { event.preventDefault(); dropzone.classList.add("dragging"); }));
["dragleave", "drop"].forEach((name) => dropzone.addEventListener(name, (event) => { event.preventDefault(); dropzone.classList.remove("dragging"); }));
dropzone.addEventListener("drop", (event) => chooseFile(event.dataTransfer.files[0]));
window.addEventListener("beforeunload", revokeObjectUrl);

async function checkHealth() { const status = $(".system-status"); try { const response = await fetch("/api/health", { headers: { Accept: "application/json" } }); if (!response.ok) throw new Error(); const data = await response.json(); status.classList.add("online"); $("#apiStatus").textContent = data.database === "connected" ? "System ready" : "Database unavailable"; } catch { status.classList.add("offline"); $("#apiStatus").textContent = "System unavailable"; } }
checkHealth();
