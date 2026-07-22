import { DEV_MODE, EMAILJS_SERVICE_ID, EMAILJS_TEMPLATE_ID, EMAILJS_PUBLIC_KEY, _EMPLOYMENT_LABELS } from "./constants.js";
import { getProfile, setProfile, showToast, updateNavIcon } from "./utils.js";

let emailjsInitialized = false;
let _authEmail = "";
let _authCompanyList = [];

function initEmailJS() {
  if (typeof emailjs !== "undefined" && EMAILJS_PUBLIC_KEY) {
    emailjs.init(EMAILJS_PUBLIC_KEY);
    emailjsInitialized = true;
  }
}

async function sendEmailJS(templateParams) {
  if (!emailjsInitialized) {
    console.warn("EmailJS not initialized.");
    return { ok: false, error: "EmailJS not configured" };
  }
  try {
    const res = await emailjs.send(EMAILJS_SERVICE_ID, EMAILJS_TEMPLATE_ID, templateParams);
    return { ok: true, res };
  } catch (err) {
    return { ok: false, error: err.text || err.message };
  }
}

function promptSendCode() {
  const email = document.getElementById("promptEmail").value.trim();
  const errEl = document.getElementById("promptError");
  const btn = document.getElementById("promptSendBtn");
  const text = document.getElementById("promptSendText");
  const spinner = document.getElementById("promptSendSpinner");
  if (!email || !email.includes("@")) {
    errEl.textContent = "Please enter a valid email address.";
    errEl.classList.remove("hidden");
    return;
  }
  errEl.classList.add("hidden");
  btn.disabled = true;
  text.textContent = "Sending";
  spinner.classList.remove("hidden");
  _authEmail = email;
  fetch("/api/auth/send-code", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  }).then(r => r.json()).then(d => {
    if (d.ok) {
      if (DEV_MODE) {
        document.getElementById("modalEmail").textContent = email;
        document.getElementById("authModal").style.display = "flex";
        document.querySelectorAll(".code-digit").forEach(inp => { inp.value = ""; });
        setTimeout(() => document.querySelector(".code-digit").focus(), 100);
        return;
      }
      sendEmailJS({
        email: email,
        subject: "Your Job Agent verification code",
        passcode: d.code,
      }).then(emailRes => {
        if (!emailRes.ok) {
          errEl.textContent = emailRes.error || "Failed to send email.";
          errEl.classList.remove("hidden");
          btn.disabled = false;
          text.textContent = "Send Code";
          spinner.classList.add("hidden");
          return;
        }
        document.getElementById("modalEmail").textContent = email;
        document.getElementById("authModal").style.display = "flex";
        document.querySelectorAll(".code-digit").forEach(inp => { inp.value = ""; });
        setTimeout(() => document.querySelector(".code-digit").focus(), 100);
      });
      return;
    } else {
      errEl.textContent = d.error || "Failed to send code.";
      errEl.classList.remove("hidden");
    }
    btn.disabled = false;
    text.textContent = "Send Code";
    spinner.classList.add("hidden");
  }).catch(() => {
    errEl.textContent = "Network error. Please try again.";
    errEl.classList.remove("hidden");
    btn.disabled = false;
    text.textContent = "Send Code";
    spinner.classList.add("hidden");
  });
}

function closeAuthModal() {
  document.getElementById("authModal").style.display = "none";
  document.getElementById("authStep1").classList.remove("hidden");
  const s4 = document.getElementById("authStep4");
  if (s4) s4.classList.add("hidden");
  const btn = document.getElementById("promptSendBtn");
  if (btn) btn.disabled = false;
  const text = document.getElementById("promptSendText");
  if (text) text.textContent = "Send Code";
  const spinner = document.getElementById("promptSendSpinner");
  if (spinner) spinner.classList.add("hidden");
}

function showAuthModal() {
  _authEmail = prompt("Enter your email to sign in:");
  if (!_authEmail || !_authEmail.includes("@")) return;
  document.getElementById("promptEmail").value = _authEmail;
  promptSendCode();
}

function verifyCode() {
  const digits = document.querySelectorAll("#authModal .code-digit");
  const code = Array.from(digits).map(d => d.value).join("");
  const errEl = document.getElementById("authCodeError");
  if (code.length !== 6) { errEl.textContent = "Please enter the full 6-digit code."; errEl.classList.remove("hidden"); return; }
  errEl.classList.add("hidden");
  fetch("/api/auth/verify-code", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: _authEmail, code }),
  }).then(r => r.json()).then(d => {
    if (d.ok) {
      if (d.user.company) {
        setProfile({ email: d.user.email, name: d.user.name, company: d.user.company, position: d.user.position || "", linkedin_url: d.user.linkedin_url || "", referral_credits: d.user.referral_credits || 0 });
        closeAuthModal();
        window.loadProfile();
        showToast("Successfully signed in");
      } else {
        document.getElementById("authStep1").classList.add("hidden");
        document.getElementById("authStep4").classList.remove("hidden");
        document.getElementById("authName").value = d.user.name || d.user.email.split("@")[0];
        document.getElementById("authName").focus();
      }
    } else {
      errEl.textContent = d.error || "Invalid code provided.";
      errEl.classList.remove("hidden");
    }
  }).catch(() => {
    errEl.textContent = "Network error. Please try again.";
    errEl.classList.remove("hidden");
  });
}

function selectEmploymentStatus(status) {
  document.querySelectorAll("#authStep4 .employment-pill").forEach(p => p.classList.remove("active-pill"));
  const pill = document.querySelector(`#authStep4 .employment-pill[data-status="${status}"]`);
  if (pill) pill.classList.add("active-pill");
  const group = document.getElementById("authCompanyGroup");
  if (group) {
    group.classList.toggle("hidden", status !== "employed");
    if (status !== "employed") {
      document.getElementById("authCompany").value = "";
    }
  }
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
  const input = document.getElementById("authCompany");
  const dropdown = document.getElementById("companyDropdown");
  const val = input.value.toLowerCase().trim();
  const matches = val ? _authCompanyList.filter(c => c.toLowerCase().includes(val)) : _authCompanyList;
  let html = matches.slice(0, 30).map(c =>
    `<div class="px-3 py-2 text-sm cursor-pointer hover:bg-indigo-50 transition-colors" onclick="selectCompany('${c.replace(/'/g, "\\'")}')">${c}</div>`
  ).join("");
  if (val && !_authCompanyList.some(c => c.toLowerCase() === val)) {
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
  await fetch("/api/auth/companies", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!_authCompanyList.includes(name)) {
    _authCompanyList.push(name);
    _authCompanyList.sort();
  }
  selectCompany(name);
}

function selectCompany(name) {
  document.getElementById("authCompany").value = name;
  document.getElementById("companyDropdown").classList.add("hidden");
}

async function authRegister() {
  if (!_authEmail) return;
  const status = document.querySelector("#authStep4 .employment-pill.active-pill")?.dataset?.status || "employed";
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
    company = _EMPLOYMENT_LABELS[status] || "";
  }
  errEl.classList.add("hidden");
  btn.disabled = true;
  btn.textContent = "Saving...";
  try {
    const r = await fetch("/api/auth/register", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: _authEmail, name, company, position, linkedin_url: linkedin }),
    });
    const d = await r.json();
    if (!d.ok) {
      errEl.textContent = d.error || "Failed to save profile.";
      errEl.classList.remove("hidden");
      btn.disabled = false;
      btn.textContent = "Complete Profile";
      return;
    }
    setProfile(d.user);
    document.getElementById("authStep4").classList.add("hidden");
    closeAuthModal();
    window.loadProfile();
    showToast("Profile complete!");
  } catch (e) {
    errEl.textContent = "Network error. Try again.";
    errEl.classList.remove("hidden");
  }
  btn.disabled = false;
  btn.textContent = "Complete Profile";
}

// Attach to window for onclick handlers
// Only set if not already defined (search.js may have set stepper versions)
window.sendEmailJS = sendEmailJS;
window.promptSendCode = promptSendCode;
if (!window.closeAuthModal) window.closeAuthModal = closeAuthModal;
if (!window.showAuthModal) window.showAuthModal = showAuthModal;
window.verifyCode = verifyCode;
if (!window.selectEmploymentStatus) window.selectEmploymentStatus = selectEmploymentStatus;
if (!window.filterCompanyDropdown) window.filterCompanyDropdown = filterCompanyDropdown;
if (!window.addCustomCompany) window.addCustomCompany = addCustomCompany;
if (!window.selectCompany) window.selectCompany = selectCompany;
if (!window.authRegister) window.authRegister = authRegister;

export { initEmailJS, sendEmailJS, loadAuthCompanyList };
