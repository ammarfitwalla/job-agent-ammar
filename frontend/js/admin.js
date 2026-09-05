// ── Auth Guard ──
const _adminEmail = "ammarfitwalla@gmail.com";
const _email = localStorage.getItem("jobagent_profile_email");
if (!_email || _email.toLowerCase() !== _adminEmail.toLowerCase()) { window.location.href = "/app"; }

function _esc(s) { return (s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;"); }

// ── State ──
let dailyChart, statusChart, comboChart;
let allSessions = [];
let _refreshInterval = null;
let _refreshActive = true;
let _ready = false;
let _sortKey = "date", _sortDir = -1;

// ── Utils ──
function formatDate(iso) {
  if (!iso) return "\u2014";
  const d = new Date(iso + (iso.endsWith("Z") ? "" : "Z"));
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

function formatRelative(iso) {
  if (!iso) return "\u2014";
  const diff = Math.floor((Date.now() - new Date(iso + (iso.endsWith("Z") ? "" : "Z")).getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

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
    loadStats(); loadSessions(); loadRegistrations(); loadVisits(); loadComboUsage(); loadCacheStats(); loadServerStats();
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
      { n: d.total_scraped_jobs, l: "Jobs Scraped", c: "green" },
      { n: formatDuration(d.avg_duration_seconds), l: "Avg Duration", c: "blue" },
      { n: Math.round(d.completed / total * 100) + "%", l: "Completion Rate", c: "green" },
      { n: d.total_scraped_jobs ? Math.round(d.total_scraped_jobs / total) : "\u2014", l: "Avg Jobs/Session", c: "sky" },
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

// ── Combo Usage ──
async function loadComboUsage() {
  try {
    const r = await fetch("/api/admin/prewarm/usage?limit=20", { cache: "no-cache" });
    const d = await r.json();
    const combos = (d.combos || []).filter(c => c.usage_count > 0);
    if (!combos.length) {
      document.getElementById("comboChart").parentElement.querySelector("h3").textContent = "Top Combo Usage (No data yet)";
      return;
    }
    const labels = combos.map(c => `${c.role} · ${c.site}${c.city ? " · " + c.city : ""}${c.state ? " · " + c.state : ""}${c.country ? " · " + c.country.toUpperCase() : ""}${c.internship_mode ? " · internship" : ""}`);
    const data = combos.map(c => c.usage_count);

    if (comboChart) comboChart.destroy();
    comboChart = new Chart(document.getElementById("comboChart"), {
      type: "bar",
      data: {
        labels,
        datasets: [{
          label: "Searches",
          data,
          backgroundColor: "rgba(99,102,241,.6)",
          borderColor: "#6366f1",
          borderWidth: 1,
          borderRadius: 3,
          borderSkipped: false,
        }],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        plugins: { legend: { display: false } },
        scales: {
          x: { beginAtZero: true, ticks: { stepSize: 1, precision: 0, font: { size: 10 } }, grid: { color: "#f1f5f9" } },
          y: { grid: { display: false }, ticks: { font: { size: 11 } } },
        },
      },
    });
  } catch {}
}

// ── Server Stats ──
async function loadServerStats() {
  try {
    const r = await fetch("/api/admin/server", { cache: "no-cache" });
    const d = await r.json();
    const mem = d.memory || {};
    const cpu = d.cpu || {};
    const disk = d.disk || {};
    const pctBar = (pct, color) =>
      `<div style="background:#e2e8f0;border-radius:8px;height:10px;overflow:hidden;margin-top:8px">
        <div style="width:${Math.min(pct, 100)}%;height:100%;background:${color};border-radius:8px;transition:width 0.6s ease"></div>
      </div>`;
    const statCard = (title, pct, detail, icon) => {
      const color = pct > 90 ? "#ef4444" : pct > 70 ? "#f59e0b" : "#10b981";
      return `<div style="background:var(--bg-card);border:1px solid var(--border-light);border-radius:var(--radius-md);padding:20px 24px;min-width:0">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px">
          <span style="font-size:13px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px">${_esc(title)}</span>
          <span style="font-size:22px">${icon}</span>
        </div>
        <div style="font-size:28px;font-weight:700;color:${color}">${pct}%</div>
        <div style="font-size:13px;color:var(--text-light);margin-top:2px">${_esc(detail)}</div>
        ${pctBar(pct, color)}
      </div>`;
    };
    const memDetail = `${mem.used_gb} GB / ${mem.total_gb} GB used`;
    const diskDetail = `${disk.used_gb} GB / ${disk.total_gb} GB used`;
    const cpuDetail = `${cpu.cores} cores · Load: ${cpu.load_1}/${cpu.load_5}/${cpu.load_15}`;
    const grid = `
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px;margin-bottom:24px">
        ${statCard("Memory", mem.percent, memDetail, "🧠")}
        ${statCard("CPU Load", Math.min((cpu.load_1 / cpu.cores) * 100, 100).toFixed(0), cpuDetail, "⚡")}
        ${statCard("Disk", disk.percent, diskDetail, "💾")}
      </div>`;
    const row = (label, value) =>
      `<div style="display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid var(--border-lighter)">
        <span style="color:var(--text-muted);font-size:13px">${_esc(label)}</span>
        <span style="font-weight:600;font-size:13px;font-family:'JetBrains Mono',monospace">${_esc(String(value))}</span>
      </div>`;
    const details = `
      <div style="background:var(--bg-card);border:1px solid var(--border-light);border-radius:var(--radius-md);padding:20px 24px">
        <h3 style="font-size:15px;font-weight:600;margin-bottom:12px">System Info</h3>
        ${row("Hostname", d.hostname || "—")}
        ${row("Uptime", d.uptime_formatted || "—")}
        ${row("Processes", d.processes || "—")}
        ${row("Python", d.python_version || "—")}
        ${row("CPU Cores", cpu.cores)}
        ${row("Load (1 / 5 / 15 min)", `${cpu.load_1} / ${cpu.load_5} / ${cpu.load_15}`)}
      </div>`;
    document.getElementById("serverStats").innerHTML = grid + details;
  } catch (e) {
    document.getElementById("serverStats").innerHTML =
      `<div style="text-align:center;padding:40px;color:var(--text-light)">Failed to load server stats</div>`;
  }
}

// ── Cache Stats ──
async function loadCacheStats() {
  try {
    const r = await fetch("/api/admin/cache-stats", { cache: "no-cache" });
    const d = await r.json();
    const sites = d.sites || [];
    const rows = sites.map(s => `<tr>
      <td>${s.site || "\u2014"}</td>
      <td>${s.entries || 0}</td>
      <td>${s.total_jobs || 0}</td>
      <td>${s.last_cached ? formatRelative(s.last_cached) : "\u2014"}</td>
    </tr>`).join("");
    const newest = sites.reduce((acc, s) => {
      return !acc || (s.last_cached && s.last_cached > acc) ? s.last_cached : acc;
    }, null);
    const totalRow = sites.length ? `<tr style="font-weight:600;border-top:2px solid #e2e8f0">
      <td>Total</td>
      <td>${d.total_entries}</td>
      <td>${d.total_jobs}</td>
      <td>${formatRelative(newest)}</td>
    </tr>` : "";
    document.getElementById("cacheBody").innerHTML = rows ? rows + totalRow : '<tr><td colspan="4" class="empty">No cached jobs</td></tr>';

    const rowMap = d.rows || {};
    const siteRows = sites.map(s => {
      const list = rowMap[s.site] || [];
      const body = list.length ? list.map(x => `<tr>
        <td style="white-space:nowrap">${x.id}</td>
        <td>${_esc(x.role) || "\u2014"}</td>
        <td>${_esc(x.city) || "\u2014"}</td>
        <td>${_esc(x.state) || "\u2014"}</td>
        <td>${_esc(x.country) || "\u2014"}</td>
        <td style="text-align:center">${x.internship_mode ? "Yes" : "\u2014"}</td>
        <td style="text-align:center">${x.is_remote ? "Yes" : "\u2014"}</td>
        <td style="text-align:center">${x.job_count ?? 0}</td>
        <td style="white-space:nowrap">${x.scraped_at ? formatRelative(x.scraped_at) : "\u2014"}</td>
        <td style="text-align:center">${x.usage_count ?? 0}</td>
        <td style="white-space:nowrap">${x.last_used_at ? formatRelative(x.last_used_at) : "\u2014"}</td>
      </tr>`).join("") : '<tr><td colspan="11" class="empty">No cached rows</td></tr>';
      return `<div class="chart-box db-card" style="max-width:100%;margin-top:16px">
        <h3>${_esc(s.site || "Unknown")} &mdash; Top 10 Cached Jobs</h3>
        <div class="table-wrap"><table><thead><tr>
          <th>ID</th><th>Role</th><th>City</th><th>State</th><th>Country</th><th>Intern</th>
          <th>Remote</th><th>Jobs</th><th>Scraped</th><th>Used</th><th>Last Used</th>
        </tr></thead><tbody>${body}</tbody></table></div>
      </div>`;
    }).join("");
    const container = document.getElementById("cacheSiteRows");
    if (container) container.innerHTML = siteRows;
  } catch {}
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
    { k: "user_email", l: "User" }, { k: "mode_label", l: "Mode" }, { k: "classification", l: "Status" },
    { k: "location", l: "Location" }, { k: "sites_label", l: "Sites" }, { k: "relevant_jobs", l: "Jobs" },
    { k: "resume", l: "Resume" }, { k: "duration_label", l: "Duration" },
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
      <td><span class="sid-cell" title="${_esc(s.id)}">${_esc(s.id?.slice(0, 12))}...</span></td>
      <td title="${_esc(s.user_email || "")}">${_esc(s.user_email) || "\u2014"}</td>
      <td><span class="mode-badge ${mc}">${ml}</span></td>
      <td><span class="badge ${sc}">${_esc(s.classification)}</span></td>
      <td title="${_esc(s.location || "")}">${_esc(s.location) || "\u2014"}</td>
      <td class="sites-cell" title="${_esc((s.sites || []).join(", "))}">${_esc((s.sites || []).join(", "))}</td>
      <td>${s.relevant_jobs || 0}</td>
      <td>${s.resume_available ? `<a class="job-link" href="/api/admin/sessions/${encodeURIComponent(s.id)}/resume" target="_blank">View &#8599;</a>` : "\u2014"}</td>
      <td>${formatDuration(s.elapsed_seconds)}</td>
    </tr><tr class="detail-row" id="detail-${s.id}" data-session='${sj}'><td colspan="10"><div class="detail-panel" id="panel-${s.id}"><div class="empty">Loading session details...</div></div></td></tr>`;
  }).join("") || `<tr><td colspan="10"><div class="empty">No sessions found</div></td></tr>`;
}

function sortSessions(key) {
  if (_sortKey === key) _sortDir *= -1; else { _sortKey = key; _sortDir = -1; }
  const map = { "date": "created_at", "id_label": "id", "user_email": "user_email", "mode_label": "internship_mode", "classification": "classification", "sites_label": "sites", "relevant_jobs": "relevant_jobs", "resume": "resume_available", "duration_label": "elapsed_seconds" };
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
    (s.user_email || "").toLowerCase().includes(q) ||
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
    if (d.error) { panel.innerHTML += `<div class="empty">${_esc(d.error)}</div>`; return; }

    const s = d.session || {};
    const refs = d.referral_requests || [];
    let html = "";

    if (refs.length) {
      html += `<div class="section"><div class="section-title">Referral Requests (${refs.length})</div>`;
      html += `<table style="width:100%"><tr><th>Job</th><th>Score</th><th>To</th><th>Status</th><th>Date</th></tr>`;
      html += refs.map(r => `<tr>
        <td style="max-width:280px"><span class="truncate" title="${_esc(r.job_title)}">${_esc(r.job_title) || "\u2014"}</span>
          ${r.company ? `<div style="font-size:11px;color:#64748b">${_esc(r.company)}</div>` : ""}</td>
        <td class="score-cell">${r.match_score ?? 0}
          <div class="score-bar"><div class="score-fill" style="width:${Math.min(r.match_score || 0, 100)}%"></div></div>
        </td>
        <td>${_esc(r.to_name || r.to_email || "\u2014")}${r.to_company ? ` <span style="font-size:11px;color:#64748b">(${_esc(r.to_company)})</span>` : ""}</td>
        <td>${statusPill(r.status)}</td>
        <td style="white-space:nowrap">${formatDate(r.created_at)}</td>
      </tr>`).join("");
      html += `</table></div>`;
    }

    if (!refs.length) {
      html += `<div class="empty">${s.user_email ? "No referral requests from this user yet" : "No user recorded for this session (sessions before this change are not linked to a user)"}</div>`;
    }
    panel.innerHTML = renderBasicDetail(sid, sd) + html;
  } catch (e) { panel.innerHTML += `<div class="empty">${_esc(e.message)}</div>`; }
}

function statusPill(status) {
  const map = {
    pending: "badge-amber", accepted: "badge-green", declined: "badge-red", rejected: "badge-red",
    saved: "badge-blue", applied: "badge-amber", interview: "badge-purple", offer: "badge-green",
  };
  return `<span class="badge ${map[status] || "badge-gray"}">${status || "\u2014"}</span>`;
}

function renderBasicDetail(sid, s) {
  let h = "";
  if ((s.keywords || []).length) h += `<div class="section"><div class="section-title">Keywords</div><div style="display:flex;flex-wrap:wrap;gap:4px">${s.keywords.map(k => `<span class="badge badge-blue">${_esc(k)}</span>`).join("")}</div></div>`;
  if ((s.roles || []).length) h += `<div class="section"><div class="section-title">Roles</div><div style="display:flex;flex-wrap:wrap;gap:4px">${s.roles.map(r => `<span class="badge badge-gray">${_esc(r)}</span>`).join("")}</div></div>`;
  if ((s.sites || []).length) h += `<div class="section"><div class="section-title">Sites</div><div>${_esc(s.sites.join(", "))}</div></div>`;
  return h ? `<div style="display:flex;flex-wrap:wrap;gap:16px;margin-bottom:12px">${h}</div>` : "";
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
      `      <div style="font-size:12px;padding:4px 0;border-bottom:1px solid #f1f5f9;display:flex;gap:12px;align-items:center">
        <span style="font-family:monospace;min-width:120px">${_esc(ip.ip)}</span>
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
        <td style="font-family:monospace;font-size:12px">${_esc(v.ip_address)}</td>
        <td>${_esc([v.country, v.region, v.city].filter(Boolean).join(", ")) || "\u2014"}</td>
        <td>${_esc(v.device_type) || "\u2014"}</td>
        <td>${_esc(v.path) || "\u2014"}</td>
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
      document.getElementById("registrationBody").innerHTML = '<tr><td colspan="10"><div class="empty">No registrations yet</div></td></tr>';
      return;
    }

    const expanded = new Set();

    function renderRow(u, i) {
      const status = deriveStatus(u.company);
      const jobsLabel = u.company ? "View" : "\u2014";
      const esc = _esc;
      return `
        <tr class="reg-row" data-idx="${i}" data-email="${esc(u.email)}">
          <td style="text-align:center;white-space:nowrap">
            ${u.company ? `<button class="pill-btn jobs-toggle" data-email="${esc(u.email)}" data-idx="${i}">${jobsLabel}</button>` : ""}
            <button class="pill-btn edit-user-btn" data-email="${esc(u.email)}" style="margin-left:6px;color:#4f46e5;border-color:#c7d2fe">Edit</button>
          </td>
          <td style="white-space:nowrap">${u.created_at ? formatDate(u.created_at) : "\u2014"}</td>
          <td>${esc(u.name) || "\u2014"}</td>
          <td>${esc(u.email)}</td>
          <td>${status}</td>
          <td>${esc(u.company) || "\u2014"}</td>
          <td>${esc(u.position) || "\u2014"}</td>
          <td class="jobs-count" data-email="${esc(u.email)}">...</td>
          <td style="text-align:center">${u.referral_credits ?? 0}</td>
          <td style="white-space:nowrap">${u.updated_at ? formatDate(u.updated_at) : "\u2014"}</td>
        </tr>
        <tr class="jobs-detail-row" id="jobs-detail-${i}" style="display:none">
          <td colspan="10" style="padding:0"><div class="jobs-detail-cell"><div class="jobs-loading">Loading...</div></div></td>
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
      const editBtn = e.target.closest(".edit-user-btn");
      if (editBtn) {
        const email = editBtn.dataset.email;
        const user = regs.find(x => x.email === email);
        if (user) openUserModal(user);
        return;
      }
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

// ── User Create/Edit (CRU) ──
let _editingUserEmail = null;

function _userModalError(msg, show = true) {
  const el = document.getElementById("userModalError");
  if (!el) return;
  el.textContent = msg || "";
  el.style.display = show && msg ? "block" : "none";
}

function openUserModal(user) {
  _editingUserEmail = user ? user.email : null;
  const title = document.getElementById("userModalTitle");
  title.textContent = user ? "Edit User" : "Add User";
  document.getElementById("userEmailInput").value = user ? user.email : "";
  document.getElementById("userEmailInput").disabled = !!user;
  document.getElementById("userNameInput").value = user ? (user.name || "") : "";
  document.getElementById("userCompanyInput").value = user ? (user.company || "") : "";
  document.getElementById("userPositionInput").value = user ? (user.position || "") : "";
  document.getElementById("userLinkedinInput").value = user ? (user.linkedin_url || "") : "";
  document.getElementById("userCreditsInput").value = user ? (user.referral_credits ?? 0) : "";
  document.getElementById("userOptInWrap").style.display = user ? "flex" : "none";
  document.getElementById("userOptInInput").checked = user ? !!user.refer_opt_in : false;
  _userModalError("");
  const modal = document.getElementById("userModal");
  modal.style.display = "flex";
}

function closeUserModal() {
  document.getElementById("userModal").style.display = "none";
}

async function saveUser() {
  const emailInput = document.getElementById("userEmailInput");
  const nameInput = document.getElementById("userNameInput");
  const email = emailInput.value.trim();
  const name = nameInput.value.trim();
  if (!email || !name) {
    _userModalError("Email and name are required.");
    return;
  }
  const payload = {
    name,
    company: document.getElementById("userCompanyInput").value.trim(),
    position: document.getElementById("userPositionInput").value.trim(),
    linkedin_url: document.getElementById("userLinkedinInput").value.trim(),
  };

  const btn = document.getElementById("userSaveBtn");
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="btn-spinner"></span> Saving...';
  _userModalError("");
  try {
    let r, d;
    if (_editingUserEmail) {
      payload.referral_credits = parseInt(document.getElementById("userCreditsInput").value, 10) || 0;
      payload.refer_opt_in = document.getElementById("userOptInInput").checked ? 1 : 0;
      r = await fetch(`/api/admin/users/${encodeURIComponent(_editingUserEmail)}?email=${encodeURIComponent(_adminEmail)}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
      });
      d = await r.json();
    } else {
      payload.email = email;
      r = await fetch(`/api/admin/users?email=${encodeURIComponent(_adminEmail)}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
      });
      d = await r.json();
    }
    if (!r.ok || !d.ok) {
      _userModalError(d.detail || d.error || "Failed to save user.");
      btn.disabled = false;
      btn.innerHTML = orig;
      return;
    }
    closeUserModal();
    loadRegistrations();
    loadStats();
    loadDbInfo();
  } catch {
    _userModalError("Network error.");
  }
  btn.disabled = false;
  btn.innerHTML = orig;
}

// ── Tabs ──
function switchTab(name, group = "main") {
  document.querySelectorAll(`.tabs[data-group="${group}"] .tab`).forEach(t => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(`.tab-content[data-group="${group}"]`).forEach(c => c.classList.toggle("active", c.dataset.tab === name));
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
window.loadVisits = loadVisits;
window.loadRegistrations = loadRegistrations;
window.openUserModal = openUserModal;
window.closeUserModal = closeUserModal;
window.saveUser = saveUser;
window.loadCacheStats = loadCacheStats;
window.loadServerStats = loadServerStats;
window.switchTab = switchTab;
window.loadDbInfo = loadDbInfo;
window.restoreDB = restoreDB;
window.mergeDB = mergeDB;

// ── Init ──
loadStats(); loadSessions(); loadRegistrations(); loadVisits(); loadComboUsage(); loadDbInfo(); loadCacheStats(); loadServerStats();
startRefresh();
