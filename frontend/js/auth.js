import { DEV_MODE, EMAILJS_SERVICE_ID, EMAILJS_TEMPLATE_ID, EMAILJS_PUBLIC_KEY, _EMPLOYMENT_LABELS } from "./constants.js";
import { setProfile, showToast } from "./utils.js";

let emailjsInitialized = false;
let _authEmail = "";
let _authCompanyList = [];
const SEARCH_CACHE_KEY = "jobagent_last_search";
const _invitedBy = (new URLSearchParams(window.location.search)).get("ref") || "";
const _inviteCompany = (new URLSearchParams(window.location.search)).get("company") || "";
const _el = (id) => document.getElementById(id);

function initEmailJS() {
  if (typeof emailjs !== "undefined" && EMAILJS_PUBLIC_KEY) {
    emailjs.init(EMAILJS_PUBLIC_KEY);
    emailjsInitialized = true;
  }
}

async function sendEmailJS(templateParams) {
  if (!emailjsInitialized) {
    if (typeof emailjs !== "undefined" && EMAILJS_PUBLIC_KEY) {
      emailjs.init(EMAILJS_PUBLIC_KEY);
      emailjsInitialized = true;
    } else {
      console.warn("EmailJS not initialized.");
      return { ok: false, error: "EmailJS not configured" };
    }
  }
  try {
    const res = await emailjs.send(EMAILJS_SERVICE_ID, EMAILJS_TEMPLATE_ID, templateParams);
    return { ok: true, res };
  } catch (err) {
    return { ok: false, error: err.text || err.message };
  }
}

function _setPendingEmail(email) {
  try { sessionStorage.setItem("ja_pending_email", email); } catch (e) {}
}

function _getPendingEmail() {
  if (_authEmail) return _authEmail;
  try {
    const stored = sessionStorage.getItem("ja_pending_email");
    if (stored) return stored;
  } catch (e) {}
  const labels = [_el("modalEmail"), _el("authSentEmail")];
  for (const l of labels) {
    if (l && l.textContent.trim()) return l.textContent.trim();
  }
  const input = _el("authEmail") || _el("promptEmail");
  if (input && input.value.trim()) return input.value.trim();
  return "";
}

function _clearAuthErrors() {
  ["authSendError", "authCodeError", "authRegisterError", "authFallbackCode"].forEach(id => {
    const e = _el(id);
    if (e) e.classList.add("hidden");
  });
}

function _resetAuthSteps() {
  ["authStepEmail", "authStepCode", "authStep3", "authStep4"].forEach(id => {
    const e = _el(id);
    if (e) e.classList.add("hidden");
  });
}

function _setSentLabel(email) {
  const sent = _el("authSentEmail");
  if (sent) sent.textContent = email;
  const modal = _el("modalEmail");
  if (modal) modal.textContent = email;
}

function openAuthModal() {
  const m = _el("authModal");
  if (m) m.style.display = "flex";
}

function closeAuthModal() {
  const m = _el("authModal");
  if (m) m.style.display = "none";
  _resetAuthSteps();
  const defaultStep = _el("authStepEmail") || _el("authStepCode");
  if (defaultStep) defaultStep.classList.remove("hidden");
  _clearAuthErrors();
  const btn = _el("promptSendBtn");
  if (btn) btn.disabled = false;
  const text = _el("promptSendText");
  if (text) text.textContent = "Send Code";
  const spinner = _el("promptSendSpinner");
  if (spinner) spinner.classList.add("hidden");
  if (typeof window.onAuthModalClosed === "function") window.onAuthModalClosed();
}

function _revealCodeStep() {
  const emailStep = _el("authStepEmail");
  if (emailStep) emailStep.classList.add("hidden");
  const codeStep = _el("authStepCode");
  if (codeStep) codeStep.classList.remove("hidden");
  document.querySelectorAll("#authModal .code-digit").forEach(inp => { inp.value = ""; });
  const first = document.querySelector("#authModal .code-digit");
  if (first) setTimeout(() => first.focus(), 60);
}

function showAuthModal() {
  const m = _el("authModal");
  if (!m) return;
  const email = _getPendingEmail();
  _authEmail = email;
  const emailStep = _el("authStepEmail");
  if (emailStep) {
    _resetAuthSteps();
    _clearAuthErrors();
    emailStep.classList.remove("hidden");
    const emailInput = _el("authEmail");
    if (emailInput) { emailInput.value = email || ""; emailInput.focus(); }
    openAuthModal();
    return;
  }
  if (email) {
    _resetAuthSteps();
    _clearAuthErrors();
    _revealCodeStep();
    openAuthModal();
    return;
  }
  const card = _el("authPrompt");
  if (card) { card.classList.remove("hidden"); card.scrollIntoView({ behavior: "smooth", block: "center" }); }
  const promptEmail = _el("promptEmail");
  if (promptEmail) promptEmail.focus();
}

async function _sendCodeCore(email, btn, errEl, opts) {
  opts = opts || {};
  if (!email || !email.includes("@")) {
    if (errEl) { errEl.textContent = "Please enter a valid email address."; errEl.classList.remove("hidden"); }
    return;
  }
  if (errEl) errEl.classList.add("hidden");
  if (btn) btn.disabled = true;
  if (opts.useTextLabel !== false && btn) btn.textContent = "Sending...";
  try {
    const r = await fetch("/api/auth/send-code", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });
    const d = await r.json();
    if (!d.ok) {
      if (errEl) { errEl.textContent = d.error || "Failed to send code. Try again."; errEl.classList.remove("hidden"); }
      return;
    }
    _authEmail = email;
    _setPendingEmail(email);
    if (DEV_MODE) {
      const fc = _el("authFallbackCode");
      if (fc) { fc.textContent = `DEV code: ${d.code || ""}`; fc.classList.remove("hidden"); }
    } else if (d.fallback && d.code) {
      const emailRes = await sendEmailJS({
        email: email,
        subject: "Your Job Agent verification code",
        passcode: d.code,
      });
      if (!emailRes.ok) {
        const fc = _el("authFallbackCode");
        if (fc) {
          fc.textContent = `Email couldn't be sent (${emailRes.error}) — your code: ${d.code}`;
          fc.classList.remove("hidden");
        }
      }
    }
    _setSentLabel(email);
    _revealCodeStep();
    openAuthModal();
  } catch (e) {
    if (errEl) { errEl.textContent = "Network error. Try again."; errEl.classList.remove("hidden"); }
    console.warn("[auth] send-code error", e);
  } finally {
    if (btn) btn.disabled = false;
    if (opts.useTextLabel !== false && btn) btn.textContent = "Send Code";
    if (typeof opts.onDone === "function") opts.onDone();
  }
}

function authSendCode() {
  const emailInput = _el("authEmail");
  const email = emailInput ? emailInput.value.trim() : "";
  _sendCodeCore(email, _el("authSendBtn"), _el("authSendError"));
}

function promptSendCode() {
  const emailInput = _el("promptEmail");
  const email = emailInput ? emailInput.value.trim() : "";
  const btn = _el("promptSendBtn");
  const text = _el("promptSendText");
  const spinner = _el("promptSendSpinner");
  if (btn) btn.disabled = true;
  if (text) text.textContent = "Sending";
  if (spinner) spinner.classList.remove("hidden");
  _sendCodeCore(email, btn, _el("promptError"), {
    useTextLabel: false,
    onDone: () => {
      if (btn) btn.disabled = false;
      if (text) { text.textContent = "Send Code"; if (spinner) spinner.classList.add("hidden"); }
    },
  });
}

async function authVerifyCode() {
  const digits = document.querySelectorAll("#authModal .code-digit");
  const code = Array.from(digits).map(d => d.value).join("");
  const errEl = _el("authCodeError");
  const btn = _el("authVerifyBtn");
  if (code.length !== 6) {
    if (errEl) { errEl.textContent = "Enter the full 6-digit code."; errEl.classList.remove("hidden"); }
    return;
  }
  if (errEl) errEl.classList.add("hidden");
  const email = _getPendingEmail();
  if (!email) {
    if (errEl) { errEl.textContent = "Session expired — please request a new code."; errEl.classList.remove("hidden"); }
    console.warn("[auth] verify attempted without email");
    return;
  }
  if (btn) { btn.disabled = true; btn.textContent = "Verifying..."; }
  try {
    const r = await fetch("/api/auth/verify-code", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, code }),
    });
    const d = await r.json();
    if (!d.ok) {
      if (errEl) { errEl.textContent = d.error || "Invalid code. Try again."; errEl.classList.remove("hidden"); }
      return;
    }
    try { sessionStorage.removeItem("ja_pending_email"); } catch (e) {}
    const codeStep = _el("authStepCode");
    if (codeStep) codeStep.classList.add("hidden");
    if (d.user.company) {
      setProfile({
        email: d.user.email,
        name: d.user.name || d.user.email.split("@")[0],
        company: d.user.company,
        position: d.user.position || "",
        linkedin_url: d.user.linkedin_url || "",
        referral_credits: d.user.referral_credits || 0,
        refer_opt_in: d.user.refer_opt_in || 0,
      });
      if (typeof window.afterAuthConnected === "function") {
        window.afterAuthConnected();
        const s3 = _el("authStep3");
        if (s3) {
          s3.classList.remove("hidden");
          if (typeof window.updateProfileIcon === "function") window.updateProfileIcon();
          if (typeof window.refreshProfileResumeBtn === "function") window.refreshProfileResumeBtn();
          setTimeout(() => closeAuthModal(), 500);
        }
      } else {
        closeAuthModal();
        if (typeof window.loadProfile === "function") window.loadProfile();
        showToast("Successfully signed in");
      }
    } else {
      const s3 = _el("authStep3");
      if (s3) s3.classList.add("hidden");
      const s4 = _el("authStep4");
      if (s4) {
        s4.classList.remove("hidden");
        const nm = _el("authName");
        if (nm) { nm.value = d.user.name || d.user.email.split("@")[0]; nm.focus(); }
        prefillInviteDetails();
      }
    }
  } catch (e) {
    if (errEl) { errEl.textContent = "Network error. Try again."; errEl.classList.remove("hidden"); }
    console.warn("[auth] verify error", e);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "Verify"; }
  }
}

function selectEmploymentStatus(status) {
  document.querySelectorAll("#authStep4 .employment-pill").forEach(p => p.classList.remove("active-pill"));
  const pill = document.querySelector(`#authStep4 .employment-pill[data-status="${status}"]`);
  if (pill) pill.classList.add("active-pill");
  const group = _el("authCompanyGroup");
  if (group) {
    group.classList.toggle("hidden", status !== "employed");
    if (status !== "employed") {
      const c = _el("authCompany");
      if (c) c.value = "";
    }
  }
}

function prefillInviteDetails(done) {
  // When arriving via /app?ref=<email>&company=X, prefill company + show invite notice.
  if (_inviteCompany) {
    const c = _el("authCompany");
    if (c) c.value = _inviteCompany;
    document.querySelectorAll("#authStep4 .employment-pill").forEach(p => {
      p.classList.toggle("active-pill", p.dataset.status === "employed");
    });
    const group = _el("authCompanyGroup");
    if (group) group.classList.remove("hidden");
  }
  if (_invitedBy) {
    const inviteBanner = _el("authInviteBanner");
    if (inviteBanner) inviteBanner.classList.remove("hidden");
  }
  if (done) done();
}

async function loadAuthCompanyList() {
  if (_authCompanyList.length > 0) return;
  try {
    const r = await fetch("/api/auth/companies");
    const d = await r.json();
    _authCompanyList = d.companies || [];
  } catch (e) {}
}

function filterCompanyDropdown() {
  const input = _el("authCompany");
  const dropdown = _el("companyDropdown");
  if (!input || !dropdown) return;
  const val = input.value.toLowerCase().trim();
  const matches = val ? _authCompanyList.filter(c => c.toLowerCase().includes(val)) : _authCompanyList;
  let html = matches.slice(0, 30).map(c =>
    `<div class="px-3 py-2 text-sm cursor-pointer hover:bg-indigo-50 transition-colors company-option" data-company="${c.replace(/"/g, '&quot;')}">${c.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")}</div>`
  ).join("");
  if (val && !_authCompanyList.some(c => c.toLowerCase() === val)) {
    html += `<div class="px-3 py-2 text-sm cursor-pointer text-indigo-600 border-t border-slate-100 hover:bg-indigo-50 transition-colors font-medium add-custom-company" data-company="${val.replace(/"/g, '&quot;')}">+ Add "${input.value.trim().replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")}"</div>`;
  }
  if (!html) {
    dropdown.classList.add("hidden");
    return;
  }
  dropdown.innerHTML = html;
  dropdown.classList.remove("hidden");
}

let _lastCustomCompany = "";
function addCustomCompany(name, event) {
  if (event && typeof event.stopPropagation === "function") event.stopPropagation();
  selectCompany(name);
  if (_lastCustomCompany !== name) {
    _lastCustomCompany = name;
    if (typeof showToast === "function") showToast(`Company set to ${name}`);
    fetch("/api/auth/companies", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }).catch(() => {});
  }
  if (!_authCompanyList.includes(name)) {
    _authCompanyList.push(name);
    _authCompanyList.sort();
  }
}

function selectCompany(name) {
  const company = _el("authCompany");
  if (company) company.value = name;
  const dropdown = _el("companyDropdown");
  if (dropdown) dropdown.classList.add("hidden");
}

document.addEventListener("click", function(e) {
  const dd = _el("companyDropdown");
  if (!dd) return;
  if (!e.target.closest("#authCompany") && !e.target.closest("#companyDropdown")) {
    dd.classList.add("hidden");
    return;
  }
  const opt = e.target.closest(".company-option");
  if (opt) { selectCompany(opt.dataset.company); return; }
  const addBtn = e.target.closest(".add-custom-company");
  if (addBtn) { addCustomCompany(addBtn.dataset.company, new Event("click")); }
});

async function authRegister() {
  const email = _getPendingEmail();
  if (!email) {
    const errEl = _el("authRegisterError");
    if (errEl) {
      errEl.textContent = "Session expired — please request a new code.";
      errEl.classList.remove("hidden");
    }
    console.warn("[auth] register attempted without email");
    return;
  }
  const status = document.querySelector("#authStep4 .employment-pill.active-pill")?.dataset?.status || "employed";
  const nameEl = _el("authName");
  const name = nameEl ? nameEl.value.trim() : "";
  const position = _el("authPosition") ? _el("authPosition").value.trim() : "";
  const linkedin = _el("authLinkedin") ? _el("authLinkedin").value.trim() : "";
  const btn = _el("authRegisterBtn");
  const errEl = _el("authRegisterError");
  if (errEl) errEl.classList.add("hidden");
  if (!name) {
    if (errEl) { errEl.textContent = "Please enter your name."; errEl.classList.remove("hidden"); }
    return;
  }
  let company;
  if (status === "employed") {
    const cEl = _el("authCompany");
    company = cEl ? cEl.value.trim() : "";
    if (!company) {
      if (errEl) { errEl.textContent = "Please enter your company."; errEl.classList.remove("hidden"); }
      return;
    }
  } else {
    company = _EMPLOYMENT_LABELS[status] || "";
  }
  if (btn) btn.disabled = true;
  if (btn) btn.textContent = "Saving...";
  try {
    let searchId = "";
    try {
      const raw = localStorage.getItem(SEARCH_CACHE_KEY);
      if (raw) { const s = JSON.parse(raw); if (s?.searchId) searchId = s.searchId; }
    } catch (e) {}
    const r = await fetch("/api/auth/register", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email, name, company, position,
        linkedin_url: linkedin,
        search_id: searchId,
        refer_opt_in: _el("authReferOptIn")?.checked ? 1 : 0,
        invited_by: _invitedBy || "",
      }),
    });
    const d = await r.json();
    if (!d.ok) {
      if (errEl) { errEl.textContent = d.error || "Failed to save profile."; errEl.classList.remove("hidden"); }
      return;
    }
    try { sessionStorage.removeItem("ja_pending_email"); } catch (e) {}
    setProfile(d.user);
    const resumeFile = _el("authResume")?.files?.[0];
    if (resumeFile) {
      try {
        const fd = new FormData();
        fd.append("file", resumeFile);
        await fetch(`/api/profile/resume?email=${encodeURIComponent(email)}`, { method: "POST", body: fd });
      } catch (e) {}
    }
    const s4 = _el("authStep4");
    if (s4) s4.classList.add("hidden");
    if (typeof window.afterAuthConnected === "function") {
      const s3 = _el("authStep3");
      if (s3) s3.classList.remove("hidden");
      if (typeof window.updateProfileIcon === "function") window.updateProfileIcon();
      if (typeof window.refreshProfileResumeBtn === "function") window.refreshProfileResumeBtn();
      if (_invitedBy) showToast("Welcome! You're now available for referrals — +5 credits earned");
      setTimeout(() => {
        closeAuthModal();
        if (typeof window.afterAuthConnected === "function") window.afterAuthConnected();
      }, 1000);
    } else {
      closeAuthModal();
      if (typeof window.loadProfile === "function") window.loadProfile();
      showToast(_invitedBy ? "Welcome! You're now available for referrals — +5 credits earned" : "Profile complete!");
    }
  } catch (e) {
    if (errEl) { errEl.textContent = "Network error. Try again."; errEl.classList.remove("hidden"); }
    console.warn("[auth] register error", e);
  }
  if (btn) { btn.disabled = false; btn.textContent = "Complete Profile"; }
}

function setupCodeInputs() {
  document.querySelectorAll("#authModal .code-digit").forEach(inp => {
    inp.addEventListener("input", function () {
      if (this.value && this.dataset.idx < "5") {
        const next = document.querySelector(`#authModal .code-digit[data-idx="${parseInt(this.dataset.idx) + 1}"]`);
        if (next) next.focus();
      }
    });
    inp.addEventListener("keydown", function (e) {
      if ((e.key === "Backspace" || e.key === "Backward") && !this.value && this.dataset.idx > "0") {
        const prev = document.querySelector(`#authModal .code-digit[data-idx="${parseInt(this.dataset.idx) - 1}"]`);
        if (prev) { prev.focus(); prev.value = ""; }
      }
      if (e.key === "Enter") authVerifyCode();
    });
    inp.addEventListener("paste", function (e) {
      e.preventDefault();
      const text = (e.clipboardData || window.clipboardData).getData("text").replace(/\D/g, "");
      if (text.length !== 6) return;
      const inputs = document.querySelectorAll("#authModal .code-digit");
      inputs.forEach((input, i) => { input.value = text[i] || ""; });
      const last = inputs[inputs.length - 1];
      if (last) last.focus();
    });
  });
}

function authResendCode() {
  const err = _el("authCodeError");
  if (err) err.classList.add("hidden");
  authSendCode();
}

function authGoBack() {
  const emailStep = _el("authStepEmail");
  const codeStep = _el("authStepCode");
  if (emailStep) emailStep.classList.remove("hidden");
  if (codeStep) codeStep.classList.add("hidden");
  const s4 = _el("authStep4");
  if (s4) s4.classList.add("hidden");
  const err = _el("authSendError");
  if (err) err.classList.add("hidden");
  const emailInput = _el("authEmail");
  if (emailInput) emailInput.focus();
}

document.addEventListener("DOMContentLoaded", () => {
  setupCodeInputs();
  loadAuthCompanyList();
});

// Attach to window for onclick handlers (single canonical auth flow)
window.sendEmailJS = sendEmailJS;
window.promptSendCode = promptSendCode;
window.authSendCode = authSendCode;
window.showAuthModal = showAuthModal;
window.closeAuthModal = closeAuthModal;
window.verifyCode = authVerifyCode;
window.authVerifyCode = authVerifyCode;
window.authResendCode = authResendCode;
window.authGoBack = authGoBack;
window.authRegister = authRegister;
window.selectEmploymentStatus = selectEmploymentStatus;
window.prefillInviteDetails = prefillInviteDetails;
window.filterCompanyDropdown = filterCompanyDropdown;
window.addCustomCompany = addCustomCompany;
window.selectCompany = selectCompany;
window.setupCodeInputs = setupCodeInputs;

export { initEmailJS, sendEmailJS, loadAuthCompanyList };