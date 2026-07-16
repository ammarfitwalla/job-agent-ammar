import { clearProfile, updateNavIcon } from "./utils.js";
import { initEmailJS, loadAuthCompanyList } from "./auth.js";
import { loadProfile, loadProfileCompanyList } from "./profile.js";

// ── Logout ──

function logout() {
  document.getElementById("logoutModal").classList.remove("hidden");
}

function confirmLogout() {
  document.getElementById("logoutModal").classList.add("hidden");
  clearProfile();
  window.location.href = "/";
}

function cancelLogout() {
  document.getElementById("logoutModal").classList.add("hidden");
}

// ── Stats Bar ──

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
  } catch (e) {}
}

// ── Event Listeners ──

document.addEventListener("click", function (e) {
  const dd = document.getElementById("companyDropdown");
  if (dd && !e.target.closest("#authCompany") && !e.target.closest("#companyDropdown")) {
    dd.classList.add("hidden");
  }
  const pdd = document.getElementById("profileCompanyDropdown");
  if (pdd && !e.target.closest("#profileCompany") && !e.target.closest("#profileCompanyDropdown")) {
    pdd.classList.add("hidden");
  }
});

// ── DOMContentLoaded ──

document.addEventListener("DOMContentLoaded", function () {
  loadStatsBar();
  loadAuthCompanyList();

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
      if (e.key === "Enter") window.verifyCode();
    });
    inp.addEventListener("paste", function (e) {
      e.preventDefault();
      const text = (e.clipboardData || window.clipboardData).getData("text").replace(/\D/g, "");
      if (text.length !== 6) return;
      const inputs = document.querySelectorAll("#authModal .code-digit");
      inputs.forEach((input, i) => { input.value = text[i] || ""; });
      inputs[5].focus();
    });
  });

  initEmailJS();
  updateNavIcon();
  loadProfile();
  loadProfileCompanyList();
});

// ── Window globals for onclick ──

window.logout = logout;
window.confirmLogout = confirmLogout;
window.cancelLogout = cancelLogout;
