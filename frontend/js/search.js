// ===== STATE =====
const SEARCH_CACHE_KEY = "jobagent_last_search";
const SEARCH_CACHE_TTL = 30 * 60 * 1000;
let pollTimer = null;
let hasRawJobs = false;
let allJobs = [];
let customRoles = [];
let selectedRoles = new Set();
let customKeywords = [];
let scrapeAttempts = 0;
let shownSlowWarning = false;
let voteCount = 0;
let voteThreshold = 100;
let hasVoted = false;
let countriesMap = {};
let selectedLocation = null;
let searchTimeout = null;
let lastQuery = "";
let lastRenderedCount = 0;
let lastFilteredGen = 0;
let lastPassNum = 0;
let allStates = [];
let internshipMode = false;
let activeFilters = { site: '', experience_level: '' };
let _searchId = crypto.randomUUID();

let _selectedSites = [];
let _searchStart = 0;
let _searchComplete = false;
let _pendingSaveJob = null;
let _uploadedFilename = "";
let _authEmail = "";

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
document.addEventListener("DOMContentLoaded", () => {
  setupCodeInputs();
  window.fetchProfile().then(() => window.updateProfileIcon());
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
      { label: "scraped", value: d.total_raw_jobs },
      { label: "matches", value: d.total_relevant_jobs },
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
        reason: job.reason || "",
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
    const job = allJobs.find(j => j.url === url);
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
  const urls = allJobs.map(j => j.url).filter(Boolean);
  if (!urls.length) return;
  try {
    const r = await fetch("/api/saved-jobs/batch-check", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ email: profile.email, urls }),
    });
    const d = await r.json();
    if (d.saved_map) {
      allJobs.forEach(j => {
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
  if (_searchId && pollTimer) {
    try { navigator.sendBeacon(`/scrape/stop?search_id=${_searchId}`); } catch {}
    clearInterval(pollTimer);
    pollTimer = null;
  }
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
  if (url.includes('adzuna')) return 'Adzuna';
  if (url.includes('linkedin')) return 'LinkedIn';
  if (url.includes('indeed')) return 'Indeed';
  if (url.includes('remoteok')) return 'RemoteOK';
  if (url.includes('weworkremotely')) return 'WWR';
  return new URL(url).hostname.replace('www.', '').split('.')[0];
}

function renderFilterBar() {
  const bar = document.getElementById("filterBar");
  if (!allJobs.length) { bar.classList.add("hidden"); return; }
  bar.classList.remove("hidden");

  const sites = [...new Set(allJobs.map(j => siteFromUrl(j.url)).filter(Boolean))];
  const exps = [...new Set(allJobs.map(j => j.experience_level).filter(Boolean))];

  const allActive = !activeFilters.site && !activeFilters.experience_level;
  let html = `<span class="cursor-pointer px-3 py-1.5 rounded-lg border text-sm font-medium transition-colors ${allActive ? 'bg-slate-800 text-white border-slate-800' : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'}" data-filter="all">All Results</span>`;

  sites.forEach(s => {
    const active = activeFilters.site.toLowerCase() === s.toLowerCase();
    html += `<span class="cursor-pointer px-3 py-1.5 rounded-lg border text-sm font-medium transition-colors flex items-center gap-1 ${active ? 'bg-slate-800 text-white border-slate-800' : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'}" data-filter="site" data-value="${s}">${s}${active ? '<svg class="w-3 h-3 ml-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>' : ''}</span>`;
  });

  exps.forEach(e => {
    const active = activeFilters.experience_level === e;
    const label = e === "internship" ? "Internship" : e === "entry_level" ? "Entry Level" : e;
    html += `<span class="cursor-pointer px-3 py-1.5 rounded-lg border text-sm font-medium transition-colors flex items-center gap-1 ${active ? 'bg-slate-800 text-white border-slate-800' : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'}" data-filter="exp" data-value="${e}">${label}${active ? '<svg class="w-3 h-3 ml-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>' : ''}</span>`;
  });

  bar.innerHTML = html;

  bar.querySelectorAll("span[data-filter]").forEach(chip => {
    chip.addEventListener("click", () => {
      const filter = chip.dataset.filter;
      const value = chip.dataset.value;
      if (filter === "all") {
        activeFilters = { site: '', experience_level: '' };
      } else if (filter === "site") {
        activeFilters.site = activeFilters.site === value ? '' : value;
      } else if (filter === "exp") {
        activeFilters.experience_level = activeFilters.experience_level === value ? '' : value;
      }
      applyThreshold();
      renderFilterBar();
    });
  });
}

// ===== INIT =====
checkRawJobs();
loadRoles();
fetchVoteCount();
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
    return saved && saved.searchId && Date.now() - saved.timestamp < SEARCH_CACHE_TTL;
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

async function fetchVoteCount() {
  try { const r = await fetch("/votes"); const d = await r.json(); voteCount = d.votes; voteThreshold = d.threshold; } catch {}
}

// ===== HELPERS =====
function showElement(id) { document.getElementById(id).classList.remove("hidden"); }
function hideElement(id) { document.getElementById(id).classList.add("hidden"); }

function setStatus(msg, type = "blue") {
  const el = document.getElementById("status");
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
  const el = document.getElementById("stepProgress");
  if (!el) return;
  el.classList.remove("hidden", "step-progress-exit");
  hideElement("results");

  const siteIcons = { linkedin: "in", indeed: "indeed", adzuna: "ADZ", remoteok: "ROK", weworkremotely: "WWR", naukri: "NAU", gulftalent: "GT", eurojobs: "EUR" };
  const timeline = document.getElementById("timeline");
  if (!timeline) return;

  let html = "";
  const shown = new Set();

  for (const log of logs || []) {
    const msg = log.event || log.message || "";
    const elapsed = log.elapsed_seconds || 0;
    const ts = elapsed ? `${elapsed}s` : "";

    let m = msg.match(/\[SCRAPE\] (Pass \d+\/\d+ — )?(\w+)\.\.\.$/);
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

    m = msg.match(/\[SCRAPE\] (\w+) returned (\d+) jobs/);
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

    m = msg.match(/\[SCRAPE\] (\w+): (\d+) fetched, (\d+) new/);
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

    m = msg.match(/\[SCRAPE\] Total raw jobs: (\d+)/);
    if (m && !shown.has("total-raw")) {
      shown.add("total-raw");
      html += `<div class="flex items-center gap-3 py-1.5 text-slate-500 border-t border-slate-100 mt-1 pt-2">
        <span class="w-14 text-xs text-slate-400 shrink-0">${ts}</span>
        <span class="text-slate-600">${m[1]} jobs collected</span>
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

    m = msg.match(/\[SCRAPE\] Pipeline complete/);
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

    m = msg.match(/\[SCRAPE\] Enough relevant \((\d+).*\), stopping/);
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

  timeline.innerHTML = html;
}

function hideStepProgress() {
  const el = document.getElementById("stepProgress");
  if (!el) return;
  el.classList.add("step-progress-exit");
  setTimeout(() => el.classList.add("hidden"), 350);
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

function clearSearchState() {
  cancelActiveSearch();
  allJobs = [];
  _searchComplete = false;
  _searchId = crypto.randomUUID();
  _uploadedFilename = "";
  lastRenderedCount = 0;
  lastFilteredGen = 0;
  lastPassNum = 0;
  hasRawJobs = false;
  scrapeAttempts = 0;
  shownSlowWarning = false;
  activeFilters = { site: '', experience_level: '' };
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
  const tl = document.getElementById("timeline");
  if (tl) tl.innerHTML = "";
  const sr = document.getElementById("suggestedRoles");
  if (sr) { sr.innerHTML = ""; sr.classList.add("hidden"); }
  hideElement("stepProgress");
  document.title = "AI Job Agent";
  setStatus("", "");
  localStorage.removeItem(SEARCH_CACHE_KEY);
}

document.getElementById("resume").addEventListener("input", updateSearchBtn);
document.getElementById("resume").addEventListener("input", () => {
  if (document.getElementById("resume").value.trim()) clearSearchState();
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
  const displayJobs = getFilteredJobs();
  const companies = displayJobs.map(j => j.company);
  if (typeof window.loadCompanyUserCounts === "function") {
    window.loadCompanyUserCounts(companies).then(() => {
      renderJobs(displayJobs);
    });
  } else {
    renderJobs(displayJobs);
  }
  updateCountBadge(displayJobs.length);
  renderFilterBar();
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
    if (d.suggested_roles) renderSuggestedRoles(d.suggested_roles);
    setStatus("Keywords successfully extracted.", "green");
  } catch (e) { setStatus("Failed to extract keywords.", "red"); }
  finally { btn.textContent = "✨ Auto-Extract Keywords"; btn.disabled = false; }
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

function getAdzunaCountry() { return selectedLocation ? selectedLocation.country_code : "us"; }
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
  const sites = getSelectedSites(), keywords = getSelectedKeywords(), roles = getSelectedRoles();
  _selectedSites = sites.slice();
  if (!roles.length) return setStatus("Missing required field: Select at least one job role.", "red");
  if (!sites.length) return setStatus("Missing required field: Select at least one job board.", "red");
  if (!document.getElementById("locationInput").value.trim()) return setStatus("Missing required field: Enter a location.", "red");

  const btn = document.getElementById("searchBtn");
  btn.innerHTML = '<svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg> Searching Data...';
  btn.disabled = true;
  document.getElementById("extractBtn").disabled = true;

  _searchId = crypto.randomUUID();
  _searchComplete = false;
  lastRenderedCount = 0;
  lastFilteredGen = 0;
  lastPassNum = 0;
  allJobs = [];
  activeFilters = { site: '', experience_level: '' };
  document.getElementById("filterBar").classList.add("hidden");

  renderTimeline([], "running");
  document.title = "🔍 Searching... - AI Job Agent";
  setStatus("Initializing data collection...", "blue");
  logEvent("search_started", { sites, keywords_count: keywords.length, roles_count: roles.length });

  try {
    await fetch("/scrape", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
      sites, keywords, resume_text: resume, roles,
      adzuna_country: getAdzunaCountry(),
      indeed_country: getIndeedCountry(),
      location: getLocation() || document.getElementById("locationInput").value,
      internship_mode: internshipMode,
      search_id: _searchId,
      original_resume: _uploadedFilename,
      user_email: (window.getProfile() || {}).email || "",
    })});
    _uploadedFilename = "";
    scrapeAttempts = 0;
    pollResults();
  } catch (e) {
    document.title = "AI Job Agent";
    setStatus("Error: " + e.message, "red");
    logEvent("search_error", { error: e.message }, Math.round((Date.now() - _searchStart) / 1000));
    resetSearchBtn(); hideElement("stepProgress"); showElement("results");
  }
});

// ===== VOTE =====
async function handleVote(btn) {
  if (hasVoted) return;
  try {
    const r = await fetch("/vote", { method: "POST" });
    const d = await r.json();
    voteCount = d.votes;
    voteThreshold = d.threshold;
    hasVoted = true;
    applyThreshold();
  } catch {}
}

// ===== POLL =====
function pollResults() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    scrapeAttempts++;
    try {
      const r = await fetch(`/scrape/status?search_id=${_searchId}`);
      const d = await r.json();

      if (d.queue_position > 0) {
        renderTimeline([], d.status);
        document.title = "⏳ Queued... - AI Job Agent";
        return;
      }

      if (!_searchComplete && lastRenderedCount === 0) {
        renderTimeline(d.logs || [], d.status);
      }

      if (d.status === "running") {
        const inPass = d.max_passes > 0 && d.pass_num > 0;
        const genChanged = d.filtered_gen !== lastFilteredGen;
        const countChanged = d.last_scrape_relevant !== lastRenderedCount;

        if (d.last_scrape_relevant > 0) {
          if (genChanged && inPass) {
            setStatus(`Batch ${d.pass_num}/${d.max_passes} processed — ${d.last_scrape_relevant} matches`, "blue");
          } else if (countChanged) {
            setStatus(`Evaluating... ${d.last_scrape_relevant} matches so far`, "blue");
          } else if (d.pass_num > lastPassNum && lastPassNum > 0) {
            setStatus(`${d.last_scrape_relevant} matches, scanning deeper (pass ${d.pass_num}/${d.max_passes})`, "amber");
          } else {
            setStatus(`${d.last_scrape_relevant} matches found`, "blue");
          }
          await loadResultsIncremental(d.filtered_gen);
        } else {
          setStatus(d.last_scrape_raw > 0 ? "Scoring results..." : "Collecting job data...", "blue");
        }
        document.title = d.last_scrape_relevant > 0
          ? `(${d.last_scrape_relevant}) Jobs - AI Job Agent`
          : (d.last_scrape_raw > 0 ? "🤖 Scoring... - AI Job Agent" : "📡 Scraping... - AI Job Agent");
        lastFilteredGen = d.filtered_gen;
        lastPassNum = d.pass_num;
      }

      if (d.status === "done" || d.status === "error") {
        clearInterval(pollTimer); pollTimer = null;
        if (d.status === "error") {
          document.title = "AI Job Agent";
          setStatus("Data collection encountered an error.", "red");
          logEvent("search_error", { status: "error" }, Math.round((Date.now() - _searchStart) / 1000));
          await loadResults(d);
        } else {
          if (lastRenderedCount === 0) {
            renderTimeline(d.logs || [], "done");
            await new Promise(r => setTimeout(r, 800));
            hideStepProgress();
          }
          await loadResults(d);
        }
      } else if (scrapeAttempts > 80 && !shownSlowWarning) {
        shownSlowWarning = true;
        setStatus("Network responses are slower than usual, continuing processing...", "amber");
      }
    } catch {
      clearInterval(pollTimer); pollTimer = null;
      document.title = "AI Job Agent";
      setStatus("Connection lost while polling.", "red");
      resetSearchBtn(); hideElement("stepProgress"); showElement("results");
    }
  }, 3000);
}

async function loadResultsIncremental(filteredGen) {
  if (_searchComplete) return;
  const gen = filteredGen !== undefined ? filteredGen : lastFilteredGen;
  try {
    const r = await fetch(`/jobs?search_id=${_searchId}`);
    const d = await r.json();
    const jobs = d.jobs || [];
    if (jobs.length > 0 && (jobs.length !== lastRenderedCount || gen !== lastFilteredGen)) {
      lastRenderedCount = jobs.length;
      lastFilteredGen = gen;
      allJobs = jobs;
      showElement("results");
      hideElement("stepProgress");
      document.title = `(${jobs.length}) Jobs - AI Job Agent`;
      await checkSavedStatuses();
      applyThreshold();
    }
  } catch {}
}

// ===== LOAD RESULTS =====
async function loadResults(statusData) {
  _searchComplete = true;
  try {
    const r = await fetch(`/jobs?search_id=${_searchId}`);
    const d = await r.json();
    allJobs = d.jobs || [];
    hasRawJobs = true;
    showElement("results");
    await checkSavedStatuses();
    applyThreshold();
    localStorage.setItem(SEARCH_CACHE_KEY, JSON.stringify({
      searchId: _searchId,
      timestamp: Date.now(),
      params: {
        sites: getSelectedSites ? getSelectedSites() : [],
        keywords: getSelectedKeywords ? getSelectedKeywords() : [],
        roles: getSelectedRoles ? getSelectedRoles() : [],
        location: document.getElementById("locationInput")?.value || "",
        internshipMode: internshipMode,
      },
    }));
    let msg;
    if (allJobs.length) {
      const siteCount = (statusData?.logs || []).reduce((acc, log) => {
        const m = (log.event || log.message || "").match(/\[SCRAPE\] (\w+) returned \d+ jobs/);
        if (m) acc.add(m[1]);
        return acc;
      }, new Set()).size;
      const passSummary = siteCount > 0 ? ` across ${siteCount} sources` : "";
      msg = `Analysis complete: ${allJobs.length} matches found${passSummary}.`;
      document.title = `(${allJobs.length}) Jobs - AI Job Agent`;
      logEvent("search_completed", { jobs_count: allJobs.length }, Math.round((Date.now() - _searchStart) / 1000));
    } else {
      msg = "Analysis complete: No high-confidence matches found in this region.";
      document.title = "AI Job Agent";
      logEvent("search_completed", { jobs_count: 0 }, Math.round((Date.now() - _searchStart) / 1000));
    }
    setStatus(msg, allJobs.length ? "green" : "amber");

  } catch (e) { setStatus("Failed to render final results: " + e.message, "red"); }
  resetSearchBtn();
}

// ===== RENDER JOBS =====
function renderJobs(jobs, companyUsers) {
  const c = document.getElementById("results");
  if (!jobs.length) {
    c.innerHTML = `
      <div class="premium-card min-h-[400px] flex flex-col items-center justify-center text-center p-8">
        <div class="w-12 h-12 rounded-xl bg-slate-50 flex items-center justify-center mb-4 border border-slate-100">
          <svg class="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>
        </div>
        <h3 class="text-sm font-semibold text-slate-800">No jobs match your current filters</h3>
        <p class="text-xs text-slate-500 mt-1">Try broadening your target roles or selecting more job boards.</p>
      </div>`;
    return;
  }

  const showAll = voteCount >= voteThreshold || !!window.getProfile();
  const limit = 5;

  function cardHtml(j) {
    const sc = j.total_score || 0;
    const scoreClass = sc >= 85 ? "text-emerald-600 bg-emerald-50 border-emerald-100" :
                       sc >= 60 ? "text-indigo-600 bg-indigo-50 border-indigo-100" :
                       "text-amber-600 bg-amber-50 border-amber-100";
    const barColor = sc >= 85 ? "bg-emerald-500" : sc >= 60 ? "bg-indigo-500" : "bg-amber-500";
    const siteName = siteFromUrl(j.url);
    const isSaved = j._saved || false;

    const expBadge = j.experience_level === "internship"
      ? '<span class="text-xs bg-teal-50 text-teal-700 border border-teal-100 px-2.5 py-1 rounded-md font-medium flex items-center gap-1"><svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20"><path d="M10.394 2.08a1 1 0 00-.788 0l-7 3a1 1 0 000 1.84L5.25 8.051a.999.999 0 01.356-.257l4-1.714a1 1 0 11.788 1.838L7.667 9.088l1.94.831a1 1 0 00.787 0l7-3a1 1 0 000-1.838l-7-3zM3.31 9.397L5 10.12v4.102a8.969 8.969 0 00-1.05-.174 1 1 0 01-.89-.89 11.115 11.115 0 01.25-3.762zM9.3 16.573A9.026 9.026 0 007 14.935v-3.957l1.818.78a3 3 0 002.364 0l5.508-2.361a11.026 11.026 0 01.25 3.762 1 1 0 01-.89.89 8.968 8.968 0 00-5.35 2.524 1 1 0 01-1.4 0z"/></svg> Internship</span>'
      : j.experience_level === "entry_level"
        ? '<span class="text-xs bg-slate-100 text-slate-700 border border-slate-200 px-2.5 py-1 rounded-md font-medium">Entry Level</span>'
        : "";

    return `
    <a href="${j.url}" target="_blank" class="block group relative bg-white rounded-2xl p-5 sm:p-6 border border-[#e8ecf1] hover:border-slate-300 hover:shadow-lg transition-all duration-300 outline-none focus:ring-2 focus:ring-indigo-500">

      <div class="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
        <div class="flex-1 min-w-0">
          <div class="flex flex-wrap items-center gap-2 mb-2">
            <h3 class="text-sm sm:text-base font-semibold text-slate-900 group-hover:text-indigo-600 transition-colors truncate pr-1">${j.title}</h3>
            ${expBadge}
          </div>
          <p class="text-sm text-slate-600 flex items-center gap-2 truncate">
            <span class="font-medium">${j.company}</span>
            <span class="w-1 h-1 rounded-full bg-slate-300 shrink-0"></span>
            <span>${j.location}</span>
            ${j.salary ? `<span class="w-1 h-1 rounded-full bg-slate-300 shrink-0"></span><span class="premium-badge bg-emerald-50 text-emerald-700 border-emerald-100 font-medium">${j.salary}</span>` : ""}
          </p>
        </div>

        <div class="flex flex-row sm:flex-col items-center sm:items-end gap-3 sm:gap-1 shrink-0">
          <div class="flex items-center gap-2">
            <span class="text-[11px] uppercase font-bold tracking-wider text-slate-400">Match</span>
            <span class="px-3 py-1 rounded-lg border font-mono text-sm font-bold ${scoreClass}">${sc}</span>
          </div>
          <div class="text-[11px] text-slate-400 flex items-center gap-2">
            <span title="AI Relevancy">AI <span class="font-medium text-slate-600">${j.ai_score || 0}</span></span>
            <span class="text-slate-300">|</span>
            <span title="Keyword Hits">KW <span class="font-medium text-slate-600">${j.keyword_score || 0}</span></span>
          </div>
        </div>
      </div>

      ${j.reason ? `
      <div class="mt-4 bg-slate-50/70 rounded-xl p-4 border border-slate-100">
        <p class="text-sm text-slate-600 leading-relaxed"><strong class="text-slate-800">✨ AI Note:</strong> ${j.reason}</p>
      </div>` : ""}

      <div class="flex items-center justify-between mt-4 pt-4 border-t border-slate-100">
        <div class="flex items-center gap-2.5 flex-1 pr-3 min-w-0">
          <button class="bookmark-btn shrink-0 text-xs font-semibold transition-all duration-200 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border ${isSaved ? 'bg-indigo-500 text-white border-indigo-500 hover:bg-indigo-600' : 'bg-indigo-50 text-indigo-600 border-indigo-200 hover:bg-indigo-100 active:bg-indigo-200'}" data-url="${j.url || ''}" onclick="toggleSaveJob(event)" title="Save job">
            ${isSaved
              ? '<svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg> Saved'
              : '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4"/></svg> Save'
            }
          </button>
          <button class="shrink-0 text-xs font-semibold transition-all duration-200 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border bg-violet-50 text-violet-600 border-violet-200 hover:bg-violet-100 active:bg-violet-200" onclick="event.preventDefault(); event.stopPropagation(); window._referralJobTitle='${(j.title||'').replace(/'/g, "\\'")}'; window._referralMatchScore=${j.total_score||0}; window._referralJobUrl='${(j.url||'').replace(/'/g, "\\'")}'; showReferralUsers('${j.company.replace(/'/g, "\\'")}')" title="See referrals at this company">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z"/></svg>
            Referrals
          </button>
        </div>
        <div class="flex items-center gap-1.5 text-xs font-medium text-slate-400 shrink-0">
          <span>via ${siteName}</span>
          <svg class="w-4 h-4 group-hover:text-indigo-600 group-hover:translate-x-0.5 transition-all" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3"></path></svg>
        </div>
      </div>

      <div class="absolute bottom-0 left-0 h-0.5 w-full bg-slate-100 rounded-b-2xl overflow-hidden">
        <div class="h-full ${barColor} transition-all duration-500" style="width: ${Math.min(sc, 100)}%"></div>
      </div>
    </a>`;
  }

  if (jobs.length > limit && !showAll) {
    const lockedCount = jobs.length - limit;
    const profile = window.getProfile();
    const unlockHtml = profile
      ? `<button class="premium-btn premium-btn-primary mt-3" onclick="handleVote(this)">Unlock All Results <span class="bg-white/20 px-1.5 rounded text-xs">${voteCount}/${voteThreshold}</span></button>`
      : `<button class="premium-btn premium-btn-primary mt-3" onclick="showAuthModal()">Sign in</button>`;

    c.innerHTML = jobs.slice(0, limit).map(j => cardHtml(j)).join("") + `
      <div class="relative rounded-2xl overflow-hidden mt-4">
        <div class="blur-job space-y-4 px-1">${jobs.slice(limit, limit+2).map(j => cardHtml(j)).join("")}</div>
        <div class="absolute inset-0 flex items-center justify-center bg-gradient-to-t from-[#f8fafc] via-white/80 to-transparent">
          <div class="bg-white border border-[#e8ecf1] rounded-2xl p-6 text-center shadow-lg mx-4 max-w-sm w-full transform -translate-y-4">
            <div class="w-12 h-12 rounded-2xl bg-slate-50 border border-slate-100 flex items-center justify-center mx-auto mb-3">
              <svg class="w-5 h-5 text-slate-700" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"></path></svg>
            </div>
            <h4 class="font-semibold text-slate-900 text-sm">${lockedCount} more high-match roles hidden</h4>
            <p class="text-xs text-slate-500 mt-1">${profile ? 'Support the project via a free vote to instantly unlock all results.' : 'Sign in to unlock all results and request referrals.'}</p>
            ${unlockHtml}
          </div>
        </div>
      </div>`;
  } else {
    c.innerHTML = jobs.map(j => cardHtml(j)).join("");
  }
}

// ===== RESTORE LAST SEARCH ON PAGE LOAD =====
(async function restoreLastSearch() {
  const raw = localStorage.getItem(SEARCH_CACHE_KEY);
  if (!raw) return;
  let saved;
  try { saved = JSON.parse(raw); } catch { return; }
  if (!saved || !saved.searchId || Date.now() - saved.timestamp > SEARCH_CACHE_TTL) return;
  try {
    const r = await fetch(`/scrape/status?search_id=${saved.searchId}`);
    const status = await r.json();
    if (status.status === "done" || status.status === "error") {
      _searchId = saved.searchId;
      _searchComplete = true;
      if (status.status === "done") {
        await loadResults(status);
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
window.authResendCode = authResendCode;
window.toggleSaveJob = toggleSaveJob;
window.handleVote = handleVote;
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
