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

  const breakdown = sites.map(s => {
    const count = allJobs.filter(j => siteFromUrl(j.url) === s).length;
    return `${count} ${s}`;
  }).join(" · ");

  let html = `<span id="breakdownText">${breakdown}</span>`;

  const allActive = !activeFilters.site && !activeFilters.experience_level;
  html += `<span class="filter-chip${allActive ? ' active' : ''}" data-filter="all">All</span>`;

  sites.forEach(s => {
    const active = activeFilters.site.toLowerCase() === s.toLowerCase();
    html += `<span class="filter-chip${active ? ' active' : ''}" data-filter="site" data-value="${s}">${s}${active ? '<span class="chip-remove">✕</span>' : ''}</span>`;
  });

  exps.forEach(e => {
    const active = activeFilters.experience_level === e;
    const label = e === "internship" ? "🎓 Internship" : e === "entry_level" ? "🌱 Entry" : e;
    html += `<span class="filter-chip${active ? ' active' : ''}" data-filter="exp" data-value="${e}">${label}${active ? '<span class="chip-remove">✕</span>' : ''}</span>`;
  });

  bar.innerHTML = html;

  bar.querySelectorAll(".filter-chip").forEach(chip => {
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

async function checkRawJobs() {
  try { const r = await fetch("/scrape/status"); const d = await r.json(); hasRawJobs = d.last_scrape_raw > 0; } catch {}
}

async function fetchVoteCount() {
  try { const r = await fetch("/votes"); const d = await r.json(); voteCount = d.votes; voteThreshold = d.threshold; } catch {}
}

// ===== HELPERS =====
function showElement(id) {
  document.getElementById(id).classList.remove("hidden");
}
function hideElement(id) {
  document.getElementById(id).classList.add("hidden");
}

function setStatus(msg, type) {
  const el = document.getElementById("status");
  el.classList.remove("hidden", "bg-blue-50", "text-blue-700", "bg-red-50", "text-red-700", "bg-emerald-50", "text-emerald-700");
  if (type === "red") el.classList.add("bg-red-50", "text-red-700");
  else if (type === "green") el.classList.add("bg-emerald-50", "text-emerald-700");
  else el.classList.add("bg-blue-50", "text-blue-700");
  el.innerHTML = `<svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="${type === "red" ? "M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" : type === "green" ? "M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" : "M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"}"/></svg><span>${msg}</span>`;
}

function showSpinner(msg) {
  document.getElementById("spinnerMsg").textContent = msg;
  showElement("spinner");
}
function hideSpinner() {
  hideElement("spinner");
}

function resetSearchBtn() {
  document.getElementById("searchBtn").innerHTML = '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg> Search Jobs';
  document.getElementById("searchBtn").disabled = false;
  document.getElementById("extractBtn").disabled = false;
}

function updateCountBadge(n) {
  const el = document.getElementById("resultCount");
  el.textContent = n;
  el.classList.remove("count-pop");
  void el.offsetWidth;
  el.classList.add("count-pop");
}

function updateSearchBtn() {
  const hasResume = document.getElementById("resume").value.trim().length > 0;
  const hasRoles = getSelectedRoles().length > 0;
  document.getElementById("searchBtn").disabled = !(hasResume && hasRoles);
}

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
    alert("Upload failed: " + err.message);
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
  if (!resume) return alert("Paste your resume first");
  const btn = document.getElementById("extractBtn");
  btn.textContent = "Extracting...";
  btn.disabled = true;
  try {
    const r = await fetch("/resume/keywords", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ resume_text: resume }) });
    const d = await r.json();
    renderKeywords(d.keywords);
  } catch (e) { alert("Failed: " + e.message); }
  finally { btn.textContent = "Extract Keywords"; btn.disabled = false; }
});

function renderKeywords(kws) {
  const c = document.getElementById("keywords");
  if (!kws.length) { c.innerHTML = '<span class="text-xs text-slate-400 italic">No keywords found</span>'; return; }
  c.innerHTML = kws.map(k => `<label class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium cursor-pointer transition ${k.selected ? 'bg-indigo-100 text-indigo-700 hover:bg-indigo-200' : 'bg-slate-100 text-slate-500 hover:bg-slate-200'}"><input type="checkbox" value="${k.word}" ${k.selected ? "checked" : ""} class="hidden" onchange="this.parentElement.classList.toggle('bg-indigo-100');this.parentElement.classList.toggle('text-indigo-700');this.parentElement.classList.toggle('bg-slate-100');this.parentElement.classList.toggle('text-slate-500');updateKwCount()"><span>${k.word}</span></label>`).join("");
  updateKwCount();
}

function updateKwCount() {
  const n = getSelectedKeywords().length;
  document.getElementById("kwCount").textContent = n + " selected";
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
  c.innerHTML = customKeywords.map(kw => `<span class="inline-flex items-center gap-1 bg-purple-100 text-purple-700 text-xs px-2.5 py-0.5 rounded-full"><span>${kw}</span><button class="remove-kw hover:text-red-500 font-bold leading-none" data-kw="${kw}">&times;</button></span>`).join("");
  c.querySelectorAll(".remove-kw").forEach(b => b.addEventListener("click", () => { customKeywords = customKeywords.filter(k => k !== b.dataset.kw); renderCustomKeywords(); updateKwCount(); }));
}

// ===== ROLES =====
async function loadRoles() {
  try { const r = await fetch("/roles"); const d = await r.json(); renderRoles(d.categories); } catch {}
}

function renderRoles(categories) {
  const c = document.getElementById("roles");
  const labels = { tech: "Tech", sales: "Sales", media: "Media", healthcare: "Healthcare", finance: "Finance", admin: "Admin", legal: "Legal", education: "Education", civil: "Civil (Construction)" };
  c.innerHTML = Object.entries(categories).map(([cat, roles]) =>
    `<details class="border border-slate-200 rounded-lg overflow-hidden text-sm">
      <summary class="cursor-pointer px-3 py-1.5 bg-slate-50 hover:bg-slate-100 text-xs font-medium text-slate-500 flex items-center gap-2">${labels[cat]||cat} <span class="text-slate-400 font-normal">(${roles.length})</span></summary>
      <div class="p-2 space-y-0.5 max-h-40 overflow-y-auto">${roles.map(r => `<label class="flex items-center gap-2 px-1 py-0.5 rounded hover:bg-slate-50 cursor-pointer text-xs"><input type="checkbox" class="role-cb accent-indigo-600" value="${r}" onchange="updateRoleCount()"><span>${r}</span></label>`).join("")}</div>
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
  c.innerHTML = customRoles.map(r => `<span class="inline-flex items-center gap-1 bg-purple-100 text-purple-700 text-xs px-2.5 py-0.5 rounded-full"><span>${r}</span><button class="remove-role hover:text-red-500 font-bold leading-none" data-role="${r}">&times;</button></span>`).join("");
  c.querySelectorAll(".remove-role").forEach(b => b.addEventListener("click", () => { customRoles = customRoles.filter(r => r !== b.dataset.role); renderCustomRoles(); updateRoleCount(); }));
}

function updateRoleCount() {
  document.getElementById("roleCount").textContent = getSelectedRoles().length + " selected";
  updateSearchBtn();
}

function getSelectedRoles() { return [...Array.from(document.querySelectorAll(".role-cb:checked")).map(e => e.value), ...customRoles]; }

// ===== SITES =====
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
  if (!allStates.length) {
    results.innerHTML = '<div class="px-3 py-2 text-xs text-slate-400">Loading states...</div>';
    results.classList.remove("hidden");
    return;
  }
  const lower = query.toLowerCase();
  const matches = allStates
    .filter(s => s.state.toLowerCase().includes(lower))
    .slice(0, 8);
  if (!matches.length) {
    results.innerHTML = '<div class="px-3 py-2 text-xs text-slate-400">No results</div>';
    results.classList.remove("hidden");
    return;
  }
  matches.forEach(item => {
    const label = [item.state, item.country].filter(Boolean).join(", ");
    const div = document.createElement("div");
    div.className = "px-3 py-2 text-sm cursor-pointer hover:bg-indigo-50 text-slate-700 border-b border-slate-100 last:border-0";
    div.textContent = label;
    div.addEventListener("mousedown", (e) => {
      e.preventDefault();
      selectLocation({ state: item.state, country: item.country, country_code: item.country_code, label });
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
  el.innerHTML = `<span>${loc.label}</span><button class="ml-1 hover:text-red-500 font-bold leading-none text-emerald-500" id="clearLocation">&times;</button>`;
  el.classList.remove("hidden");
  document.getElementById("clearLocation").addEventListener("click", () => {
    selectedLocation = null;
    el.classList.add("hidden");
    document.getElementById("locationInput").value = "";
  });
}

function getAdzunaCountry() {
  return selectedLocation ? selectedLocation.country_code : "us";
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
  const header = document.getElementById("mainHeader");
  const panel = document.getElementById("internshipPanel");
  if (internshipMode) {
    document.body.classList.add("internship-mode");
    toggle.style.background = "#0d9488";
    knob.style.left = "22px";
    btn.innerHTML = '<span class="text-base">🎓</span> Find Internships';
    header.style.background = "linear-gradient(135deg, #0f766e 0%, #0d9488 45%, #14b8a6 100%)";
    if (panel) { panel.style.background = "#f0fdfa"; panel.style.borderColor = "#99f6e4"; }
  } else {
    document.body.classList.remove("internship-mode");
    toggle.style.background = "#cbd5e1";
    knob.style.left = "2px";
    btn.innerHTML = '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg> Search Jobs';
    header.style.background = "linear-gradient(135deg, #1e1b4b 0%, #3730a3 45%, #6d28d9 100%)";
    if (panel) { panel.style.background = "#f0fdf4"; panel.style.borderColor = "#bbf7d0"; }
  }
});

// ===== SEARCH =====
document.getElementById("searchBtn").addEventListener("click", async () => {
  const resume = document.getElementById("resume").value.trim();
  if (!resume) return alert("Paste your resume first");
  const sites = getSelectedSites(), keywords = getSelectedKeywords(), roles = getSelectedRoles();
  if (!sites.length) return alert("Select at least one site");
  if (!roles.length) return alert("Select at least one role category");

  document.getElementById("searchBtn").innerHTML = '<svg class="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg> Searching...';
  document.getElementById("searchBtn").disabled = true;
  document.getElementById("extractBtn").disabled = true;

  lastRenderedCount = 0;
  lastFilteredGen = 0;
  lastPassNum = 0;
  allJobs = [];
  activeFilters = { site: '', experience_level: '' };
  document.getElementById("filterBar").classList.add("hidden");
  showSpinner("Contacting scrapers...");
  hideElement("results");
  setStatus("Starting scrape...");
  try {
    await fetch("/scrape", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
      sites, keywords, resume_text: resume, roles,
      adzuna_country: getAdzunaCountry(),
      indeed_country: getIndeedCountry(),
      location: getLocation(),
      internship_mode: internshipMode
    })});
    scrapeAttempts = 0;
    pollResults();
  } catch (e) { setStatus("Error: " + e.message, "red"); resetSearchBtn(); hideSpinner(); }
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
      const r = await fetch("/scrape/status");
      const d = await r.json();

      if (d.queue_position > 0) {
        showSpinner(`Queued at position ${d.queue_position}...`);
        return;
      }

      if (d.status === "running") {
        const inPass = d.max_passes > 0 && d.pass_num > 0;
        const genChanged = d.filtered_gen !== lastFilteredGen;
        const countChanged = d.last_scrape_relevant !== lastRenderedCount;

        if (d.last_scrape_raw > 0) {
          hideSpinner();
          if (d.last_scrape_relevant > 0) {
            if (genChanged && inPass) {
              setStatus(`\u2713 Pass ${d.pass_num}/${d.max_passes} complete \u2014 ${d.last_scrape_relevant} relevant so far`);
            } else if (countChanged) {
              setStatus(`Scoring${inPass ? ` Pass ${d.pass_num}/${d.max_passes}` : ""} jobs with AI... (${d.last_scrape_relevant} relevant)`);
            } else if (d.pass_num > lastPassNum && lastPassNum > 0) {
              setStatus(`${d.last_scrape_relevant} relevant so far, searching for more (Pass ${d.pass_num}/${d.max_passes})...`);
            } else {
              setStatus(`${d.last_scrape_relevant} relevant so far${inPass ? ` (Pass ${d.pass_num}/${d.max_passes})` : ""}`);
            }
            await loadResultsIncremental(d.filtered_gen);
          } else {
            if (d.pass_num > lastPassNum && lastPassNum > 0) {
              setStatus(`No matches yet, searching for more (Pass ${d.pass_num}/${d.max_passes})...`);
            } else if (genChanged && inPass) {
              setStatus(`\u2713 Pass ${d.pass_num}/${d.max_passes} complete \u2014 no matches yet`);
            } else {
              setStatus(`Scoring${inPass ? ` Pass ${d.pass_num}/${d.max_passes}` : ""} jobs with AI... (no matches yet)`);
            }
          }
        } else {
          showSpinner(`Scraping job boards${inPass ? ` (Pass ${d.pass_num}/${d.max_passes})` : ""}... (rate-limit delays active)`);
        }
        lastFilteredGen = d.filtered_gen;
        lastPassNum = d.pass_num;
      }

      if (d.status === "done" || d.status === "error") {
        clearInterval(pollTimer); pollTimer = null;
        hideSpinner();
        if (d.status === "error") setStatus("Scraping failed", "red");
        await loadResults(d);
      } else if (scrapeAttempts > 90) {
        setStatus("Scraping is taking longer than expected — still processing...", undefined);
      }
    } catch {
      clearInterval(pollTimer); pollTimer = null;
      setStatus("Error polling results", "red");
      resetSearchBtn(); hideSpinner();
    }
  }, 2000);
}

async function loadResultsIncremental(filteredGen) {
  try {
    const r = await fetch("/jobs");
    const d = await r.json();
    const jobs = d.jobs || [];
    const gen = filteredGen !== undefined ? filteredGen : lastFilteredGen;
    if (jobs.length > 0 && (jobs.length !== lastRenderedCount || gen !== lastFilteredGen)) {
      lastRenderedCount = jobs.length;
      lastFilteredGen = gen;
      jobs.sort((a, b) => (b.total_score || 0) - (a.total_score || 0));
      showElement("results");
      renderJobs(jobs);
      updateCountBadge(jobs.length);
    }
  } catch {}
}

// ===== LOAD RESULTS =====
async function loadResults(statusData) {
  try {
    const r = await fetch("/jobs");
    const d = await r.json();
    allJobs = d.jobs || [];
    hasRawJobs = true;
    showElement("results");
    applyThreshold();
    let msg;
    if (allJobs.length) {
      const passSummary = statusData && statusData.max_passes > 0 && statusData.pass_num > 0 ? ` after ${statusData.pass_num}/${statusData.max_passes} passes` : "";
      msg = `Found ${allJobs.length} relevant jobs${passSummary}`;
    } else {
      msg = "No relevant jobs found";
    }
    setStatus(msg, allJobs.length ? "green" : undefined);
  } catch (e) { setStatus("Error loading results: " + e.message, "red"); }
  resetSearchBtn();
}

// ===== RENDER JOBS =====
function renderJobs(jobs) {
  const c = document.getElementById("results");
  if (!jobs.length) {
    c.innerHTML = `<div class="flex flex-col items-center justify-center py-20 text-slate-300">
      <div class="w-14 h-14 rounded-2xl bg-slate-50 border border-slate-100 flex items-center justify-center mb-4">
        <svg class="w-6 h-6 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>
      </div>
      <p class="text-sm font-medium text-slate-400">No matching jobs found</p>
       <p class="text-xs text-slate-300 mt-1">Try changing keywords or job roles</p>
    </div>`;
    return;
  }

  const showAll = voteCount >= voteThreshold;
  const limit = 5;

  function cardHtml(j) {
    const sc = j.total_score || 0;
    const barPct = Math.min(sc, 100);
    const barColor = sc >= 80 ? "bg-emerald-500" : sc >= 50 ? "bg-amber-400" : "bg-red-400";
    const txtColor = sc >= 80 ? "text-emerald-600" : sc >= 50 ? "text-amber-600" : "text-red-500";
    const expBadge = j.experience_level === "internship"
      ? '<span class="text-xs bg-emerald-100 text-emerald-700 px-2 py-0.5 rounded-full font-medium">🎓 Internship</span>'
      : j.experience_level === "entry_level"
        ? '<span class="text-xs bg-sky-100 text-sky-700 px-2 py-0.5 rounded-full font-medium">🌱 Entry Level</span>'
        : "";
    return `<div class="border border-slate-100 rounded-xl p-4 hover:shadow-md hover:border-slate-200 transition cursor-default ${j.experience_level ? 'border-l-4 ' + (j.experience_level === 'internship' ? 'border-l-emerald-400' : 'border-l-sky-400') : ''}">
      <div class="flex items-start justify-between gap-3">
        <div class="min-w-0">
          <div class="flex items-center gap-2 flex-wrap">
            <h3 class="font-semibold text-slate-800 truncate">${j.title}</h3>
            ${expBadge}
          </div>
          <p class="text-sm text-slate-400 truncate">${j.company} &middot; ${j.location}</p>
        </div>
        <div class="text-right shrink-0">
          ${j.salary ? `<div class="text-xs font-semibold text-emerald-600 whitespace-nowrap">${j.salary}</div>` : ""}
          <div class="font-mono text-lg font-bold ${txtColor}">${sc}</div>
          <div class="text-xs text-slate-400">AI ${j.ai_score || 0} / KW ${j.keyword_score || 0}</div>
        </div>
      </div>
      <div class="mt-2 w-full h-1.5 bg-slate-100 rounded-full overflow-hidden">
        <div class="score-fill h-full ${barColor} rounded-full" style="width:0" data-w="${barPct}"></div>
      </div>
      ${j.tags && j.tags.length ? `<div class="flex flex-wrap gap-1 mt-2">${j.tags.slice(0, 6).map(t => `<span class="text-xs bg-slate-100 text-slate-500 px-2 py-0.5 rounded-full">${t}</span>`).join('')}</div>` : ""}
      ${j.reason ? `<p class="text-xs text-slate-400 mt-2 leading-relaxed">${j.reason}</p>` : ""}
      <a href="${j.url}" target="_blank" class="text-indigo-600 text-xs hover:text-indigo-700 hover:underline mt-2 inline-flex items-center gap-1">${j.url.replace(/^https?:\/\//, '').substring(0, 40)}${j.url.length > 40 ? '...' : ''} <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg></a>
    </div>`;
  }

  if (jobs.length > limit && !showAll) {
    const lockedCount = jobs.length - limit;
    const voteBtnHtml = hasVoted
      ? `<button class="vote-btn mt-3 bg-slate-300 text-slate-500 px-5 py-2 rounded-lg text-sm font-medium inline-flex items-center gap-1.5 shadow-sm cursor-not-allowed"><span>✓</span> Voted</button>`
      : `<button class="vote-btn mt-3 bg-amber-500 hover:bg-amber-600 disabled:bg-amber-300 disabled:cursor-not-allowed text-white px-5 py-2 rounded-lg text-sm font-medium transition inline-flex items-center gap-1.5 shadow-sm" onclick="handleVote(this)">👍 Vote (${voteCount}/${voteThreshold})</button>`;
    c.innerHTML = jobs.slice(0, limit).map(j => cardHtml(j)).join("") + `
      <div class="relative border border-slate-100 rounded-xl overflow-hidden mt-3">
        <div class="blur-job">${jobs.slice(limit).map(j => cardHtml(j)).join("")}</div>
        <div class="absolute inset-0 flex items-center justify-center">
          <div class="bg-white/80 backdrop-blur-sm rounded-xl p-5 text-center shadow-lg mx-3 max-w-sm">
            <div class="text-3xl mb-1">🔒</div>
            <p class="font-semibold text-slate-800 text-sm">${lockedCount} more job${lockedCount > 1 ? 's' : ''} locked</p>
            <p class="text-xs text-slate-500 mt-0.5">Support the project to unlock all</p>
            ${voteBtnHtml}
          </div>
        </div>
      </div>`;
  } else {
    c.innerHTML = jobs.map(j => cardHtml(j)).join("");
  }
  requestAnimationFrame(() => {
    c.querySelectorAll('.score-fill').forEach(el => {
      el.style.width = el.dataset.w + '%';
    });
  });
}
