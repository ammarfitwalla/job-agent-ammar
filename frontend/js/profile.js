import { getProfile, setProfile, showToast, updateNavIcon } from "./utils.js";
import { _PROFILE_EMPLOYMENT_LABELS, _PROFILE_LABEL_TO_STATUS } from "./constants.js";

let _profileCompanyList = [];

async function loadProfile() {
  const profile = getProfile();
  const logoutBtn = document.getElementById("logoutBtn");
  if (!profile) {
    document.getElementById("authPrompt").classList.remove("hidden");
    document.getElementById("profileContent").classList.add("hidden");
    logoutBtn.classList.add("hidden");
    updateNavIcon();
    setTimeout(() => document.getElementById("promptEmail").focus(), 100);
    return;
  }
  logoutBtn.classList.remove("hidden");
  updateNavIcon();
  document.getElementById("authPrompt").classList.add("hidden");
  document.getElementById("profileContent").classList.remove("hidden");
  document.getElementById("profileSkeleton").classList.remove("hidden");
  document.getElementById("dashboardSidebar").classList.add("hidden");
  document.getElementById("dashboardMain").classList.add("hidden");

  const jobsPromise = window.loadSavedJobs ? window.loadSavedJobs().catch(() => {}) : Promise.resolve();
  const refPromise = window.loadReferrals ? window.loadReferrals().catch(() => {}) : Promise.resolve();

  try {
    const r = await fetch(`/api/profile?email=${encodeURIComponent(profile.email)}`);
    const d = await r.json();
    document.getElementById("profileSkeleton").classList.add("hidden");
    document.getElementById("dashboardSidebar").classList.remove("hidden");
    document.getElementById("dashboardMain").classList.remove("hidden");
    if (d.error) { showToast(d.error); return; }
    setProfile(d);
    renderProfile(d);
  } catch (e) {
    document.getElementById("profileSkeleton").classList.add("hidden");
    document.getElementById("dashboardSidebar").classList.remove("hidden");
    document.getElementById("dashboardMain").classList.remove("hidden");
    renderProfile({
      name: profile.name || "User",
      email: profile.email,
      created_at: new Date().toISOString(),
      status_counts: { total: 0 },
    });
  }
  await Promise.all([jobsPromise, refPromise]);
}

function renderProfile(data) {
  document.getElementById("profileName").textContent = data.name;
  document.getElementById("profileEmail").textContent = data.email;
  document.getElementById("profileAvatar").textContent = data.name.charAt(0).toUpperCase();
  const d = new Date(data.created_at);
  document.getElementById("profileJoined").textContent = "Member since " + d.toLocaleDateString("en-US", { year: "numeric", month: "long" });
  const credits = data.referral_credits || 0;
  const creditText = document.getElementById("profileCreditsText");
  if (creditText) creditText.textContent = credits + " referral credits";

  const company = data.company || "";
  const position = data.position || "";
  const linkedin = data.linkedin_url || "";

  const parts = [];
  if (position) parts.push(position);
  if (company) parts.push("at " + company);
  document.getElementById("profileHeadline").textContent = parts.join(" ") || "";
  document.getElementById("profileHeadline").classList.toggle("hidden", !parts.length);

  const statusLabel = _PROFILE_LABEL_TO_STATUS[company]
    || (company ? "Employed" : "");
  const badge = document.getElementById("profileStatusBadge");
  if (statusLabel) {
    badge.textContent = statusLabel;
    badge.classList.remove("hidden");
  } else {
    badge.classList.add("hidden");
  }

  const linkedinEl = document.getElementById("profileLinkedin");
  if (linkedin) {
    linkedinEl.href = linkedin;
    linkedinEl.textContent = linkedin.replace(/^https?:\/\//, "").replace(/\/$/, "");
    linkedinEl.classList.remove("hidden");
    linkedinEl.parentElement.classList.remove("hidden");
  } else {
    linkedinEl.classList.add("hidden");
    linkedinEl.parentElement.classList.add("hidden");
  }

  window.renderStatusTabs(data.status_counts || {});
}

async function loadProfileCompanyList() {
  if (_profileCompanyList.length > 0) return;
  try {
    const r = await fetch("/api/auth/companies");
    const d = await r.json();
    _profileCompanyList = d.companies || [];
  } catch (e) {}
}

function filterProfileCompanyDropdown() {
  const input = document.getElementById("editCompany");
  const dropdown = document.getElementById("editCompanyDropdown");
  if (!input || !dropdown) return;
  const val = input.value.toLowerCase().trim();
  const matches = val ? _profileCompanyList.filter(c => c.toLowerCase().includes(val)) : _profileCompanyList;
  let html = matches.slice(0, 30).map(c =>
    `<div class="px-3 py-2 text-sm cursor-pointer hover:bg-indigo-50 transition-colors" onclick="selectProfileCompany('${c.replace(/'/g, "\\'")}')">${c}</div>`
  ).join("");
  if (val && !_profileCompanyList.some(c => c.toLowerCase() === val)) {
    html += `<div class="px-3 py-2 text-sm cursor-pointer text-indigo-600 border-t border-slate-100 hover:bg-indigo-50 transition-colors font-medium" onclick="addCustomProfileCompany('${val.replace(/'/g, "\\'")}', event)">+ Add "${input.value.trim()}"</div>`;
  }
  if (!html) {
    dropdown.classList.add("hidden");
    return;
  }
  dropdown.innerHTML = html;
  dropdown.classList.remove("hidden");
}

async function addCustomProfileCompany(name, event) {
  event.stopPropagation();
  await fetch("/api/auth/companies", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!_profileCompanyList.includes(name)) {
    _profileCompanyList.push(name);
    _profileCompanyList.sort();
  }
  selectProfileCompany(name);
}

function selectProfileCompany(name) {
  document.getElementById("editCompany").value = name;
  document.getElementById("editCompanyDropdown").classList.add("hidden");
}

function profileSelectEmploymentStatus(status) {
  document.querySelectorAll("#profileEditPills .employment-pill").forEach(p => p.classList.remove("active-pill"));
  const pill = document.querySelector(`#profileEditPills .employment-pill[data-status="${status}"]`);
  if (pill) pill.classList.add("active-pill");
  const group = document.getElementById("editCompanyGroup");
  if (group) {
    group.classList.toggle("hidden", status !== "employed");
    if (status !== "employed") {
      document.getElementById("editCompany").value = "";
    }
  }
}

function enableProfileEdit() {
  const profile = getProfile();
  if (!profile) return;
  document.getElementById("profileDisplayMode").classList.add("hidden");
  document.getElementById("profileEditMode").classList.remove("hidden");
  document.getElementById("editName").value = document.getElementById("profileName").textContent || "";
  const currentHeadline = document.getElementById("profileHeadline").textContent || "";
  const currentCompany = currentHeadline.includes("at ") ? currentHeadline.split("at ").pop().trim() : "";
  const matchedStatus = _PROFILE_LABEL_TO_STATUS[currentCompany];
  if (matchedStatus) {
    profileSelectEmploymentStatus(matchedStatus);
    document.getElementById("editCompany").value = "";
  } else {
    profileSelectEmploymentStatus("employed");
    document.getElementById("editCompany").value = currentCompany;
  }
  loadProfileCompanyList();
  filterProfileCompanyDropdown();
  document.getElementById("editRole").value = document.getElementById("profileHeadline").textContent.split(" at ")[0] || "";
  const linkedinEl = document.getElementById("profileLinkedin");
  document.getElementById("editLinkedin").value = linkedinEl.classList.contains("hidden") ? "" : linkedinEl.href;
  document.getElementById("editName").focus();
}

function disableProfileEdit() {
  document.getElementById("profileDisplayMode").classList.remove("hidden");
  document.getElementById("profileEditMode").classList.add("hidden");
}

async function saveProfile() {
  const profile = getProfile();
  if (!profile) return;
  const name = document.getElementById("editName").value.trim();
  if (!name) {
    showToast("Name is required");
    return;
  }
  const status = document.querySelector("#profileEditPills .employment-pill.active-pill")?.dataset?.status || "employed";
  const position = document.getElementById("editRole").value.trim();
  const linkedin = document.getElementById("editLinkedin").value.trim();
  let company;
  if (status === "employed") {
    company = document.getElementById("editCompany").value.trim();
    if (!company) {
      showToast("Enter your company name");
      document.getElementById("editCompany").focus();
      return;
    }
  } else {
    company = _PROFILE_EMPLOYMENT_LABELS[status] || "";
  }
  try {
    const r = await fetch("/api/profile", {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: profile.email, company, position, linkedin_url: linkedin }),
    });
    const d = await r.json();
    if (d.ok) {
      setProfile(d.user);
      const companyStr = d.user.company || "";
      const positionStr = d.user.position || "";
      const parts = [];
      if (positionStr) parts.push(positionStr);
      if (companyStr) parts.push("at " + companyStr);
      document.getElementById("profileHeadline").textContent = parts.join(" ") || "";
      document.getElementById("profileHeadline").classList.toggle("hidden", !parts.length);
      const statusLabel = _PROFILE_LABEL_TO_STATUS[companyStr] || (companyStr ? "Employed" : "");
      const badge = document.getElementById("profileStatusBadge");
      if (statusLabel) {
        badge.textContent = statusLabel;
        badge.classList.remove("hidden");
      } else {
        badge.classList.add("hidden");
      }
      if (d.user.linkedin_url) {
        document.getElementById("profileLinkedin").href = d.user.linkedin_url;
        document.getElementById("profileLinkedin").textContent = d.user.linkedin_url.replace(/^https?:\/\//, "").replace(/\/$/, "");
        document.getElementById("profileLinkedin").classList.remove("hidden");
        document.getElementById("profileLinkedin").parentElement.classList.remove("hidden");
      } else {
        document.getElementById("profileLinkedin").classList.add("hidden");
        document.getElementById("profileLinkedin").parentElement.classList.add("hidden");
      }
      saveNameLocally(profile.email, name);
    } else {
      showToast("Failed to update");
    }
  } catch (e) {
    showToast("Network error");
  }
}

async function saveNameLocally(email, name) {
  document.getElementById("profileName").textContent = name;
  document.getElementById("profileAvatar").textContent = name.charAt(0).toUpperCase();
  try {
    const r = await fetch("/api/profile/name", {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, name }),
    });
    const d = await r.json();
    if (d.ok) {
      const profile = getProfile();
      if (profile) {
        profile.name = name;
        setProfile(profile);
      }
    }
  } catch (e) {}
  disableProfileEdit();
  showToast("Profile updated");
}

function switchDashboardTab(tab) {
  document.querySelectorAll(".dashboard-tab").forEach(el => el.classList.remove("active"));
  const tabEl = document.getElementById("tab-" + tab);
  if (tabEl) tabEl.classList.add("active");
  if (tab === "jobs") {
    document.getElementById("viewJobs").classList.remove("hidden");
    document.getElementById("viewReferrals").classList.add("hidden");
  } else {
    document.getElementById("viewJobs").classList.add("hidden");
    document.getElementById("viewReferrals").classList.remove("hidden");
  }
}

function openReferralFromCTA() {
  const modal = document.getElementById("referralModal");
  if (modal) {
    modal.classList.remove("hidden");
    modal.classList.add("flex");
  }
}

window.loadProfile = loadProfile;
window.renderProfile = renderProfile;
window.profileSelectEmploymentStatus = profileSelectEmploymentStatus;
window.enableProfileEdit = enableProfileEdit;
window.disableProfileEdit = disableProfileEdit;
window.saveProfile = saveProfile;
window.filterProfileCompanyDropdown = filterProfileCompanyDropdown;
window.addCustomProfileCompany = addCustomProfileCompany;
window.selectProfileCompany = selectProfileCompany;
window.switchDashboardTab = switchDashboardTab;
window.openReferralFromCTA = openReferralFromCTA;

export { loadProfile, loadProfileCompanyList };
