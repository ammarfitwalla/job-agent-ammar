/* referrals-page.js — Standalone public /referrals page.
   Self-contained: does NOT import referrals.js (that file is coupled to the
   search-page DOM). Reuses api.js (classic), utils.js, auth.js, terms.js. */
import { getProfile, setProfile, fetchProfile, showToast, htmlEscape } from "./utils.js";

const $ = (id) => document.getElementById(id);

// Page state
let _allCompanies = [];
let _filteredCompanies = [];
let _companyUserCache = {};
let _currentCompany = "";
let _currentJobUrl = "";
let _currentJobTitle = "";
let _resolvedCompany = "";

// Referrer state caches
let _notifiedCompanies = new Set();
try { _notifiedCompanies = new Set((sessionStorage.getItem("referralNotified") || "").split(",").filter(Boolean)); } catch (e) {}

const NOTIFY_CHECK_SVG = '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5"/></svg>';
const NOTIFY_SAVED_CLASSES = "w-full inline-flex items-center justify-center gap-1.5 text-xs font-semibold text-emerald-700 bg-emerald-50 border border-emerald-200/60 px-4 py-2.5 rounded-xl cursor-default";
const NOTIFY_SAVED_LABEL = "You're on the list - we'll notify you";

function _persistNotifiedCompanies() {
  try { sessionStorage.setItem("referralNotified", [..._notifiedCompanies].join(",")); } catch (e) {}
}

function _esc(x) { return htmlEscape(x); }

// ── Directory ──

async function loadDirectory() {
  const grid = $("directoryGrid");
  const empty = $("directoryEmpty");
  grid.innerHTML = `<div class="col-span-full flex flex-col items-center justify-center py-12 gap-3 text-slate-400">
    <svg class="w-6 h-6 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
    <p class="text-sm">Loading companies...</p></div>`;
  try {
    const r = await fetch("/api/users/referrer-directory");
    const d = await r.json();
    _allCompanies = d.companies || [];
    _filteredCompanies = [..._allCompanies];
    renderDirectory();
  } catch (e) {
    grid.innerHTML = "";
    if (empty) {
      empty.classList.remove("hidden");
      empty.innerHTML = `<p class="text-sm font-medium text-slate-600">Couldn't load the company list.</p>
        <p class="text-xs text-slate-400 mt-1">Please refresh and try again.</p>`;
    }
  }
}

function renderDirectory() {
  const grid = $("directoryGrid");
  if (_filteredCompanies.length === 0) {
    grid.innerHTML = "";
    const empty = $("directoryEmpty");
    if (empty) empty.classList.remove("hidden");
    return;
  }
  const empty = $("directoryEmpty");
  if (empty) empty.classList.add("hidden");
  grid.innerHTML = _filteredCompanies.map((c) => `
    <button class="company-card text-left bg-white rounded-2xl border border-slate-200 p-5 transition-all cursor-pointer" onclick="window.RP.openCompany('${_esc(c.company.replace(/'/g, "\\'"))}')">
      <div class="flex items-start justify-between gap-2">
        <div class="w-10 h-10 rounded-xl bg-brand-100 text-brand-700 flex items-center justify-center font-bold text-lg shrink-0">${_esc((c.company || "?").charAt(0).toUpperCase())}</div>
        <span class="text-[11px] font-semibold px-2 py-1 rounded-lg bg-emerald-50 text-emerald-700 whitespace-nowrap">${c.referrer_count} referrer${c.referrer_count === 1 ? "" : "s"}</span>
      </div>
      <div class="mt-3 font-semibold text-slate-900 text-sm leading-snug">${_esc(c.company)}</div>
    </button>`).join("");
}

function filterDirectory(value) {
  const q = (value || "").trim().toLowerCase();
  _filteredCompanies = q
    ? _allCompanies.filter((c) => (c.company || "").toLowerCase().includes(q))
    : [..._allCompanies];
  renderDirectory();
}

// ── URL resolver ──

async function resolveUrl() {
  const input = $("urlInput");
  const errEl = $("resolveError");
  const btn = $("resolveBtn");
  const url = input ? input.value.trim() : "";
  if (!url) { showToast("Paste a job link first"); return; }
  if (!/^https?:\/\//i.test(url)) { showToast("Link must start with http:// or https://"); return; }
  if (errEl) errEl.classList.add("hidden");
  if (btn) { btn.disabled = true; btn.textContent = "Finding referrers..."; }
  try {
    const r = await fetch("/api/referrals/resolve-url", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    if (r.status === 429) { showToast("Too many requests. Try again in a minute."); return; }
    const d = await r.json();
    if (!d.ok) { showToast(d.detail || "Could not read that link"); return; }
    _currentJobUrl = d.url || url;
    _resolvedCompany = d.company || "";
    _currentJobTitle = d.job_title || "";

    $("resolvedCompany").value = _resolvedCompany;
    $("resolvedTitle").value = _currentJobTitle;
    const hint = $("resolveHint");
    const candidates = d.company_candidates || [];
    const unique = [...new Set([...candidates, _resolvedCompany].filter(Boolean))];
    const hintParts = [];
    if (_resolvedCompany) {
      hintParts.push(`<span class="text-emerald-600 font-medium">We found the company automatically.</span>`);
    } else {
      hintParts.push(`<span class="text-amber-600 font-medium">We couldn't detect the company - type it below.</span>`);
    }
    if (d.referrer_count) {
      hintParts.push(` <span class="text-slate-500">${d.referrer_count} insider referral${d.referrer_count === 1 ? "" : "s"} available.</span>`);
    } else {
      hintParts.push(` <span class="text-slate-500">No referrers listed yet - you can still view this company.</span>`);
    }
    hint.innerHTML = hintParts.join("");
    const candBox = $("resolveCandidates");
    if (candBox) candBox.remove();
    if (unique.length > 1) {
      const box = document.createElement("div");
      box.id = "resolveCandidates";
      box.className = "mt-2 space-y-1";
      box.innerHTML = unique.map((cand) =>
        `<button onclick="window.RP.pickResolvedCompany('${_esc(cand.replace(/'/g, "\\'"))}')"
           class="block w-full text-left px-3 py-2 text-sm text-slate-600 hover:bg-slate-50 rounded-lg">${_esc(cand)}</button>`).join("");
      $("resolveStep2").insertBefore(box, $("resolvedCompany").closest(".flex"));
    }

    $("resolveStep1").classList.add("hidden");
    $("resolveStep2").classList.remove("hidden");
  } catch (e) {
    showToast("Network error");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "Find referrers"; }
  }
}

function pickResolvedCompany(name) {
  $("resolvedCompany").value = name;
  const candBox = $("resolveCandidates");
  if (candBox) candBox.remove();
}

function resetResolve() {
  $("resolveStep2").classList.add("hidden");
  $("resolveStep1").classList.remove("hidden");
  $("resolveCandidates")?.remove();
  $("urlInput").value = "";
  _currentJobUrl = "";
  _resolvedCompany = "";
  _currentJobTitle = "";
  $("urlInput").focus();
}

function proceedFromResolved() {
  const company = $("resolvedCompany").value.trim();
  if (!company) { showToast("Enter the company name first"); return; }
  _currentCompany = company;
  _currentJobTitle = $("resolvedTitle").value.trim() || _currentJobTitle || "";
  $("resolverSection").scrollIntoView({ behavior: "smooth", block: "start" });
  openPanel(company);
}

// ── Referrer panel ──

function openCompany(company) {
  _currentCompany = company;
  _currentJobUrl = "";
  _currentJobTitle = "";
  if (!_isMobile()) {
    $("resolverSection").scrollIntoView({ behavior: "smooth", block: "start" });
  }
  openPanel(company);
}

function closePanel() {
  $("referrerPanel").classList.add("hidden");
  $("referrerPanel").classList.remove("is-open");
  $("panelBackdrop").classList.add("hidden");
  $("panelBackdrop").classList.remove("show");
  if (!_isMobile()) {
    $("resolverSection").scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

const _isMobile = () => window.matchMedia("(max-width: 767px)").matches;

function getResumeText() {
  try {
    const cached = localStorage.getItem("jobagent_resume_text");
    if (cached && cached.trim()) return cached.trim();
  } catch (e) {}
  return "";
}

async function loadOutgoing() {
  if (!getProfile()) return [];
  try {
    const r = await window.api("/api/referrals/outgoing", { cache: "no-cache" });
    const d = await r.json();
    return d.requests || [];
  } catch (e) {
    return [];
  }
}

async function openPanel(company) {
  $("panelCompanyTitle").textContent = company;
  $("panelCounter").textContent = "";
  $("referrerPanel").classList.remove("hidden");
  $("referrerPanel").classList.add("fade-in");
  if (_isMobile()) {
    $("referrerPanel").classList.add("is-open");
    $("panelBackdrop").classList.remove("hidden");
    $("panelBackdrop").classList.add("show");
  }

  // Monthly counter (only for signed-in seekers)
  if (getProfile()) {
    window.api("/api/referrals/remaining")
      .then((r) => r.json())
      .then((d) => {
        if (d.remaining > 0) $("panelCounter").textContent = `${d.remaining}/${d.limit} requests remaining this month`;
      }).catch(() => {});
  }

  if (!_companyUserCache[company]) {
    try {
      const r = await fetch(`/api/users/at-company?company=${encodeURIComponent(company)}`);
      const d = await r.json();
      _companyUserCache[company] = d || { users: [], count: 0 };
    } catch (e) {
      _companyUserCache[company] = { users: [], count: 0 };
    }
  }
  const cu = _companyUserCache[company];
  const users = (cu && cu.users) || [];
  const profile = getProfile();
  const list = $("referrerList");

  if (!profile) {
    list.innerHTML = `
      <div class="space-y-2 opacity-60 pointer-events-none select-none">
        ${[1, 2, 3].map((i) => `
        <div class="flex items-center justify-between p-3 bg-white border border-slate-100 rounded-xl">
          <div class="flex items-center gap-3 min-w-0">
            <div class="w-8 h-8 rounded-full bg-slate-300 flex items-center justify-center text-sm font-bold shrink-0 text-slate-500">?</div>
            <div class="min-w-0">
              <div class="text-sm font-medium text-slate-500 truncate">Insider at ${_esc(company)}</div>
              <div class="text-xs text-slate-500 truncate">Position hidden until you sign in</div>
            </div>
          </div>
          <button class="text-xs font-medium text-slate-500 bg-slate-100 px-3 py-1.5 rounded-lg">Ask for Referral</button>
        </div>`).join("")}
      </div>
      <button onclick="closeAuthModal(); showAuthModal()" class="w-full bg-indigo-600 hover:bg-indigo-700 text-white py-3 rounded-lg text-sm font-semibold transition-colors mt-3">Sign in to request referrals</button>`;
    return;
  }

  if (users.length === 0) {
    list.innerHTML = `<div class="text-center py-8">
      <div class="w-10 h-10 rounded-full bg-slate-50 flex items-center justify-center mx-auto mb-3">
        <svg class="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/></svg>
      </div>
      <p class="text-sm font-medium text-slate-600">No referrers at ${_esc(company)} yet</p>
      <p class="text-xs text-slate-400 mt-1">Be the first to open the door - invite an insider or get notified.</p>
      <div class="mt-4 max-w-xs mx-auto">
        ${_notifiedCompanies.has(company.toLowerCase())
          ? `<button type="button" disabled class="${NOTIFY_SAVED_CLASSES}">${NOTIFY_CHECK_SVG} ${NOTIFY_SAVED_LABEL}</button>`
          : `<button id="notifyWhenAvailableBtn" onclick="window.RP.notifyWhenAvailable()" class="w-full inline-flex items-center justify-center gap-1.5 text-xs font-semibold text-indigo-600 bg-indigo-50 hover:bg-indigo-100 border border-indigo-200/60 px-4 py-2.5 rounded-xl transition-colors">
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0M3.124 7.5A8.969 8.969 0 015.292 3m13.416 0a8.969 8.969 0 012.168 4.5"/></svg>
              Notify me when a referrer joins
            </button>`}
      </div>
    </div>`;
    return;
  }

  const outgoing = await loadOutgoing();
  list.innerHTML = users.map((u) => {
    const existing = outgoing.find((req) =>
      req.to_referrer_id === u.id &&
      req.company === _currentCompany &&
      (!_currentJobUrl || req.job_url === _currentJobUrl));
    let btnHtml;
    if (existing && (existing.status === "pending" || existing.status === "cancelled")) {
      btnHtml = existing.status === "pending"
        ? `<button class="btn-withdraw" data-id="${existing.id}" data-referrer-id="${_esc(u.id)}" onclick="window.RP.withdrawRow(this)">Withdraw</button>`
        : `<button class="btn-ask" data-referrer-id="${_esc(u.id)}" onclick="window.RP.askRow(this)">Ask for Referral</button>`;
    } else if (existing) {
      const st = existing.status;
      const stCls = st === "accepted" ? "bg-emerald-50 text-emerald-700" : st === "declined" ? "bg-red-50 text-red-700" : "bg-slate-100 text-slate-600";
      btnHtml = `<span class="text-[11px] font-semibold px-3 py-1.5 rounded-lg ${stCls}">${st.charAt(0).toUpperCase() + st.slice(1)}</span>`;
    } else {
      btnHtml = `<button class="btn-ask" data-referrer-id="${_esc(u.id)}" onclick="window.RP.askRow(this)">Ask for Referral</button>`;
    }
    return `
    <div class="flex items-center justify-between p-3 bg-white border border-slate-100 rounded-xl">
      <div class="flex items-center gap-3 min-w-0">
        <div class="w-8 h-8 rounded-full bg-indigo-100 text-indigo-700 flex items-center justify-center text-sm font-bold shrink-0">?</div>
        <div class="min-w-0">
          <div class="text-sm font-medium text-slate-900 truncate">Insider at ${_esc(company)}</div>
          ${u.position ? `<div class="text-xs text-slate-500 truncate">${_esc(u.position)}</div>` : `<div class="text-xs text-slate-400 truncate">Position not shared</div>`}
        </div>
      </div>
      ${btnHtml}
    </div>`;
  }).join("");
}

// ── Resume row (copied/adapted from referrals.js) ──

let _referralResumeFilename = "";
let _referralResumeReady = false;

async function resolveSessionResume() {
  const sid = window._searchSessionId || "";
  if (sid) {
    return fetch(`/scrape/status?search_id=${encodeURIComponent(sid)}`)
      .then((r) => r.json())
      .then((d) => (d && d.resume_filename) || "")
      .catch(() => "");
  }
  if (!(getProfile() && getProfile().resume_filename)) {
    await fetchProfile();
  }
  return (getProfile() && getProfile().resume_filename) || "";
}

function referralResumeNote(filename) {
  return `<div class="text-[11px] text-slate-500 bg-slate-50 border border-slate-100 rounded-lg px-2.5 py-1.5 flex items-center gap-1.5 max-w-full w-full">
    <svg class="w-3.5 h-3.5 text-indigo-400 shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
    <span class="min-w-0 flex-1 truncate text-ellipsis overflow-hidden"><span class="font-medium text-slate-600">${_esc(filename)}</span> will be sent to the referrer</span>
  </div>`;
}

function setupResumeRow(row) {
  resolveSessionResume().then((fname) => {
    _referralResumeFilename = fname;
    _referralResumeReady = true;
    if (fname) {
      row.innerHTML = referralResumeNote(fname);
      return;
    }
    row.innerHTML = `
      <label class="inline-flex items-center gap-1.5 cursor-pointer text-[11px] font-semibold text-indigo-600 bg-indigo-50 hover:bg-indigo-100 border border-indigo-200/60 px-3 py-1.5 rounded-lg transition-colors">
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5"/></svg>
        <span class="ref-resume-upload-lbl">Upload resume (required)</span>
        <input type="file" accept=".pdf,.docx,.txt" class="hidden ref-resume-file">
      </label>
      <p class="text-[10px] text-slate-400 mt-1 pl-0.5">Your resume is shown to the referrer only after they accept your request.</p>`;
    const input = row.querySelector(".ref-resume-file");
    input.addEventListener("change", async () => {
      const file = input.files && input.files[0];
      if (!file) return;
      const lbl = row.querySelector(".ref-resume-upload-lbl");
      lbl.textContent = "Uploading...";
      const fd = new FormData();
      fd.append("file", file);
      try {
        const r = await window.api("/api/profile/resume", { method: "POST", body: fd });
        const d = await r.json();
        if (d.ok && d.filename) {
          _referralResumeFilename = d.filename;
          const p = getProfile();
          setProfile({ ...p, resume_filename: d.filename });
          showToast("Resume saved as your default resume");
          row.innerHTML = referralResumeNote(d.filename);
        } else {
          lbl.textContent = "Upload failed. Try again.";
          showToast("Could not read that file. Use a PDF, DOCX, or TXT resume.");
        }
      } catch (e) {
        lbl.textContent = "Upload failed. Try again.";
        showToast("Resume upload failed. Check your connection.");
      }
      input.value = "";
    });
  });
}

// ── Ask / Send / Withdraw ──

function askRow(btn) {
  const row = btn.closest(".flex.items-center.justify-between");
  if (!row) return;
  const existing = row.parentElement.querySelector(".referral-ask-row");
  if (existing) { existing.remove(); return; }
  _referralResumeFilename = "";
  _referralResumeReady = false;
  const msgRow = document.createElement("div");
  msgRow.className = "referral-ask-row w-full mt-2 pt-2 border-t border-slate-100";
  msgRow.innerHTML = `
    <div class="ref-job-row mb-2">
      <label class="block text-[11px] font-semibold text-slate-500 mb-1">Job link (required)</label>
      <input type="url" class="ref-job-input w-full border border-slate-200 rounded-lg px-3 py-2 text-sm bg-slate-50 focus:bg-white focus:border-indigo-300 transition-colors" placeholder="https://linkedin.com/jobs/view/..." value="${_esc(_currentJobUrl)}" autocomplete="off">
    </div>
    <div class="ref-title-row mb-2">
      <label class="block text-[11px] font-semibold text-slate-500 mb-1">Job title <span class="font-normal text-slate-400">(auto-detected, editable)</span></label>
      <input type="text" class="ref-title-input w-full border border-slate-200 rounded-lg px-3 py-2 text-sm bg-slate-50 focus:bg-white focus:border-indigo-300 transition-colors" placeholder="e.g. Senior Software Engineer" value="${_esc(_currentJobTitle)}" autocomplete="off">
    </div>
    <div class="ref-resume-row mb-2"></div>
    <textarea class="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm bg-slate-50 focus:bg-white focus:border-indigo-300 resize-none transition-colors" rows="2" placeholder="Add a message (optional)..." maxlength="500"></textarea>
    <div class="flex gap-2 mt-2">
      <button class="flex-1 bg-indigo-600 hover:bg-indigo-700 text-white py-1.5 rounded-lg text-xs font-semibold transition-colors referral-send-btn">Send Request</button>
      <button class="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-600 rounded-lg text-xs font-medium transition-colors referral-cancel-btn">Cancel</button>
    </div>`;
  row.parentElement.appendChild(msgRow);
  const jobInput = msgRow.querySelector(".ref-job-input");
  const titleInput = msgRow.querySelector(".ref-title-input");
  let titleEditable = true;
  let titleGuessTimer = null;
  const guessTitle = () => {
    clearTimeout(titleGuessTimer);
    const url = (jobInput ? jobInput.value.trim() : "");
    if (!/^https?:\/\//i.test(url)) return;
    titleGuessTimer = setTimeout(async () => {
      try {
        const r = await fetch("/api/referrals/resolve-url", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url }),
        });
        if (r.status === 429 || !r.ok) return;
        const d = await r.json();
        if (d && d.job_title && titleEditable) titleInput.value = d.job_title;
      } catch (e) {}
    }, 600);
  };
  jobInput.addEventListener("input", guessTitle);
  jobInput.addEventListener("change", guessTitle);
  titleInput.addEventListener("input", () => { titleEditable = false; });
  msgRow.querySelector(".referral-send-btn").onclick = function () {
    const jobInput = msgRow.querySelector(".ref-job-input");
    const jobUrl = (jobInput ? jobInput.value.trim() : "").trim();
    if (!jobUrl || !/^https?:\/\//i.test(jobUrl)) {
      const lbl = msgRow.querySelector(".ref-job-row label");
      if (lbl) { lbl.textContent = "Paste the job link first"; lbl.style.color = "#dc2626"; }
      let err = msgRow.querySelector(".ref-job-error");
      if (!err) {
        err = document.createElement("p");
        err.className = "ref-job-error text-[11px] text-red-500 font-medium mt-1.5 pl-0.5";
        err.textContent = "Please paste the job link before sending your request.";
        msgRow.querySelector(".ref-job-row").appendChild(err);
      }
      if (jobInput) jobInput.focus();
      return;
    }
    _currentJobUrl = jobUrl;
    const titleInput = msgRow.querySelector(".ref-title-input");
    if (titleInput) _currentJobTitle = titleInput.value.trim();
    if (!_referralResumeFilename) {
      const lbl = msgRow.querySelector(".ref-resume-upload-lbl");
      if (lbl) { lbl.textContent = "Upload your resume to send"; lbl.closest("label").style.color = "#dc2626"; }
      let err = msgRow.querySelector(".ref-resume-error");
      if (!err) {
        err = document.createElement("p");
        err.className = "ref-resume-error text-[11px] text-red-500 font-medium mt-1.5 pl-0.5";
        err.textContent = "Please upload your resume before sending your request.";
        msgRow.appendChild(err);
      }
      return;
    }
    const message = msgRow.querySelector("textarea").value.trim();
    sendRequest(btn, msgRow, message);
  };
  msgRow.querySelector(".referral-cancel-btn").onclick = function () { msgRow.remove(); };
  msgRow.querySelector("textarea").focus();
  setupResumeRow(msgRow.querySelector(".ref-resume-row"));
}

async function sendRequest(btn, msgRow, message) {
  const referrerId = btn.dataset.referrerId;
  const sendBtn = msgRow.querySelector(".referral-send-btn");
  sendBtn.disabled = true;
  sendBtn.textContent = "Sending...";
  try {
    const r = await window.api("/api/referrals/request", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        referrer_id: referrerId,
        job_url: _currentJobUrl || "",
        job_title: _currentJobTitle || "",
        company: _currentCompany,
        match_score: 0,
        message: message,
        resume_filename: _referralResumeFilename || "",
        job_description: "",
        resume_text: getResumeText(),
        skip_score: true,
      }),
    });
    const d = await r.json();
    if (d.ok) {
      showToast("Referral request sent!");
      msgRow.remove();
      refreshCounter();
      openPanel(_currentCompany);
    } else {
      sendBtn.disabled = false;
      sendBtn.textContent = "Send Request";
      showToast(d.error || "Failed to send request");
    }
  } catch (e) {
    sendBtn.disabled = false;
    sendBtn.textContent = "Send Request";
    showToast("Network error");
  }
}

function withdrawRow(btn) {
  if (!confirm("Withdraw this referral request?")) return;
  const id = btn.dataset.id;
  btn.disabled = true;
  btn.textContent = "Withdrawing...";
  window.api(`/api/referrals/${id}/withdraw`, { method: "PUT" })
    .then((r) => r.json())
    .then((d) => {
      if (d.ok) {
        showToast("Referral withdrawn");
        refreshCounter();
        openPanel(_currentCompany);
      } else {
        btn.disabled = false;
        btn.textContent = "Withdraw";
        showToast(d.error || "Failed to withdraw");
      }
    })
    .catch(() => {
      btn.disabled = false;
      btn.textContent = "Withdraw";
      showToast("Network error");
    });
}

function refreshCounter() {
  if (!getProfile()) return;
  window.api("/api/referrals/remaining")
    .then((r) => r.json())
    .then((d) => {
      if (d.remaining > 0) $("panelCounter").textContent = `${d.remaining}/${d.limit} requests remaining this month`;
      else $("panelCounter").textContent = "";
    }).catch(() => {});
}

// ── Notify me (empty state on signed-in users) ──

async function notifyWhenAvailable() {
  const profile = getProfile();
  if (!profile) { showToast("Sign in to get notified"); return; }
  const company = _currentCompany;
  if (!company) return;
  if (_notifiedCompanies.has(company.toLowerCase())) { showToast("You're already on the list"); return; }
  try {
    const r = await window.api("/api/referrals/notify", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ company }),
    });
    const d = await r.json();
    if (d.ok) {
      _notifiedCompanies.add(company.toLowerCase());
      _persistNotifiedCompanies();
      openPanel(company);
      showToast(`We'll notify you when a referrer at ${company} joins`);
    } else {
      showToast(d.error || "Could not save that");
    }
  } catch (e) {
    showToast("Network error");
  }
}

// ── After auth: refresh the open panel / nav in place (no navigation) ──

window.afterAuthConnected = function () {
  updateProfileIcon();
  if (_currentCompany) openPanel(_currentCompany);
};

function updateProfileIcon() {
  const link = $("profileLink");
  const profile = getProfile();
  if (profile && profile.email) {
    const initial = (profile.name || profile.email).charAt(0).toUpperCase();
    link.innerHTML = `<span class="w-6 h-6 rounded-full bg-indigo-500 text-white flex items-center justify-center text-xs font-bold leading-none">${_esc(initial)}</span>`;
    link.classList.remove("border-slate-300");
    link.classList.add("border-indigo-200");
  } else {
    link.innerHTML = '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z"/></svg>';
    link.classList.add("border-slate-300");
    link.classList.remove("border-indigo-200");
  }
}

// ── Boot ──

document.addEventListener("DOMContentLoaded", () => {
  updateProfileIcon();
  loadDirectory();
});

// Public API for inline onclick handlers
window.RP = {
  loadDirectory,
  filterDirectory,
  openCompany,
  closePanel,
  resolveUrl,
  pickResolvedCompany,
  proceedFromResolved,
  resetResolve,
  askRow,
  withdrawRow,
  notifyWhenAvailable,
};