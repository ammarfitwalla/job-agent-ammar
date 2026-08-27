import { getProfile, setProfile, showToast, htmlEscape, formatDate } from "./utils.js";
import { _MONTHLY_LIMIT, REFERRAL_COOLDOWN } from "./constants.js";

// Referral Modal state
let _referralCompany = "";
let _referralJobTitle = "";
let _referralMatchScore = 0;
let _referralJobUrl = "";
let _companyUserCache = {};

// Referral Dashboard state
let _referralTab = "incoming";
let _referralNotifTimer = null;

async function loadCompanyUserCounts(companies) {
  const unique = [...new Set(companies.filter(Boolean))];
  const needed = unique.filter(c => !(c in _companyUserCache));
  if (needed.length === 0) return;
  const results = await Promise.allSettled(
    needed.map(c =>
      fetch(`/api/users/at-company?company=${encodeURIComponent(c)}`).then(r => r.json())
    )
  );
  needed.forEach((c, i) => {
    const r = results[i];
    _companyUserCache[c] = r.status === "fulfilled" && r.value ? r.value : { users: [], count: 0 };
  });
}

async function refreshCompanyUser(company) {
  try {
    const r = await fetch(`/api/users/at-company?company=${encodeURIComponent(company)}`);
    const d = await r.json();
    _companyUserCache[company] = d || { users: [], count: 0 };
  } catch (e) {
    _companyUserCache[company] = { users: [], count: 0 };
  }
}

async function checkReferralNotifications() {
  if (_referralNotifTimer) { clearTimeout(_referralNotifTimer); _referralNotifTimer = null; }
  const profile = getProfile();
  if (!profile) return;
  try {
    const r = await fetch(`/api/referrals/incoming?email=${encodeURIComponent(profile.email)}`);
    const d = await r.json();
    const pending = (d.requests || []).filter(req => req.status === "pending").length;
    const badge = document.getElementById("referralBadge");
    if (badge) {
      if (pending > 0) {
        badge.textContent = pending > 9 ? "9+" : pending;
        badge.classList.remove("hidden");
      } else {
        badge.classList.add("hidden");
      }
    }
  } catch {}
  _referralNotifTimer = setTimeout(checkReferralNotifications, 30000);
}

// ── Referral Modal ──

function closeReferralModal() {
  document.getElementById("referralModal").classList.add("hidden");
  document.getElementById("referralModal").classList.remove("flex");
}

function refreshReferralRemaining() {
  const profile = getProfile();
  if (!profile) return;
  const el = document.getElementById("referralRemaining");
  fetch(`/api/referrals/remaining?email=${encodeURIComponent(profile.email)}`)
    .then(r => r.json())
    .then(d => {
      if (d.remaining > 0) {
        el.textContent = `${d.remaining}/${d.limit} requests remaining this month`;
        el.classList.remove("hidden");
      } else {
        el.classList.add("hidden");
      }
    }).catch(() => {});
}

// ── "Got a job link? Get referred" URL modal ──

function openReferralUrlModal() {
  const modal = document.getElementById("referralUrlModal");
  if (!modal) return;
  const step1 = document.getElementById("referralUrlStep1");
  const step2 = document.getElementById("referralUrlStep2");
  if (step1) step1.classList.remove("hidden");
  if (step2) step2.classList.add("hidden");
  const input = document.getElementById("referralUrlInput");
  if (input) { input.value = ""; setTimeout(() => input.focus(), 50); }
  if (step2) {
    const c = document.getElementById("referralUrlCompany");
    if (c) c.value = "";
    const t = document.getElementById("referralUrlTitle");
    if (t) t.value = "";
    const dd = document.getElementById("referralUrlCandidates");
    if (dd) dd.classList.add("hidden");
  }
  modal.classList.remove("hidden");
  modal.classList.add("flex");
}

function closeReferralUrlModal() {
  const modal = document.getElementById("referralUrlModal");
  if (!modal) return;
  modal.classList.add("hidden");
  modal.classList.remove("flex");
}

async function submitReferralUrlResolve() {
  const input = document.getElementById("referralUrlInput");
  const errEl = document.getElementById("referralUrlError");
  const btn = document.getElementById("referralUrlFindBtn");
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
    window._referralJobUrl = d.url || url;
    window._referralJobTitle = d.job_title || "";
    const company = d.company || "";
    const candidates = d.company_candidates || [];

    const step1 = document.getElementById("referralUrlStep1");
    const step2 = document.getElementById("referralUrlStep2");
    if (step1) step1.classList.add("hidden");
    if (step2) step2.classList.remove("hidden");

    const c = document.getElementById("referralUrlCompany");
    if (c) c.value = company;
    const t = document.getElementById("referralUrlTitle");
    if (t) t.value = d.job_title || "";
    const hint = document.getElementById("referralUrlHint");
    if (hint) {
      hint.innerHTML = d.company
        ? `<span class="text-emerald-600 font-medium">We found the company automatically.</span> Fix it if it looks wrong.`
        : `<span class="text-amber-600 font-medium">We couldn't detect the company — type it below.</span>`;
    }

    const dd = document.getElementById("referralUrlCandidates");
    if (dd) {
      const unique = [...new Set([...candidates, company].filter(Boolean))];
      if (unique.length <= 1) {
        dd.classList.add("hidden");
      } else {
        dd.innerHTML = unique.map(cand =>
          `<button type="button" onclick="document.getElementById('referralUrlCompany').value='${htmlEscape(cand.replace(/'/g, "\\'"))}'"
             class="block w-full text-left px-3 py-2 text-sm text-slate-600 hover:bg-slate-50 rounded-lg">${htmlEscape(cand)}</button>`).join("");
        dd.classList.remove("hidden");
      }
    }
  } catch (e) {
    showToast("Network error");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "Find referrers"; }
  }
}

function proceedFromUrlToReferrers() {
  const c = document.getElementById("referralUrlCompany");
  const t = document.getElementById("referralUrlTitle");
  const company = c ? c.value.trim() : "";
  if (!company) { showToast("Enter the company name first"); return; }
  window._referralCompany = company;
  window._referralJobTitle = (t && t.value.trim()) || window._referralJobTitle || "";
  closeReferralUrlModal();
  showReferralUsers(company);
}

// ── Empty-state viral loop: invite a friend / get notified ──

function getShareLink(company) {
  const profile = getProfile();
  if (!profile || !profile.email) return "";
  let link = `${window.location.origin}/app?ref=${encodeURIComponent(profile.email)}`;
  if (company) link += `&company=${encodeURIComponent(company)}`;
  return link;
}

async function inviteReferrer(company) {
  const profile = getProfile();
  if (!profile) { closeReferralModal(); window.showAuthModal(); return; }
  const link = getShareLink(company);
  try {
    const r = await fetch("/api/referrals/invite", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: profile.email, company: company || "" }),
    });
    const d = await r.json();
    if (!d.ok && d.error) { showToast(d.error); return; }
  } catch {}
  const shareText = `I'm looking for referrals on Career Hub — use this link to join and earn referral credits: ${link}`;
  if (navigator.share && navigator.canShare) {
    try {
      await navigator.share({ title: "Join Career Hub", text: shareText, url: link });
      return;
    } catch (e) { /* fall through to clipboard */ }
  }
  try {
    await navigator.clipboard.writeText(link);
    showToast("Invite link copied! Share it and you both earn referral credits");
  } catch {
    showToast(`Share this link: ${link}`);
  }
}

async function notifyWhenAvailable(company) {
  const profile = getProfile();
  if (!profile) { closeReferralModal(); window.showAuthModal(); return; }
  if (!company) { showToast("No company selected"); return; }
  try {
    const r = await fetch("/api/referrals/notify", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: profile.email, company }),
    });
    const d = await r.json();
    showToast(d.ok ? `We'll notify you when a referrer at ${company} joins` : (d.error || "Could not save that"));
  } catch {
    showToast("Network error");
  }
}

async function showReferralUsers(company) {
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
  const users = cu && cu.users ? cu.users : [];
  _referralCompany = company;
  const profile = getProfile();
  const modal = document.getElementById("referralModal");
  const list = document.getElementById("referralUserList");
  const title = document.getElementById("referralCompanyTitle");
  const remainingEl = document.getElementById("referralRemaining");
  title.textContent = company;
  if (profile) {
    fetch(`/api/referrals/remaining?email=${encodeURIComponent(profile.email)}`)
      .then(r => r.json())
      .then(d => {
        if (d.remaining > 0) {
          remainingEl.textContent = `${d.remaining}/${d.limit} requests remaining this month`;
          remainingEl.classList.remove("hidden");
        }
      }).catch(() => {});
  } else {
    remainingEl.classList.add("hidden");
  }
  if (!profile) {
    list.innerHTML = `
      <div class="space-y-2 opacity-50 pointer-events-none select-none">
        ${[1, 2, 3].map(i => `
        <div class="flex items-center justify-between p-3 bg-white border border-slate-100 rounded-xl">
          <div class="flex items-center gap-3 min-w-0">
            <div class="w-8 h-8 rounded-full bg-slate-300 flex items-center justify-center text-sm font-bold shrink-0 text-slate-500">?</div>
            <div class="min-w-0">
              <div class="text-sm font-medium text-slate-500 truncate">????</div>
              <div class="text-xs text-slate-500 truncate">Position at ${htmlEscape(company)}</div>
            </div>
          </div>
          <button class="text-xs font-medium text-slate-500 bg-slate-100 px-3 py-1.5 rounded-lg">Ask for Referral</button>
        </div>
        `).join("")}
      </div>
      <button onclick="closeReferralModal(); showAuthModal()" class="w-full bg-indigo-600 hover:bg-indigo-700 text-white py-3 rounded-lg text-sm font-semibold transition-colors mt-3">Sign in to see the list</button>
    `;
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    return;
  }
  if (users.length === 0) {
    list.innerHTML = `<div class="text-center py-8">
      <div class="w-10 h-10 rounded-full bg-slate-50 flex items-center justify-center mx-auto mb-3">
        <svg class="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/></svg>
      </div>
      <p class="text-sm font-medium text-slate-600">No referrers at ${htmlEscape(company)} yet</p>
      <p class="text-xs text-slate-400 mt-1">Be the first to open the door — invite an insider or get notified.</p>
      <div class="mt-4 space-y-2 max-w-xs mx-auto">
        <button onclick="inviteReferrer('${htmlEscape(company.replace(/'/g, "\\'"))}')" class="w-full inline-flex items-center justify-center gap-1.5 text-xs font-semibold text-white bg-gradient-to-r from-brand-600 to-brand-700 hover:from-brand-700 hover:to-brand-700 px-4 py-2.5 rounded-xl transition-all shadow-sm shadow-brand-500/20">
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10"/></svg>
          Invite a friend at ${htmlEscape(company)} — earn credits
        </button>
        <button onclick="notifyWhenAvailable('${htmlEscape(company.replace(/'/g, "\\'"))}')" class="w-full inline-flex items-center justify-center gap-1.5 text-xs font-semibold text-indigo-600 bg-indigo-50 hover:bg-indigo-100 border border-indigo-200/60 px-4 py-2.5 rounded-xl transition-colors">
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0M3.124 7.5A8.969 8.969 0 015.292 3m13.416 0a8.969 8.969 0 012.168 4.5"/></svg>
          Notify me when a referrer joins
        </button>
      </div>
    </div>`;
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    return;
  }
  let outgoingRequests = [];
  if (profile) {
    try {
      const r = await fetch(`/api/referrals/outgoing?email=${encodeURIComponent(profile.email)}`);
      const d = await r.json();
      outgoingRequests = d.requests || [];
    } catch (e) {}
  }
  list.innerHTML = users.map(u => {
    const existing = outgoingRequests.find(req =>
      req.to_email === u.email && req.job_url === (window._referralJobUrl || "") && req.company === _referralCompany
    );
    let btnHtml = "";
    if (!profile) {
      btnHtml = `<button class="text-xs font-medium text-slate-400 bg-slate-50 px-3 py-1.5 rounded-lg referral-signin-btn">Sign in to ask</button>`;
    } else if (existing && existing.status === "pending") {
      btnHtml = `<button class="text-xs font-medium text-red-600 bg-red-50 hover:bg-red-100 px-3 py-1.5 rounded-lg transition-colors referral-withdraw-btn" data-id="${existing.id}" data-email="${htmlEscape(u.email)}" data-name="${htmlEscape(u.name)}">Withdraw</button>`;
    } else if (existing && existing.status === "cancelled") {
      btnHtml = `<button class="text-xs font-medium text-indigo-600 bg-indigo-50 hover:bg-indigo-100 px-3 py-1.5 rounded-lg transition-colors referral-ask-btn" data-email="${htmlEscape(u.email)}" data-name="${htmlEscape(u.name)}">Ask for Referral</button>`;
    } else if (existing) {
      btnHtml = `<span class="text-xs font-medium text-slate-400 px-3 py-1.5">${htmlEscape(existing.status)}</span>`;
    } else {
      btnHtml = `<button class="text-xs font-medium text-indigo-600 bg-indigo-50 hover:bg-indigo-100 px-3 py-1.5 rounded-lg transition-colors referral-ask-btn" data-email="${htmlEscape(u.email)}" data-name="${htmlEscape(u.name)}">Ask for Referral</button>`;
    }
    return `
    <div class="flex items-center justify-between p-3 bg-white border border-slate-100 rounded-xl">
      <div class="flex items-center gap-3 min-w-0">
        <div class="w-8 h-8 rounded-full bg-indigo-100 text-indigo-700 flex items-center justify-center text-sm font-bold shrink-0">${htmlEscape(u.name.charAt(0).toUpperCase())}</div>
        <div class="min-w-0">
          <div class="text-sm font-medium text-slate-900 truncate">${htmlEscape(u.name)}</div>
          <div class="text-xs text-slate-500 truncate">${htmlEscape(u.position || "Works at " + company)}</div>
        </div>
      </div>
      ${btnHtml}
    </div>`;
  }).join("");
  modal.classList.remove("hidden");
  modal.classList.add("flex");
}

function getResumeText() {
  const el = document.getElementById("resume");
  if (el && el.value && el.value.trim()) return el.value.trim();
  try {
    const cached = localStorage.getItem("jobagent_resume_text");
    if (cached && cached.trim()) return cached.trim();
  } catch {}
  return "";
}

async function scoreReferralJob() {
  const profile = getProfile();
  const url = window._referralJobUrl || "";
  const title = window._referralJobTitle || "";
  const company = _referralCompany;
  if (typeof window.ensureJobScored === "function") {
    try {
      const s = await window.ensureJobScored(url) || 0;
      if (s > 0) return s;
    } catch {}
  }
  const description = typeof window.getReferralJobDescription === "function"
    ? (window.getReferralJobDescription(url) || "")
    : (window._referralJobDescription || "");
  try {
    const r = await fetch("/api/referrals/score", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        from_email: (profile || {}).email || "",
        job_url: url,
        job_title: title,
        company: company,
        job_description: description,
        resume_text: getResumeText(),
      }),
    });
    const d = await r.json();
    return d.ok ? (d.score || 0) : 0;
  } catch {
    return 0;
  }
}

async function askReferral(btn, toEmail, toName) {
  const profile = getProfile();
  if (!profile) { closeReferralModal(); window.showAuthModal(); return; }
  if (toEmail === profile.email) {
    showToast("You can't refer yourself");
    return;
  }

  let hasDefaultResume = !!(profile.resume_filename || "");
  if (!profile.resume_filename) {
    try {
      const r = await fetch(`/api/profile?email=${encodeURIComponent(profile.email)}`);
      const d = await r.json();
      if (d && d.email) {
        setProfile(d);
        hasDefaultResume = !!(d.resume_filename || "");
      }
    } catch {}
  }
  if (!hasDefaultResume && (isProfilePage() || !getResumeText())) {
    promptAddResume();
    return;
  }

  const card = btn.closest(".flex.items-center.justify-between");
  if (!card) return;
  const existing = card.querySelector(".referral-msg-box");
  if (existing) { existing.remove(); return; }

  btn.disabled = true;
  const origText = btn.textContent;
  btn.textContent = "Scoring job...";
  const score = await scoreReferralJob();
  window._referralMatchScore = score;
  btn.disabled = false;
  btn.textContent = origText;

  const msgBox = document.createElement("div");
  msgBox.className = "referral-msg-box w-full mt-2 pt-2 border-t border-slate-100";
  msgBox.innerHTML = `
    ${score > 0 ? `<div class="text-xs font-medium text-indigo-600 bg-indigo-50 border border-indigo-100 rounded-lg px-3 py-1.5 mb-2">✨ AI Match: ${Math.round(score)}% against your resume</div>` : ""}
    <textarea class="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm bg-slate-50 focus:bg-white focus:border-indigo-300 resize-none transition-colors" rows="2" placeholder="Add a message (optional)..." maxlength="500"></textarea>
    <div class="flex gap-2 mt-2">
      <button class="flex-1 bg-indigo-600 hover:bg-indigo-700 text-white py-1.5 rounded-lg text-xs font-semibold transition-colors referral-send-btn">Send Request</button>
      <button class="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-600 rounded-lg text-xs font-medium transition-colors referral-cancel-btn">Cancel</button>
    </div>`;
  card.parentElement.appendChild(msgBox);
  msgBox.querySelector(".referral-send-btn").onclick = function () {
    const message = msgBox.querySelector("textarea").value.trim();
    sendReferralRequest(btn, toEmail, toName, message, msgBox);
  };
  msgBox.querySelector(".referral-cancel-btn").onclick = function () { msgBox.remove(); };
  msgBox.querySelector("textarea").focus();
}

let _resumePromptResolve = null;

function closeResumePromptModal() {
  const modal = document.getElementById("resumePromptModal");
  if (modal) {
    modal.classList.add("hidden");
    modal.classList.remove("flex");
  }
  const r = _resumePromptResolve;
  _resumePromptResolve = null;
  if (r) r(false);
}

function setDefaultResumeChoice(choice) {
  const modal = document.getElementById("resumePromptModal");
  if (modal) {
    modal.classList.add("hidden");
    modal.classList.remove("flex");
  }
  const r = _resumePromptResolve;
  _resumePromptResolve = null;
  if (r) r(choice);
}

function openResumePromptModal() {
  return new Promise((resolve) => {
    const modal = document.getElementById("resumePromptModal");
    _resumePromptResolve = resolve;
    modal.classList.remove("hidden");
    modal.classList.add("flex");
  });
}

async function uploadDefaultResume(resumeText) {
  const profile = getProfile();
  if (!profile || !resumeText) return false;
  const file = new File([resumeText], "resume.txt", { type: "text/plain" });
  const fd = new FormData();
  fd.append("file", file);
  try {
    const r = await fetch(`/api/profile/resume?email=${encodeURIComponent(profile.email)}`, { method: "POST", body: fd });
    const d = await r.json();
    if (d.ok && d.filename) {
      const p = getProfile();
      setProfile({ ...p, resume_filename: d.filename });
      if (typeof window.refreshProfileResumeBtn === "function") window.refreshProfileResumeBtn();
      return true;
    }
    return false;
  } catch {
    return false;
  }
}

function isProfilePage() {
  return !!document.getElementById("editResumeFile");
}

function promptAddResume() {
  closeReferralModal();
  const msgEl = document.getElementById("addResumeMsg");
  if (msgEl) {
    msgEl.textContent = isProfilePage()
      ? "Please edit your profile and upload a resume before sending a referral request."
      : "Please upload a resume on your Profile page before sending a referral request.";
  }
  openAddResumeModal();
}

function openAddResumeModal() {
  const modal = document.getElementById("addResumeModal");
  if (modal) {
    modal.classList.remove("hidden");
    modal.classList.add("flex");
  }
}

function closeAddResumeModal() {
  const modal = document.getElementById("addResumeModal");
  if (modal) {
    modal.classList.add("hidden");
    modal.classList.remove("flex");
  }
}

function addResumePrimaryAction() {
  closeAddResumeModal();
  if (typeof window.enableProfileEdit === "function") {
    window.enableProfileEdit();
  } else {
    window.location.href = "profile.html";
  }
}

async function sendReferralRequest(btn, toEmail, toName, message, msgBox) {
  const profile = getProfile();

  let hasDefaultResume = true;
  try {
    const r = await fetch(`/api/profile?email=${encodeURIComponent(profile.email)}`);
    const d = await r.json();
    if (d && d.email) {
      setProfile(d);
      hasDefaultResume = !!(d.resume_filename || "");
    }
  } catch {
    hasDefaultResume = true;
  }

  if (!hasDefaultResume) {
    const resumeText = getResumeText();
    if (isProfilePage() || !resumeText) {
      promptAddResume();
      return;
    }
    const useIt = await openResumePromptModal();
    if (!useIt) {
      promptAddResume();
      return;
    }
    const uploaded = await uploadDefaultResume(resumeText);
    if (!uploaded) {
      showToast("Failed to set your default resume. Please try again.");
      return;
    }
    showToast("Default resume set");
  }

  btn.disabled = true;
  btn.textContent = "Sending...";
  fetch("/api/referrals/request", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      from_email: profile.email,
      to_email: toEmail,
      job_url: window._referralJobUrl || "",
      job_title: window._referralJobTitle || "",
      company: _referralCompany,
      match_score: window._referralMatchScore || 0,
      message: message,
      job_description: typeof window.getReferralJobDescription === "function"
        ? (window.getReferralJobDescription(window._referralJobUrl || "") || "")
        : (window._referralJobDescription || ""),
      resume_text: getResumeText(),
    }),
  }).then(r => r.json()).then(d => {
    if (d.ok) {
      showToast(`Referral request sent to ${toName}!`);
      btn.textContent = "Withdraw";
      btn.onclick = function () { withdrawReferralRequest(d.id, btn, toEmail, toName); };
      btn.disabled = false;
      btn.className = "text-xs font-medium text-red-600 bg-red-50 hover:bg-red-100 px-3 py-1.5 rounded-lg transition-colors";
      if (msgBox) msgBox.remove();
      refreshReferralRemaining();
      if (typeof window.loadSavedJobs === "function") {
        window.loadSavedJobs().catch(() => {});
      }
    } else {
      showToast(d.error || "Failed to send request");
      btn.disabled = false;
      btn.textContent = "Ask for Referral";
    }
  }).catch((err) => {
    console.error("askReferral error:", err);
    showToast("Network error");
    btn.disabled = false;
    btn.textContent = "Ask for Referral";
  });
}

function withdrawReferralRequest(id, btn, toEmail, toName) {
  if (!confirm("Withdraw this referral request?")) return;
  btn.disabled = true;
  btn.textContent = "Withdrawing...";
  fetch(`/api/referrals/${id}/withdraw`, {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: getProfile().email }),
  }).then(r => {
    console.log("withdraw response status:", r.status);
    return r.json();
  }).then(d => {
    console.log("withdraw response data:", d);
    if (d.ok) {
      showToast("Referral withdrawn");
      refreshReferralRemaining();
      _companyUserCache[_referralCompany] = null;
      showReferralUsers(_referralCompany);
      loadReferrals();
    } else {
      showToast(d.error || "Failed to withdraw");
      btn.disabled = false;
      btn.textContent = "Withdraw";
    }
  }).catch((err) => {
    console.error("withdrawReferralRequest error:", err);
    showToast("Network error");
    btn.disabled = false;
    btn.textContent = "Withdraw";
  });
}

// ── Referral Dashboard ──

function switchReferralTab(tab) {
  _referralTab = tab;
  const tabs = ["incoming", "outgoing", "accepted", "declined"];
  tabs.forEach(t => {
    const el = document.getElementById("tab" + t.charAt(0).toUpperCase() + t.slice(1));
    el.className = tab === t
      ? "tab-btn px-4 py-2 rounded-lg text-sm font-semibold bg-indigo-50 text-indigo-700 transition-colors flex items-center gap-2 whitespace-nowrap"
      : "tab-btn px-4 py-2 rounded-lg text-sm font-medium text-slate-500 hover:bg-slate-50 transition-colors flex items-center gap-2 whitespace-nowrap";
  });
  loadReferrals();
}

async function loadReferrals() {
  const profile = getProfile();
  if (!profile) return;
  const el = document.getElementById("referralListContainer");
  const setCount = (id, n) => { const e = document.getElementById(id); if (e) e.textContent = n; };

  el.innerHTML = `
    <div class="flex flex-col items-center justify-center py-12 gap-3 text-slate-400">
      <svg class="w-6 h-6 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
      <p class="text-sm">Loading referral requests...</p>
    </div>`;

  try {
    const [inc, out] = await Promise.all([
      fetch(`/api/referrals/incoming?email=${encodeURIComponent(profile.email)}`, { cache: "no-cache" }).then(r => r.json()),
      fetch(`/api/referrals/outgoing?email=${encodeURIComponent(profile.email)}`, { cache: "no-cache" }).then(r => r.json()),
    ]);
    const incReqs = (inc.requests || []).map(r => ({ ...r, _direction: "from" }));
    const outReqs = (out.requests || []).map(r => ({ ...r, _direction: "to" }));
    const allReqs = [...incReqs, ...outReqs];

    setCount("incomingCount", allReqs.filter(r => r._direction === "from" && r.status === "pending").length);
    setCount("outgoingCount", allReqs.filter(r => r._direction === "to" && r.status === "pending").length);
    setCount("acceptedCount", allReqs.filter(r => r.status === "accepted").length);
    setCount("declinedCount", allReqs.filter(r => r.status === "declined").length);

    let reqs;
    if (_referralTab === "incoming") {
      reqs = allReqs.filter(r => r._direction === "from" && r.status === "pending");
    } else if (_referralTab === "outgoing") {
      reqs = allReqs.filter(r => r._direction === "to" && (r.status === "pending" || r.status === "cancelled"));
    } else if (_referralTab === "accepted") {
      reqs = allReqs.filter(r => r.status === "accepted");
    } else {
      reqs = allReqs.filter(r => r.status === "declined");
    }
    reqs.sort((a, b) => (b.updated_at || b.created_at || "").localeCompare(a.updated_at || a.created_at || ""));

    const statEl = document.getElementById("statReferrals");
    if (statEl) statEl.textContent = reqs.length;

    const emptyStates = {
      incoming: ["No pending requests", "When someone asks you for a referral, it will show up here."],
      outgoing: ["No sent requests", "Requests you send to people at a company will appear here."],
      accepted: ["No accepted referrals", "Accepted referral requests will appear here."],
      declined: ["No declined referrals", "Declined referral requests will appear here."],
    };
    const es = emptyStates[_referralTab] || emptyStates.incoming;

    if (reqs.length === 0) {
      el.innerHTML = `<div class="text-center py-12 px-4 bg-white rounded-2xl border border-slate-200 border-dashed">
        <div class="w-12 h-12 bg-slate-50 rounded-full flex items-center justify-center mx-auto mb-3">
          <svg class="w-6 h-6 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z"/></svg>
        </div>
        <p class="text-sm font-medium text-slate-600">${es[0]}</p>
        <p class="text-xs text-slate-400 mt-1">${es[1]}</p>
      </div>`;
      return;
    }

    const nameColors = [
      "bg-red-100 text-red-600", "bg-indigo-100 text-indigo-600",
      "bg-emerald-100 text-emerald-600", "bg-amber-100 text-amber-600",
      "bg-violet-100 text-violet-600", "bg-cyan-100 text-cyan-600",
      "bg-pink-100 text-pink-600",
    ];

    const STATUS_META = {
      pending: { label: "Pending", cls: "bg-amber-50 text-amber-700" },
      accepted: { label: "Accepted", cls: "bg-emerald-50 text-emerald-700" },
      declined: { label: "Declined", cls: "bg-red-50 text-red-700" },
      cancelled: { label: "Withdrawn", cls: "bg-slate-100 text-slate-600" },
    };

    const scorePillCls = s => s >= 70 ? "from-emerald-500 to-teal-600" : s >= 50 ? "from-amber-500 to-orange-500" : "from-slate-400 to-slate-600";

    const cooldownNote = (r) => {
      if (!r.accepted_at) return "";
      const elapsed = (Date.now() - new Date(r.accepted_at).getTime()) / 1000;
      if (elapsed >= REFERRAL_COOLDOWN) return "";
      const left = REFERRAL_COOLDOWN - elapsed;
      const h = Math.floor(left / 3600);
      const m = Math.floor((left % 3600) / 60);
      return `<p class="text-xs text-slate-400 font-medium inline-flex items-center gap-1.5">
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
        Ready to confirm in ${h}h ${m}m
      </p>`;
    };

    const buildCard = (r) => {
      const isIncoming = _referralTab === "incoming" || r._direction === "from";
      const name = isIncoming ? (r.from_name || "Unknown") : (r.to_name || "Unknown");
      const nc = nameColors[name.length % nameColors.length];
      const sm = STATUS_META[r.status] || { label: r.status, cls: "bg-slate-100 text-slate-600" };
      const dirCls = isIncoming ? "bg-indigo-50 text-indigo-600" : "bg-slate-100 text-slate-600";
      const dirLabel = isIncoming ? "Received" : "Sent";

      let actions = "";
      if (_referralTab === "incoming" && r.status === "pending") {
        actions = `
          <div class="flex items-center gap-2">
            <button class="inline-flex items-center gap-1.5 text-xs font-semibold text-white bg-emerald-600 hover:bg-emerald-700 px-3.5 py-2 rounded-lg transition-colors shadow-sm accept-referral-btn" data-id="${r.id}">
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5"/></svg>
              Accept
            </button>
            <button class="inline-flex items-center gap-1.5 text-xs font-semibold text-red-600 bg-red-50 hover:bg-red-100 px-3 py-1.5 rounded-lg transition-colors decline-referral-btn" data-id="${r.id}">
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>
              Decline
            </button>
          </div>`;
      }
      if (_referralTab === "outgoing" && r.status === "pending") {
        actions = `<button class="inline-flex items-center gap-1.5 text-xs font-semibold text-red-600 bg-red-50 hover:bg-red-100 px-3 py-1.5 rounded-lg transition-colors withdraw-referral-btn" data-id="${r.id}">
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>
          Withdraw request
        </button>`;
      } else if (_referralTab === "outgoing" && r.status === "cancelled") {
        _referralCompany = r.company || "";
        actions = `<button class="inline-flex items-center gap-1.5 text-xs font-semibold text-indigo-600 bg-indigo-50 hover:bg-indigo-100 px-3 py-1.5 rounded-lg transition-colors referral-ask-btn" data-email="${htmlEscape(r.to_email || '')}" data-name="${htmlEscape(r.to_name || '')}" data-job-url="${htmlEscape(r.job_url || '')}" data-job-title="${htmlEscape(r.job_title || '')}" data-company="${htmlEscape(r.company || '')}">
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15"/></svg>
          Ask again
        </button>`;
      }
      if (_referralTab === "accepted" && isIncoming) {
        if (r.credit_awarded) {
          actions = `<p class="text-xs text-emerald-600 font-semibold inline-flex items-center gap-1.5"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5"/></svg>Referred — +10 credits earned</p>`;
        } else if (r.receiver_confirmed) {
          actions = `<p class="text-xs text-slate-500 font-medium inline-flex items-center gap-1.5"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>You've confirmed. Waiting for the sender to confirm...</p>`;
        } else {
          actions = cooldownNote(r) || `<button class="inline-flex items-center gap-1.5 text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-700 px-3.5 py-2 rounded-lg transition-colors shadow-sm complete-referral-btn" data-id="${r.id}">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5"/></svg>
            Mark as Referred (+10 credits)
          </button>`;
        }
      }
      if (_referralTab === "accepted" && !isIncoming) {
        if (r.credit_awarded) {
          actions = `<p class="text-xs text-emerald-600 font-semibold inline-flex items-center gap-1.5"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5"/></svg>Referred — +10 credits earned</p>`;
        } else if (r.sender_confirmed) {
          actions = `<p class="text-xs text-slate-500 font-medium inline-flex items-center gap-1.5"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>You've confirmed. Waiting for the receiver to confirm...</p>`;
        } else {
          actions = cooldownNote(r) || `<button class="inline-flex items-center gap-1.5 text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-700 px-3.5 py-2 rounded-lg transition-colors shadow-sm sender-confirm-referral-btn" data-id="${r.id}">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5"/></svg>
            Confirm Referred
          </button>`;
        }
      }

      const dateLabel = r.status === "cancelled" ? "Withdrawn" : r.status === "pending" ? "Asked" : r.status === "accepted" ? "Accepted" : "Declined";
      const dateStr = r.updated_at || r.created_at;

      const scorePill = r.match_score > 0 ? `
        <span class="inline-flex items-center justify-center min-w-[2.75rem] px-2.5 py-1 rounded-lg text-xs font-bold text-white shadow-sm bg-gradient-to-r ${scorePillCls(r.match_score)}">${Math.round(r.match_score)}%</span>` : "";

      const contactBox = r.status === "accepted" ? `
        <div class="mt-3 rounded-xl bg-gradient-to-r from-indigo-50 to-violet-50 border border-indigo-100 p-3 space-y-2">
          <div class="flex items-center gap-2">
            <span class="text-[11px] font-bold uppercase tracking-wider text-indigo-500">${isIncoming ? "Contact unlocked" : "Receiver info"}</span>
            <svg class="w-3.5 h-3.5 text-indigo-400" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z" clip-rule="evenodd"/></svg>
          </div>
          ${isIncoming ? `
            <div class="flex flex-wrap items-center gap-2">
              <span class="text-sm font-medium text-slate-700">${htmlEscape(r.from_email)}</span>
              <button class="inline-flex items-center gap-1 text-[11px] font-semibold text-indigo-600 bg-white border border-indigo-200 hover:bg-indigo-50 px-2 py-1 rounded-md transition-colors copy-ref-email-btn" data-email="${htmlEscape(r.from_email)}">Copy</button>
            </div>
            ${r.from_company || r.from_position ? `<p class="text-xs text-slate-500">${[r.from_position, r.from_company].filter(Boolean).join(" at ")}</p>` : ""}
            <div class="flex flex-wrap gap-3 pt-1">
              ${r.from_linkedin_url ? `<a href="${htmlEscape(r.from_linkedin_url)}" target="_blank" class="text-xs text-indigo-600 hover:underline inline-flex items-center gap-1"><svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24"><path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/></svg>LinkedIn</a>` : ""}
              ${r.from_resume_filename ? `<a href="/api/profile/resume?email=${encodeURIComponent(r.from_email)}" class="text-xs text-indigo-600 hover:underline inline-flex items-center gap-1"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>Resume</a>` : ""}
            </div>` : `
            <div class="flex flex-wrap items-center gap-2">
              <span class="text-sm font-medium text-slate-700">${htmlEscape(r.to_email)}</span>
              <button class="inline-flex items-center gap-1 text-[11px] font-semibold text-indigo-600 bg-white border border-indigo-200 hover:bg-indigo-50 px-2 py-1 rounded-md transition-colors copy-ref-email-btn" data-email="${htmlEscape(r.to_email)}">Copy</button>
            </div>
            ${r.to_linkedin_url ? `<div class="flex flex-wrap gap-3 pt-1"><a href="${htmlEscape(r.to_linkedin_url)}" target="_blank" class="text-xs text-indigo-600 hover:underline inline-flex items-center gap-1"><svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24"><path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/></svg>LinkedIn</a></div>` : ""}` }
        </div>` : "";

      return `
      <div class="bg-white border border-slate-200 rounded-2xl p-4 sm:p-5 hover:border-indigo-300 hover:shadow-md transition-all">
        <div class="flex items-start justify-between gap-3">
          <div class="flex items-center gap-3 min-w-0 flex-1">
            <div class="w-10 h-10 rounded-xl ${nc} flex items-center justify-center font-bold text-lg shrink-0">${htmlEscape(name.charAt(0).toUpperCase())}</div>
            <div class="min-w-0">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="font-semibold text-slate-900 text-sm">${htmlEscape(name)}</span>
                <span class="text-[11px] font-semibold px-2 py-0.5 rounded-lg ${sm.cls}">${sm.label}</span>
                <span class="text-[11px] font-semibold px-2 py-0.5 rounded-lg ${dirCls}">${dirLabel}</span>
              </div>
              <div class="mt-2 space-y-1.5">
                <div class="flex items-center gap-2 flex-wrap">
                  <p class="text-sm font-semibold text-slate-900">${htmlEscape(r.job_title || "Job at " + r.company)}</p>
                  ${scorePill}
                </div>
                <div class="flex items-center gap-2 flex-wrap text-xs">
                  ${r.company ? `<span class="text-slate-500">${htmlEscape(r.company)}</span>` : ""}
                  ${r.job_url ? `<a href="${htmlEscape(r.job_url)}" target="_blank" class="text-indigo-600 hover:underline inline-flex items-center gap-1"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>View Job Posting</a>` : ""}
                </div>
              </div>
              ${r.message ? `<p class="mt-2 rounded-lg bg-indigo-50/70 border border-indigo-100 px-3 py-2 text-xs text-slate-600">${htmlEscape(r.message)}</p>` : ""}
              ${contactBox}
            </div>
          </div>
          <div class="flex flex-col items-end gap-2 shrink-0">
            <span class="text-[11px] text-slate-400 whitespace-nowrap">${dateLabel} ${dateStr ? formatDate(dateStr) : ""}</span>
          </div>
        </div>
        ${actions ? `<div class="mt-3 pt-3 border-t border-slate-100 flex items-center justify-between gap-2 flex-wrap">${actions}</div>` : ""}
      </div>`;
    };

    if (_referralTab === "accepted" || _referralTab === "declined") {
      const received = reqs.filter(r => r._direction === "from");
      const sent = reqs.filter(r => r._direction === "to");
      const parts = [];
      if (received.length) {
        parts.push(`<h4 class="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-2"><span class="inline-block w-1.5 h-1.5 rounded-full bg-indigo-400"></span>Received</h4>`);
        parts.push(received.map(buildCard).join(""));
      }
      if (sent.length) {
        if (received.length) parts.push(`<div class="mt-6 pt-4 border-t border-slate-100"></div>`);
        parts.push(`<h4 class="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-2"><span class="inline-block w-1.5 h-1.5 rounded-full bg-slate-300"></span>Sent</h4>`);
        parts.push(sent.map(buildCard).join(""));
      }
      el.innerHTML = parts.join("");
    } else {
      el.innerHTML = reqs.map(buildCard).join("");
    }
  } catch (e) {
    el.innerHTML = `<div class="text-center text-sm text-slate-400 py-8">Failed to load referrals</div>`;
  }
}

async function acceptReferral(id) {
  const profile = getProfile();
  if (!profile) return;
  try {
    const r = await fetch(`/api/referrals/${id}/accept`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: profile.email }),
    });
    const d = await r.json();
    if (d.ok && d.contact) {
      showToast(`Contact revealed: ${d.contact.email}`);
      loadReferrals();
    }
  } catch (e) {
    showToast("Failed to accept");
  }
}

async function declineReferral(id) {
  const profile = getProfile();
  if (!profile) return;
  try {
    const r = await fetch(`/api/referrals/${id}/decline`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: profile.email }),
    });
    const d = await r.json();
    if (d.ok) {
      showToast("Referral declined");
      loadReferrals();
    }
  } catch (e) {
    showToast("Failed to decline");
  }
}

async function completeReferral(id) {
  const profile = getProfile();
  if (!profile) return;
  if (!confirm("Have you submitted the referral for this person? You can't undo this.")) return;
  try {
    const r = await fetch(`/api/referrals/${id}/complete`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: profile.email }),
    });
    const d = await r.json();
    if (d.ok) {
      if (d.credits_awarded) {
        showToast("Both confirmed! +10 credits earned");
        window.loadProfile();
      } else {
        showToast("You've confirmed. Waiting for sender...");
      }
      loadReferrals();
    } else {
      showToast(d.error || "Failed");
    }
  } catch (e) {
    showToast("Network error");
  }
}

async function senderConfirmReferral(id) {
  const profile = getProfile();
  if (!profile) return;
  if (!confirm("Confirm that this person referred you? You can't undo this.")) return;
  try {
    const r = await fetch(`/api/referrals/${id}/confirm`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: profile.email }),
    });
    const d = await r.json();
    if (d.ok) {
      if (d.credits_awarded) {
        showToast("Both confirmed! +10 credits earned");
        window.loadProfile();
      } else {
        showToast("You've confirmed. Waiting for receiver...");
      }
      loadReferrals();
    } else {
      showToast(d.error || "Failed");
    }
  } catch (e) {
    showToast("Network error");
  }
}

function copyRefEmail(btn, email) {
  if (!email) return;
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(email).then(() => {
      const orig = btn.textContent;
      btn.textContent = "Copied!";
      setTimeout(() => { btn.textContent = orig; }, 1500);
    }).catch(() => {
      const orig = btn.textContent;
      btn.textContent = "Copied!";
      setTimeout(() => { btn.textContent = orig; }, 1500);
    });
  } else {
    const orig = btn.textContent;
    btn.textContent = "Copied!";
    setTimeout(() => { btn.textContent = orig; }, 1500);
  }
}

async function withdrawReferral(id) {
  const profile = getProfile();
  if (!profile) return;
  if (!confirm("Withdraw this referral request?")) return;
  try {
    const r = await fetch(`/api/referrals/${id}/withdraw`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: profile.email }),
    });
    const d = await r.json();
    if (d.ok) {
      showToast("Referral withdrawn");
      loadReferrals();
      refreshReferralRemaining();
    } else {
      showToast(d.error || "Failed to withdraw");
    }
  } catch (e) {
    console.error("withdrawReferral error:", e);
    showToast("Network error");
  }
}

// ── Event delegation for data-attribute buttons ──
document.addEventListener("click", (e) => {
  const signinBtn = e.target.closest(".referral-signin-btn");
  if (signinBtn) { closeReferralModal(); window.showAuthModal(); return; }
  const askBtn = e.target.closest(".referral-ask-btn");
  if (askBtn) {
    e.preventDefault();
    if (askBtn.dataset.jobUrl) window._referralJobUrl = askBtn.dataset.jobUrl;
    if (askBtn.dataset.jobTitle) window._referralJobTitle = askBtn.dataset.jobTitle;
    if (askBtn.dataset.company) _referralCompany = askBtn.dataset.company;
    window._referralMatchScore = 0;
    window._referralJobDescription = '';
    askReferral(askBtn, askBtn.dataset.email, askBtn.dataset.name);
    return;
  }
  const withdrawBtn = e.target.closest(".referral-withdraw-btn");
  if (withdrawBtn) { withdrawReferralRequest(parseInt(withdrawBtn.dataset.id), withdrawBtn, withdrawBtn.dataset.email, withdrawBtn.dataset.name); return; }
  const acceptBtn = e.target.closest(".accept-referral-btn");
  if (acceptBtn) { acceptReferral(parseInt(acceptBtn.dataset.id)); return; }
  const declineBtn = e.target.closest(".decline-referral-btn");
  if (declineBtn) { declineReferral(parseInt(declineBtn.dataset.id)); return; }
  const withdrawRefBtn = e.target.closest(".withdraw-referral-btn");
  if (withdrawRefBtn) { withdrawReferral(parseInt(withdrawRefBtn.dataset.id)); return; }
  const completeBtn = e.target.closest(".complete-referral-btn");
  if (completeBtn) { completeReferral(parseInt(completeBtn.dataset.id)); return; }
  const senderBtn = e.target.closest(".sender-confirm-referral-btn");
  if (senderBtn) { senderConfirmReferral(parseInt(senderBtn.dataset.id)); return; }
  const copyBtn = e.target.closest(".copy-ref-email-btn");
  if (copyBtn) { copyRefEmail(copyBtn, copyBtn.dataset.email); return; }
});

window.closeReferralModal = closeReferralModal;
window.closeResumePromptModal = closeResumePromptModal;
window.setDefaultResumeChoice = setDefaultResumeChoice;
window.closeAddResumeModal = closeAddResumeModal;
window.addResumePrimaryAction = addResumePrimaryAction;
window.refreshReferralRemaining = refreshReferralRemaining;
window.showReferralUsers = showReferralUsers;
window.askReferral = askReferral;
window.withdrawReferralRequest = withdrawReferralRequest;
window.switchReferralTab = switchReferralTab;
window.loadReferrals = loadReferrals;
window.acceptReferral = acceptReferral;
window.declineReferral = declineReferral;
window.completeReferral = completeReferral;
window.senderConfirmReferral = senderConfirmReferral;
window.withdrawReferral = withdrawReferral;
window.copyRefEmail = copyRefEmail;
window.loadCompanyUserCounts = loadCompanyUserCounts;
window.refreshCompanyUser = refreshCompanyUser;
window.checkReferralNotifications = checkReferralNotifications;
window.openReferralUrlModal = openReferralUrlModal;
window.closeReferralUrlModal = closeReferralUrlModal;
window.submitReferralUrlResolve = submitReferralUrlResolve;
window.proceedFromUrlToReferrers = proceedFromUrlToReferrers;
window.inviteReferrer = inviteReferrer;
window.notifyWhenAvailable = notifyWhenAvailable;

export { loadReferrals, refreshReferralRemaining, loadCompanyUserCounts, refreshCompanyUser, checkReferralNotifications };
