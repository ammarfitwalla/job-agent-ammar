// ── Auth Guard ──
const _adminEmail = "ammarfitwalla@gmail.com";
const _email = localStorage.getItem("jobagent_profile_email");
if (!_email || _email.toLowerCase() !== _adminEmail.toLowerCase()) { window.location.href = "/"; }

// ── State ──
let dailyChart, statusChart, scoreChart;
let allSessions = [];
let _refreshInterval = null;
let _refreshActive = true;
let _ready = false;
let _sortKey = "date", _sortDir = -1;

// ── Utils ──
function formatDate(iso) {
  if (!iso) return "\u2014";
  const d = new Date(iso);
  const now = new Date();
  const pad = n => String(n).padStart(2, "0");
  const datePart = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const timePart = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const diff = Math.floor((now - d) / 86400000);
  const suffix = diff === 0 ? "today" : diff === 1 ? "yesterday" : `${diff}d ago`;
  return `${datePart} ${timePart} (${suffix})`;
}

function formatDuration(sec) {
  if (!sec || sec <= 0) return "\u2014";
  if (sec < 60) return `${Math.round(sec)}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${Math.round(sec % 60)}s`;
  return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`;
}

function fmtTime() { return new Date().toLocaleTimeString(); }

function showRealContent() {
  if (_ready) return;
  _ready = true;
  document.getElementById("skelCards").style.display = "none";
  document.querySelector(".skel-charts").style.display = "none";
  document.getElementById("realContent").style.display = "block";
  document.getElementById("lastRefreshed").textContent = "Updated " + fmtTime();
}

function setRefreshing(on) {
  document.getElementById("refreshToggle").classList.toggle("spinning", on);
}

// ── Auto-refresh ──
function toggleRefresh() {
  _refreshActive = !_refreshActive;
  const el = document.getElementById("refreshToggle");
  el.classList.toggle("active", _refreshActive);
  document.getElementById("refreshIcon").textContent = _refreshActive ? "\u21bb" : "\u2716";
  document.getElementById("refreshLabel").textContent = _refreshActive ? "Auto-refresh" : "Paused";
  if (_refreshActive) startRefresh(); else stopRefresh();
}

function startRefresh() {
  stopRefresh();
  _refreshInterval = setInterval(() => {
    setRefreshing(true);
    loadStats(); loadSessions(); loadScores(); loadRegistrations(); loadVisits();
  }, 300000);
}

function stopRefresh() {
  if (_refreshInterval) { clearInterval(_refreshInterval); _refreshInterval = null; }
}

// ── Stats ──
async function loadStats() {
  try {
    const r = await fetch("/api/admin/stats", { cache: "no-cache" });
    const d = await r.json();
    const total = d.total_sessions || 1;
    document.getElementById("cards").innerHTML = [
      { n: d.total_sessions, l: "Total Sessions", c: "blue" },
      { n: d.completed, l: "Completed", c: "green" },
      { n: d.cancelled, l: "Cancelled", c: "amber" },
      { n: d.abandoned, l: "Abandoned", c: "red" },
      { n: d.errors, l: "Errors", c: "red" },
      { n: d.total_users, l: "Registrations", c: "purple" },
      { n: d.total_raw_jobs, l: "Raw Jobs", c: "sky" },
      { n: d.total_relevant_jobs, l: "Relevant Jobs", c: "green" },
      { n: formatDuration(d.avg_duration_seconds), l: "Avg Duration", c: "blue" },
      { n: Math.round(d.completed / total * 100) + "%", l: "Completion Rate", c: "green" },
      { n: d.total_raw_jobs ? Math.round(d.total_raw_jobs / total) : "\u2014", l: "Avg Jobs/Session", c: "sky" },
      { n: d.total_users && d.total_sessions ? Math.round(d.total_sessions / d.total_users) : "\u2014", l: "Sessions/User", c: "purple" },
      { n: d.total_visits || 0, l: "Total Visits", c: "teal" },
      { n: d.unique_visitors || 0, l: "Unique Visitors", c: "teal" },
      { n: d.visit_avg_duration_seconds ? Math.round(d.visit_avg_duration_seconds) + "s" : "\u2014", l: "Avg Visit Duration", c: "teal" },
    ].map((o, i) => `<div class="card ${o.c}" style="animation-delay:${i * .03}s"><div class="num">${o.n}</div><div class="label">${o.l}</div></div>`).join("");

    const days = d.daily.map(r => r.day.slice(5));
    const counts = d.daily.map(r => r.count);
    if (dailyChart) dailyChart.destroy();
    const grad = document.createElement("canvas").getContext("2d").createLinearGradient(0, 0, 0, 160);
    grad.addColorStop(0, "rgba(59,130,246,.5)");
    grad.addColorStop(1, "rgba(59,130,246,.05)");
    dailyChart = new Chart(document.getElementById("dailyChart"), {
      type: "bar",
      data: { labels: days, datasets: [{
        label: "Sessions", data: counts, backgroundColor: grad, borderColor: "#3b82f6",
        borderWidth: 1, borderRadius: 3, borderSkipped: false,
      }] },
      options: {
        responsive: true, plugins: { legend: { display: false } },
        scales: {
          y: { beginAtZero: true, ticks: { stepSize: 1, precision: 0, font: { size: 10 } }, grid: { color: "#f1f5f9" } },
          x: { grid: { display: false }, ticks: { font: { size: 10 } } },
        },
      }
    });

    if (statusChart) statusChart.destroy();
    statusChart = new Chart(document.getElementById("statusChart"), {
      type: "doughnut",
      data: {
        labels: ["Completed", "Cancelled", "Abandoned", "Errors"],
        datasets: [{
          data: [d.completed || 0, d.cancelled || 0, d.abandoned || 0, d.errors || 0],
          backgroundColor: ["#10b981", "#f59e0b", "#f87171", "#fca5a5"],
          borderWidth: 2, borderColor: "#fff",
        }]
      },
      options: {
        responsive: true, cutout: "65%",
        plugins: {
          legend: { position: "bottom", labels: { boxWidth: 10, padding: 14, font: { size: 11 }, usePointStyle: true } },
        },
        animation: { animateRotate: true },
      }
    });
    showRealContent();
  } catch { showRealContent(); }
  setRefreshing(false);
}

// ── Sessions ──
async function loadSessions() {
  try {
    const r = await fetch("/api/admin/sessions", { cache: "no-cache" });
    const d = await r.json();
    allSessions = d.sessions || [];
    renderSessions(allSessions);
  } catch {}
}

function renderSessions(sessions) {
  const cols = [
    { k: "date", l: "Date" }, { k: "id_label", l: "Session ID" },
    { k: "mode_label", l: "Mode" }, { k: "classification", l: "Status" },
    { k: "location", l: "Location" }, { k: "sites_label", l: "Sites" }, { k: "relevant_jobs", l: "Jobs" },
    { k: "duration_label", l: "Duration" },
  ];
  const sorted = _sortKey === "date" ? _sortDir : 0;
  document.getElementById("sessionHead").innerHTML =
    "<tr>" + cols.map(c => `<th onclick="sortSessions('${c.k}')">${c.l}<span class="sort-arrow ${c.k === 'date' ? 'active' : ''}">${sorted === 1 ? '&#9650;' : sorted === -1 ? '&#9660;' : '&#9650;&#9660;'}</span></th>`).join("") + "</tr>";

  document.getElementById("sessionBody").innerHTML = sessions.map(s => {
    const sc = { Completed: "badge-green", Cancelled: "badge-amber", Abandoned: "badge-red", Error: "badge-red" }[s.classification] || "badge-gray";
    const mc = s.internship_mode ? "mode-internship" : "mode-normal";
    const ml = s.internship_mode ? "internship" : "normal";
    const sj = JSON.stringify({ keywords: s.keywords || [], roles: s.roles || [], sites: s.sites || [], id: s.id }).replace(/'/g, "&#39;");
    return `<tr class="clickable" onclick="toggleDetail('${s.id}')">
      <td style="white-space:nowrap">${s.created_at ? formatDate(s.created_at) : "\u2014"}</td>
      <td><span class="sid-cell" title="${s.id}">${s.id?.slice(0, 12)}...</span></td>
      <td><span class="mode-badge ${mc}">${ml}</span></td>
      <td><span class="badge ${sc}">${s.classification}</span></td>
      <td title="${s.location || ""}">${s.location || "\u2014"}</td>
      <td class="sites-cell" title="${(s.sites || []).join(", ")}">${(s.sites || []).join(", ")}</td>
      <td>${s.relevant_jobs || 0}</td>
      <td>${formatDuration(s.elapsed_seconds)}</td>
    </tr><tr class="detail-row" id="detail-${s.id}" data-session='${sj}'><td colspan="8"><div class="detail-panel" id="panel-${s.id}"><div class="empty">Loading session details...</div></div></td></tr>`;
  }).join("") || `<tr><td colspan="8"><div class="empty">No sessions found</div></td></tr>`;
}

function sortSessions(key) {
  if (_sortKey === key) _sortDir *= -1; else { _sortKey = key; _sortDir = -1; }
  const map = { "date": "created_at", "id_label": "id", "mode_label": "internship_mode", "classification": "classification", "sites_label": "sites", "relevant_jobs": "relevant_jobs", "duration_label": "elapsed_seconds" };
  const ak = map[key] || key;
  const sorted = [...allSessions].sort((a, b) => {
    let va = a[ak] ?? "", vb = b[ak] ?? "";
    if (ak === "internship_mode") { va = a.internship_mode ? 1 : 0; vb = b.internship_mode ? 1 : 0; } else if (ak === "sites") { va = (a.sites || []).join(","); vb = (b.sites || []).join(","); }
    if (typeof va === "string") return _sortDir * va.localeCompare(vb);
    return _sortDir * ((va || 0) - (vb || 0));
  });
  renderSessions(sorted);
}

function filterSessions() {
  const q = document.getElementById("sessionSearch").value.toLowerCase();
  renderSessions(allSessions.filter(s =>
    (s.keywords || []).join(" ").toLowerCase().includes(q) ||
    (s.roles || []).join(" ").toLowerCase().includes(q) ||
    (s.sites || []).join(" ").toLowerCase().includes(q) ||
    s.classification.toLowerCase().includes(q) ||
    s.id?.toLowerCase().includes(q)
  ));
}

async function toggleDetail(sid) {
  const row = document.getElementById(`detail-${sid}`);
  const panel = document.getElementById(`panel-${sid}`);
  const isOpen = row.classList.contains("open");
  row.classList.toggle("open");
  if (isOpen) return;

  const sd = JSON.parse(row.dataset.session || "{}");
  panel.innerHTML = renderBasicDetail(sid, sd);

  try {
    const r = await fetch(`/api/admin/sessions/${sid}`);
    const d = await r.json();
    if (d.error) { panel.innerHTML += `<div class="empty">${d.error}</div>`; return; }

    const events = (d.events || []).slice(-30);
    const jobs = (d.jobs || []).slice(0, 20);
    let html = "";

    if (events.length) {
      html += `<div class="section"><div class="section-title">Events (last 30)</div>`;
      html += events.map(e => `<div class="ev"><span class="ev-time">${e.elapsed_seconds || 0}s</span><span>${e.event}</span></div>`).join("");
      html += `</div>`;
    }
    if (jobs.length) {
      html += `<div class="section"><div class="section-title">Top Scoring Jobs</div>`;
      html += `<table style="width:100%"><tr><th>Title</th><th>Company</th><th>Score</th><th></th></tr>`;
      html += jobs.map(j => `<tr>
        <td style="max-width:300px"><span class="truncate" title="${j.title}">${j.title}</span></td>
        <td>${j.company || "\u2014"}</td>
        <td class="score-cell">${j.total_score ?? "\u2014"} <span style="font-size:11px;color:#94a3b8">(AI ${j.ai_score || 0} / KW ${j.keyword_score || 0})</span>
          <div class="score-bar"><div class="score-fill" style="width:${Math.min(j.total_score || 0, 100)}%"></div></div>
        </td>
        <td>${j.url ? `<a class="job-link" href="${j.url}" target="_blank">Open &#8599;</a>` : "\u2014"}</td>
      </tr>`).join("");
      html += `</table></div>`;
    }
    if (!events.length && !jobs.length) html += `<div class="empty">No events or jobs for this session</div>`;
    if (d.resume_available) html = `<div class="section"><a href="/api/admin/sessions/${sid}/resume" target="_blank" style="font-size:12px;color:#3b82f6;font-weight:500">View Resume &#8599;</a></div>` + html;
    panel.innerHTML = renderBasicDetail(sid, sd) + html;
  } catch (e) { panel.innerHTML += `<div class="empty">${e.message}</div>`; }
}

function renderBasicDetail(sid, s) {
  let h = "";
  if ((s.keywords || []).length) h += `<div class="section"><div class="section-title">Keywords</div><div style="display:flex;flex-wrap:wrap;gap:4px">${s.keywords.map(k => `<span class="badge badge-blue">${k}</span>`).join("")}</div></div>`;
  if ((s.roles || []).length) h += `<div class="section"><div class="section-title">Roles</div><div style="display:flex;flex-wrap:wrap;gap:4px">${s.roles.map(r => `<span class="badge badge-gray">${r}</span>`).join("")}</div></div>`;
  if ((s.sites || []).length) h += `<div class="section"><div class="section-title">Sites</div><div>${s.sites.join(", ")}</div></div>`;
  return h ? `<div style="display:flex;flex-wrap:wrap;gap:16px;margin-bottom:12px">${h}</div>` : "";
}

// ── Scores ──
async function loadScores() {
  try {
    const r = await fetch("/api/admin/scores", { cache: "no-cache" });
    const d = await r.json();
    const dist = d.distribution || [];
    if (scoreChart) scoreChart.destroy();
    const grad = document.createElement("canvas").getContext("2d").createLinearGradient(0, 0, 0, 200);
    grad.addColorStop(0, "rgba(16,185,129,.5)");
    grad.addColorStop(1, "rgba(16,185,129,.05)");
    scoreChart = new Chart(document.getElementById("scoreHistogram"), {
      type: "bar",
      data: { labels: dist.map(b => b.range), datasets: [{
        label: "Jobs", data: dist.map(b => b.count), backgroundColor: grad,
        borderColor: "#10b981", borderWidth: 1, borderRadius: 3, borderSkipped: false,
      }] },
      options: { responsive: true, plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: true, ticks: { stepSize: 1, precision: 0, font: { size: 10 } }, grid: { color: "#f1f5f9" } }, x: { grid: { display: false }, ticks: { font: { size: 10 } } } },
      }
    });
  } catch {}
}

// ── Visits ──
async function loadVisits() {
  try {
    const r = await fetch("/api/admin/visits", { cache: "no-cache" });
    const d = await r.json();
    const visits = d.visits || [];
    const stats = d.stats || {};

    const devHtml = Object.entries(stats.devices || {}).map(([k, v]) =>
      `<div class="card teal" style="flex:0 0 auto;min-width:100px"><div class="num">${v}</div><div class="label">${k}</div></div>`
    ).join("");
    document.getElementById("visitCards").innerHTML = devHtml +
      `<div class="card teal" style="flex:0 0 auto;min-width:100px"><div class="num">${stats.total_visits || 0}</div><div class="label">Total</div></div>` +
      `<div class="card teal" style="flex:0 0 auto;min-width:100px"><div class="num">${stats.unique_visitors || 0}</div><div class="label">Unique</div></div>`;

    const ipHtml = (stats.by_ip || []).slice(0, 20).map(ip =>
      `<div style="font-size:12px;padding:4px 0;border-bottom:1px solid #f1f5f9;display:flex;gap:12px;align-items:center">
        <span style="font-family:monospace;min-width:120px">${ip.ip}</span>
        <span style="color:#64748b;min-width:40px">${ip.count}x</span>
        <span style="color:#94a3b8;min-width:80px">${ip.country || ""}</span>
        <span style="color:#94a3b8;font-size:11px">${ip.last_visit ? formatDate(ip.last_visit) : ""}</span>
      </div>`
    ).join("");
    if (ipHtml) {
      document.getElementById("visitCards").insertAdjacentHTML("afterend",
        `<div class="table-wrap" style="margin:12px 0"><div style="padding:8px 0;font-weight:600;font-size:13px">Top IPs</div>${ipHtml}</div>`);
    }

    document.getElementById("visitBody").innerHTML = visits.length
      ? visits.map(v => `<tr>
        <td style="white-space:nowrap">${v.created_at ? formatDate(v.created_at) : "\u2014"}</td>
        <td style="font-family:monospace;font-size:12px">${v.ip_address}</td>
        <td>${[v.country, v.region, v.city].filter(Boolean).join(", ") || "\u2014"}</td>
        <td>${v.device_type || "\u2014"}</td>
        <td>${v.path || "\u2014"}</td>
        <td>${v.duration_seconds ? Math.round(v.duration_seconds) + "s" : "\u2014"}</td>
      </tr>`).join("")
      : '<tr><td colspan="6"><div class="empty">No visits yet</div></td></tr>';
  } catch {}
}

const _STATUS_LABELS = { Student: "student", Graduate: "graduate", "Laid Off": "laid_off", "Career Break": "career_break" };

function deriveStatus(company) {
  if (!company) return "\u2014";
  const s = _STATUS_LABELS[company];
  return s ? s.replace("_", " ") : "Employed";
}

async function loadRegistrations() {
  try {
    const r = await fetch("/api/admin/registrations", { cache: "no-cache" });
    const d = await r.json();
    const regs = d.registrations || [];

    async function fetchSavedJobs(email) {
      try {
        const r = await fetch(`/api/saved-jobs?email=${encodeURIComponent(email)}`);
        const d = await r.json();
        return d.jobs || [];
      } catch { return []; }
    }

    if (!regs.length) {
      document.getElementById("registrationBody").innerHTML = '<tr><td colspan="9"><div class="empty">No registrations yet</div></td></tr>';
      return;
    }

    const expanded = new Set();

    function renderRow(u, i) {
      const status = deriveStatus(u.company);
      const jobsLabel = u.company ? "View" : "\u2014";
      return `
        <tr class="reg-row" data-idx="${i}">
          <td style="text-align:center">${u.company ? `<button class="pill-btn jobs-toggle" data-email="${u.email}" data-idx="${i}">${jobsLabel}</button>` : ""}</td>
          <td style="white-space:nowrap">${u.created_at ? formatDate(u.created_at) : "\u2014"}</td>
          <td>${u.name || "\u2014"}</td>
          <td>${u.email}</td>
          <td>${status}</td>
          <td>${u.company || "\u2014"}</td>
          <td>${u.position || "\u2014"}</td>
          <td class="jobs-count" data-email="${u.email}">...</td>
          <td style="white-space:nowrap">${u.updated_at ? formatDate(u.updated_at) : "\u2014"}</td>
        </tr>
        <tr class="jobs-detail-row" id="jobs-detail-${i}" style="display:none">
          <td colspan="9" style="padding:0"><div class="jobs-detail-cell"><div class="jobs-loading">Loading...</div></div></td>
        </tr>`;
    }

    const html = regs.map((u, i) => renderRow(u, i)).join("");
    document.getElementById("registrationBody").innerHTML = html;

    // Fetch saved jobs count per user
    regs.forEach(async (u) => {
      if (!u.company) return;
      const jobs = await fetchSavedJobs(u.email);
      const cell = document.querySelector(`.jobs-count[data-email="${u.email}"]`);
      if (cell) cell.textContent = jobs.length || "0";
    });

    // Toggle saved jobs detail on button click
    document.getElementById("registrationBody").addEventListener("click", async (e) => {
      const btn = e.target.closest(".jobs-toggle");
      if (!btn) return;
      const idx = btn.dataset.idx;
      const email = btn.dataset.email;
      const detailRow = document.getElementById(`jobs-detail-${idx}`);
      if (!detailRow) return;

      if (detailRow.style.display === "table-row") {
        detailRow.style.display = "none";
        btn.textContent = "View";
        return;
      }

      detailRow.style.display = "table-row";
      btn.textContent = "Hide";
      const cell = detailRow.querySelector(".jobs-detail-cell");

      const jobs = await fetchSavedJobs(email);
      if (!jobs.length) {
        cell.innerHTML = '<div class="empty" style="padding:12px">No saved jobs</div>';
        return;
      }
      cell.innerHTML = `<table class="inner-table"><thead><tr><th>Title</th><th>Company</th><th>Status</th><th>Saved</th></tr></thead><tbody>
        ${jobs.map(j => `<tr>
          <td>${j.title ? `<a href="${j.url || "#"}" target="_blank">${j.title}</a>` : "\u2014"}</td>
          <td>${j.company || "\u2014"}</td>
          <td>${j.application_status || "saved"}</td>
          <td style="white-space:nowrap">${j.saved_at ? formatDate(j.saved_at) : "\u2014"}</td>
        </tr>`).join("")}
      </tbody></table>`;
    });
  } catch {}
}

// ── Tabs ──
function switchTab(name) {
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".tab-content").forEach(c => c.classList.toggle("active", c.id === `tab-${name}`));
}

// ── Database ──
async function loadDbInfo() {
  try {
    const r = await fetch(`/api/admin/db/info?email=${encodeURIComponent(_adminEmail)}`);
    const d = await r.json();
    if (d.error) { document.getElementById("dbInfo").textContent = "Failed to load"; return; }
    document.getElementById("dbInfo").innerHTML = `Size: <strong>${d.size_mb} MB</strong> \u00b7 Sessions: <strong>${d.sessions}</strong> \u00b7 Users: <strong>${d.users}</strong>`;
  } catch {
    document.getElementById("dbInfo").textContent = "Failed to load";
  }
}

async function restoreDB() {
  const input = document.getElementById("dbFileInput");
  const file = input.files[0];
  if (!file) { alert("Select a .db file first"); return; }
  const size = file.size > 1048576 ? (file.size / 1048576).toFixed(1) + " MB" : Math.round(file.size / 1024) + " KB";
  if (!confirm(`Restore "${file.name}" (${size})?\nThis replaces the current database and cannot be undone.`)) return;
  const btn = document.querySelector(".db-card .btn-primary");
  const origHTML = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="btn-spinner"></span> Restoring...';
  const result = document.getElementById("dbRestoreResult");
  result.textContent = "";
  result.className = "db-result";
  const fd = new FormData();
  fd.append("file", file);
  fd.append("email", _adminEmail);
  try {
    const r = await fetch("/api/admin/db/restore", { method: "POST", body: fd });
    const d = await r.json();
    if (d.ok) {
      result.className = "db-result success";
      result.textContent = "Restored! Reloading...";
      setTimeout(() => location.reload(), 1500);
    } else {
      result.className = "db-result error";
      result.textContent = d.error || "Failed";
    }
  } catch {
    result.className = "db-result error";
    result.textContent = "Network error";
  }
  btn.disabled = false;
  btn.innerHTML = origHTML;
}

async function mergeDB() {
  const input = document.getElementById("dbFileInput");
  const file = input.files[0];
  if (!file) { alert("Select a .db file first"); return; }
  const size = file.size > 1048576 ? (file.size / 1048576).toFixed(1) + " MB" : Math.round(file.size / 1024) + " KB";
  if (!confirm(`Merge "${file.name}" (${size})?\nNew records will be added, existing ones preserved.`)) return;
  const btn = document.getElementById("mergeBtn");
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="btn-spinner"></span> Merging...';
  const result = document.getElementById("dbMergeResult");
  result.textContent = ""; result.className = "db-result";
  const fd = new FormData();
  fd.append("file", file); fd.append("email", _adminEmail);
  try {
    const r = await fetch("/api/admin/db/merge", { method: "POST", body: fd });
    const d = await r.json();
    if (d.ok) {
      const entries = Object.entries(d.inserted || {});
      const summary = entries.length ? entries.map(([t, n]) => `${t}: ${n}`).join(" \u00b7 ") : "No new records";
      result.className = "db-result success";
      result.textContent = `Merged! ${summary}`;
      loadDbInfo(); loadStats(); loadSessions(); loadRegistrations();
    } else {
      result.className = "db-result error";
      result.textContent = d.error || "Failed";
    }
  } catch {
    result.className = "db-result error";
    result.textContent = "Network error";
  }
  btn.disabled = false; btn.innerHTML = orig;
}

// ── Resume Upload ──
window.handleResumeFiles = function handleResumeFiles(files) {
  const count = document.getElementById("resumeFileCount");
  const list = document.getElementById("resumeFileList");
  if (!files.length) {
    count.textContent = "No files selected";
    list.innerHTML = "";
    return;
  }
  count.textContent = `${files.length} file${files.length > 1 ? "s" : ""} selected`;
  list.innerHTML = Array.from(files).map(f =>
    `<div style="padding:3px 0">${f.name} (${(f.size / 1024).toFixed(1)} KB)</div>`
  ).join("");
};

window.uploadResumes = async function uploadResumes() {
  const input = document.getElementById("resumeFileInput");
  const files = input.files;
  if (!files.length) { alert("Select resume files first"); return; }
  const btn = document.getElementById("resumeUploadBtn");
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="btn-spinner"></span> Uploading...';
  const result = document.getElementById("resumeUploadResult");
  result.textContent = ""; result.className = "db-result";
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  fd.append("email", _adminEmail);
  try {
    const r = await fetch("/api/admin/resume/upload", { method: "POST", body: fd });
    const d = await r.json();
    if (d.ok) {
      const ok = d.files.filter(f => f.ok).length;
      const fail = d.files.filter(f => !f.ok).length;
      result.className = "db-result success";
      result.textContent = `${ok} uploaded` + (fail ? `, ${fail} failed` : "");
      if (fail) {
        const list = document.getElementById("resumeFileList");
        list.innerHTML = d.files.map(f =>
          `<div style="padding:3px 0;color:${f.ok ? "#059669" : "#dc2626"}">${f.filename} — ${f.ok ? "OK" : f.error}</div>`
        ).join("");
      }
    } else {
      result.className = "db-result error";
      result.textContent = d.error || "Failed";
    }
  } catch (e) {
    result.className = "db-result error";
    result.textContent = "Network error";
  }
  btn.disabled = false;
  btn.innerHTML = orig;
};

// ── Window globals for onclick ──
window.formatDate = formatDate;
window.formatDuration = formatDuration;
window.toggleRefresh = toggleRefresh;
window.loadStats = loadStats;
window.loadSessions = loadSessions;
window.renderSessions = renderSessions;
window.sortSessions = sortSessions;
window.filterSessions = filterSessions;
window.toggleDetail = toggleDetail;
window.loadScores = loadScores;
window.loadVisits = loadVisits;
window.loadRegistrations = loadRegistrations;
window.switchTab = switchTab;
window.loadDbInfo = loadDbInfo;
window.restoreDB = restoreDB;
window.mergeDB = mergeDB;

// ── Init ──
loadStats(); loadSessions(); loadScores(); loadRegistrations(); loadVisits(); loadDbInfo();
startRefresh();
