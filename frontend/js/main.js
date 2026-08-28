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
  window.location.href = "/app";
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
      { label: "jobs scraped", value: d.total_scraped },
      { label: "users", value: d.total_users },
      { label: "companies", value: d.total_companies },
    ].map(s => `<span class="inline-flex items-center gap-1"><span class="font-semibold text-slate-700">${s.value.toLocaleString()}</span> <span class="text-slate-400">${s.label}</span></span>`).join('<span class="text-slate-200">·</span>');
    bar.classList.remove("hidden");
  } catch (e) {}
}

// ── Event Listeners ──

document.addEventListener("click", function (e) {
  const pdd = document.getElementById("profileCompanyDropdown");
  if (pdd && !e.target.closest("#profileCompany") && !e.target.closest("#profileCompanyDropdown")) {
    pdd.classList.add("hidden");
  }
});

// ── DOMContentLoaded ──

document.addEventListener("DOMContentLoaded", function () {
  loadStatsBar();
  loadAuthCompanyList();

  initEmailJS();
  updateNavIcon();
  loadProfile();
  loadProfileCompanyList();
});

// ── Window globals for onclick ──

window.logout = logout;
window.confirmLogout = confirmLogout;
window.cancelLogout = cancelLogout;
