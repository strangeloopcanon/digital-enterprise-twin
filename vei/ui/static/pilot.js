const state = {
  payload: null,
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function getJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

function metricTile(label, value, detail = "") {
  return `
    <article class="metric-card">
      <p class="eyebrow">${escapeHtml(label)}</p>
      <strong>${escapeHtml(value)}</strong>
      ${detail ? `<p class="metric-detail">${escapeHtml(detail)}</p>` : ""}
    </article>
  `;
}

function renderBanner() {
  const banner = document.getElementById("pilot-status-banner");
  const payload = state.payload;
  if (!banner) {
    return;
  }
  banner.classList.remove("pilot-status-live", "pilot-status-waiting");
  if (!payload || !payload.manifest) {
    banner.textContent = "No pilot stack is configured for this workspace yet.";
    return;
  }
  if (payload.services_ready) {
    banner.classList.add("pilot-status-live");
    banner.textContent = "Pilot stack is live. Point an outside agent at the gateway and watch the company respond.";
    return;
  }
  banner.classList.add("pilot-status-waiting");
  banner.textContent = "Pilot files exist, but the gateway or Studio is not running right now.";
}

function renderHeader() {
  const payload = state.payload;
  const manifest = payload?.manifest;
  document.getElementById("pilot-company-title").textContent = manifest
    ? `${manifest.organization_name} — ${manifest.crisis_name}`
    : "Pilot not configured";
  document.getElementById("pilot-summary").textContent = manifest
    ? "Launch the twin, connect an outside agent, and follow the live run from one sidecar console."
    : "Run `vei pilot up` for this workspace to generate the launch details and live controls.";
  document.getElementById("pilot-open-studio").href = manifest?.studio_url || "/";
  document.getElementById("pilot-open-gateway").href = manifest?.gateway_status_url || "#";
}

function renderLaunch() {
  const payload = state.payload;
  const manifest = payload?.manifest;
  const launchGrid = document.getElementById("pilot-launch-grid");
  const surfaceList = document.getElementById("pilot-surface-list");
  const snippetsPanel = document.getElementById("pilot-snippets");
  if (!launchGrid || !surfaceList || !snippetsPanel) {
    return;
  }
  if (!manifest) {
    launchGrid.innerHTML = metricTile("Pilot", "Not configured");
    surfaceList.innerHTML = "";
    snippetsPanel.innerHTML = "";
    return;
  }
  launchGrid.innerHTML = [
    metricTile("Studio", manifest.studio_url, "Company-side view"),
    metricTile("Pilot Console", manifest.pilot_console_url, "Operator sidecar"),
    metricTile("Gateway", manifest.gateway_url, "Outside-agent entrypoint"),
    metricTile("Bearer token", manifest.bearer_token, "Shared pilot token"),
    metricTile("First exercise", manifest.recommended_first_exercise, "Suggested starting move"),
    metricTile("Sample client", manifest.sample_client_path, "Bundled quick-start script"),
  ].join("");
  surfaceList.innerHTML = (manifest.supported_surfaces || [])
    .map((surface) => `<span class="badge">${escapeHtml(surface.title)} · ${escapeHtml(surface.base_path)}</span>`)
    .join("");
  snippetsPanel.innerHTML = (manifest.snippets || [])
    .map(
      (snippet) => `
        <article class="pilot-snippet-card">
          <div class="pilot-snippet-head">
            <strong>${escapeHtml(snippet.title)}</strong>
            <div class="chip-row">
              <span class="badge">${escapeHtml(snippet.name)}</span>
              <span class="badge">${escapeHtml(snippet.language || "bash")}</span>
            </div>
          </div>
          <pre>${escapeHtml(snippet.content)}</pre>
        </article>
      `
    )
    .join("");
}

function renderActivity() {
  const panel = document.getElementById("pilot-activity-list");
  const activity = state.payload?.activity || [];
  if (!panel) {
    return;
  }
  if (!activity.length) {
    panel.innerHTML = `<p class="metric-detail">No outside-agent actions yet. Use the sample client or connect your own agent to start the run.</p>`;
    return;
  }
  panel.innerHTML = activity
    .map(
      (item) => `
        <article class="pilot-activity-card">
          <div class="pilot-activity-head">
            <strong>${escapeHtml(item.label)}</strong>
            <span class="badge">${escapeHtml(item.channel)}</span>
          </div>
          <p class="metric-detail">${escapeHtml(item.tool || "No resolved tool recorded")}</p>
          ${(item.object_refs || []).length
            ? `<div class="chip-row">${item.object_refs.map((ref) => `<span class="badge">${escapeHtml(ref)}</span>`).join("")}</div>`
            : ""}
        </article>
      `
    )
    .join("");
}

function renderOutcome() {
  const payload = state.payload;
  const outcome = payload?.outcome;
  const panel = document.getElementById("pilot-outcome-grid");
  if (!panel) {
    return;
  }
  if (!outcome) {
    panel.innerHTML = metricTile("Outcome", "Unavailable");
    return;
  }
  panel.innerHTML = [
    metricTile("Twin status", payload.twin_status || "stopped", outcome.summary),
    metricTile("Requests", String(payload.request_count || 0), "External requests handled"),
    metricTile("Contract", outcome.contract_ok === true ? "healthy" : outcome.contract_ok === false ? "at risk" : "pending", `${outcome.issue_count || 0} open issues`),
    metricTile("Current tension", outcome.current_tension || "No live tension summary", outcome.latest_tool || "No latest tool yet"),
  ].join("");
  if ((outcome.affected_surfaces || []).length) {
    panel.innerHTML += `
      <article class="pilot-outcome-callout">
        <p class="eyebrow">Surfaces under pressure</p>
        <div class="chip-row">
          ${outcome.affected_surfaces.map((item) => `<span class="badge">${escapeHtml(item)}</span>`).join("")}
        </div>
      </article>
    `;
  }
}

function renderControls() {
  const manifest = state.payload?.manifest;
  const actionStatus = document.getElementById("pilot-action-status");
  const resetButton = document.getElementById("pilot-reset-button");
  const finalizeButton = document.getElementById("pilot-finalize-button");
  const disabled = !manifest;
  resetButton.disabled = disabled;
  finalizeButton.disabled = disabled;
  if (!manifest && actionStatus) {
    actionStatus.textContent = "Run `vei pilot up` to enable reset and finalize controls.";
  }
}

function renderAll() {
  renderBanner();
  renderHeader();
  renderLaunch();
  renderActivity();
  renderOutcome();
  renderControls();
}

async function loadPilotStatus() {
  try {
    state.payload = await getJson("/api/pilot");
  } catch {
    state.payload = null;
  }
  renderAll();
}

async function runPilotAction(path, successMessage) {
  const status = document.getElementById("pilot-action-status");
  status.textContent = "Working…";
  try {
    state.payload = await getJson(path, { method: "POST" });
    status.textContent = successMessage;
    renderAll();
  } catch (error) {
    status.textContent = error instanceof Error ? error.message : "Request failed";
  }
}

document.getElementById("pilot-reset-button").addEventListener("click", () => {
  runPilotAction("/api/pilot/reset", "Twin reset complete. The gateway is back at baseline.");
});

document.getElementById("pilot-finalize-button").addEventListener("click", () => {
  runPilotAction("/api/pilot/finalize", "Current run finalized.");
});

loadPilotStatus();
setInterval(loadPilotStatus, 5000);
