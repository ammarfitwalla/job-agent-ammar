// ── Visit Tracking ──
// Sends a start beacon on script evaluation and an end beacon on
// beforeunload / pagehide / visibilitychange → hidden.
// Loads after api.js on every tracked page; landing.html omits api.js
// so getAuthEmail may be absent (sends blank email).

(function () {
  var _visitId = crypto.randomUUID();
  var _visitStart = Date.now();

  function _detectDevice() {
    var ua = navigator.userAgent;
    if (/Mobi|Android|iPhone|iPad|iPod|BlackBerry|Windows Phone|IEMobile|Opera Mini/i.test(ua)) return "phone";
    if (/Tablet|iPad|PlayBook|Silk/i.test(ua)) return "tablet";
    return "desktop";
  }

  function _visitBeacon(endpoint, data) {
    try {
      navigator.sendBeacon(endpoint, new Blob([JSON.stringify(data)], { type: "application/json" }));
    } catch (e) {}
  }

  var _email = "";
  if (typeof window.getAuthEmail === "function") _email = window.getAuthEmail() || "";
  // Landing has no api.js (getAuthEmail absent); read the token email directly.
  if (!_email) {
    try { _email = localStorage.getItem("ja_token_email") || ""; } catch (e) {}
  }

  // Persist one session id per tab across page navigations so / → /profile →
  // /app share the same session (sessionStorage survives same-tab navigation).
  var _sessionId = "";
  try {
    _sessionId = sessionStorage.getItem("ja_visit_session") || "";
    if (!_sessionId) {
      _sessionId = crypto.randomUUID();
      sessionStorage.setItem("ja_visit_session", _sessionId);
    }
  } catch (e) {}

  _visitBeacon("/api/visit/start", {
    visit_id: _visitId,
    device_type: _detectDevice(),
    path: window.location.pathname,
    referer: document.referrer || "",
    session_id: _sessionId,
    user_email: _email,
  });

  function _endVisit() {
    _visitBeacon("/api/visit/end", {
      visit_id: _visitId,
      total_duration: (Date.now() - _visitStart) / 1000,
    });
  }

  window.addEventListener("beforeunload", _endVisit);
  window.addEventListener("pagehide", _endVisit);
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") _endVisit();
  });
})();
