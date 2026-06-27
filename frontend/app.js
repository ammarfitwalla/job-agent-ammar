// ===== STATE =====
let pollTimer = null;
let hasRawJobs = false;
let allJobs = [];
let customRoles = [];
let customKeywords = [];
let scrapeAttempts = 0;
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
let _leadSubmitted = false;
let _leadDismissed = false;
let _selectedSites = [];
let _searchStart = 0;

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
  let html = `<span class="cursor-pointer px-3 py-1.5 rounded-lg border text-xs font-medium transition-colors ${allActive ? 'bg-slate-800 text-white border-slate-800' : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'}" data-filter="all">All Results</span>`;

  sites.forEach(s => {
    const active = activeFilters.site.toLowerCase() === s.toLowerCase();
    html += `<span class="cursor-pointer px-3 py-1.5 rounded-lg border text-xs font-medium transition-colors flex items-center gap-1 ${active ? 'bg-slate-800 text-white border-slate-800' : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'}" data-filter="site" data-value="${s}">${s}${active ? '<svg class="w-3 h-3 ml-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>' : ''}</span>`;
  });

  exps.forEach(e => {
    const active = activeFilters.experience_level === e;
    const label = e === "internship" ? "Internship" : e === "entry_level" ? "Entry Level" : e;
    html += `<span class="cursor-pointer px-3 py-1.5 rounded-lg border text-xs font-medium transition-colors flex items-center gap-1 ${active ? 'bg-slate-800 text-white border-slate-800' : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'}" data-filter="exp" data-value="${e}">${label}${active ? '<svg class="w-3 h-3 ml-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>' : ''}</span>`;
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
setTimeout(() => {
  const el = document.getElementById("splashOverlay");
  if (el) el.classList.add("splash-hidden");
}, 3000);

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

function setStepProgress(steps) {
  const el = document.getElementById("stepProgress");
  el.classList.remove("hidden", "step-progress-exit");
  hideElement("results");
  steps.forEach((s, i) => {
    const container = document.getElementById(`step${i + 1}`);
    const circle = document.getElementById(`step${i + 1}Circle`);
    const spinner = document.getElementById(`step${i + 1}Spinner`);
    const check = document.getElementById(`step${i + 1}Check`);
    const msg = document.getElementById(`step${i + 1}Msg`);
    container.className = "flex items-start gap-4";
    container.classList.add(`step-${s.status}`);
    circle.classList.toggle("hidden", s.status !== "pending");
    spinner.classList.toggle("hidden", s.status !== "active");
    check.classList.toggle("hidden", s.status !== "done");
    msg.textContent = s.msg;
    if (i < 2) {
      const conn = document.getElementById(`conn${i + 1}`);
      if (s.status === "done") conn.className = "w-px h-full connector-line bg-green-400";
      else if (s.status === "active") conn.className = "w-px h-full connector-line bg-blue-400";
      else conn.className = "w-px h-full connector-line bg-slate-200";
    }
  });
}
function hideStepProgress() {
  const el = document.getElementById("stepProgress");
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
  const el = document.getElementById("resultCount");
  el.textContent = n;
  el.parentElement.classList.remove("count-pop");
  void el.parentElement.offsetWidth;
  el.parentElement.classList.add("count-pop");
}

function updateSearchBtn() {}

document.getElementById("resume").addEventListener("input", updateSearchBtn);

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
  renderJobs(displayJobs);
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
    setStatus("Keywords successfully extracted.", "green");
  } catch (e) { setStatus("Failed to extract keywords.", "red"); }
  finally { btn.textContent = "Auto-Extract Keywords"; btn.disabled = false; }
});

function renderKeywords(kws) {
  const c = document.getElementById("keywords");
  if (!kws.length) { c.innerHTML = '<span class="text-xs text-slate-400 italic">No keywords found</span>'; return; }
  c.innerHTML = kws.map(k => `
    <label class="inline-flex items-center gap-1.5 px-2.5 py-1.5 border rounded-lg text-[11px] font-medium cursor-pointer transition-colors ${k.selected ? 'bg-slate-900 text-white border-slate-900' : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'}">
      <input type="checkbox" value="${k.word}" ${k.selected ? "checked" : ""} class="hidden" onchange="this.parentElement.classList.toggle('bg-slate-900');this.parentElement.classList.toggle('text-white');this.parentElement.classList.toggle('border-slate-900');this.parentElement.classList.toggle('bg-white');this.parentElement.classList.toggle('text-slate-600');this.parentElement.classList.toggle('border-slate-200');updateKwCount()">
      <span>${k.word}</span>
    </label>`).join("");
  updateKwCount();
}

function updateKwCount() {
  const n = getSelectedKeywords().length;
  document.getElementById("kwCount").textContent = n;
}

// ===== CUSTOM KEYWORDS =====
document.getElementById("addKeywordBtn").addEventListener("click", () => {
  const i = document.getElementById("customKeywordInput");
  const kw = i.value.trim().toLowerCase();
  if (!kw || customKeywords.includes(kw)) return;
  customKeywords.push(kw); i.value = ""; renderCustomKeywords(); updateKwCount();
});
document.getElementById("customKeywordInput").addEventListener("keydown", e => { if (e.key === "Enter") document.getElementById("addKeywordBtn").click(); });

function renderCustomKeywords() {
  const c = document.getElementById("customKeywords");
  c.innerHTML = customKeywords.map(kw => `
    <span class="inline-flex items-center gap-1 bg-indigo-50 border border-indigo-100 text-indigo-700 text-[11px] px-2.5 py-1 rounded-lg font-medium">
      <span>${kw}</span>
      <button class="remove-kw hover:text-indigo-900 ml-1 opacity-70 hover:opacity-100" data-kw="${kw}">
        <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
      </button>
    </span>`).join("");
  c.querySelectorAll(".remove-kw").forEach(b => b.addEventListener("click", () => { customKeywords = customKeywords.filter(k => k !== b.dataset.kw); renderCustomKeywords(); updateKwCount(); }));
}

// ===== ROLES =====
async function loadRoles() {
  try { const r = await fetch("/roles"); const d = await r.json(); renderRoles(d.categories); } catch {}
}

function renderRoles(categories) {
  const c = document.getElementById("roles");
  const labels = { tech: "Engineering & IT", sales: "Sales & Marketing", media: "Media & Design", healthcare: "Healthcare", finance: "Finance", admin: "Administration", legal: "Legal", education: "Education", civil: "Civil & Construction" };
  c.innerHTML = Object.entries(categories).map(([cat, roles]) =>
    `<details class="group border border-slate-100 rounded-xl overflow-hidden bg-white mb-1">
      <summary class="cursor-pointer px-3 py-2 bg-slate-50/50 hover:bg-slate-50 text-[11px] font-semibold text-slate-700 flex items-center transition-colors">
        ${labels[cat]||cat} <span class="ml-2 text-slate-400 font-normal">(${roles.length})</span>
      </summary>
      <div class="p-2 bg-white space-y-1 border-t border-slate-50">
        ${roles.map(r => `
          <label class="flex items-center gap-2.5 px-2 py-1.5 rounded-lg hover:bg-slate-50 cursor-pointer text-xs text-slate-600 transition-colors">
            <input type="checkbox" class="role-cb w-3.5 h-3.5 rounded border-slate-300 text-slate-900 focus:ring-slate-900" value="${r}" onchange="updateRoleCount()">
            <span>${r}</span>
          </label>`).join("")}
      </div>
    </details>`
  ).join("");
}

document.getElementById("addRoleBtn").addEventListener("click", () => {
  const i = document.getElementById("customRoleInput");
  const r = i.value.trim();
  if (!r || customRoles.includes(r)) return;
  customRoles.push(r); i.value = ""; renderCustomRoles(); updateRoleCount();
});
document.getElementById("customRoleInput").addEventListener("keydown", e => { if (e.key === "Enter") document.getElementById("addRoleBtn").click(); });

function renderCustomRoles() {
  const c = document.getElementById("customRoles");
  c.innerHTML = customRoles.map(r => `
    <span class="inline-flex items-center gap-1 bg-emerald-50 border border-emerald-100 text-emerald-700 text-[11px] px-2.5 py-1 rounded-lg font-medium">
      <span>${r}</span>
      <button class="remove-role hover:text-emerald-900 ml-1 opacity-70 hover:opacity-100" data-role="${r}">
        <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
      </button>
    </span>`).join("");
  c.querySelectorAll(".remove-role").forEach(b => b.addEventListener("click", () => { customRoles = customRoles.filter(r => r !== b.dataset.role); renderCustomRoles(); updateRoleCount(); }));
}

function updateRoleCount() {
  document.getElementById("roleCount").textContent = getSelectedRoles().length;
  updateSearchBtn();
}

function getSelectedRoles() { return [...Array.from(document.querySelectorAll(".role-cb:checked")).map(e => e.value), ...customRoles]; }
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

  // Search countries from loaded map
  const countryMatches = Object.entries(countriesMap)
    .filter(([code, name]) => name.toLowerCase().includes(lower) || code.includes(lower))
    .slice(0, 3)
    .map(([code, name]) => ({
      state: null,
      country: name,
      country_code: code,
      label: name
    }));

  // Search states if loaded
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
    btn.classList.replace("bg-slate-900", "bg-teal-600");
    btn.classList.replace("hover:bg-slate-800", "hover:bg-teal-700");
    btn.classList.replace("shadow-slate-900/10", "shadow-teal-600/20");
    btn.innerHTML = '<span class="text-base">🎓</span> Search Internships';
    document.getElementById("logoIcon").classList.replace("bg-slate-900", "bg-teal-600");
  } else {
    document.body.classList.remove("internship-mode");
    toggle.classList.replace("bg-teal-500", "bg-slate-200");
    knob.style.transform = "translateX(0)";
    btn.classList.replace("bg-teal-600", "bg-slate-900");
    btn.classList.replace("hover:bg-teal-700", "hover:bg-slate-800");
    btn.classList.replace("shadow-teal-600/20", "shadow-slate-900/10");
    btn.innerHTML = '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg> Start Search';
    document.getElementById("logoIcon").classList.replace("bg-teal-600", "bg-slate-900");
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
  lastRenderedCount = 0;
  lastFilteredGen = 0;
  lastPassNum = 0;
  allJobs = [];
  activeFilters = { site: '', experience_level: '' };
  document.getElementById("filterBar").classList.add("hidden");

  setStepProgress([
    { status: "active", msg: "Connecting to Indeed, LinkedIn, Adzuna..." },
    { status: "pending", msg: "Waiting for data..." },
    { status: "pending", msg: "Waiting..." }
  ]);
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
      search_id: _searchId
    })});
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

// ===== LEAD CAPTURE =====
function maybeShowLeadCapture() {
  if (_leadSubmitted || _leadDismissed) return;
  const modal = document.getElementById("leadModal");
  if (!modal) return;
  modal.classList.remove("hidden");
}

document.getElementById("submitLead")?.addEventListener("click", async () => {
  if (_leadSubmitted) return;
  const email = document.getElementById("leadEmail").value.trim();
  if (!email || !email.includes("@")) {
    document.getElementById("leadEmail").classList.add("border-red-400");
    return;
  }
  document.getElementById("leadEmail").classList.remove("border-red-400");
  const name = document.getElementById("leadName").value.trim();
  const btn = document.getElementById("submitLead");
  btn.disabled = true;
  btn.innerHTML = '<svg class="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg> Submitting...';
  try {
    await fetch("/api/lead", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: _searchId,
        email,
        name,
        roles: getSelectedRoles(),
        location: getLocation() || document.getElementById("locationInput").value,
        keywords: getSelectedKeywords(),
        internship_mode: internshipMode,
        resume_snippet: (document.getElementById("resume").value || "").slice(0, 200),
      }),
    });
    _leadSubmitted = true;
    document.getElementById("leadEmail").classList.add("hidden");
    document.getElementById("leadName").classList.add("hidden");
    document.getElementById("submitLead").classList.add("hidden");
    document.getElementById("leadSuccess").classList.remove("hidden");
  } catch {
    btn.disabled = false;
    btn.innerHTML = "Notify Me";
  }
});

document.getElementById("dismissLead")?.addEventListener("click", () => {
  _leadDismissed = true;
  document.getElementById("leadModal").classList.add("hidden");
});

document.getElementById("leadEmail")?.addEventListener("input", () => {
  document.getElementById("leadEmail").classList.remove("border-red-400");
});

// ===== POLL =====
function pollResults() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    scrapeAttempts++;
    try {
      const r = await fetch(`/scrape/status?search_id=${_searchId}`);
      const d = await r.json();

      if (d.queue_position > 0) {
        setStepProgress([
          { status: "active", msg: `Position ${d.queue_position} in queue...` },
          { status: "pending", msg: "Waiting for data..." },
          { status: "pending", msg: "Waiting..." }
        ]);
        document.title = "⏳ Queued... - AI Job Agent";
        return;
      }

      // Per-step ETA
      for (let si = 1; si <= 3; si++) {
        const container = document.getElementById(`step${si}`);
        const etaEl = document.getElementById(`step${si}Eta`);
        if (!etaEl || !container) continue;
        const isActive = container.classList.contains("step-active");
        if (isActive && d.status === "running" && _searchStart > 0) {
          const elapsed = Math.round((Date.now() - _searchStart) / 1000);
          const hasLinkedIn = _selectedSites.includes("linkedin");
          const multiSite = _selectedSites.length >= 2;
          const scrapeEst = _selectedSites.length >= 3 ? 60 : 40;
          const est = [scrapeEst, 60, 2][si - 1];
          const soFar = [scrapeEst, scrapeEst + 60, scrapeEst + 62][si - 1];
          const remaining = Math.max(1, soFar - elapsed);
          etaEl.textContent = `~${remaining}s`;
          etaEl.classList.remove("hidden");
        } else {
          etaEl.classList.add("hidden");
        }
      }

      if (d.status === "running") {
        const inPass = d.max_passes > 0 && d.pass_num > 0;
        const genChanged = d.filtered_gen !== lastFilteredGen;
        const countChanged = d.last_scrape_relevant !== lastRenderedCount;

        if (d.last_scrape_raw > 0) {
          if (d.last_scrape_relevant > 0) {
            if (genChanged && inPass) {
              setStatus(`Batch ${d.pass_num}/${d.max_passes} processed \u2014 ${d.last_scrape_relevant} matches found`, "blue");
            } else if (countChanged) {
              setStatus(`AI evaluating candidates... (${d.last_scrape_relevant} matches)`, "blue");
            } else if (d.pass_num > lastPassNum && lastPassNum > 0) {
              setStatus(`${d.last_scrape_relevant} matches found, scanning further (Batch ${d.pass_num}/${d.max_passes})...`, "amber");
            } else {
              setStatus(`${d.last_scrape_relevant} relevant roles found so far`, "blue");
            }
            await loadResultsIncremental(d.filtered_gen);
          } else {
            document.title = "🤖 Scoring... - AI Job Agent";
            if (d.pass_num > lastPassNum && lastPassNum > 0) {
              setStepProgress([
                { status: "done", msg: `Scraped ${d.last_scrape_raw} jobs` },
                { status: "active", msg: `Filtering generic roles, scanning deeper (Batch ${d.pass_num}/${d.max_passes})...` },
                { status: "pending", msg: "Waiting for AI results..." }
              ]);
            } else if (genChanged && inPass) {
              setStepProgress([
                { status: "done", msg: `Scraped ${d.last_scrape_raw} jobs` },
                { status: "active", msg: `Batch ${d.pass_num}/${d.max_passes} scored, analyzing...` },
                { status: "pending", msg: "Waiting for AI results..." }
              ]);
            } else {
              setStepProgress([
                { status: "done", msg: `Scraped ${d.last_scrape_raw} jobs` },
                { status: "active", msg: `AI scoring ${d.last_scrape_raw} results...` },
                { status: "pending", msg: "Waiting for AI results..." }
              ]);
            }
          }
        } else {
          setStepProgress([
            { status: "active", msg: `Gathering data from networks${inPass ? ` (Batch ${d.pass_num}/${d.max_passes})` : ""}...` },
            { status: "pending", msg: "Waiting for data..." },
            { status: "pending", msg: "Waiting..." }
          ]);
          document.title = "📡 Scraping... - AI Job Agent";
        }
        lastFilteredGen = d.filtered_gen;
        lastPassNum = d.pass_num;
      }

      if (d.status === "done" || d.status === "error") {
        clearInterval(pollTimer); pollTimer = null;
        if (d.status === "error") {
          hideElement("stepProgress");
          document.title = "AI Job Agent";
          setStatus("Data collection encountered an error.", "red");
          logEvent("search_error", { status: "error" }, Math.round((Date.now() - _searchStart) / 1000));
          await loadResults(d);
        } else {
          setStepProgress([
            { status: "done", msg: `Scraped ${d.last_scrape_raw || 0} jobs` },
            { status: "done", msg: `Found ${d.last_scrape_relevant || 0} matches` },
            { status: "done", msg: "Analysis complete" }
          ]);
          await new Promise(r => setTimeout(r, 500));
          hideStepProgress();
          await loadResults(d);
        }
      } else if (scrapeAttempts > 90) {
        setStatus("Network responses are slower than usual, continuing processing...", "amber");
      }
    } catch {
      clearInterval(pollTimer); pollTimer = null;
      document.title = "AI Job Agent";
      setStatus("Connection lost while polling.", "red");
      resetSearchBtn(); hideElement("stepProgress"); showElement("results");
    }
  }, 1000);
}

async function loadResultsIncremental(filteredGen) {
  const gen = filteredGen !== undefined ? filteredGen : lastFilteredGen;
  try {
    const r = await fetch(`/jobs?search_id=${_searchId}`);
    const d = await r.json();
    const jobs = d.jobs || [];
    if (jobs.length > 0 && (jobs.length !== lastRenderedCount || gen !== lastFilteredGen)) {
      lastRenderedCount = jobs.length;
      lastFilteredGen = gen;
      jobs.sort((a, b) => (b.total_score || 0) - (a.total_score || 0));
      showElement("results");
      hideElement("stepProgress");
      document.title = `(${jobs.length}) Jobs - AI Job Agent`;
      renderJobs(jobs);
      updateCountBadge(jobs.length);
    }
  } catch {}
}

// ===== LOAD RESULTS =====
async function loadResults(statusData) {
  try {
    const r = await fetch(`/jobs?search_id=${_searchId}`);
    const d = await r.json();
    allJobs = d.jobs || [];
    hasRawJobs = true;
    showElement("results");
    applyThreshold();
    let msg;
    if (allJobs.length) {
      const passSummary = statusData && statusData.max_passes > 0 && statusData.pass_num > 0 ? ` across ${statusData.pass_num} sources` : "";
      msg = `Analysis complete: ${allJobs.length} matches found${passSummary}.`;
      document.title = `(${allJobs.length}) Jobs - AI Job Agent`;
      logEvent("search_completed", { jobs_count: allJobs.length }, Math.round((Date.now() - _searchStart) / 1000));
    } else {
      msg = "Analysis complete: No high-confidence matches found in this region.";
      document.title = "AI Job Agent";
      logEvent("search_completed", { jobs_count: 0 }, Math.round((Date.now() - _searchStart) / 1000));
    }
    setStatus(msg, allJobs.length ? "green" : "amber");
    setTimeout(maybeShowLeadCapture, 2000);
  } catch (e) { setStatus("Failed to render final results: " + e.message, "red"); }
  resetSearchBtn();
}

// ===== RENDER JOBS =====
function renderJobs(jobs) {
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

  const showAll = voteCount >= voteThreshold;
  const limit = 5;

  function cardHtml(j) {
    const sc = j.total_score || 0;
    const scoreClass = sc >= 85 ? "text-emerald-600 bg-emerald-50 border-emerald-100" :
                       sc >= 60 ? "text-indigo-600 bg-indigo-50 border-indigo-100" :
                       "text-amber-600 bg-amber-50 border-amber-100";
    const barColor = sc >= 85 ? "bg-emerald-500" : sc >= 60 ? "bg-indigo-500" : "bg-amber-500";
    const siteName = siteFromUrl(j.url);

    const expBadge = j.experience_level === "internship"
      ? '<span class="text-[10px] bg-teal-50 text-teal-700 border border-teal-100 px-2 py-0.5 rounded-md font-medium flex items-center gap-1"><svg class="w-3 h-3" fill="currentColor" viewBox="0 0 20 20"><path d="M10.394 2.08a1 1 0 00-.788 0l-7 3a1 1 0 000 1.84L5.25 8.051a.999.999 0 01.356-.257l4-1.714a1 1 0 11.788 1.838L7.667 9.088l1.94.831a1 1 0 00.787 0l7-3a1 1 0 000-1.838l-7-3zM3.31 9.397L5 10.12v4.102a8.969 8.969 0 00-1.05-.174 1 1 0 01-.89-.89 11.115 11.115 0 01.25-3.762zM9.3 16.573A9.026 9.026 0 007 14.935v-3.957l1.818.78a3 3 0 002.364 0l5.508-2.361a11.026 11.026 0 01.25 3.762 1 1 0 01-.89.89 8.968 8.968 0 00-5.35 2.524 1 1 0 01-1.4 0z"/></svg> Internship</span>'
      : j.experience_level === "entry_level"
        ? '<span class="text-[10px] bg-slate-100 text-slate-700 border border-slate-200 px-2 py-0.5 rounded-md font-medium">Entry Level</span>'
        : "";

    return `
    <a href="${j.url}" target="_blank" class="block group relative bg-white rounded-2xl p-5 border border-slate-200 hover:border-slate-300 hover:shadow-lg transition-all duration-300 outline-none focus:ring-2 focus:ring-indigo-500">

      <div class="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
        <div class="flex-1 min-w-0">
          <div class="flex flex-wrap items-center gap-2 mb-1.5">
            <h3 class="text-base font-semibold text-slate-900 group-hover:text-indigo-600 transition-colors truncate pr-2">${j.title}</h3>
            ${expBadge}
          </div>
          <p class="text-sm text-slate-600 flex items-center gap-2 truncate">
            <span class="font-medium">${j.company}</span>
            <span class="w-1 h-1 rounded-full bg-slate-300"></span>
            <span>${j.location}</span>
            ${j.salary ? `<span class="w-1 h-1 rounded-full bg-slate-300"></span><span class="font-medium text-emerald-700 bg-emerald-50 px-1.5 rounded">${j.salary}</span>` : ""}
          </p>
        </div>

        <div class="flex sm:flex-col items-center sm:items-end justify-between sm:justify-start shrink-0 pt-1 sm:pt-0">
          <div class="flex flex-col items-end">
            <div class="flex items-center gap-2">
              <div class="text-[10px] uppercase font-bold tracking-wider text-slate-400">Match</div>
              <div class="px-2.5 py-1 rounded-lg border font-mono text-sm font-bold ${scoreClass}">${sc}</div>
            </div>
            <div class="text-[10px] text-slate-400 mt-1 flex items-center gap-1.5">
              <span title="AI Relevancy">AI <span class="font-medium text-slate-600">${j.ai_score || 0}</span></span>
              <span class="text-slate-300">|</span>
              <span title="Keyword Hits">KW <span class="font-medium text-slate-600">${j.keyword_score || 0}</span></span>
            </div>
          </div>
        </div>
      </div>

      ${j.reason ? `
      <div class="mt-4 bg-slate-50/50 rounded-xl p-3 border border-slate-100">
        <p class="text-xs text-slate-600 leading-relaxed"><strong class="text-slate-800">AI Note:</strong> ${j.reason}</p>
      </div>` : ""}

      <div class="flex items-center justify-between mt-4 pt-4 border-t border-slate-100">
        <div class="flex flex-wrap gap-1.5 flex-1 pr-4 overflow-hidden h-6">
          ${j.tags && j.tags.length ? j.tags.slice(0, 5).map(t => `<span class="text-[10px] bg-slate-100 text-slate-600 px-2 py-0.5 rounded-md whitespace-nowrap">${t}</span>`).join('') : ""}
          ${j.tags && j.tags.length > 5 ? `<span class="text-[10px] text-slate-400 px-1 py-0.5 whitespace-nowrap">+${j.tags.length - 5} more</span>` : ""}
        </div>
        <div class="flex items-center gap-1.5 text-[11px] font-medium text-slate-400 shrink-0">
          <span>via ${siteName}</span>
          <svg class="w-3.5 h-3.5 group-hover:text-indigo-600 group-hover:translate-x-0.5 transition-all" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3"></path></svg>
        </div>
      </div>

      <div class="absolute bottom-0 left-0 h-0.5 w-full bg-slate-100 rounded-b-2xl overflow-hidden">
        <div class="h-full ${barColor} transition-all duration-500" style="width: ${Math.min(sc, 100)}%"></div>
      </div>
    </a>`;
  }

  if (jobs.length > limit && !showAll) {
    const lockedCount = jobs.length - limit;
    const voteBtnHtml = hasVoted
      ? `<button class="mt-4 bg-slate-100 text-slate-400 px-6 py-2.5 rounded-xl text-sm font-semibold inline-flex items-center gap-2 cursor-not-allowed border border-slate-200"><svg class="w-4 h-4 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg> Voted</button>`
      : `<button class="mt-4 bg-slate-900 hover:bg-slate-800 text-white px-6 py-2.5 rounded-xl text-sm font-semibold transition-all shadow-lg shadow-slate-900/10 inline-flex items-center gap-2" onclick="handleVote(this)">Unlock All Results <span class="bg-white/20 px-1.5 rounded text-[10px]">${voteCount}/${voteThreshold}</span></button>`;

    c.innerHTML = jobs.slice(0, limit).map(j => cardHtml(j)).join("") + `
      <div class="relative rounded-2xl overflow-hidden mt-4">
        <div class="blur-job space-y-4 px-1">${jobs.slice(limit, limit+2).map(j => cardHtml(j)).join("")}</div>
        <div class="absolute inset-0 flex items-center justify-center bg-gradient-to-t from-[#FAFAFA] via-white/80 to-transparent">
          <div class="bg-white border border-slate-200 rounded-2xl p-6 text-center shadow-lg mx-4 max-w-sm w-full transform -translate-y-4">
            <div class="w-12 h-12 bg-slate-50 border border-slate-100 rounded-full flex items-center justify-center mx-auto mb-3">
              <svg class="w-5 h-5 text-slate-700" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"></path></svg>
            </div>
            <h4 class="font-semibold text-slate-900 text-sm">${lockedCount} more high-match roles hidden</h4>
            <p class="text-xs text-slate-500 mt-1">Support the project via a free vote to instantly unlock all results.</p>
            ${voteBtnHtml}
          </div>
        </div>
      </div>`;
  } else {
    c.innerHTML = jobs.map(j => cardHtml(j)).join("");
  }
}
