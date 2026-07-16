import { getProfile, showToast } from "./utils.js";

let allSavedJobs = [];
let _filterStatus = "";

function renderStatusTabs(counts) {
  const all = ["saved", "applied", "interviewing", "offer", "rejected"];
  const labels = { saved: "Saved", applied: "Applied", interviewing: "Interviewing", offer: "Offer", rejected: "Rejected" };
  const el = document.getElementById("jobFilters");

  const getTabClass = (isActive) => isActive
    ? "bg-indigo-50 text-indigo-700"
    : "text-slate-500 hover:bg-slate-50";

  const getCountClass = (isActive) => isActive ? "bg-indigo-200 text-indigo-800" : "bg-slate-100 text-slate-500";

  let html = `<button class="px-4 py-2 rounded-lg text-sm font-semibold transition-colors flex items-center gap-2 whitespace-nowrap ${getTabClass(!_filterStatus)}" onclick="filterJobs('')">
    All <span class="py-0.5 px-2 rounded-full text-xs font-bold ${getCountClass(!_filterStatus)}">${counts.total || 0}</span>
  </button>`;

  for (const s of all) {
    if ((counts[s] || 0) > 0 || _filterStatus === s) {
      const isActive = _filterStatus === s;
      html += `<button class="px-4 py-2 rounded-lg text-sm font-semibold transition-colors flex items-center gap-2 whitespace-nowrap ${getTabClass(isActive)}" data-status="${s}" onclick="filterJobs('${s}')">
        ${labels[s]} <span class="py-0.5 px-2 rounded-full text-xs font-bold ${getCountClass(isActive)}">${counts[s] || 0}</span>
      </button>`;
    }
  }
  el.innerHTML = html;
}

function filterJobs(status) {
  _filterStatus = status;
  const counts = allSavedJobs.reduce((acc, job) => {
    const s = job.application_status || "saved";
    acc[s] = (acc[s] || 0) + 1;
    acc.total = (acc.total || 0) + 1;
    return acc;
  }, { total: 0 });
  renderStatusTabs(counts);
  renderJobList();
  const statEl = document.getElementById("statSaved");
  if (statEl) statEl.textContent = allSavedJobs.length;
}

async function loadSavedJobs() {
  const profile = getProfile();
  if (!profile) return;
  try {
    const r = await fetch(`/api/saved-jobs?email=${encodeURIComponent(profile.email)}`);
    const d = await r.json();
    allSavedJobs = d.jobs || [];
    filterJobs(_filterStatus);
  } catch (e) {
    allSavedJobs = [];
    filterJobs(_filterStatus);
  }
}

function renderJobList() {
  const jobs = _filterStatus ? allSavedJobs.filter(j => (j.application_status || "saved") === _filterStatus) : allSavedJobs;
  const el = document.getElementById("jobListContainer");
  if (!jobs.length) {
    el.innerHTML = `
      <div class="text-center py-16 px-4 bg-white rounded-2xl border border-slate-200 border-dashed">
        <div class="w-16 h-16 bg-slate-50 rounded-full flex items-center justify-center mx-auto mb-4">
          <svg class="w-8 h-8 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M17.593 3.322c1.1.128 1.907 1.077 1.907 2.185V21L12 17.25 4.5 21V5.507c0-1.108.806-2.057 1.907-2.185a48.507 48.507 0 0111.186 0z"/></svg>
        </div>
        <h3 class="text-slate-900 font-medium mb-1">${_filterStatus ? `No ${_filterStatus} jobs found` : "No saved jobs yet"}</h3>
        <p class="text-slate-500 text-sm">When you bookmark jobs, they will appear here.</p>
      </div>`;
    return;
  }

  const statusColors = {
    saved: { bg: "bg-slate-100", text: "text-slate-700" },
    applied: { bg: "bg-blue-100", text: "text-blue-700" },
    interviewing: { bg: "bg-amber-100", text: "text-amber-700" },
    offer: { bg: "bg-emerald-100", text: "text-emerald-700" },
    rejected: { bg: "bg-red-100", text: "text-red-700" },
  };

  const companyColors = [
    "bg-red-100 text-red-600", "bg-indigo-100 text-indigo-600",
    "bg-emerald-100 text-emerald-600", "bg-amber-100 text-amber-600",
    "bg-violet-100 text-violet-600", "bg-cyan-100 text-cyan-600",
    "bg-pink-100 text-pink-600", "bg-lime-100 text-lime-600",
  ];

  const getStatusStyle = (status) => statusColors[status] || statusColors.saved;
  const getCompanyColor = (company) => companyColors[company.length % companyColors.length];

  el.innerHTML = jobs.map(j => {
    const status = j.application_status || "saved";
    const sc = getStatusStyle(status);
    const cc = getCompanyColor(j.company || "");
    const savedDate = j.saved_at ? new Date(j.saved_at).toLocaleDateString("en-US", { month: "short", day: "numeric" }) : "";
    const tags = (j.tags || []).slice(0, 3);

    return `
    <div class="bg-white border border-slate-200 rounded-2xl p-4 sm:p-5 hover:border-indigo-300 hover:shadow-md transition-all group cursor-pointer flex flex-col sm:flex-row gap-4 items-start sm:items-center justify-between">
      <div class="flex items-start sm:items-center gap-4 w-full sm:w-auto">
        <div class="w-12 h-12 rounded-xl ${cc} flex items-center justify-center font-bold text-xl shrink-0">${(j.company || "?").charAt(0).toUpperCase()}</div>
        <div class="flex-1 min-w-0">
          <h4 class="font-bold text-slate-900 text-base group-hover:text-indigo-600 transition-colors truncate">
            <a href="${j.url}" target="_blank">${j.title || "Untitled Position"}</a>
          </h4>
          <div class="flex flex-wrap items-center text-sm text-slate-500 mt-0.5 gap-x-2 gap-y-1">
            <span class="font-medium text-slate-700">${j.company || "Unknown"}</span>
            <span class="hidden sm:inline">•</span>
            ${j.location ? `<span class="truncate">${j.location}</span>` : ""}
            ${j.total_score ? `<span class="font-semibold text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded text-xs flex items-center gap-1"><svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z"/></svg>${j.total_score}/100</span>` : ""}
          </div>
          ${tags.length ? `<div class="flex flex-wrap items-center gap-1.5 mt-2">${tags.map(t => `<span class="text-xs font-medium bg-slate-100 text-slate-600 px-2 py-0.5 rounded-md">${t}</span>`).join("")}</div>` : ""}
        </div>
      </div>

      <div class="flex items-center justify-between w-full sm:w-auto gap-3 sm:pl-5 sm:border-l sm:border-slate-100 shrink-0">
        <div class="flex items-center gap-2">
          <span class="px-2.5 py-1 rounded-lg text-xs font-semibold ${sc.bg} ${sc.text}">${status.charAt(0).toUpperCase() + status.slice(1)}</span>
          <div class="relative inline-block">
            <select class="status-select outline-none border-0 bg-transparent text-xs font-semibold text-slate-400 cursor-pointer pr-4 appearance-none" onchange="updateStatus(${j.id}, this.value)" title="Change status">
              <option value="saved" ${status === "saved" ? "selected" : ""}>Saved</option>
              <option value="applied" ${status === "applied" ? "selected" : ""}>Applied</option>
              <option value="interviewing" ${status === "interviewing" ? "selected" : ""}>Interviewing</option>
              <option value="offer" ${status === "offer" ? "selected" : ""}>Offer</option>
              <option value="rejected" ${status === "rejected" ? "selected" : ""}>Rejected</option>
            </select>
          </div>
        </div>
        <button class="text-xs font-medium text-indigo-600 hover:text-indigo-700 bg-indigo-50 hover:bg-indigo-100 px-2.5 py-1.5 rounded-lg transition-colors" onclick="event.stopPropagation(); _referralJobTitle='${(j.title || "").replace(/'/g, "\\'")}'; _referralMatchScore=${j.total_score || 0}; _referralJobUrl='${(j.url || "").replace(/'/g, "\\'")}'; showReferralUsers('${(j.company || "").replace(/'/g, "\\'")}')" title="See referrals at this company">
          <svg class="w-3.5 h-3.5 inline" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z"/></svg>
        </button>
        <button class="text-slate-400 hover:text-red-500 transition-colors p-1 rounded-md hover:bg-red-50" onclick="removeJob(${j.id})" title="Remove">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
        </button>
      </div>
    </div>`;
  }).join("");
}

async function updateStatus(jobId, status) {
  try {
    const r = await fetch(`/api/saved-jobs/${jobId}/status`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    const d = await r.json();
    if (d.ok) {
      const job = allSavedJobs.find(j => j.id === jobId);
      if (job) job.application_status = status;
      filterJobs(_filterStatus);
      showToast("Application status updated");
    }
  } catch (e) {
    const job = allSavedJobs.find(j => j.id === jobId);
    if (job) job.application_status = status;
    filterJobs(_filterStatus);
    showToast("Application status updated");
  }
}

async function removeJob(jobId) {
  try {
    const r = await fetch(`/api/saved-jobs/${jobId}`, { method: "DELETE" });
    const d = await r.json();
    if (d.deleted) {
      allSavedJobs = allSavedJobs.filter(j => j.id !== jobId);
      filterJobs(_filterStatus);
      showToast("Job removed from saved list");
    }
  } catch (e) {
    allSavedJobs = allSavedJobs.filter(j => j.id !== jobId);
    filterJobs(_filterStatus);
    showToast("Job removed from saved list");
  }
}

window.renderStatusTabs = renderStatusTabs;
window.filterJobs = filterJobs;
window.loadSavedJobs = loadSavedJobs;
window.updateStatus = updateStatus;
window.removeJob = removeJob;

export { loadSavedJobs, renderStatusTabs };
