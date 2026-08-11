// ===== STATE =====
function relativeDate(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return '';
  const now = new Date();
  const diffMs = now - d;
  const diffDays = Math.floor(diffMs / 86400000);
  const diffHours = Math.floor(diffMs / 3600000);
  if (diffHours < 1) return 'just now';
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays === 0) return 'today';
  if (diffDays === 1) return 'yesterday';
  if (diffDays < 7) return `${diffDays}d ago`;
  if (diffDays < 30) return `${Math.floor(diffDays / 7)}w ago`;
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

const SEARCH_CACHE_KEY = "jobagent_last_search";
const SEARCH_CACHE_TTL = 30 * 60 * 1000;
const RELEVANCE_LIMIT = 5;
const RELEVANCE_CACHE_KEY = "jobagent_relevance_used";
const RESUME_CACHE_KEY = "jobagent_resume_text";
let pollTimer = null;
let hasRawJobs = false;
let allJobs = [];
let customRoles = [];
let selectedRoles = new Set();
let customKeywords = [];
let scrapeAttempts = 0;
let shownSlowWarning = false;
let countriesMap = {};
let selectedLocation = null;
let searchTimeout = null;
let lastQuery = "";
let lastRenderedCount = 0;
let allStates = [];
let internshipMode = false;
let activeFilters = { site: '', experience_level: '' };
let currentSort = 'relevant';
let _searchId = crypto.randomUUID();
let _relevanceUsed = 0;
let _relevanceScoring = new Set();

let _selectedSites = [];
let _searchStart = 0;
let _searchComplete = false;
let _pendingSaveJob = null;
let _uploadedFilename = "";
let _authEmail = "";
let _referralCounts = {};
let _refreshCooldown = false;
let _currentPage = 1;
const _pageSize = 10;

let suggestedRoles = [];
let searchIds = [];

// Tab state
let customJobs = [];
let aiJobs = [];
let _customRoleList = [];
let _aiRoleList = [];
let searchMode = 'current';
let activeTab = 'custom';
let customPollTimer = null;
let aiPollTimer = null;
let customPollTimers = {};
let aiLogs = [];
let aiStatus = '';

// ── Visit Tracking ──
(function() {
  const _visitId = crypto.randomUUID();
  const _visitStart = Date.now();

  function _detectDevice() {
    const ua = navigator.userAgent;
    if (/Mobi|Android|iPhone|iPad|iPod|BlackBerry|Windows Phone|IEMobile|Opera Mini/i.test(ua)) return "phone";
    if (/Tablet|iPad|PlayBook|Silk/i.test(ua)) return "tablet";
    return "desktop";
  }

  function _visitBeacon(endpoint, data) {
    try {
      const blob = new Blob([JSON.stringify(data)], { type: "application/json" });
      navigator.sendBeacon(endpoint, blob);
    } catch {}
  }

  _visitBeacon("/api/visit/start", {
    visit_id: _visitId,
    device_type: _detectDevice(),
    path: window.location.pathname,
    referer: document.referrer || "",
    session_id: "",
    user_email: "",
  });

  function _endVisit() {
    _visitBeacon("/api/visit/end", {
      visit_id: _visitId,
      total_duration: (Date.now() - _visitStart) / 1000,
    });
  }

  window.addEventListener("beforeunload", _endVisit);
  window.addEventListener("pagehide", _endVisit);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") _endVisit();
  });
})();

// ===== TOAST =====
if (typeof window.showToast !== "function") {
  let _toastTimer = null;
  function showToast(msg, icon) {
    const el = document.getElementById("toast");
    const msgEl = document.getElementById("toastMsg");
    const iconEl = document.getElementById("toastIcon");
    msgEl.textContent = msg;
    iconEl.innerHTML = icon || '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>';
    el.classList.remove("hidden");
    clearTimeout(_toastTimer);
    _toastTimer = setTimeout(() => el.classList.add("hidden"), 3000);
  }
}

// ===== AUTH =====
function showAuthModal() {
  document.getElementById("authStep1").classList.remove("hidden");
  document.getElementById("authStep2").classList.add("hidden");
  document.getElementById("authStep3").classList.add("hidden");
  document.getElementById("authStep4").classList.add("hidden");
  document.getElementById("authEmail").value = "";
  document.getElementById("authSendError").classList.add("hidden");
  document.getElementById("authCodeError").classList.add("hidden");
  document.getElementById("authRegisterError").classList.add("hidden");
  document.getElementById("authEmail").focus();
  document.getElementById("authModal").classList.remove("hidden");
  loadCompanyList();
}
let _pendingAuthRefresh = false;

function closeAuthModal() {
  document.getElementById("authModal").classList.add("hidden");
  if (_pendingAuthRefresh) {
    _pendingAuthRefresh = false;
    applyThreshold();
  }
}
function authGoBack() {
  document.getElementById("authStep1").classList.remove("hidden");
  document.getElementById("authStep2").classList.add("hidden");
  document.getElementById("authStep4").classList.add("hidden");
  document.getElementById("authSendError").classList.add("hidden");
}

let _companyList = [];

async function loadCompanyList() {
  if (_companyList.length > 0) return;
  try {
    const r = await fetch("/api/auth/companies");
    const d = await r.json();
    _companyList = d.companies || [];
  } catch {}
}

function filterCompanyDropdown() {
  const input = document.getElementById("authCompany");
  const dropdown = document.getElementById("companyDropdown");
  const val = input.value.toLowerCase().trim();
  const matches = val ? _companyList.filter(c => c.toLowerCase().includes(val)) : _companyList;
  let html = matches.slice(0, 30).map(c =>
    `<div class="px-3 py-2 text-sm cursor-pointer hover:bg-indigo-50 transition-colors" onclick="selectCompany('${c.replace(/'/g, "\\'")}')">${c}</div>`
  ).join("");
  if (val && !_companyList.some(c => c.toLowerCase() === val)) {
    html += `<div class="px-3 py-2 text-sm cursor-pointer text-indigo-600 border-t border-slate-100 hover:bg-indigo-50 transition-colors font-medium" onclick="addCustomCompany('${val.replace(/'/g, "\\'")}', event)">+ Add "${input.value.trim()}"</div>`;
  }
  if (!html) {
    dropdown.classList.add("hidden");
    return;
  }
  dropdown.innerHTML = html;
  dropdown.classList.remove("hidden");
}

async function addCustomCompany(name, event) {
  event.stopPropagation();
  const r = await fetch("/api/auth/companies", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ name }),
  });
  if (!_companyList.includes(name)) {
    _companyList.push(name);
    _companyList.sort();
  }
  selectCompany(name);
}

function selectCompany(name) {
  document.getElementById("authCompany").value = name;
  document.getElementById("companyDropdown").classList.add("hidden");
}

document.addEventListener("click", function(e) {
  const dd = document.getElementById("companyDropdown");
  if (dd && !e.target.closest("#authCompany") && !e.target.closest("#companyDropdown")) {
    dd.classList.add("hidden");
  }
});

function selectEmploymentStatus(status) {
  document.querySelectorAll(".employment-pill").forEach(p => p.classList.remove("active-pill"));
  const pill = document.querySelector(`.employment-pill[data-status="${status}"]`);
  if (pill) pill.classList.add("active-pill");
  const group = document.getElementById("authCompanyGroup");
  if (group) {
    group.classList.toggle("hidden", status !== "employed");
    if (status !== "employed") {
      document.getElementById("authCompany").value = "";
    }
  }
}

async function authRegister() {
  if (!_authEmail) return;
  const status = document.querySelector(".employment-pill.active-pill")?.dataset?.status || "employed";
  const name = document.getElementById("authName").value.trim();
  const position = document.getElementById("authPosition").value.trim();
  const linkedin = document.getElementById("authLinkedin").value.trim();
  const btn = document.getElementById("authRegisterBtn");
  const errEl = document.getElementById("authRegisterError");
  if (!name) {
    errEl.textContent = "Please enter your name.";
    errEl.classList.remove("hidden");
    return;
  }
  let company;
  if (status === "employed") {
    company = document.getElementById("authCompany").value.trim();
    if (!company) {
      errEl.textContent = "Please enter your company.";
      errEl.classList.remove("hidden");
      return;
    }
  } else {
    company = window._EMPLOYMENT_LABELS[status] || "";
  }
  errEl.classList.add("hidden");
  btn.disabled = true;
  btn.textContent = "Saving...";
  try {
    let searchId = "";
    try {
      const raw = localStorage.getItem(SEARCH_CACHE_KEY);
      if (raw) { const s = JSON.parse(raw); if (s?.searchId) searchId = s.searchId; }
    } catch {}
    const r = await fetch("/api/auth/register", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ email: _authEmail, name, company, position, linkedin_url: linkedin, search_id: searchId }),
    });
    const d = await r.json();
    if (!d.ok) {
      errEl.textContent = d.error || "Failed to save profile.";
      errEl.classList.remove("hidden");
      btn.disabled = false;
      btn.textContent = "Complete Profile";
      return;
    }
    const resumeFile = document.getElementById("authResume")?.files?.[0];
    if (resumeFile) {
      try {
        const fd = new FormData();
        fd.append("file", resumeFile);
        await fetch(`/api/profile/resume?email=${encodeURIComponent(_authEmail)}`, { method: "POST", body: fd });
      } catch {}
    }
    window.setProfile(d.user);
    document.getElementById("authStep4").classList.add("hidden");
    document.getElementById("authStep3").classList.remove("hidden");
    window.updateProfileIcon();
    refreshProfileResumeBtn();
    setTimeout(() => {
      closeAuthModal();
      _pendingAuthRefresh = true;
      if (_pendingSaveJob) {
        doSaveJob(_pendingSaveJob);
        _pendingSaveJob = null;
      }
    }, 1000);
  } catch {
    errEl.textContent = "Network error. Try again.";
    errEl.classList.remove("hidden");
  }
  btn.disabled = false;
  btn.textContent = "Complete Profile";
}

async function authSendCode() {
  const email = document.getElementById("authEmail").value.trim();
  const btn = document.getElementById("authSendBtn");
  const errEl = document.getElementById("authSendError");
  if (!email || !email.includes("@")) {
    errEl.textContent = "Please enter a valid email address.";
    errEl.classList.remove("hidden");
    return;
  }
  errEl.classList.add("hidden");
  btn.disabled = true;
  btn.textContent = "Sending...";
  try {
    const r = await fetch("/api/auth/send-code", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ email }),
    });
    const d = await r.json();
    if (!d.ok) {
      errEl.textContent = d.error || "Failed to send code. Try again.";
      errEl.classList.remove("hidden");
      btn.disabled = false;
      btn.textContent = "Send Code";
      return;
    }
    _authEmail = email;
    if (window.DEV_MODE) {
      document.getElementById("authSentEmail").textContent = email;
      document.getElementById("authStep1").classList.add("hidden");
      document.getElementById("authStep2").classList.remove("hidden");
      document.querySelectorAll(".code-digit").forEach(inp => { inp.value = ""; });
      document.querySelector(".code-digit").focus();
      btn.disabled = false;
      btn.textContent = "Send Code";
      return;
    }
    const emailRes = await window.sendEmailJS({
      email: email,
      subject: "Your Job Agent verification code",
      passcode: d.code,
    });
    if (!emailRes.ok) {
      errEl.textContent = emailRes.error || "Failed to send email. Try again.";
      errEl.classList.remove("hidden");
      btn.disabled = false;
      btn.textContent = "Send Code";
      return;
    }
    _authEmail = email;
    document.getElementById("authSentEmail").textContent = email;
    document.getElementById("authStep1").classList.add("hidden");
    document.getElementById("authStep2").classList.remove("hidden");
    document.querySelectorAll(".code-digit").forEach(inp => { inp.value = ""; });
    document.querySelector(".code-digit").focus();
  } catch (e) {
    errEl.textContent = "Network error. Try again.";
    errEl.classList.remove("hidden");
  }
  btn.disabled = false;
  btn.textContent = "Send Code";
}

async function authVerifyCode() {
  const digits = document.querySelectorAll(".code-digit");
  const code = Array.from(digits).map(d => d.value).join("");
  const btn = document.getElementById("authVerifyBtn");
  const errEl = document.getElementById("authCodeError");
  if (code.length !== 6) {
    errEl.textContent = "Enter the full 6-digit code.";
    errEl.classList.remove("hidden");
    return;
  }
  errEl.classList.add("hidden");
  btn.disabled = true;
  btn.textContent = "Verifying...";
  try {
    const r = await fetch("/api/auth/verify-code", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ email: _authEmail, code }),
    });
    const d = await r.json();
    if (!d.ok) {
      errEl.textContent = d.error || "Invalid code. Try again.";
      errEl.classList.remove("hidden");
      btn.disabled = false;
      btn.textContent = "Verify";
      return;
    }
    document.getElementById("authStep2").classList.add("hidden");
    if (d.user.company) {
      window.setProfile({ email: d.user.email, name: d.user.name || d.user.email.split("@")[0], company: d.user.company, position: d.user.position || "", linkedin_url: d.user.linkedin_url || "", referral_credits: d.user.referral_credits || 0 });
      document.getElementById("authStep3").classList.remove("hidden");
      window.updateProfileIcon();
      refreshProfileResumeBtn();
      setTimeout(() => closeAuthModal(), 500);
      _pendingAuthRefresh = true;
    } else {
      document.getElementById("authStep4").classList.remove("hidden");
      document.getElementById("authName").value = d.user.name || d.user.email.split("@")[0];
      document.getElementById("authName").focus();
    }
  } catch (e) {
    errEl.textContent = "Network error. Try again.";
    errEl.classList.remove("hidden");
  }
  btn.disabled = false;
  btn.textContent = "Verify";
}

function authResendCode() {
  document.getElementById("authCodeError").classList.add("hidden");
  authSendCode();
}

function setupCodeInputs() {
  document.querySelectorAll(".code-digit").forEach(inp => {
    inp.addEventListener("input", function () {
      if (this.value && this.dataset.idx < "5") {
        const next = document.querySelector(`.code-digit[data-idx="${parseInt(this.dataset.idx) + 1}"]`);
        if (next) next.focus();
      }
    });
    inp.addEventListener("keydown", function (e) {
      if (e.key === "Backward" || e.key === "Backspace") {
        if (!this.value && this.dataset.idx > "0") {
          const prev = document.querySelector(`.code-digit[data-idx="${parseInt(this.dataset.idx) - 1}"]`);
          if (prev) { prev.focus(); prev.value = ""; }
        }
      }
      if (e.key === "Enter") authVerifyCode();
    });
    inp.addEventListener("paste", function(e) {
      e.preventDefault();
      const text = (e.clipboardData || window.clipboardData).getData("text").replace(/\D/g, "");
      if (text.length !== 6) return;
      const inputs = document.querySelectorAll(".code-digit");
      inputs.forEach((input, i) => { input.value = text[i] || ""; });
      inputs[5].focus();
    });
  });
}
async function refreshProfileResumeBtn() {
  const btn = document.getElementById("useProfileResume");
  if (!btn) return;
  const profile = getProfile();
  if (!profile) { btn.classList.add("hidden"); return; }
  let hasResume = !!(profile.resume_filename || "");
  if (!profile.resume_filename) {
    try {
      const r = await fetch(`/api/profile?email=${encodeURIComponent(profile.email)}`);
      const d = await r.json();
      if (d && d.email) { window.setProfile(d); hasResume = !!(d.resume_filename || ""); }
    } catch {}
  }
  btn.classList.toggle("hidden", !hasResume);
}

async function useProfileResume() {
  const profile = getProfile();
  if (!profile || !profile.email) return;
  const btn = document.getElementById("useProfileResume");
  const lbl = document.getElementById("useProfileResumeLabel");
  if (btn) { btn.disabled = true; if (lbl) lbl.textContent = "Loading..."; }
  try {
    const r = await fetch(`/api/profile/resume/text?email=${encodeURIComponent(profile.email)}`);
    const d = await r.json();
    if (!d.ok || !d.text) throw new Error(d.error || "No resume found");
    const ta = document.getElementById("resume");
    ta.value = d.text;
    _uploadedFilename = "";
    try { localStorage.setItem(RESUME_CACHE_KEY, d.text); } catch {}
    clearSearchState();
    document.getElementById("refreshRolesBtn").disabled = false;
    updateSearchBtn();
    document.getElementById("extractBtn").click();
  } catch (e) {
    setStatus("Could not load your profile resume: " + (e.message || e), "red");
  } finally {
    if (btn) { btn.disabled = false; if (lbl) lbl.textContent = "Use my profile resume"; }
  }
}

document.addEventListener("DOMContentLoaded", () => {
  setupCodeInputs();
  window.fetchProfile().then(() => { window.updateProfileIcon(); refreshProfileResumeBtn(); });
  loadStatsBar();
});

async function loadStatsBar() {
  const bar = document.getElementById("statsBar");
  const content = document.getElementById("statsContent");
  if (!bar || !content) return;
  try {
    const r = await fetch("/api/stats/public");
    const d = await r.json();
    if (d.total_users === undefined) return;
    content.innerHTML = [
      { label: "searches", value: d.total_searches },
      { label: "jobs scraped", value: d.total_raw_jobs },
    ].map(s => `<span class="inline-flex items-center gap-1"><span class="font-semibold text-slate-700">${s.value.toLocaleString()}</span> <span class="text-slate-400">${s.label}</span></span>`).join('<span class="text-slate-200">·</span>');
    bar.classList.remove("hidden");
  } catch {}
}

// ===== SAVE JOBS =====
async function toggleSaveJob(event) {
  event.preventDefault();
  event.stopPropagation();
  const url = event.currentTarget?.dataset?.url;
  if (!url) return;
  const job = allJobs.find(j => j.url === url);
  if (!job) return;
  const profile = window.getProfile();
  if (!profile) {
    _pendingSaveJob = job;
    showAuthModal();
    return;
  }
  if (job._saved) {
    await doUnsaveJob(job);
  } else {
    await doSaveJob(job);
  }
}

function jobCardHtml(j) {
  const siteName = siteFromUrl(j.url);
  const isSaved = j._saved || false;
  const scored = j.total_score != null;
  const limitReached = _relevanceUsed >= RELEVANCE_LIMIT;
  const relevanceLocked = limitReached || !_searchComplete;

  const expBadge = j.experience_level === "internship"
    ? '<span class="text-xs bg-teal-50 text-teal-700 border border-teal-100 px-2.5 py-1 rounded-md font-medium flex items-center gap-1"><svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20"><path d="M10.394 2.08a1 1 0 00-.788 0l-7 3a1 1 0 000 1.84L5.25 8.051a.999.999 0 01.356-.257l4-1.714a1 1 0 11.788 1.838L7.667 9.088l1.94.831a1 1 0 00.787 0l7-3a1 1 0 000-1.838l-7-3zM3.31 9.397L5 10.12v4.102a8.969 8.969 0 00-1.05-.174 1 1 0 01-.89-.89 11.115 11.115 0 01.25-3.762zM9.3 16.573A9.026 9.026 0 007 14.935v-3.957l1.818.78a3 3 0 002.364 0l5.508-2.361a11.026 11.026 0 01.25 3.762 1 1 0 01-.89.89 8.968 8.968 0 00-5.35 2.524 1 1 0 01-1.4 0z"/></svg> Internship</span>'
    : j.experience_level === "entry_level"
      ? '<span class="text-xs bg-slate-100 text-slate-700 border border-slate-200 px-2.5 py-1 rounded-md font-medium">Entry Level</span>'
      : "";

  const levelBadge = j.job_level && j.job_level !== "Not Applicable"
    ? `<span class="text-xs bg-blue-50 text-blue-700 border border-blue-100 px-2 py-0.5 rounded-md font-medium">${j.job_level}</span>`
    : "";

  const companyHtml = j.company_url
    ? `<span class="font-medium text-indigo-600 hover:underline cursor-pointer" onclick="event.preventDefault(); event.stopPropagation(); window.open('${j.company_url.replace(/'/g, "\\'")}', '_blank')">${j.company}</span>`
    : `<span class="font-medium">${j.company}</span>`;

  const tagsHtml = j.tags && j.tags.length
    ? `<div class="mt-3 flex flex-wrap gap-1.5">${j.tags.slice(0, 6).map(t =>
        `<span class="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded-md">${typeof t === 'string' ? t : ''}</span>`
      ).join("")}</div>`
    : "";

  const scorePill = scored
    ? `<div class="shrink-0 text-right">
        <span class="text-[10px] font-bold uppercase tracking-wider text-slate-400">AI Match</span>
        <div class="mt-1 inline-flex items-center justify-center min-w-[3.25rem] px-3 py-1.5 rounded-xl font-bold text-sm text-white shadow-sm bg-gradient-to-r ${j.total_score >= 70 ? 'from-emerald-500 to-teal-600' : j.total_score >= 50 ? 'from-amber-500 to-orange-500' : 'from-slate-400 to-slate-600'}">${Math.round(j.total_score)}%</div>
      </div>`
    : "";

  const aiNoteHtml = j.reason
    ? `<div class="mt-3 rounded-xl bg-gradient-to-r from-indigo-50 to-fuchsia-50 border border-indigo-100 px-3.5 py-3 flex items-start gap-2">
        <span class="text-sm leading-none shrink-0 mt-0.5">✨</span>
        <p class="text-xs leading-relaxed text-slate-700">${j.reason}</p>
      </div>`
    : "";

  const relevanceBtn = scored
    ? `          <button class="w-full sm:w-auto justify-center shrink-0 text-xs font-semibold inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border bg-emerald-50 text-emerald-700 border-emerald-200 opacity-60 cursor-default" disabled data-url="${j.url || ''}" title="Scored">
        <svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>
        <span>Scored</span>
      </button>`
    : `<button data-relevance-btn="true" class="w-full sm:w-auto justify-center shrink-0 text-xs font-semibold transition-all duration-200 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border ${relevanceLocked ? 'bg-slate-50 text-slate-400 border-slate-200 opacity-50 cursor-not-allowed' : 'bg-slate-50 text-slate-600 border-slate-200 hover:bg-slate-100 active:bg-slate-200'}" data-url="${j.url || ''}" onclick="event.preventDefault(); event.stopPropagation(); checkRelevance(event)" title="Check relevance" ${relevanceLocked ? 'disabled' : ''}>
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
        <span>Check relevance</span>
      </button>`;

  return `
    <a href="${j.url}" target="_blank" data-job-url="${j.url || ''}" class="block group relative bg-white rounded-2xl p-5 sm:p-6 border border-[#e8ecf1] hover:border-slate-300 hover:shadow-lg transition-all duration-300 outline-none focus:ring-2 focus:ring-indigo-500">
      <div class="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
        <div class="flex-1 min-w-0">
          <div class="flex flex-wrap items-center gap-2 mb-2">
            <h3 class="text-sm sm:text-base font-semibold text-slate-900 group-hover:text-indigo-600 transition-colors truncate pr-1">${j.title}</h3>
            ${expBadge} ${levelBadge}
          </div>
          <p class="text-sm text-slate-600 flex items-center gap-2 truncate">
            ${companyHtml}
            <span class="w-1 h-1 rounded-full bg-slate-300 shrink-0"></span>
            <span>${j.location}</span>
            ${j.salary ? `<span class="w-1 h-1 rounded-full bg-slate-300 shrink-0"></span><span class="premium-badge bg-emerald-50 text-emerald-700 border-emerald-100 font-medium">${j.salary}</span>` : ""}
            ${j.date_posted ? `<span class="w-1 h-1 rounded-full bg-slate-300 shrink-0"></span><span class="text-xs text-slate-400">${relativeDate(j.date_posted)}</span>` : ""}
          </p>
        </div>
        ${scorePill}
      </div>

      ${tagsHtml}

      ${aiNoteHtml}

      <div class="flex items-center justify-between mt-4 pt-4 border-t border-slate-100">
        <div class="flex flex-col sm:flex-row items-stretch sm:items-center gap-2 sm:gap-2.5 flex-1 pr-3 min-w-0">
          <button class="bookmark-btn w-full sm:w-auto justify-center shrink-0 text-xs font-semibold transition-all duration-200 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border ${isSaved ? 'bg-indigo-500 text-white border-indigo-500 hover:bg-indigo-600' : 'bg-indigo-50 text-indigo-600 border-indigo-200 hover:bg-indigo-100 active:bg-indigo-200'}" data-url="${j.url || ''}" onclick="toggleSaveJob(event)" title="Save job">
            ${isSaved
              ? '<svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg> Saved'
              : '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4"/></svg> Save'
            }
          </button>
          ${relevanceBtn}
          <button class="w-full sm:w-auto justify-center shrink-0 text-xs font-semibold transition-all duration-200 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border bg-violet-50 text-violet-600 border-violet-200 hover:bg-violet-100 active:bg-violet-200 referral-btn" data-company="${j.company.replace(/"/g, '&quot;')}" onclick="event.preventDefault(); event.stopPropagation(); window._referralJobTitle='${(j.title||'').replace(/'/g, "\\'")}'; window._referralMatchScore=0; window._referralJobUrl='${(j.url||'').replace(/'/g, "\\'")}'; showReferralUsers('${j.company.replace(/'/g, "\\'")}')" title="See referrals at this company">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z"/></svg>
            <span class="referral-label">Referrals</span>
          </button>
        </div>
        <div class="flex items-center gap-1.5 text-xs font-medium text-slate-400 shrink-0">
          <span>via ${siteName}</span>
          <svg class="w-4 h-4 group-hover:text-indigo-600 group-hover:translate-x-0.5 transition-all" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3"></path></svg>
        </div>
      </div>
    </a>`;
}

function loadRelevanceUsed() {
  try {
    const raw = localStorage.getItem(RELEVANCE_CACHE_KEY);
    if (!raw) return 0;
    const saved = JSON.parse(raw);
    if (!saved || saved.searchId !== _searchId) return 0;
    return Math.max(0, parseInt(saved.used, 10) || 0);
  } catch { return 0; }
}

function saveRelevanceUsed() {
  try {
    localStorage.setItem(RELEVANCE_CACHE_KEY, JSON.stringify({ searchId: _searchId, used: _relevanceUsed }));
  } catch {}
}

function resetRelevanceState() {
  _relevanceUsed = 0;
  _relevanceScoring.clear();
  saveRelevanceUsed();
}

function relevanceButtonsDisabled() {
  return _relevanceUsed >= RELEVANCE_LIMIT;
}

function disableAllRelevanceButtons() {
  document.querySelectorAll('[data-relevance-btn="true"]').forEach(btn => {
    btn.disabled = true;
    btn.classList.remove("hover:bg-slate-100", "active:bg-slate-200");
    btn.classList.add("opacity-50", "cursor-not-allowed");
  });
}

function setRelevanceButtonLoading(btn, loading) {
  if (!btn) return;
  if (loading) {
    btn.dataset.origHtml = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<svg class="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg> Scoring…';
  } else if (btn.dataset.origHtml) {
    btn.innerHTML = btn.dataset.origHtml;
    btn.disabled = false;
    delete btn.dataset.origHtml;
  }
}

async function checkRelevance(event) {
  event.preventDefault();
  event.stopPropagation();
  const url = event.currentTarget?.dataset?.url;
  if (!url) return;

  _relevanceUsed = loadRelevanceUsed();
  if (_relevanceUsed >= RELEVANCE_LIMIT) {
    disableAllRelevanceButtons();
    window.showToast(`You've reached the limit of ${RELEVANCE_LIMIT} relevance checks for this search.`, "red");
    return;
  }

  const job = allJobs.find(j => j.url === url) || customJobs.find(j => j.url === url) || aiJobs.find(j => j.url === url);
  if (!job) return;
  if (job.total_score != null) return;
  if (_relevanceScoring.has(url)) return;

  const btn = event.currentTarget;
  const profile = window.getProfile();
  setRelevanceButtonLoading(btn, true);
  _relevanceScoring.add(url);

  try {
    const r = await fetch("/jobs/check-relevance", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        search_id: _searchId,
        url: url,
        resume_text: document.getElementById("resume")?.value.trim() || "",
        email: (profile || {}).email || "",
      }),
    });
    const d = await r.json();
    if (!d.ok || !d.score) {
      setRelevanceButtonLoading(btn, false);
      _relevanceScoring.delete(url);
      window.showToast(d.error || "Failed to score this job. Try again.", "red");
      return;
    }

    job.total_score = d.score.total_score;
    job.ai_score = d.score.ai_score;
    job.keyword_score = d.score.keyword_score;
    job.reason = d.score.reason || "";

    _relevanceUsed += 1;
    saveRelevanceUsed();
    _relevanceScoring.delete(url);

    rerenderJobCard(job);

    window.showToast("Job scored!", "green");
    if (_relevanceUsed >= RELEVANCE_LIMIT) {
      disableAllRelevanceButtons();
      window.showToast(`All ${RELEVANCE_LIMIT} relevance checks used.`, "blue");
    }
  } catch (e) {
    setRelevanceButtonLoading(btn, false);
    _relevanceScoring.delete(url);
    window.showToast("Network error while scoring. Try again.", "red");
  }
}

function rerenderJobCard(job) {
  const url = job.url || "";
  const card = document.querySelector(`[data-job-url="${CSS.escape(url)}"]`);
  if (!card) return;
  const rendered = jobCardHtml(job);
  const container = document.createElement("div");
  container.innerHTML = rendered;
  const newCard = container.firstElementChild;
  if (newCard) card.replaceWith(newCard);
}

window.ensureJobScored = async function (url) {
  const job = allJobs.find(j => j.url === url) || customJobs.find(j => j.url === url) || aiJobs.find(j => j.url === url);
  if (!job) return 0;
  if (job.total_score != null) return job.total_score;
  const profile = window.getProfile();
  try {
    const r = await fetch("/jobs/check-relevance", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        search_id: _searchId,
        url: url,
        resume_text: document.getElementById("resume")?.value.trim() || "",
        email: (profile || {}).email || "",
      }),
    });
    const d = await r.json();
    if (!d.ok || !d.score) return 0;
    job.total_score = d.score.total_score;
    job.ai_score = d.score.ai_score;
    job.keyword_score = d.score.keyword_score;
    job.reason = d.score.reason || "";
    rerenderJobCard(job);
    return job.total_score;
  } catch {
    return 0;
  }
};

window.getReferralJobDescription = function (url) {
  const job = allJobs.find(j => j.url === url) || customJobs.find(j => j.url === url) || aiJobs.find(j => j.url === url);
  return (job && job.description) || "";
};

async function doSaveJob(job) {
  const profile = window.getProfile();
  if (!profile) return;
  try {
    const r = await fetch("/api/saved-jobs", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        email: profile.email,
        title: job.title || "",
        company: job.company || "",
        url: job.url || "",
        location: job.location || "",
        salary: job.salary || "",
        total_score: job.total_score || 0,
        ai_score: job.ai_score || 0,
        keyword_score: job.keyword_score || 0,
        experience_level: job.experience_level || "",
        tags: job.tags || [],
        site: job._site || "",
      }),
    });
    const d = await r.json();
    if (d.saved) {
      job._saved = true;
      job._savedId = d.id;
      updateSaveButtons();
      window.showToast("Job saved!");
    }
  } catch {}
}

async function doUnsaveJob(job) {
  if (!job._savedId) return;
  try {
    await fetch(`/api/saved-jobs/${job._savedId}`, { method: "DELETE" });
    job._saved = false;
    job._savedId = null;
    updateSaveButtons();
    window.showToast("Job removed from saved", '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>');
  } catch {}
}

function updateSaveButtons() {
  document.querySelectorAll(".bookmark-btn").forEach(btn => {
    const url = btn.dataset.url;
  const job = allJobs.find(j => j.url === url) || customJobs.find(j => j.url === url) || aiJobs.find(j => j.url === url);
    if (!job) return;
    if (job._saved) {
      btn.innerHTML = '<svg class="w-3 h-3" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg> Saved';
      btn.classList.add("bg-indigo-500", "text-white", "border-indigo-500", "hover:bg-indigo-600");
      btn.classList.remove("bg-indigo-50", "text-indigo-600", "border-indigo-200", "hover:bg-indigo-100", "active:bg-indigo-200");
    } else {
      btn.innerHTML = '<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4"/></svg> Save';
      btn.classList.remove("bg-indigo-500", "text-white", "border-indigo-500", "hover:bg-indigo-600");
      btn.classList.add("bg-indigo-50", "text-indigo-600", "border-indigo-200", "hover:bg-indigo-100", "active:bg-indigo-200");
    }
  });
}

async function checkSavedStatuses() {
  const profile = window.getProfile();
  if (!profile) return;
  const jobsToCheck = allJobs;
  const urls = jobsToCheck.map(j => j.url).filter(Boolean);
  if (!urls.length) return;
  try {
    const r = await fetch("/api/saved-jobs/batch-check", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ email: profile.email, urls }),
    });
    const d = await r.json();
    if (d.saved_map) {
      jobsToCheck.forEach(j => {
        const sid = d.saved_map[j.url];
        if (sid) {
          j._saved = true;
          j._savedId = sid;
        }
      });
      updateSaveButtons();
    }
  } catch {}
}

function logEvent(event, data = {}, elapsed = 0) {
  try {
    const body = JSON.stringify({ session_id: _searchId, event, data, elapsed });
    const blob = new Blob([body], { type: "application/json" });
    navigator.sendBeacon("/api/events", blob);
  } catch {}
}

function cancelActiveSearch() {
  const allIds = searchIds.length > 0 ? searchIds : (_searchId ? [_searchId] : []);
  for (const sid of allIds) {
    try { navigator.sendBeacon(`/scrape/stop?search_id=${sid}`); } catch {}
  }
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
}
window.addEventListener("beforeunload", cancelActiveSearch);
window.addEventListener("pagehide", cancelActiveSearch);

function getFilteredJobs() {
  let jobs = allJobs;
  if (activeFilters.site)
    jobs = jobs.filter(j => siteFromUrl(j.url).toLowerCase() === activeFilters.site.toLowerCase());
  if (activeFilters.experience_level)
    jobs = jobs.filter(j => j.experience_level === activeFilters.experience_level);
  return jobs;
}

function siteFromUrl(url) {
  if (!url) return '';
  if (url.includes('linkedin')) return 'LinkedIn';
  if (url.includes('indeed')) return 'Indeed';
  return new URL(url).hostname.replace('www.', '').split('.')[0];
}

// ===== INIT =====
checkRawJobs();
loadRoles();
(() => {
  try {
    const saved = localStorage.getItem(RESUME_CACHE_KEY);
    if (saved) {
      document.getElementById("resume").value = saved;
      document.getElementById("refreshRolesBtn").disabled = false;
    }
  } catch {}
})();
updateSearchBtn();
setupLocationSearch();
(async () => {
  await fetchCountries();
  await loadStates();
})();
const _hasCachedSearch = (() => {
  try {
    const raw = localStorage.getItem(SEARCH_CACHE_KEY);
    if (!raw) return false;
    const saved = JSON.parse(raw);
    return saved && saved.searchIds && saved.searchIds.length > 0 && Date.now() - saved.timestamp < SEARCH_CACHE_TTL;
  } catch { return false; }
})();
if (_hasCachedSearch) {
  const el = document.getElementById("splashOverlay");
  if (el) el.classList.add("splash-hidden");
} else {
  setTimeout(() => {
    const el = document.getElementById("splashOverlay");
    if (el) el.classList.add("splash-hidden");
  }, 2000);
}

async function checkRawJobs() {
  try { const r = await fetch("/scrape/status"); const d = await r.json(); hasRawJobs = d.last_scrape_raw > 0; } catch {}
}

// ===== HELPERS =====
function showElement(id) { document.getElementById(id).classList.remove("hidden"); }
function hideElement(id) { document.getElementById(id).classList.add("hidden"); }

function setStatus(msg, type = "blue") {
  const el = document.getElementById("status");
  if (!msg) {
    el.classList.add("hidden");
    el.innerHTML = "";
    return;
  }
  el.classList.remove("hidden", "bg-indigo-50", "text-indigo-700", "border-indigo-100", "bg-red-50", "text-red-700", "border-red-100", "bg-emerald-50", "text-emerald-700", "border-emerald-100", "bg-amber-50", "text-amber-700", "border-amber-100");

  let icon = '';
  if (type === "red") {
    el.classList.add("bg-red-50", "text-red-700", "border-red-100");
    icon = '<svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>';
  } else if (type === "green") {
    el.classList.add("bg-emerald-50", "text-emerald-700", "border-emerald-100");
    icon = '<svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>';
  } else if (type === "amber") {
    el.classList.add("bg-amber-50", "text-amber-700", "border-amber-100");
    icon = '<svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>';
  } else {
    el.classList.add("bg-indigo-50", "text-indigo-700", "border-indigo-100");
    icon = '<svg class="w-4 h-4 shrink-0 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path></svg>';
  }

  el.innerHTML = `${icon}<span>${msg}</span>`;
}

function renderTimeline(logs, status) {
  const siteIcons = { linkedin: "in", indeed: "indeed" };

  let html = "";
  const shown = new Set();

  for (const log of logs || []) {
    const msg = log.event || log.message || "";
    const elapsed = log.elapsed_seconds || 0;
    const ts = elapsed ? `${elapsed}s` : "";

    let m = msg.match(/\[(?:SCRAPE|DIRECT)\] (Pass \d+\/\d+ — )?(\w+)\.\.\.$/);
    if (m) {
      const site = m[2];
      const key = `site-start-${site}`;
      if (!shown.has(key)) {
        shown.add(key);
        const icon = siteIcons[site] || site.slice(0, 3).toUpperCase();
        html += `<div class="flex items-center gap-3 py-1.5 text-slate-600 timeline-active">
          <span class="w-14 text-xs text-slate-400 shrink-0">${ts}</span>
          <span class="w-10 h-6 rounded text-[10px] font-bold bg-blue-100 text-blue-700 flex items-center justify-center shrink-0">${icon}</span>
          <span class="text-sm text-slate-500">Fetching jobs...</span>
        </div>`;
      }
      continue;
    }

    m = msg.match(/\[(?:SCRAPE|DIRECT)\] (\w+) returned (\d+) jobs/);
    if (m) {
      const site = m[1];
      const count = m[2];
      const key = `site-done-${site}`;
      if (!shown.has(key)) {
        shown.add(key);
        const icon = siteIcons[site] || site.slice(0, 3).toUpperCase();
        html += `<div class="flex items-center gap-3 py-1.5 text-slate-700">
          <span class="w-14 text-xs text-slate-400 shrink-0">${ts}</span>
          <span class="w-10 h-6 rounded text-[10px] font-bold bg-green-100 text-green-700 flex items-center justify-center shrink-0">${icon}</span>
          <span class="text-green-700 font-medium">${count} jobs</span>
        </div>`;
      }
      continue;
    }

    m = msg.match(/\[(?:SCRAPE|DIRECT)\] (\w+): (\d+) fetched, (\d+) new/);
    if (m) {
      const site = m[1];
      const count = m[2];
      const newCount = m[3];
      const key = `site-pass-${site}-${newCount}`;
      if (!shown.has(key) && parseInt(newCount) > 0) {
        shown.add(key);
        const icon = siteIcons[site] || site.slice(0, 3).toUpperCase();
        html += `<div class="flex items-center gap-3 py-1.5 text-slate-700">
          <span class="w-14 text-xs text-slate-400 shrink-0">${ts}</span>
          <span class="w-10 h-6 rounded text-[10px] font-bold bg-green-100 text-green-700 flex items-center justify-center shrink-0">${icon}</span>
          <span class="text-green-700 font-medium">+${newCount} jobs</span>
        </div>`;
      }
      continue;
    }

    m = msg.match(/\[(?:SCRAPE|DIRECT)\] Total raw jobs: (\d+)/);
    if (m && !shown.has("total-raw")) {
      shown.add("total-raw");
      html += `<div class="flex items-center gap-3 py-1.5 text-slate-500 border-t border-slate-100 mt-1 pt-2">
        <span class="w-14 text-xs text-slate-400 shrink-0">${ts}</span>
        <span class="text-slate-600">${m[1]} jobs collected</span>
      </div>`;
      continue;
    }

    m = msg.match(/\[(?:DIRECT)\] Title filter: \d+ → (\d+)/);
    if (m && !shown.has("title-filter")) {
      shown.add("title-filter");
      html += `<div class="flex items-center gap-3 py-1.5 text-slate-600">
        <span class="w-14 text-xs text-slate-400 shrink-0">${ts}</span>
        <span class="text-slate-600">${m[1]} jobs match role</span>
      </div>`;
      continue;
    }

    m = msg.match(/\[(?:DIRECT)\] Internship filter: \d+ → (\d+)/);
    if (m && !shown.has("exp-filter")) {
      shown.add("exp-filter");
      html += `<div class="flex items-center gap-3 py-1.5 text-slate-600">
        <span class="w-14 text-xs text-slate-400 shrink-0">${ts}</span>
        <span class="text-slate-600">${m[1]} internship/entry-level jobs</span>
      </div>`;
      continue;
    }

    m = msg.match(/\[SCORE\] Batch (\d+)\/(\d+) done/);
    if (m && !shown.has("scoring")) {
      shown.add("scoring");
      html += `<div class="flex items-center gap-3 py-1.5 timeline-active">
        <span class="w-14 text-xs text-slate-400 shrink-0">${ts}</span>
        <span class="w-10 h-6 rounded text-[10px] font-bold bg-purple-100 text-purple-700 flex items-center justify-center shrink-0">AI</span>
        <span class="text-slate-600">Scoring batch ${m[1]}/${m[2]}...</span>
      </div>`;
      continue;
    }

    m = msg.match(/\[MATCH ENGINE\] (\d+) relevant jobs returned/);
    if (m && !shown.has("matches")) {
      shown.add("matches");
      html += `<div class="flex items-center gap-3 py-1.5 text-slate-700">
        <span class="w-14 text-xs text-slate-400 shrink-0">${ts}</span>
        <span class="w-10 h-6 rounded text-[10px] font-bold bg-green-100 text-green-700 flex items-center justify-center shrink-0">✓</span>
        <span class="text-green-700 font-medium">${m[1]} matches found</span>
      </div>`;
      continue;
    }

    m = msg.match(/\[(?:SCRAPE|DIRECT)\] Pipeline complete/);
    if (m && !shown.has("complete")) {
      shown.add("complete");
      const matchCount = msg.match(/(\d+) relevant/);
      const label = matchCount ? `${matchCount[1]} matches` : "Done";
      html += `<div class="flex items-center gap-3 py-1.5 text-slate-700 border-t border-slate-100 mt-1 pt-2">
        <span class="w-14 text-xs text-slate-400 shrink-0">${ts}</span>
        <span class="w-10 h-6 rounded text-[10px] font-bold bg-green-100 text-green-700 flex items-center justify-center shrink-0">✓</span>
        <span class="text-green-700 font-medium">Analysis complete — ${label}</span>
      </div>`;
      continue;
    }

    m = msg.match(/\[(?:SCRAPE|DIRECT)\] Enough relevant \((\d+).*\), stopping/);
    if (m && !shown.has("enough")) {
      shown.add("enough");
      html += `<div class="flex items-center gap-3 py-1.5 text-slate-700">
        <span class="w-14 text-xs text-slate-400 shrink-0">${ts}</span>
        <span class="w-10 h-6 rounded text-[10px] font-bold bg-green-100 text-green-700 flex items-center justify-center shrink-0">✓</span>
        <span class="text-green-700 font-medium">${m[1]} matches — target reached</span>
      </div>`;
      continue;
    }

    if ((msg.includes("Cancelled") || msg.includes("cancelled")) && !shown.has("cancelled")) {
      shown.add("cancelled");
      html += `<div class="flex items-center gap-3 py-1.5 text-red-600">
        <span class="w-14 text-xs text-slate-400 shrink-0">${ts}</span>
        <span class="w-10 h-6 rounded text-[10px] font-bold bg-red-100 text-red-700 flex items-center justify-center shrink-0">✕</span>
        <span>Cancelled</span>
      </div>`;
    }
  }

  if (!html) {
    if (status === "running") {
      html = `<div class="flex items-center gap-3 py-1.5 text-slate-500 timeline-active">
        <span class="w-14 text-xs text-slate-400 shrink-0"></span>
        <span class="text-slate-500">Starting up...</span>
      </div>`;
    } else {
      html = `<div class="text-base text-slate-400 py-2">No activity yet</div>`;
    }
  }

  return `<div class="premium-card p-4 mb-4"><div class="flex flex-col gap-1.5 text-sm font-mono">${html}</div></div>`;
}

function resetSearchBtn() {
  const btn = document.getElementById("searchBtn");
  btn.innerHTML = '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg> Start Search';
  btn.disabled = false;
  document.getElementById("extractBtn").disabled = false;
}

function updateCountBadge(n) {
}

function updateSearchBtn() {}

function clearTargetRoles() {
  selectedRoles.clear();
  customRoles = [];
  document.querySelectorAll(".role-cb").forEach(cb => { cb.checked = false; });
  renderSelectedRoles();
  updateRoleCount();
  const sr = document.getElementById("suggestedRoles");
  if (sr) { sr.innerHTML = ""; sr.classList.add("hidden"); }
  const rsi = document.getElementById("roleSearchInput");
  if (rsi) rsi.value = "";
}

function clearSearchState() {
  cancelActiveSearch();
  allJobs = [];
  customJobs = [];
  aiJobs = [];
  searchIds = [];
  _customRoleList = [];
  _aiRoleList = [];
  suggestedRoles = [];
  searchMode = 'current';
  _searchComplete = false;
  _searchId = crypto.randomUUID();
  resetRelevanceState();
  _uploadedFilename = "";
  lastRenderedCount = 0;
  hasRawJobs = false;
  scrapeAttempts = 0;
  shownSlowWarning = false;
  activeFilters = { site: '', experience_level: '' };
  currentSort = 'relevant';
  _currentPage = 1;
  document.getElementById("results").innerHTML = `
    <div class="premium-card min-h-[400px] flex flex-col items-center justify-center text-center p-8">
      <div class="w-16 h-16 rounded-2xl bg-slate-50 flex items-center justify-center mb-5 border border-slate-100">
        <svg class="w-6 h-6 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 002-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"/></svg>
      </div>
      <h3 class="text-base font-semibold text-slate-800">No jobs to display yet</h3>
      <p class="text-sm text-slate-500 mt-1 max-w-sm">Upload your resume, set your target roles and location, and start the search to find your match.</p>
    </div>`;
  const fb = document.getElementById("filterBar");
  if (fb) fb.classList.add("hidden");
  hideTabBar();
  const sr = document.getElementById("suggestedRoles");
  if (sr) { sr.innerHTML = ""; sr.classList.add("hidden"); }
  document.title = "AI Job Agent";
  setStatus("", "");
  localStorage.removeItem(SEARCH_CACHE_KEY);
}

// ===== TAB MANAGEMENT =====
const SPINNER_SVG = '<svg class="w-3.5 h-3.5 animate-spin inline mr-1.5" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>';

function statusBanner(msg, color = 'blue') {
  if (!msg) return '';
  const colors = {
    blue: 'bg-blue-50 text-blue-700 border-blue-100',
    green: 'bg-emerald-50 text-emerald-700 border-emerald-100',
    red: 'bg-red-50 text-red-700 border-red-100'
  };
  return `<div class="flex items-center px-4 py-2.5 mb-4 rounded-xl border text-sm font-medium ${colors[color] || colors.blue}">${msg}</div>`;
}

const SITE_ICONS = { linkedin: "in", indeed: "indeed" };

function isRoleSimilar(roleA, roleB) {
  const a = roleA.toLowerCase().replace(/[^a-z0-9 ]/g, '').trim();
  const b = roleB.toLowerCase().replace(/[^a-z0-9 ]/g, '').trim();
  if (a === b) return true;
  if (a.includes(b) || b.includes(a)) return true;
  const wordsA = a.split(/\s+/);
  const wordsB = b.split(/\s+/);
  const common = wordsA.filter(w => wordsB.includes(w) && w.length > 3);
  return common.length >= Math.min(wordsA.length, wordsB.length) * 0.6;
}

// ===== TAB FUNCTIONS =====
function showTabBar() {
  const el = document.getElementById("tabBar");
  if (el) el.classList.remove("hidden");
  updateTabCounts();
}

function hideTabBar() {
  const el = document.getElementById("tabBar");
  if (el) el.classList.add("hidden");
}

function switchTab(tab) {
  activeTab = tab;
  const customBtn = document.getElementById("tabCustom");
  const aiBtn = document.getElementById("tabAI");
  if (tab === 'custom') {
    customBtn.className = 'px-4 py-2.5 text-sm font-semibold border-b-2 border-indigo-600 text-slate-900 transition-colors rounded-t-lg hover:bg-slate-50';
    aiBtn.className = 'px-4 py-2.5 text-sm font-semibold border-b-2 border-transparent text-slate-400 hover:text-slate-600 transition-colors rounded-t-lg hover:bg-slate-50';
  } else {
    aiBtn.className = 'px-4 py-2.5 text-sm font-semibold border-b-2 border-indigo-600 text-slate-900 transition-colors rounded-t-lg hover:bg-slate-50';
    customBtn.className = 'px-4 py-2.5 text-sm font-semibold border-b-2 border-transparent text-slate-400 hover:text-slate-600 transition-colors rounded-t-lg hover:bg-slate-50';
  }
  renderActiveTab();
}

function updateTabCounts() {
  const c = document.getElementById("tabCustomCount");
  const a = document.getElementById("tabAICount");
  if (c) c.textContent = customJobs.length;
  if (a) a.textContent = aiJobs.length;
}

function renderActiveTab() {
  const jobs = activeTab === 'custom' ? customJobs : aiJobs;
  renderAllJobs(jobs);
}

document.getElementById("resume").addEventListener("input", updateSearchBtn);
document.getElementById("resume").addEventListener("input", () => {
  try { localStorage.setItem(RESUME_CACHE_KEY, document.getElementById("resume").value); } catch {}
  if (document.getElementById("resume").value.trim()) clearSearchState();
});

// Enable Refresh button only when resume text exists (respects cooldown)
document.getElementById("resume").addEventListener("input", () => {
  const hasResume = !!document.getElementById("resume").value.trim();
  document.getElementById("refreshRolesBtn").disabled = !hasResume || _refreshCooldown;
});

// ===== RESUME UPLOAD =====
document.getElementById("fileInput").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const lbl = document.getElementById("uploadLabel");
  const orig = lbl.textContent;
  lbl.textContent = "Uploading...";
  try {
    const form = new FormData();
    form.append("file", file);
    const r = await fetch("/resume/upload", { method: "POST", body: form });
    const d = await r.json();
    document.getElementById("resume").value = d.text;
    try { localStorage.setItem(RESUME_CACHE_KEY, d.text); } catch {}
    document.getElementById("refreshRolesBtn").disabled = false;
    clearTargetRoles();
    clearSearchState();
    _uploadedFilename = d.filename;
    updateSearchBtn();
    document.getElementById("extractBtn").click();
  } catch (err) {
    setStatus("Upload failed: " + err.message, "red");
  } finally {
    lbl.textContent = orig;
    e.target.value = "";
  }
});

function applyThreshold() {
  _currentPage = 1;
  const tabBar = document.getElementById('tabBar');
  const isTabs = tabBar && !tabBar.classList.contains('hidden');
  const baseJobs = isTabs ? (activeTab === 'custom' ? customJobs : aiJobs) : allJobs;
  if (_activeSubFilterRole === 'all') {
    renderAllJobs(baseJobs);
  } else {
    renderAllJobs(baseJobs.filter(j => j._matched_role === _activeSubFilterRole));
  }
}

// ===== RESUME -> KEYWORDS =====
document.getElementById("extractBtn").addEventListener("click", async () => {
  const resume = document.getElementById("resume").value.trim();
  if (!resume) { setStatus("Please paste or upload your resume first.", "red"); return; }
  const btn = document.getElementById("extractBtn");
  btn.textContent = "Extracting...";
  btn.disabled = true;
  try {
    const r = await fetch("/resume/keywords", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ resume_text: resume }) });
    const d = await r.json();
    renderKeywords(d.keywords);
    if (d.suggested_roles) {
      renderSuggestedRoles(d.suggested_roles);
      suggestedRoles = d.suggested_roles;
    }
    setStatus("Keywords successfully extracted.", "green");
  } catch (e) { setStatus("Failed to extract keywords.", "red"); }
  finally { btn.textContent = "✨ Auto-Extract Keywords"; btn.disabled = false; }
});

document.getElementById("refreshRolesBtn").addEventListener("click", async () => {
  if (_refreshCooldown) return;
  const resume = document.getElementById("resume").value.trim();
  if (!resume) { setStatus("Paste or upload your resume first.", "red"); return; }
  _refreshCooldown = true;
  const btn = document.getElementById("refreshRolesBtn");
  btn.disabled = true;
  try {
    const r = await fetch("/resume/keywords", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ resume_text: resume }) });
    const d = await r.json();
    if (d.suggested_roles) {
      renderSuggestedRoles(d.suggested_roles);
      suggestedRoles = d.suggested_roles;
    }
    setStatus("Recommended roles refreshed.", "green");
  } catch (e) { setStatus("Failed to refresh roles.", "red"); }
  setTimeout(() => {
    _refreshCooldown = false;
    if (document.getElementById("resume").value.trim()) {
      btn.disabled = false;
    }
  }, 10000);
});

function renderKeywords(kws) {
  const c = document.getElementById("keywords");
  if (!kws.length) { c.innerHTML = '<span class="text-sm text-slate-400 italic">No keywords found</span>'; return; }
  c.innerHTML = kws.map(k => `
    <label class="inline-flex items-center gap-2 px-3 py-2 border rounded-lg text-sm font-medium cursor-pointer transition-colors ${k.selected ? 'bg-slate-900 text-white border-slate-900' : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'}">
      <input type="checkbox" value="${k.word}" ${k.selected ? "checked" : ""} class="hidden" onchange="this.parentElement.classList.toggle('bg-slate-900');this.parentElement.classList.toggle('text-white');this.parentElement.classList.toggle('border-slate-900');this.parentElement.classList.toggle('bg-white');this.parentElement.classList.toggle('text-slate-600');this.parentElement.classList.toggle('border-slate-200');updateKwCount()">
      <span>${k.word}</span>
    </label>`).join("");
  updateKwCount();
}

function renderSuggestedRoles(roles) {
  const c = document.getElementById("suggestedRoles");
  if (!c || !roles || !roles.length) { if (c) c.classList.add("hidden"); return; }
  const allRoles = Object.values(roleCategories || {}).flat();
    c.innerHTML = '<span class="text-xs font-medium text-indigo-500 mr-1 self-center">✨ Recommended</span>' +
    roles.map(r => {
      const exists = allRoles.includes(r);
      const isSelected = selectedRoles.has(r) || customRoles.includes(r);
      return `<span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium border cursor-pointer transition-colors ${isSelected ? 'bg-indigo-100 text-indigo-700 border-indigo-200' : 'bg-indigo-50 text-indigo-600 border-indigo-100 hover:bg-indigo-100'}" onclick="selectSuggestedRole('${r.replace(/'/g, "\\'")}')">
        ${r} <span class="text-indigo-400">+</span>
      </span>`;
    }).join("");
  c.classList.remove("hidden");
}

function selectSuggestedRole(role) {
  const allRoles = Object.values(roleCategories || {}).flat();
  if (allRoles.includes(role)) {
    const cb = document.querySelector(`.role-cb[value="${role}"]`);
    if (cb) {
      cb.checked = true;
      selectedRoles.add(role);
      cb.dispatchEvent(new Event("change"));
    }
  } else {
    addRoleFromSearch(role);
  }
  updateRoleCount();
}

function updateKwCount() {
  const n = getSelectedKeywords().length;
  document.getElementById("kwCount").textContent = n;
}

// ===== CUSTOM KEYWORDS =====
function addKeyword() {
  const i = document.getElementById("customKeywordInput");
  const kw = i.value.trim().toLowerCase();
  if (!kw || customKeywords.includes(kw)) return;
  customKeywords.push(kw); i.value = ""; renderCustomKeywords(); updateKwCount();
}

document.getElementById("addKeywordBtn").addEventListener("click", addKeyword);
document.getElementById("customKeywordInput").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); addKeyword(); } });

function renderCustomKeywords() {
  const c = document.getElementById("customKeywords");
  c.innerHTML = customKeywords.map(kw => `
    <span class="inline-flex items-center gap-1.5 bg-indigo-50 border border-indigo-100 text-indigo-700 text-sm px-3 py-1.5 rounded-lg font-medium">
      <span>${kw}</span>
      <button class="remove-kw hover:text-indigo-900 ml-1 opacity-70 hover:opacity-100" data-kw="${kw}">
        <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
      </button>
    </span>`).join("");
  c.querySelectorAll(".remove-kw").forEach(b => b.addEventListener("click", () => { customKeywords = customKeywords.filter(k => k !== b.dataset.kw); renderCustomKeywords(); updateKwCount(); }));
}

// ===== ROLES =====
let roleCategories = null;
let roleSearchQuery = "";

async function loadRoles() {
  try { const r = await fetch("/roles"); const d = await r.json(); roleCategories = d.categories; renderRoles(roleCategories); } catch {}
}

function addRoleFromSearch(val) {
  if (!val || customRoles.includes(val)) return;
  customRoles.push(val);
  document.getElementById("roleSearchInput").value = "";
  roleSearchQuery = "";
  renderCustomRoles();
  updateRoleCount();
  if (roleCategories) renderRoles(roleCategories);
}

function renderRoles(categories) {
  const c = document.getElementById("roles");
  const q = roleSearchQuery.toLowerCase().trim();
  let allRoles = Object.values(categories).flat();
  if (q) {
    const words = q.split(/\s+/);
    allRoles = allRoles.filter(r => words.every(w => r.toLowerCase().includes(w)));
  }
  if (!allRoles.length && q) {
    const alreadyAdded = customRoles.includes(q);
    if (alreadyAdded) {
      c.innerHTML = '<span class="text-sm text-slate-400 italic px-2">Role already added</span>';
    } else {
      c.innerHTML = `<button class="w-full text-left flex items-center gap-2.5 px-3 py-2 rounded-lg hover:bg-emerald-50 cursor-pointer text-sm text-emerald-700 font-medium transition-colors" onclick="addRoleFromSearch('${q.replace(/'/g, "\\'")}')">
        <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>
        <span>Add <strong>${q}</strong> role</span>
      </button>`;
    }
    return;
  }
  c.innerHTML = allRoles.map(r =>
    `<label class="flex items-center gap-2.5 px-2 py-1.5 rounded-lg hover:bg-slate-50 cursor-pointer text-sm text-slate-600 transition-colors">
      <input type="checkbox" class="role-cb w-4 h-4 rounded border-slate-300 text-slate-900 focus:ring-slate-900" value="${r}" onchange="onRoleToggle(this)" ${selectedRoles.has(r) ? 'checked' : ''}>
      <span>${r}</span>
    </label>`
  ).join("");
}

function toggleRoleClearBtn() {
  const btn = document.getElementById("clearRoleSearch");
  if (!btn) return;
  btn.classList.toggle("hidden", !document.getElementById("roleSearchInput").value);
}

function filterRoles() {
  roleSearchQuery = document.getElementById("roleSearchInput").value;
  toggleRoleClearBtn();
  if (roleCategories) renderRoles(roleCategories);
}

document.getElementById("roleSearchInput").addEventListener("input", filterRoles);
document.getElementById("clearRoleSearch").addEventListener("click", () => {
  document.getElementById("roleSearchInput").value = "";
  roleSearchQuery = "";
  toggleRoleClearBtn();
  if (roleCategories) renderRoles(roleCategories);
  document.getElementById("roleSearchInput").focus();
});

document.getElementById("roleSearchInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    const val = e.target.value.trim();
    if (!val) return;
    const allRoles = Object.values(roleCategories || {}).flat();
    const exactMatch = allRoles.find(r => r.toLowerCase() === val.toLowerCase());
    if (exactMatch) {
      const cb = document.querySelector(`.role-cb[value="${exactMatch}"]`);
      if (cb) {
        cb.checked = !cb.checked;
        cb.dispatchEvent(new Event("change"));
      }
      document.getElementById("roleSearchInput").value = "";
      roleSearchQuery = "";
      toggleRoleClearBtn();
      if (roleCategories) renderRoles(roleCategories);
    } else {
      addRoleFromSearch(val);
      toggleRoleClearBtn();
    }
  }
});

function renderCustomRoles() {
  const c = document.getElementById("customRoles");
  c.innerHTML = customRoles.map(r => `
    <span class="inline-flex items-center gap-1.5 bg-emerald-50 border border-emerald-100 text-emerald-700 text-sm px-3 py-1.5 rounded-lg font-medium">
      <span>${r}</span>
      <button class="remove-role hover:text-emerald-900 ml-1 opacity-70 hover:opacity-100" data-role="${r}">
        <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
      </button>
    </span>`).join("");
  c.querySelectorAll(".remove-role").forEach(b => b.addEventListener("click", () => { customRoles = customRoles.filter(r => r !== b.dataset.role); renderCustomRoles(); updateRoleCount(); }));
}

function onRoleToggle(cb) {
  if (cb.checked) {
    selectedRoles.add(cb.value);
  } else {
    selectedRoles.delete(cb.value);
  }
  updateRoleCount();
}

function renderSelectedRoles() {
  const c = document.getElementById("selectedRoles");
  if (!selectedRoles.size) { c.innerHTML = ""; return; }
  c.innerHTML = [...selectedRoles].map(r => `
    <span class="inline-flex items-center gap-1.5 bg-indigo-50 border border-indigo-100 text-indigo-700 text-sm px-3 py-1.5 rounded-lg font-medium">
      <span>${r}</span>
      <button class="deselect-role hover:text-indigo-900 ml-1 opacity-70 hover:opacity-100" data-role="${r}">
        <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
      </button>
    </span>`).join("");
  c.querySelectorAll(".deselect-role").forEach(b => b.addEventListener("click", () => {
    selectedRoles.delete(b.dataset.role);
    if (roleCategories) renderRoles(roleCategories);
    updateRoleCount();
  }));
}

function updateRoleCount() {
  document.getElementById("roleCount").textContent = selectedRoles.size + customRoles.length;
  renderSelectedRoles();
  updateSearchBtn();
}

function getSelectedRoles() { return [...selectedRoles, ...customRoles]; }
function getSelectedSites() { return Array.from(document.querySelectorAll("#sites input:checked:not(:disabled)")).map(e => e.value); }
function getSelectedKeywords() { return [...Array.from(document.querySelectorAll("#keywords input:checked")).map(e => e.value), ...customKeywords]; }

// ===== LOCATION SEARCH =====
async function fetchCountries() {
  try {
    const r = await fetch("https://api.countrystatecity.in/v1/countries", {
      headers: { "X-CSCAPI-KEY": "99b742739363f29d601908be8af875f40eede6b161f6b455da3e85b8373ccc45" }
    });
    const data = await r.json();
    data.forEach(c => { countriesMap[c.iso2.toLowerCase()] = c.name; });
  } catch {}
}

let LOCATION_OVERRIDE = { us: "usa", gb: "uk", ae: "united arab emirates" };

async function loadStates() {
  try {
    const r = await fetch("/states");
    const d = await r.json();
    allStates = d.states || [];
  } catch {}
}

function setupLocationSearch() {
  const input = document.getElementById("locationInput");
  const results = document.getElementById("locationResults");
  const selected = document.getElementById("selectedLocation");

  input.addEventListener("input", () => {
    const q = input.value.trim();
    if (selectedLocation) { selectedLocation = null; selected.classList.add("hidden"); }
    if (q.length < 2) { results.classList.add("hidden"); return; }
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => searchState(q), 200);
  });

  input.addEventListener("blur", () => setTimeout(() => results.classList.add("hidden"), 200));
  input.addEventListener("focus", () => {
    if (results.children.length) results.classList.remove("hidden");
  });
}

function searchState(query) {
  if (query === lastQuery) return;
  lastQuery = query;
  const results = document.getElementById("locationResults");
  results.innerHTML = "";
  const lower = query.toLowerCase();

  const countryMatches = Object.entries(countriesMap)
    .filter(([code, name]) => name.toLowerCase().includes(lower) || code.includes(lower))
    .slice(0, 3)
    .map(([code, name]) => ({
      state: null,
      country: name,
      country_code: code,
      label: name
    }));

  let stateMatches = [];
  if (allStates.length) {
    const count = Math.max(0, 6 - countryMatches.length);
    stateMatches = allStates
      .filter(s => s.state.toLowerCase().includes(lower))
      .slice(0, count)
      .map(item => ({
        state: item.state,
        country: item.country,
        country_code: item.country_code,
        label: [item.state, item.country].filter(Boolean).join(", ")
      }));
  }

  const matches = [...countryMatches, ...stateMatches];
  if (!matches.length) {
    results.innerHTML = '<div class="px-4 py-3 text-xs text-slate-400">No matching locations</div>';
    results.classList.remove("hidden");
    return;
  }
  matches.forEach(item => {
    const div = document.createElement("div");
    div.className = "px-4 py-2.5 text-xs cursor-pointer hover:bg-slate-50 text-slate-700 border-b border-slate-50 last:border-0 font-medium transition-colors";
    div.textContent = item.label;
    div.addEventListener("mousedown", (e) => {
      e.preventDefault();
      selectLocation({ state: item.state, country: item.country, country_code: item.country_code, label: item.label });
    });
    results.appendChild(div);
  });
  results.classList.remove("hidden");
}

function selectLocation(loc) {
  selectedLocation = loc;
  document.getElementById("locationInput").value = loc.label;
  document.getElementById("locationResults").classList.add("hidden");
  const el = document.getElementById("selectedLocation");
  el.innerHTML = `
    <svg class="w-3 h-3 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
    <span>${loc.label}</span>
    <button class="ml-1 text-emerald-600/60 hover:text-emerald-800" id="clearLocation">
      <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
    </button>`;
  el.classList.remove("hidden");
  document.getElementById("clearLocation").addEventListener("click", () => {
    selectedLocation = null;
    el.classList.add("hidden");
    document.getElementById("locationInput").value = "";
  });
}

function getIndeedCountry() {
  if (!selectedLocation) return "USA";
  const cc = selectedLocation.country_code;
  return LOCATION_OVERRIDE[cc] || countriesMap[cc] || "usa";
}
function getLocation() {
  if (!selectedLocation) return "";
  return [selectedLocation.state, selectedLocation.country].filter(Boolean).join(", ");
}

// ===== INTERNSHIP MODE TOGGLE =====
document.getElementById("internshipToggle").addEventListener("click", () => {
  internshipMode = !internshipMode;
  const toggle = document.getElementById("internshipToggle");
  const knob = document.getElementById("toggleKnob");
  const btn = document.getElementById("searchBtn");

  if (internshipMode) {
    document.body.classList.add("internship-mode");
    toggle.classList.replace("bg-slate-200", "bg-teal-500");
    knob.style.transform = "translateX(20px)";
    btn.innerHTML = '<span class="text-base">🎓</span> Search Internships';
  } else {
    document.body.classList.remove("internship-mode");
    toggle.classList.replace("bg-teal-500", "bg-slate-200");
    knob.style.transform = "translateX(0)";
    btn.innerHTML = '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg> Start Search';
  }
});

// ===== SEARCH =====
document.getElementById("searchBtn").addEventListener("click", async () => {
  const resume = document.getElementById("resume").value.trim();
  if (!resume) return setStatus("Missing required field: Please paste or upload your resume.", "red");

  _searchStart = Date.now();
  const sites = getSelectedSites(), keywords = getSelectedKeywords();
  _selectedSites = sites.slice();

  searchIds = [];
  _customRoleList = [];
  _aiRoleList = [];
  allJobs = [];
  customJobs = [];
  aiJobs = [];
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;

  const allSelectedRoles = getSelectedRoles();
  if (!allSelectedRoles.length) return setStatus("Missing required field: Select at least one job role.", "red");
  if (!sites.length) return setStatus("Missing required field: Select at least one job board.", "red");
  if (!document.getElementById("locationInput").value.trim()) return setStatus("Missing required field: Enter a location.", "red");

  // Separate roles into custom (user-selected non-AI) vs AI-suggested
  const aiRoleSet = new Set(suggestedRoles.map(r => r.toLowerCase()));
  const userAISelected = allSelectedRoles.filter(r => aiRoleSet.has(r.toLowerCase()));
  const userCustomSelected = allSelectedRoles.filter(r => !aiRoleSet.has(r.toLowerCase()));

  let rolesToScrape;
  if (userAISelected.length > 0) {
    _customRoleList = userCustomSelected;
    _aiRoleList = userAISelected;
    rolesToScrape = [...new Set([...userCustomSelected, ...userAISelected])];
  } else {
    _customRoleList = [...new Set([...allSelectedRoles, ...suggestedRoles])];
    _aiRoleList = suggestedRoles;
    rolesToScrape = _customRoleList;
  }

  // In internship mode, discard senior/managerial roles
  if (internshipMode) {
    const SENIORITY_RE = /\b(senior|sr\.?|lead|principal|staff|director|vp|vice president|chief|head of|manager|architect|founding|partner)\b/i;
    rolesToScrape = rolesToScrape.filter(r => !SENIORITY_RE.test(r));
    _customRoleList = _customRoleList.filter(r => !SENIORITY_RE.test(r));
    _aiRoleList = _aiRoleList.filter(r => !SENIORITY_RE.test(r));
  }

  const btn = document.getElementById("searchBtn");
  btn.innerHTML = '<svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg> Searching Data...';
  btn.disabled = true;
  document.getElementById("extractBtn").disabled = true;

  _searchId = crypto.randomUUID();
  resetRelevanceState();
  _searchComplete = false;
  lastRenderedCount = 0;
  activeFilters = { site: '', experience_level: '' };
  currentSort = 'relevant';
  document.getElementById("filterBar").classList.add("hidden");

  document.title = "Searching... - AI Job Agent";
  setStatus("Initializing data collection...", "blue");
  logEvent("search_started", { sites, keywords_count: keywords.length, roles_count: rolesToScrape.length });

  try {
    searchIds = [_searchId];
    await fetch("/scrape", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sites, keywords, roles: rolesToScrape, search_id: _searchId,
        location: getLocation() || document.getElementById("locationInput").value,
        internship_mode: internshipMode,
        indeed_country: getIndeedCountry(),
        user_email: (window.getProfile() || {}).email || "",
        resume_filename: _uploadedFilename || "",
        scrape_limit: 200,
      })
    });

    if (_customRoleList.length > 0 && _aiRoleList.length > 0) {
      showTabBar();
      switchTab('custom');
    } else {
      hideTabBar();
    }

    _uploadedFilename = "";
    scrapeAttempts = 0;
    pollAllScrapes();
  } catch (e) {
    document.title = "AI Job Agent";
    setStatus("Error: " + e.message, "red");
    logEvent("search_error", { error: e.message }, Math.round((Date.now() - _searchStart) / 1000));
    resetSearchBtn(); showElement("results");
  }
});

// ===== POLL ALL SCRAPES =====
function pollAllScrapes() {
  if (pollTimer) clearInterval(pollTimer);
  let consecutiveErrors = 0;
  pollTimer = setInterval(async () => {
    const sid = searchIds[0];
    if (!sid) { clearInterval(pollTimer); pollTimer = null; return; }

    let allDone = true;
    try {
      const r = await fetch(`/scrape/status?search_id=${sid}`);
      const d = await r.json();
      if (d.status === 'running') allDone = false;
      consecutiveErrors = 0;
    } catch {
      consecutiveErrors++;
    }
    _searchComplete = allDone;

    let allRaw = [];
    try {
      const r = await fetch(`/jobs?search_id=${sid}&raw=true`);
      const d = await r.json();
      allRaw = d.jobs || [];
    } catch {}

    const seen = new Set();
    allJobs = allRaw.filter(j => {
      const key = j.url || `${j.title}|${j.company}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });

    // Route jobs to tab arrays by matched role
    customJobs = allJobs.filter(j => _customRoleList.includes(j._matched_role));
    aiJobs = allJobs.filter(j => _aiRoleList.includes(j._matched_role));

    showElement("results");

    const totalJobs = allJobs.length;

    if (!allDone) {
      if (totalJobs > 0) {
        setStatus(`${totalJobs} jobs collected`, "blue");
      } else {
        setStatus("Collecting job data...", "blue");
      }
      document.title = `(${totalJobs}) Jobs - AI Job Agent`;
      if (_customRoleList.length > 0 && _aiRoleList.length > 0) {
        updateTabCounts();
        renderActiveTab();
      } else {
        renderAllJobs(allJobs);
      }
    } else {
      await checkSavedStatuses();
      if (_customRoleList.length > 0 && _aiRoleList.length > 0) {
        showTabBar();
        switchTab('custom');
      } else {
        hideTabBar();
        renderAllJobs(allJobs);
      }
      let msg = `Analysis complete — ${totalJobs} jobs found`;
      setStatus(msg, totalJobs ? "green" : "amber");
      document.title = `(${totalJobs}) Jobs - AI Job Agent`;
    }

    if (consecutiveErrors >= 3) {
      clearInterval(pollTimer);
      pollTimer = null;
      setStatus("Connection lost. Server may be down.", "red");
      hideTabBar();
      renderAllJobs();
      return;
    }

    if (allDone) {
      clearInterval(pollTimer);
      pollTimer = null;
      logEvent("scrape_done", { roles: _customRoleList.concat(_aiRoleList), jobs: totalJobs });
      resetSearchBtn();
      // Cache
      localStorage.setItem(SEARCH_CACHE_KEY, JSON.stringify({
        searchIds,
        _customRoleList,
        _aiRoleList,
        searchMode: (customJobs.length > 0 && aiJobs.length > 0) ? 'tabs' : 'single',
        timestamp: Date.now(),
        params: {
          sites: getSelectedSites ? getSelectedSites() : [],
          keywords: getSelectedKeywords ? getSelectedKeywords() : [],
          roles: getSelectedRoles ? getSelectedRoles() : [],
          location: document.getElementById("locationInput")?.value || "",
          internshipMode: internshipMode,
        },
      }));
    }
  }, 3000);
}
// ===== RENDER JOBS =====
// ===== RENDER ALL JOBS =====
function renderAllJobs(jobs) {
  const c = document.getElementById("results");
  _relevanceUsed = loadRelevanceUsed();
  let displayJobs = jobs || allJobs;
  if (!internshipMode) {
    displayJobs = displayJobs.filter(j => j.experience_level !== "entry_level");
  }
  if (currentSort === 'recent') {
    displayJobs = [...displayJobs].sort((a, b) => {
      const da = a.date_posted || '';
      const db = b.date_posted || '';
      if (da && db) return db.localeCompare(da);
      if (da) return -1;
      if (db) return 1;
      return 0;
    });
  } else if (currentSort === 'referral') {
    displayJobs = [...displayJobs].sort((a, b) => (_referralCounts[b.company] || 0) - (_referralCounts[a.company] || 0));
  } else {
    displayJobs = [...displayJobs].sort((a, b) => (b.keyword_score || 0) - (a.keyword_score || 0));
  }
  if (!displayJobs.length) {
    c.innerHTML = `
      <div class="premium-card min-h-[400px] flex flex-col items-center justify-center text-center p-8">
        <div class="w-12 h-12 rounded-xl bg-slate-50 flex items-center justify-center mb-4 border border-slate-100">
          <svg class="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>
        </div>
        <h3 class="text-sm font-semibold text-slate-800">No jobs found</h3>
        <p class="text-xs text-slate-500 mt-1">Try different roles or broaden your job board selection.</p>
      </div>`;
    return;
  }

  // Sub-filter pills — always show if the base scope has multiple roles
  let subFilterHtml = "";
  const tabBar = document.getElementById('tabBar');
  const isTabs = tabBar && !tabBar.classList.contains('hidden');
  const baseScope = isTabs ? (activeTab === 'custom' ? customJobs : aiJobs) : allJobs;
  const baseRoles = [...new Set(baseScope.map(j => j._matched_role).filter(Boolean))];
  subFilterHtml = `<div class="flex flex-wrap items-center justify-between gap-2 mb-4" id="subFilters">`;
  if (baseRoles.length > 1) {
    const allActive = _activeSubFilterRole === 'all';
    subFilterHtml += `<div class="flex flex-wrap gap-2">
      <span class="cursor-pointer px-3 py-1.5 rounded-lg border text-sm font-medium transition-colors ${allActive ? 'bg-slate-800 text-white border-slate-800' : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'}" data-role-filter="all">All (${baseScope.length})</span>`;
    for (const role of baseRoles) {
      const count = baseScope.filter(j => j._matched_role === role).length;
      const isActive = _activeSubFilterRole === role;
      subFilterHtml += `<span class="cursor-pointer px-3 py-1.5 rounded-lg border text-sm font-medium transition-colors ${isActive ? 'bg-slate-800 text-white border-slate-800' : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'}" data-role-filter="${role}">${role} (${count})</span>`;
    }
    subFilterHtml += `</div>`;
  }
  subFilterHtml += `<span class="flex items-center gap-1.5 text-xs text-slate-400 ml-auto"><span>Sort:</span>
    <select id="sortSelect" class="bg-white border border-slate-200 rounded-lg px-2 py-1.5 text-xs font-medium text-slate-600 cursor-pointer hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-indigo-500">
      <option value="relevant" ${currentSort === 'relevant' ? 'selected' : ''}>Most Relevant</option>
      <option value="recent" ${currentSort === 'recent' ? 'selected' : ''}>Most Recent</option>
      <option value="referral" ${currentSort === 'referral' ? 'selected' : ''}>Most Referrals</option>
    </select></span>
  </div>`;

  const totalPages = Math.ceil(displayJobs.length / _pageSize);
  const start = (_currentPage - 1) * _pageSize;
  const pageJobs = displayJobs.slice(start, start + _pageSize);
  const profile = window.getProfile();

  function paginationBarHtml(tp) {
    if (tp <= 1) return '';
    const p = _currentPage;
    let html = `<div class="flex items-center justify-center gap-2 mt-6">`;
    html += `<button class="page-btn text-xs font-medium px-3 py-1.5 rounded-lg border ${p <= 1 ? 'text-slate-300 border-slate-100 cursor-not-allowed' : 'text-slate-600 border-slate-200 hover:bg-slate-50 cursor-pointer'}" data-page="${p - 1}" ${p <= 1 ? 'disabled' : ''}>Prev</button>`;
    for (let i = 1; i <= tp; i++) {
      html += `<button class="page-btn text-xs font-medium px-3 py-1.5 rounded-lg border ${i === p ? 'bg-slate-800 text-white border-slate-800 cursor-default' : (profile ? 'text-slate-600 border-slate-200 hover:bg-slate-50 cursor-pointer' : 'text-slate-400 border-slate-100 cursor-pointer')}" data-page="${i}">${i}</button>`;
    }
    html += `<button class="page-btn text-xs font-medium px-3 py-1.5 rounded-lg border ${p >= tp ? 'text-slate-300 border-slate-100 cursor-not-allowed' : 'text-slate-600 border-slate-200 hover:bg-slate-50 cursor-pointer'}" data-page="${p + 1}" ${p >= tp ? 'disabled' : ''}>Next</button>`;
    html += `</div>`;
    return html;
  }

  if (!profile && _currentPage > 1) {
    const blurred = pageJobs.map(jobCardHtml).join("");
    c.innerHTML = subFilterHtml +
      `<div class="relative mt-2">
        <div class="blur-sm pointer-events-none select-none">${blurred}</div>
        <div class="absolute inset-0 flex items-center justify-center bg-black/10 rounded-2xl">
          <div class="bg-white/90 backdrop-blur-sm rounded-xl px-6 py-5 shadow-lg text-center max-w-xs">
            <svg class="w-10 h-10 mx-auto text-slate-400 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/></svg>
            <p class="text-base font-semibold text-slate-700">${displayJobs.length - _pageSize} more jobs locked</p>
            <p class="text-sm text-slate-500 mt-1 mb-4">Sign in to see all matching jobs and request referrals.</p>
            <button onclick="showAuthModal()" class="premium-btn premium-btn-primary w-full">Sign in to unlock</button>
          </div>
        </div>
      </div>` + paginationBarHtml(totalPages);
  } else {
    c.innerHTML = subFilterHtml + pageJobs.map(jobCardHtml).join("") + paginationBarHtml(totalPages);
  }

  document.getElementById('sortSelect')?.addEventListener('change', async (e) => {
    currentSort = e.target.value;
    if (currentSort === 'referral') {
      const companies = [...new Set(allJobs.map(j => j.company).filter(Boolean))];
      if (companies.length) {
        try {
          const profile = window.getProfile();
          const email = profile?.email || '';
          const r = await fetch(`/api/users/company-counts?companies=${encodeURIComponent(companies.join(","))}&user_email=${encodeURIComponent(email)}`);
          const d = await r.json();
          _referralCounts = d.counts || {};
        } catch {}
      }
    }
    applyThreshold();
  });

  // Update referral counts
  if (profile) {
    const companies = [...new Set(displayJobs.map(j => j.company).filter(Boolean))];
    if (companies.length) {
      const email = profile.email || '';
      fetch(`/api/users/company-counts?companies=${encodeURIComponent(companies.join(","))}&user_email=${encodeURIComponent(email)}`)
        .then(r => r.json())
        .then(d => {
          _referralCounts = d.counts || {};
          document.querySelectorAll(".referral-btn[data-company]").forEach(btn => {
            const company = btn.getAttribute("data-company");
            const count = _referralCounts[company] || 0;
            const label = btn.querySelector(".referral-label");
            if (label) label.textContent = `Referrals - ${count}`;
          });
        }).catch(() => {});
    }
  }
}

  // Sub-filter event delegation (single handler, survives re-renders)
let _activeSubFilterRole = 'all';
document.addEventListener('click', (e) => {
  const el = e.target.closest('#subFilters [data-role-filter]');
  if (!el) return;
  _activeSubFilterRole = el.dataset.roleFilter;
  applyThreshold();
});

// Pagination event delegation
document.addEventListener('click', (e) => {
  const el = e.target.closest('.page-btn');
  if (!el) return;
  const page = parseInt(el.dataset.page);
  if (!page || page < 1) return;
  _currentPage = page;
  const tabBar = document.getElementById('tabBar');
  const isTabs = tabBar && !tabBar.classList.contains('hidden');
  const baseJobs = isTabs ? (activeTab === 'custom' ? customJobs : aiJobs) : allJobs;
  renderAllJobs(_activeSubFilterRole === 'all' ? baseJobs : baseJobs.filter(j => j._matched_role === _activeSubFilterRole));
});

// ===== RESTORE LAST SEARCH ON PAGE LOAD =====
(async function restoreLastSearch() {
  const raw = localStorage.getItem(SEARCH_CACHE_KEY);
  if (!raw) return;
  let saved;
  try { saved = JSON.parse(raw); } catch { return; }
  if (!saved || Date.now() - saved.timestamp > SEARCH_CACHE_TTL) return;

  try {
    if (saved.searchIds && saved.searchIds.length) {
      searchIds = saved.searchIds;
      _customRoleList = saved._customRoleList || [];
      _aiRoleList = saved._aiRoleList || [];
      searchMode = saved.searchMode || 'single';

      const sid = searchIds[0];
      if (!sid) return;
      _searchId = sid;
      _relevanceUsed = loadRelevanceUsed();

      const r = await fetch(`/scrape/status?search_id=${sid}`);
      const d = await r.json();
      const allDone = d.status !== 'running';
      _searchComplete = allDone;

      if (allDone) {
        const r = await fetch(`/jobs?search_id=${sid}&raw=true`);
        const data = await r.json();
        allJobs = data.jobs || [];
        const seen = new Set();
        allJobs = allJobs.filter(j => {
          const key = j.url || `${j.title}|${j.company}`;
          if (seen.has(key)) return false;
          seen.add(key);
          return true;
        });

        customJobs = allJobs.filter(j => _customRoleList.includes(j._matched_role));
        aiJobs = allJobs.filter(j => _aiRoleList.includes(j._matched_role));

        showElement("results");
        if (_customRoleList.length > 0 && _aiRoleList.length > 0) {
          showTabBar();
          switchTab('custom');
        } else {
          hideTabBar();
          renderAllJobs(allJobs);
        }
        setStatus(`Restored ${allJobs.length} jobs from last session`, "green");
      } else {
        showElement("results");
        pollAllScrapes();
      }
    }
  } catch {}
})();

// ===== HOW IT WORKS MODAL =====
document.getElementById('howItWorksBtn').addEventListener('click', function() {
  const m = document.getElementById('howItWorksModal');
  m.classList.remove('hidden');
  m.classList.add('flex');
});
document.getElementById('howItWorksClose').addEventListener('click', closeHowItWorks);
document.getElementById('howItWorksModal').addEventListener('click', function(e) {
  if (e.target === this) closeHowItWorks();
});
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') closeHowItWorks();
});
function closeHowItWorks() {
  const m = document.getElementById('howItWorksModal');
  m.classList.add('hidden');
  m.classList.remove('flex');
}

window.showAuthModal = showAuthModal;
window.closeAuthModal = closeAuthModal;
window.authGoBack = authGoBack;
window.selectEmploymentStatus = selectEmploymentStatus;
window.filterCompanyDropdown = filterCompanyDropdown;
window.addCustomCompany = addCustomCompany;
window.selectCompany = selectCompany;
window.authRegister = authRegister;
window.authSendCode = authSendCode;
window.authVerifyCode = authVerifyCode;
window.useProfileResume = useProfileResume;
window.refreshProfileResumeBtn = refreshProfileResumeBtn;
window.authResendCode = authResendCode;
window.toggleSaveJob = toggleSaveJob;
window.checkRelevance = checkRelevance;
window.switchTab = switchTab;
window.addRoleFromSearch = addRoleFromSearch;
window.onRoleToggle = onRoleToggle;
window.selectSuggestedRole = selectSuggestedRole;
window.updateKwCount = updateKwCount;
window.getSelectedRoles = getSelectedRoles;
window.getSelectedSites = getSelectedSites;
window.getSelectedKeywords = getSelectedKeywords;
window.searchState = searchState;
window.selectLocation = selectLocation;
window.addKeyword = addKeyword;
window.clearSearchState = clearSearchState;
window.renderSuggestedRoles = renderSuggestedRoles;
window.closeHowItWorks = closeHowItWorks;
