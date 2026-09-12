/* api.js — thin authenticated-fetch wrapper for JobAwn.
   Loaded as a CLASSIC script (no module) so it is available to all pages and module scripts.
   Publishes window.getAuthToken / setAuthToken / setAuthSession / api / downloadAuthed.
   Token is kept in localStorage so the session survives tab close, browser restart,
   and mobile tab-discard; a single spurious 401 is retried once before clearing. */
(function () {
  var TOKEN_KEY = "ja_token";
  var TOKEN_EMAIL_KEY = "ja_token_email";

  function getToken() {
    try {
      var t = localStorage.getItem(TOKEN_KEY);
      if (t) return t;
      // One-time migration: promote a sessionStorage token from before this change.
      var old = sessionStorage.getItem(TOKEN_KEY);
      if (old) {
        localStorage.setItem(TOKEN_KEY, old);
        sessionStorage.removeItem(TOKEN_KEY);
        return old;
      }
    } catch (e) {}
    return null;
  }
  function setToken(tok) {
    try {
      if (tok) localStorage.setItem(TOKEN_KEY, tok);
      else localStorage.removeItem(TOKEN_KEY);
    } catch (e) {}
  }
  function getEmail() {
    try {
      var e = localStorage.getItem(TOKEN_EMAIL_KEY);
      if (e) return e;
      // One-time migration for pre-change sessionStorage sessions.
      var old = sessionStorage.getItem(TOKEN_EMAIL_KEY);
      if (old) {
        localStorage.setItem(TOKEN_EMAIL_KEY, old);
        sessionStorage.removeItem(TOKEN_EMAIL_KEY);
        return old;
      }
    } catch (err) { return ""; }
    return "";
  }
  function setEmail(email) {
    try {
      if (email) localStorage.setItem(TOKEN_EMAIL_KEY, email);
      else localStorage.removeItem(TOKEN_EMAIL_KEY);
    } catch (e) {}
  }

  window.getAuthToken = getToken;
  window.setAuthToken = setToken;
  window.clearAuthToken = function () { setToken(null); };
  window.setAuthSession = function (tok, email) {
    setToken(tok);
    setEmail(email || "");
  };
  window.getAuthEmail = getEmail;

  async function apiOnce(path, opts) {
    var tok = getToken();
    if (tok) opts.headers["Authorization"] = "Bearer " + tok;
    return fetch(path, opts);
  }

  window.api = async function (path, opts) {
    opts = opts || {};
    opts.headers = Object.assign({}, opts.headers || {});
    var tok = getToken();
    var resp = await apiOnce(path, opts);
    if (resp.status === 401 && tok) {
      // A 401 while holding a token usually means it's dead (expired or signed
      // under a changed secret) — but retry once first to rule out a transient
      // blip. Only drop the session if the retry also 401s, so stale sessions
      // stop failing forever and don't masquerade as logged in.
      resp = await apiOnce(path, opts);
      if (resp.status === 401) {
        window.clearAuthToken();
        window.dispatchEvent(new CustomEvent("ja:auth-required", { detail: { status: 401, path: path } }));
      }
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