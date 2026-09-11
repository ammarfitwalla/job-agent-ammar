/* api.js — thin authenticated-fetch wrapper for JobAwn.
   Loaded as a CLASSIC script (no module) so it is available to all pages and module scripts.
   Publishes window.getAuthToken / setAuthToken / setAuthSession / api / downloadAuthed.
   Token is kept in sessionStorage (anti-history, refreshed each session). */
(function () {
  var TOKEN_KEY = "ja_token";
  var TOKEN_EMAIL_KEY = "ja_token_email";

  function getToken() {
    try { return sessionStorage.getItem(TOKEN_KEY); } catch (e) { return null; }
  }
  function setToken(tok) {
    try {
      if (tok) sessionStorage.setItem(TOKEN_KEY, tok);
      else sessionStorage.removeItem(TOKEN_KEY);
    } catch (e) {}
  }

  window.getAuthToken = getToken;
  window.setAuthToken = setToken;
  window.clearAuthToken = function () { setToken(null); };
  window.setAuthSession = function (tok, email) {
    setToken(tok);
    try {
      if (email) sessionStorage.setItem(TOKEN_EMAIL_KEY, email);
      else sessionStorage.removeItem(TOKEN_EMAIL_KEY);
    } catch (e) {}
  };
  window.getAuthEmail = function () {
    try { return sessionStorage.getItem(TOKEN_EMAIL_KEY) || ""; } catch (e) { return ""; }
  };

  window.api = async function (path, opts) {
    opts = opts || {};
    opts.headers = Object.assign({}, opts.headers || {});
    var tok = getToken();
    if (tok) opts.headers["Authorization"] = "Bearer " + tok;
    var resp = await fetch(path, opts);
    if (resp.status === 401) {
      // A 401 while we're holding a token means that token is dead (expired or
      // signed under a changed secret) — drop it so background pollers stop
      // failing forever and stale sessions don't masquerade as logged in.
      if (tok) window.clearAuthToken();
      window.dispatchEvent(new CustomEvent("ja:auth-required", { detail: { status: resp.status, path: path } }));
    }
    return resp;
  };

  // Protected file downloads (e.g. resumes, db dump) require the Authorization header,
  // so plain <a href> links are routed here: mark any link with data-download="1".
  window.downloadAuthed = async function (path, filename) {
    var resp = await window.api(path, { method: "GET" });
    if (!resp.ok) {
      if (typeof window.showToast === "function") window.showToast("Download failed — please sign in first");
      return false;
    }
    try {
      var blob = await resp.blob();
      var url = URL.createObjectURL(blob);
      var a = document.createElement("a");
      a.href = url;
      var cd = resp.headers.get("Content-Disposition") || "";
      var m = cd.match(/filename="?([^";]+)"?/);
      a.download = filename || (m ? m[1] : (path.split("/").pop() || "download"));
      document.body.appendChild(a);
      a.click();
      setTimeout(function () { URL.revokeObjectURL(url); a.remove(); }, 0);
      return true;
    } catch (e) {
      if (typeof window.showToast === "function") window.showToast("Download failed");
      return false;
    }
  };

  document.addEventListener("click", function (e) {
    var a = e.target && e.target.closest ? e.target.closest("a[data-download]") : null;
    if (a) {
      e.preventDefault();
      window.downloadAuthed(a.getAttribute("href") || a.href, a.getAttribute("download") || "");
    }
  });
})();