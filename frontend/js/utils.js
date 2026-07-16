let _profile = null;

function getProfile() {
  if (_profile) return _profile;
  const raw = localStorage.getItem("jobagent_profile_email");
  if (raw) return { email: raw };
  const old = localStorage.getItem("jobagent_profile");
  if (old) {
    try {
      const data = JSON.parse(old);
      if (data && data.email) {
        localStorage.setItem("jobagent_profile_email", data.email);
        localStorage.removeItem("jobagent_profile");
        return { email: data.email };
      }
    } catch (e) {}
  }
  return null;
}

function setProfile(data) {
  _profile = data;
  if (data && data.email) {
    localStorage.setItem("jobagent_profile_email", data.email);
  } else {
    localStorage.removeItem("jobagent_profile_email");
  }
}

function clearProfile() {
  _profile = null;
  localStorage.removeItem("jobagent_profile_email");
}

function updateNavIcon() {
  const link = document.getElementById("profileLink");
  const profile = getProfile();
  link.classList.remove("bg-indigo-50", "border-indigo-200", "hover:bg-indigo-100",
    "text-slate-600", "hover:text-indigo-500", "hover:bg-indigo-50", "bg-slate-100", "border-2", "border-slate-300", "hover:border-indigo-200");
  if (profile) {
    const initial = profile.name ? profile.name.charAt(0).toUpperCase() : (profile.email ? profile.email.charAt(0).toUpperCase() : "?");
    link.innerHTML = `<span class="w-[22px] h-[22px] rounded-full bg-indigo-500 text-white flex items-center justify-center text-xs font-bold leading-none" style="line-height:0">${initial}</span>`;
    link.classList.add("bg-indigo-50", "border-indigo-200", "hover:bg-indigo-100");
    link.title = profile.name || profile.email || "Profile";
  } else {
    link.innerHTML = '<svg class="w-[20px] h-[20px]" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z"/></svg>';
    link.classList.add("text-slate-600", "hover:text-indigo-500", "hover:bg-indigo-50", "bg-slate-100", "border-2", "border-slate-300", "hover:border-indigo-200");
    link.title = "Your Profile";
  }
}

function showToast(msg) {
  const existing = document.getElementById("toast-msg");
  if (existing) existing.remove();

  const el = document.createElement("div");
  el.id = "toast-msg";
  el.className = "fixed bottom-6 left-1/2 -translate-x-1/2 z-50 bg-slate-900 text-white text-sm font-medium px-5 py-3 rounded-full shadow-xl flex items-center gap-2 fade-in";
  el.innerHTML = `<svg class="w-4 h-4 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg> ${msg}`;
  document.body.appendChild(el);
  setTimeout(() => {
    el.style.opacity = "0";
    el.style.transform = "translate(-50%, 10px)";
    el.style.transition = "all 0.3s ease";
    setTimeout(() => el.remove(), 300);
  }, 2500);
}

function htmlEscape(str) {
  const div = document.createElement("div");
  div.appendChild(document.createTextNode(str || ""));
  return div.innerHTML;
}

function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
}

window.getProfile = getProfile;
window.setProfile = setProfile;
window.clearProfile = clearProfile;
window.updateNavIcon = updateNavIcon;
window.showToast = showToast;
window.htmlEscape = htmlEscape;
window.formatDate = formatDate;

export { getProfile, setProfile, clearProfile, updateNavIcon, showToast, htmlEscape, formatDate };
