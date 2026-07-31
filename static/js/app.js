const tabs = document.querySelectorAll(".tab");
const panes = { upload: document.querySelector("#uploadPane"), url: document.querySelector("#urlPane") };
const fileInput = document.querySelector("#videoFile");
const urlInput = document.querySelector("#videoUrl");
const processButton = document.querySelector("#processButton");
const dropzone = document.querySelector(".dropzone");
const preview = document.querySelector("#videoPreview");
const previewEmpty = document.querySelector("#videoEmpty");
const errorBanner = document.querySelector("#errorBanner");
let activeTab = "upload";
let selectedFile = null;
let objectUrl = null;
let polling = false;

function refreshButton() {
  processButton.disabled = polling || (activeTab === "upload" ? !selectedFile : !urlInput.value.trim());
}
tabs.forEach((tab) => tab.addEventListener("click", () => {
  tabs.forEach((item) => item.classList.remove("active"));
  Object.values(panes).forEach((pane) => pane.classList.remove("active"));
  tab.classList.add("active");
  activeTab = tab.dataset.tab;
  panes[activeTab].classList.add("active");
  refreshButton();
}));
function showError(message) { errorBanner.textContent = message; errorBanner.hidden = false; }
function clearError() { errorBanner.hidden = true; errorBanner.textContent = ""; }
function setProgress(progress, stage) {
  document.querySelector("#progressValue").textContent = `${progress}%`;
  document.querySelector("#progressBar").style.width = `${progress}%`;
  document.querySelector("#progressStage").textContent = stage;
}
function chooseFile(file) {
  selectedFile = file || null;
  clearError();
  if (objectUrl) URL.revokeObjectURL(objectUrl);
  objectUrl = selectedFile ? URL.createObjectURL(selectedFile) : null;
  preview.hidden = !objectUrl;
  previewEmpty.hidden = Boolean(objectUrl);
  if (objectUrl) preview.src = objectUrl;
  refreshButton();
}
fileInput.addEventListener("change", () => chooseFile(fileInput.files[0]));
urlInput.addEventListener("input", refreshButton);
["dragenter", "dragover"].forEach((name) => dropzone.addEventListener(name, (event) => {
  event.preventDefault(); dropzone.classList.add("dragging");
}));
["dragleave", "drop"].forEach((name) => dropzone.addEventListener(name, (event) => {
  event.preventDefault(); dropzone.classList.remove("dragging");
}));
dropzone.addEventListener("drop", (event) => chooseFile(event.dataTransfer.files[0]));
async function parseError(response) {
  try { const body = await response.json(); return body.error?.message || "The request could not be completed."; }
  catch { return "The request could not be completed."; }
}
async function pollJob(pollUrl) {
  for (;;) {
    const response = await fetch(pollUrl, { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(await parseError(response));
    const job = await response.json();
    setProgress(job.progress, job.current_stage);
    document.querySelector("#ingestionStatus").textContent = job.status === "completed"
      ? "Validated" : job.status[0].toUpperCase() + job.status.slice(1);
    if (job.video_duration) {
      const minutes = Math.floor(job.video_duration / 60);
      const seconds = Math.floor(job.video_duration % 60);
      document.querySelector(".duration").textContent =
        `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
    }
    if (job.status === "failed") throw new Error(job.error_message || "Video validation failed.");
    if (job.status === "completed") return;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
}
processButton.addEventListener("click", async () => {
  clearError(); polling = true; refreshButton(); setProgress(2, "Submitting video");
  try {
    let response;
    if (activeTab === "upload") {
      const form = new FormData(); form.append("video", selectedFile);
      response = await fetch("/api/jobs/upload", { method: "POST", body: form });
    } else {
      response = await fetch("/api/jobs/url", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: urlInput.value.trim() }),
      });
    }
    if (!response.ok) throw new Error(await parseError(response));
    const accepted = await response.json();
    await pollJob(accepted.poll_url);
  } catch (error) { showError(error.message); }
  finally { polling = false; refreshButton(); }
});
window.addEventListener("beforeunload", () => { if (objectUrl) URL.revokeObjectURL(objectUrl); });
async function checkHealth() {
  const status = document.querySelector(".system-status");
  const label = document.querySelector("#apiStatus");
  try {
    const response = await fetch("/api/health", { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error("Health check failed");
    const data = await response.json();
    status.classList.add("online");
    label.textContent = data.database === "connected" ? "System ready" : "Database unavailable";
  } catch { status.classList.add("offline"); label.textContent = "System unavailable"; }
}
checkHealth();
