import { getProfile, showToast, htmlEscape, formatDate } from "./utils.js";
import { _MONTHLY_LIMIT } from "./constants.js";

// Referral Modal state
let _referralCompany = "";
let _referralJobTitle = "";
let _referralMatchScore = 0;
let _referralJobUrl = "";
let _companyUserCache = {};

// Referral Dashboard state
let _referralTab = "incoming";

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
  if (users.length === 0 && !profile) {
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
      <p class="text-sm font-medium text-slate-600">No one from ${htmlEscape(company)} on the platform yet</p>
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
      req.to_email === u.email && req.job_url === _referralJobUrl
    );
    let btnHtml = "";
    if (!profile) {
      btnHtml = `<button class="text-xs font-medium text-slate-400 bg-slate-50 px-3 py-1.5 rounded-lg" onclick="closeReferralModal(); showAuthModal()">Sign in to ask</button>`;
    } else if (existing && existing.status === "pending") {
      btnHtml = `<button class="text-xs font-medium text-red-600 bg-red-50 hover:bg-red-100 px-3 py-1.5 rounded-lg transition-colors" onclick="withdrawReferralRequest(${existing.id}, this, '${u.email.replace(/'/g, "\\'")}', '${u.name.replace(/'/g, "\\'")}')">Withdraw</button>`;
    } else if (existing && existing.status === "cancelled") {
      btnHtml = `<button class="text-xs font-medium text-indigo-600 bg-indigo-50 hover:bg-indigo-100 px-3 py-1.5 rounded-lg transition-colors" onclick="askReferral(this, '${u.email.replace(/'/g, "\\'")}', '${u.name.replace(/'/g, "\\'")}')">Ask for Referral</button>`;
    } else if (existing) {
      btnHtml = `<span class="text-xs font-medium text-slate-400 px-3 py-1.5">${existing.status}</span>`;
    } else {
      btnHtml = `<button class="text-xs font-medium text-indigo-600 bg-indigo-50 hover:bg-indigo-100 px-3 py-1.5 rounded-lg transition-colors" onclick="askReferral(this, '${u.email.replace(/'/g, "\\'")}', '${u.name.replace(/'/g, "\\'")}')">Ask for Referral</button>`;
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

function askReferral(btn, toEmail, toName) {
  const profile = getProfile();
  if (!profile) { closeReferralModal(); window.showAuthModal(); return; }
  if (toEmail === profile.email) {
    showToast("You can't refer yourself");
    return;
  }
  if (!confirm(`Send referral request to ${toName}?`)) return;
  btn.disabled = true;
  btn.textContent = "Sending...";
  fetch("/api/referrals/request", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      from_email: profile.email,
      to_email: toEmail,
      job_url: _referralJobUrl || "",
      job_title: _referralJobTitle || "",
      company: _referralCompany,
      match_score: _referralMatchScore || 0,
    }),
  }).then(r => r.json()).then(d => {
    if (d.ok) {
      showToast(`Referral request sent to ${toName}!`);
      btn.textContent = "Withdraw";
      btn.onclick = function () { withdrawReferralRequest(d.id, btn, toEmail, toName); };
      btn.disabled = false;
      btn.className = "text-xs font-medium text-red-600 bg-red-50 hover:bg-red-100 px-3 py-1.5 rounded-lg transition-colors";
      refreshReferralRemaining();
    } else {
      showToast(d.error || "Failed to send request");
      btn.disabled = false;
      btn.textContent = "Ask for Referral";
    }
  }).catch(() => {
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
  }).then(r => r.json()).then(d => {
    if (d.ok) {
      showToast("Referral withdrawn");
      refreshReferralRemaining();
      if (toEmail && toName) {
        btn.textContent = "Ask for Referral";
        btn.onclick = function () { askReferral(btn, toEmail, toName); };
        btn.disabled = false;
        btn.className = "text-xs font-medium text-indigo-600 bg-indigo-50 hover:bg-indigo-100 px-3 py-1.5 rounded-lg transition-colors";
      } else {
        loadReferrals();
      }
    } else {
      showToast(d.error || "Failed to withdraw");
      btn.disabled = false;
      btn.textContent = "Withdraw";
    }
  }).catch(() => {
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
  try {
    let reqs = [];

    if (_referralTab === "incoming" || _referralTab === "outgoing") {
      const r = await fetch(`/api/referrals/${_referralTab}?email=${encodeURIComponent(profile.email)}`);
      const d = await r.json();
      reqs = (d.requests || []).filter(r => r.status === "pending");
    } else {
      const [inc, out] = await Promise.all([
        fetch(`/api/referrals/incoming?email=${encodeURIComponent(profile.email)}`).then(r => r.json()),
        fetch(`/api/referrals/outgoing?email=${encodeURIComponent(profile.email)}`).then(r => r.json()),
      ]);
      const incReqs = (inc.requests || []).map(r => ({ ...r, _direction: "from" }));
      const outReqs = (out.requests || []).map(r => ({ ...r, _direction: "to" }));
      if (_referralTab === "accepted") {
        reqs = [...incReqs, ...outReqs].filter(r => r.status === "accepted");
      } else {
        reqs = [...incReqs, ...outReqs].filter(r => r.status === "declined" || r.status === "cancelled");
      }
      reqs.sort((a, b) => (b.updated_at || b.created_at || "").localeCompare(a.updated_at || a.created_at || ""));
    }

    const countMap = {
      incoming: "incomingCount",
      outgoing: "outgoingCount",
      accepted: "acceptedCount",
      declined: "declinedCount",
    };
    const countEl = document.getElementById(countMap[_referralTab]);
    if (countEl) countEl.textContent = reqs.length;

    const statEl = document.getElementById("statReferrals");
    if (statEl) statEl.textContent = reqs.length;

    if (reqs.length === 0) {
      el.innerHTML = `<div class="text-center py-12 px-4 bg-white rounded-2xl border border-slate-200 border-dashed">
        <div class="w-12 h-12 bg-slate-50 rounded-full flex items-center justify-center mx-auto mb-3">
          <svg class="w-6 h-6 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z"/></svg>
        </div>
        <p class="text-sm font-medium text-slate-500">No ${_referralTab} requests</p>
      </div>`;
      return;
    }

    const nameColors = [
      "bg-red-100 text-red-600", "bg-indigo-100 text-indigo-600",
      "bg-emerald-100 text-emerald-600", "bg-amber-100 text-amber-600",
      "bg-violet-100 text-violet-600", "bg-cyan-100 text-cyan-600",
      "bg-pink-100 text-pink-600",
    ];

    const buildCard = (r) => {
      const isIncoming = _referralTab === "incoming" || r._direction === "from";
      const name = isIncoming ? (r.from_name || "Unknown") : (r.to_name || "Unknown");
      const nc = nameColors[name.length % nameColors.length];

      const statusColors = {
        pending: "bg-amber-50 text-amber-700",
        accepted: "bg-emerald-50 text-emerald-700",
        declined: "bg-red-50 text-red-700",
      };
      const sc = statusColors[r.status] || "bg-slate-100 text-slate-600";

      let actions = "";
      if (_referralTab === "incoming" && r.status === "pending") {
        actions = `
          <div class="flex gap-2">
            <button class="inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-700 bg-emerald-50 hover:bg-emerald-100 px-3 py-1.5 rounded-lg transition-colors" onclick="acceptReferral(${r.id})">
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5"/></svg>
              Accept
            </button>
            <button class="inline-flex items-center gap-1.5 text-xs font-semibold text-red-600 bg-red-50 hover:bg-red-100 px-3 py-1.5 rounded-lg transition-colors" onclick="declineReferral(${r.id})">
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>
              Decline
            </button>
          </div>`;
      }
      if (_referralTab === "outgoing" && r.status === "pending") {
        actions = `<button class="inline-flex items-center gap-1.5 text-xs font-semibold text-red-600 bg-red-50 hover:bg-red-100 px-3 py-1.5 rounded-lg transition-colors" onclick="withdrawReferral(${r.id})">
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>
          Withdraw
        </button>`;
      }
      if (_referralTab === "accepted" && isIncoming) {
        if (r.credit_awarded) {
          actions = `<p class="text-xs text-emerald-600 font-semibold inline-flex items-center gap-1"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5"/></svg>Referred — 10 credits earned</p>`;
        } else if (r.receiver_confirmed) {
          actions = `<p class="text-xs text-slate-500 font-medium">You've confirmed. Waiting for sender...</p>`;
        } else if (r.accepted_at && (Date.now() - new Date(r.accepted_at).getTime()) / 1000 < REFERRAL_COOLDOWN) {
          const left = REFERRAL_COOLDOWN - ((Date.now() - new Date(r.accepted_at).getTime()) / 1000);
          const h = Math.floor(left / 3600);
          const m = Math.floor((left % 3600) / 60);
          actions = `<p class="text-xs text-slate-400 font-medium">Ready to confirm in ${h}h ${m}m</p>`;
        } else {
          actions = `<button class="inline-flex items-center gap-1.5 text-xs font-semibold text-indigo-600 bg-indigo-50 hover:bg-indigo-100 px-3 py-1.5 rounded-lg transition-colors" onclick="completeReferral(${r.id})">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5"/></svg>
            Mark as Referred (+10 credits)
          </button>`;
        }
      }
      if (_referralTab === "accepted" && !isIncoming) {
        if (r.credit_awarded) {
          actions = `<p class="text-xs text-emerald-600 font-semibold inline-flex items-center gap-1"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5"/></svg>Referred — 10 credits earned</p>`;
        } else if (r.sender_confirmed) {
          actions = `<p class="text-xs text-slate-500 font-medium">You've confirmed. Waiting for receiver...</p>`;
        } else if (r.accepted_at && (Date.now() - new Date(r.accepted_at).getTime()) / 1000 < REFERRAL_COOLDOWN) {
          const left = REFERRAL_COOLDOWN - ((Date.now() - new Date(r.accepted_at).getTime()) / 1000);
          const h = Math.floor(left / 3600);
          const m = Math.floor((left % 3600) / 60);
          actions = `<p class="text-xs text-slate-400 font-medium">Ready to confirm in ${h}h ${m}m</p>`;
        } else {
          actions = `<button class="inline-flex items-center gap-1.5 text-xs font-semibold text-indigo-600 bg-indigo-50 hover:bg-indigo-100 px-3 py-1.5 rounded-lg transition-colors" onclick="senderConfirmReferral(${r.id})">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5"/></svg>
            Confirm Referred
          </button>`;
        }
      }

      const createdLabel = r.created_at ? `<span class="text-xs text-slate-400">${formatDate(r.created_at)}</span>` : "";
      const updatedLabel = r.updated_at && r.updated_at !== r.created_at ? `<span class="text-xs text-slate-400">· ${r.status === "cancelled" ? "Withdrawn" : r.status} ${formatDate(r.updated_at)}</span>` : "";

      return `
      <div class="bg-white border border-slate-200 rounded-2xl p-4 hover:border-indigo-300 hover:shadow-md transition-all">
        <div class="flex items-start justify-between gap-3">
          <div class="flex items-start gap-3 min-w-0 flex-1">
            <div class="w-10 h-10 rounded-xl ${nc} flex items-center justify-center font-bold text-lg shrink-0">${htmlEscape(name.charAt(0).toUpperCase())}</div>
            <div class="min-w-0">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="font-semibold text-slate-900 text-sm">${htmlEscape(name)}</span>
                <span class="text-xs font-semibold px-2 py-0.5 rounded-lg ${sc}">${r.status}</span>
              </div>
              <p class="text-xs text-slate-500 mt-0.5">${htmlEscape(r.job_title || "Job at " + r.company)}</p>
              ${r.match_score ? `<p class="text-xs text-indigo-600 font-medium mt-0.5">Match score: ${r.match_score}/100</p>` : ""}
              ${r.message ? `<p class="text-xs text-slate-500 mt-1 italic">${htmlEscape(r.message)}</p>` : ""}
              <div class="flex items-center gap-1 mt-1">${createdLabel}${updatedLabel}</div>
              ${r.status === "accepted" && isIncoming ? `
              <div class="mt-2 p-3 bg-indigo-50 border border-indigo-100 rounded-xl space-y-1.5">
                <p class="text-xs font-semibold text-indigo-700">Contact revealed</p>
                <p class="text-xs text-slate-600">${htmlEscape(r.from_email)}</p>
                <div class="flex gap-3">
                  ${r.from_linkedin_url ? `<a href="${htmlEscape(r.from_linkedin_url)}" target="_blank" class="text-xs text-indigo-600 hover:underline inline-flex items-center gap-1"><svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24"><path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/></svg>LinkedIn</a>` : ""}
                  ${r.from_resume_filename ? `<a href="/api/profile/resume?email=${encodeURIComponent(r.from_email)}" class="text-xs text-indigo-600 hover:underline inline-flex items-center gap-1"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>Resume</a>` : ""}
                </div>
              </div>` : ""}
            </div>
          </div>
          ${r.match_score ? `<div class="w-9 h-9 rounded-full bg-indigo-50 border border-indigo-100 flex items-center justify-center text-sm font-bold text-indigo-600 shrink-0">${r.match_score}</div>` : ""}
        </div>
        <div class="mt-3">${actions}</div>
      </div>`;
    };

    if (_referralTab === "accepted" || _referralTab === "declined") {
      const received = reqs.filter(r => r._direction === "from");
      const sent = reqs.filter(r => r._direction === "to");
      const parts = [];
      if (received.length) {
        parts.push(`<h4 class="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Received</h4>`);
        parts.push(received.map(buildCard).join(""));
      }
      if (sent.length) {
        if (received.length) {
          parts.push(`<div class="mt-6 pt-4 border-t border-slate-100"></div>`);
        }
        parts.push(`<h4 class="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Sent</h4>`);
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
    } else {
      showToast(d.error || "Failed to withdraw");
    }
  } catch (e) {
    showToast("Network error");
  }
}

window.closeReferralModal = closeReferralModal;
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

export { loadReferrals, refreshReferralRemaining };
