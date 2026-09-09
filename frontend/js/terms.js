(function () {
  "use strict";

  var TERMS = [
    ["What JobAwn does", "JobAwn searches multiple job boards (e.g. Indeed, LinkedIn, Adzuna, Naukri), scores jobs against your resume using AI, and helps you get referred by insiders at companies you'd like to apply to."],
    ["Accepting these terms", "By using JobAwn (the \u201cService\u201d), you agree to these Terms & Conditions. If you don't agree, please don't use the Service."],
    ["Who can use it", "You must be at least 18 years old and provide honest information about yourself and your work history."],
    ["AI scoring is a guide, not a guarantee", "Scores and matches are estimates. They are not professional career advice and don't guarantee interviews, offers, or any other outcome."],
    ["Job listings come from third parties", "Jobs are pulled from external boards we don't control. We can't verify every posting's accuracy, salary, or availability, and listings can change or disappear."],
    ["Your content stays yours", "You keep ownership of your resume and profile information. You grant us permission to store and use them to run the Service (searching, scoring, matching, and referrals)."],
    ["Referrals", "A referrer's identity is hidden until a seeker chooses to connect. By opting in as a referrer, you agree to be contacted by matched seekers. Referrer and seeker details may only be used to help with referrals \u2014 no spam, harassment, or sharing without permission."],
    ["Behave responsibly", "Don't abuse the Service: no automated scraping beyond normal use, no fake referrals, no false information, no uploading other people's data without permission, and no attempts to break or overload our systems."],
    ["Your login", "Access is tied to your email address. Keep your account details safe and don't use your access in a way that harms other users."],
    ["Availability", "The Service is provided \u201cas-is\u201d and \u201cas available\u201d. We may change, pause, or remove features, and we can't guarantee zero downtime."],
    ["Bad behavior gets removed", "We may suspend or terminate accounts that break these terms, at our discretion."],
    ["Liability", "To the fullest extent allowed by law, JobAwn isn't responsible for the outcome of your applications, missed opportunities, or any losses or damages from using the Service."],
    ["Changes to these terms", "We may update these terms from time to time. The effective date below shows the latest version, which applies from that date."],
    ["Contact", "Questions about these terms? Email ammarfitwalla@gmail.com."]
  ];

  var PRIVACY = [
    ["What we collect", "Email address, name, company, position, and LinkedIn or other profile URLs (when you provide them), resumes you upload or paste, and technical data such as IP address, device type, browser, and pages visited."],
    ["How it's used", "To verify your email with login codes, run searches and AI scoring, match referrers to seekers, keep the Service working, and improve features."],
    ["Job searches", "Search terms, saved searches, and results are stored server-side so we can return earlier results and report aggregate statistics."],
    ["Resumes", "Resume text is used to score jobs, extract keywords, and \u2014 when you opt in as a referrer \u2014 to match you with seekers and pre-fill applications. A copy is also cached in your browser so you don't have to re-paste it on every visit."],
    ["Sharing", "We don't sell your data. If you opt in as a referrer, matched seekers can see and contact you. Verification emails are sent through our email provider, with a third-party email fallback."],
    ["Storage & retention", "Data is stored in our database and backed up regularly. We don't yet offer automated account deletion \u2014 email ammarfitwalla@gmail.com and we'll delete your data on request."],
    ["Security", "Traffic is encrypted (HTTPS) and requests are rate-limited to reduce abuse. No system is completely secure, so use good judgment about what you upload."],
    ["Your rights", "You can ask us to access, correct, or delete your data at any time by emailing ammarfitwalla@gmail.com."]
  ];

  var LABELS = {
    terms: "Terms & Conditions",
    privacy: "Privacy"
  };

  var overlay, bodyEl, titleEl, termsTab, privacyTab, contentEl, footerEl;
  var injected = false;

  function el(tag, style, text) {
    var node = document.createElement(tag);
    if (style) node.style.cssText = style;
    if (text != null) node.textContent = text;
    return node;
  }

  function renderSection(section) {
    titleEl.textContent = LABELS[section] || "Terms & Conditions";
    termsTab.style.background = section === "terms" ? "#0f172a" : "#fff";
    termsTab.style.color = section === "terms" ? "#fff" : "#64748b";
    termsTab.style.borderColor = section === "terms" ? "#0f172a" : "#e2e8f0";
    privacyTab.style.background = section === "privacy" ? "#0f172a" : "#fff";
    privacyTab.style.color = section === "privacy" ? "#fff" : "#64748b";
    privacyTab.style.borderColor = section === "privacy" ? "#0f172a" : "#e2e8f0";

    contentEl.innerHTML = "";
    (section === "privacy" ? PRIVACY : TERMS).forEach(function (point) {
      var item = el("div", "margin-bottom:16px");
      item.appendChild(el("div", "font-size:13.5px;font-weight:700;color:#0f172a;margin-bottom:3px", point[0]));
      item.appendChild(el("div", "font-size:13px;color:#475569;line-height:1.55", point[1]));
      contentEl.appendChild(item);
    });
  }

  function inject() {
    if (injected) return;
    injected = true;

    overlay = el("div", "position:fixed;inset:0;z-index:10000;background:rgba(15,23,42,0.55);" +
      "display:none;align-items:center;justify-content:center;padding:16px;box-sizing:border-box");
    overlay.addEventListener("click", function (e) {
      if (e.target === overlay) closeTerms();
    });

    var panel = el("div", "background:#fff;border-radius:16px;width:640px;max-width:100%;" +
      "max-height:85vh;display:flex;flex-direction:column;box-shadow:0 20px 60px rgba(0,0,0,0.25);overflow:hidden");

    var header = el("div", "display:flex;justify-content:space-between;align-items:center;" +
      "padding:20px 24px;border-bottom:1px solid #e2e8f0");
    titleEl = el("div", "font-size:17px;font-weight:800;color:#0f172a", LABELS.terms);
    var closeBtn = el("button", "background:none;border:none;font-size:22px;color:#94a3b8;cursor:pointer;line-height:1;padding:4px", "\u00d7");
    closeBtn.setAttribute("aria-label", "Close");
    closeBtn.addEventListener("click", closeTerms);
    header.appendChild(titleEl);
    header.appendChild(closeBtn);
    panel.appendChild(header);

    var tabs = el("div", "display:flex;gap:8px;padding:14px 24px 0");
    termsTab = el("button", "font-size:13px;font-weight:700;padding:6px 14px;border-radius:999px;" +
      "border:1px solid #0f172a;background:#0f172a;color:#fff;cursor:pointer", "Terms & Conditions");
    termsTab.textContent = "Terms & Conditions";
    termsTab.addEventListener("click", function () { renderSection("terms"); });
    privacyTab = el("button", "font-size:13px;font-weight:700;padding:6px 14px;border-radius:999px;" +
      "border:1px solid #e2e8f0;background:#fff;color:#64748b;cursor:pointer", "Privacy");
    privacyTab.addEventListener("click", function () { renderSection("privacy"); });
    tabs.appendChild(termsTab);
    tabs.appendChild(privacyTab);
    panel.appendChild(tabs);

    contentEl = el("div", "padding:16px 24px 20px;overflow-y:auto");
    panel.appendChild(contentEl);

    footerEl = el("div", "display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;" +
      "padding:12px 24px;border-top:1px solid #e2e8f0;font-size:11.5px;color:#94a3b8",
      "Effective: September 2026");
    footerEl.appendChild(el("span", "", "Questions? ammarfitwalla@gmail.com"));
    panel.appendChild(footerEl);

    overlay.appendChild(panel);
    document.body.appendChild(overlay);
  }

  function openTerms(section) {
    inject();
    renderSection(section === "privacy" ? "privacy" : "terms");
    overlay.style.display = "flex";
  }

  function closeTerms() {
    if (overlay) overlay.style.display = "none";
  }

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && overlay && overlay.style.display === "flex") closeTerms();
  });

  window.openTerms = function (section) { openTerms(section); };
  window.closeTerms = closeTerms;
})();