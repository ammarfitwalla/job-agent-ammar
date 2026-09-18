(function () {
  var countriesMap = {};
  var allStates = [];
  var allCities = [];

  var UNSUPPORTED_CC = {
    ru: "Russia", ir: "Iran", iq: "Iraq", kz: "Kazakhstan", jo: "Jordan",
    lb: "Lebanon", ke: "Kenya", gh: "Ghana", tz: "Tanzania", ug: "Uganda",
    et: "Ethiopia", dz: "Algeria", tn: "Tunisia", lk: "Sri Lanka", np: "Nepal",
    mm: "Myanmar", rs: "Serbia", by: "Belarus"
  };

  function _isUnsupported(cc) {
    return !!UNSUPPORTED_CC[(cc || "").toLowerCase()];
  }

  function _unsupportedNote(ctx, loc) {
    if (!loc || !_isUnsupported(loc.country_code)) return;
    var existing = document.getElementById("loc-unsupported-popup");
    if (existing) existing.remove();
    var box = document.createElement("div");
    box.id = "loc-unsupported-popup";
    box.className = "fixed inset-x-0 bottom-4 z-[9999] mx-auto max-w-md px-4";
    var inner = document.createElement("div");
    inner.className = "relative rounded-xl border border-amber-300 bg-amber-50 p-4 shadow-xl";
    inner.innerHTML =
      '<button type="button" class="absolute right-2 top-2 text-amber-500 hover:text-amber-700 text-sm font-bold leading-none" aria-label="Dismiss">&times;</button>' +
      '<div class="flex items-start gap-2 text-amber-800">' +
      '<svg class="w-5 h-5 mt-0.5 shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>' +
      '<div><p class="font-semibold text-sm">Job results for ' + (UNSUPPORTED_CC[(loc.country_code || "").toLowerCase()] || loc.country) + ' are not supported by our Indeed source.</p>' +
      '<p class="text-xs mt-1 text-amber-700">You may still get a few results from LinkedIn. Countries not supported: Russia, Iran, Iraq, Kazakhstan, Jordan, Lebanon, Kenya, Ghana, Tanzania, Uganda, Ethiopia, Algeria, Tunisia, Sri Lanka, Nepal, Myanmar, Serbia, Belarus.</p>' +
      '</div></div>';
    box.appendChild(inner);
    inner.querySelector("button").addEventListener("click", function () { box.remove(); });
    document.body.appendChild(box);
  }

  function fetchCountries() {
    return fetch("https://api.countrystatecity.in/v1/countries", {
      headers: { "X-CSCAPI-KEY": "99b742739363f29d601908be8af875f40eede6b161f6b455da3e85b8373ccc45" }
    }).then(function (r) { return r.json(); }).then(function (data) {
      data.forEach(function (c) { countriesMap[c.iso2.toLowerCase()] = c.name; });
    }).catch(function () {});
  }

  function loadStates() {
    return fetch("/states").then(function (r) { return r.json(); }).then(function (d) {
      allStates = d.states || [];
    }).catch(function () {});
  }

  var _statesPromise = null;
  function ensureStates() {
    if (!_statesPromise) {
      _statesPromise = Promise.all([fetchCountries(), loadStates()]).catch(function () {});
    }
    return _statesPromise;
  }

  function whenReady(cb) {
    ensureStates().then(function () { try { cb(); } catch (e) {} });
  }

  function citiesFor(cc, q0) {
    var url = cc
      ? "/cities?country=" + encodeURIComponent(cc) + "&q=" + encodeURIComponent(q0)
      : "/cities?q=" + encodeURIComponent(q0);
    return fetch(url).then(function (r) { return r.json(); }).then(function (d) {
      allCities = d.cities || [];
      return allCities.slice(0, 4).map(function (c) {
        return { city: c.city, state: c.state, country: c.country, country_code: c.country_code,
                 label: [c.city, c.state, c.country].filter(Boolean).join(", ") };
      });
    }).catch(function () { return []; });
  }

  function renderMatch(ctx, item) {
    var div = document.createElement("div");
    var unsupported = _isUnsupported(item.country_code);
    div.className = "px-4 py-2.5 text-xs cursor-pointer hover:bg-slate-50 text-slate-700 border-b border-slate-50 last:border-0 font-medium transition-colors";
    div.textContent = item.label + (unsupported ? " — not supported by Indeed" : "");
    if (unsupported) div.style.color = "#b45309";
    div.addEventListener("mousedown", function (e) {
      e.preventDefault();
      selectLocation(ctx, { city: item.city || "", state: item.state, country: item.country, country_code: item.country_code, label: item.label });
    });
    return div;
  }

  async function searchState(ctx, query) {
    if (query === ctx.lastQuery) return;
    ctx.lastQuery = query;
    ctx.results.innerHTML = "";
    var lower = query.toLowerCase();
    var segs = lower.split(",").map(function (s) { return s.trim(); }).filter(Boolean);

    var countryMatches = [], cc = null;
    Object.keys(countriesMap).forEach(function (code) {
      var name = countriesMap[code];
      if (name.toLowerCase() === lower || code === lower) {
        if (!cc) cc = code;
        countryMatches.push({ state: null, country: name, country_code: code, label: name });
      }
    });
    if (!cc) {
      Object.keys(countriesMap).forEach(function (code) {
        var n2 = countriesMap[code].toLowerCase();
        if (segs.some(function (seg) { return seg === n2 || seg === code; })) { cc = code; }
      });
    }
    if (!countryMatches.length && lower.length >= 2) {
      var countryToken = segs.length > 1 ? segs[segs.length - 1] : lower;
      Object.keys(countriesMap).forEach(function (code) {
        var name = countriesMap[code];
        if (name.toLowerCase().startsWith(countryToken)) {
          countryMatches.push({ state: null, country: name, country_code: code, label: name });
        }
      });
      if (!cc && countryMatches.length === 1) cc = countryMatches[0].country_code;
    }

    var topCountries = countryMatches.slice(0, 6);
    var cityMatches = [];
    var exactCountry = countryMatches.length > 0;
    var exactState = allStates.some(function (s) { return s.state.toLowerCase() === lower; });
    var q0 = (segs[0] || lower).slice(0, 40);
    if (cc) {
      cityMatches = await citiesFor(cc, q0);
    } else if (!exactCountry && !exactState) {
      cityMatches = await citiesFor(null, q0);
    }

    var count = Math.max(0, 6 - topCountries.length - cityMatches.length);
    var stateMatches = [];
    if (allStates.length) {
      stateMatches = allStates
        .filter(function (s) {
          var sl = s.state.toLowerCase();
          return sl.includes(lower) || (segs.length > 1 && segs.some(function (seg) { return seg.length >= 3 && sl.includes(seg); }));
        })
        .slice(0, count)
        .map(function (item) {
          return { state: item.state, country: item.country, country_code: item.country_code,
                   label: [item.state, item.country].filter(Boolean).join(", ") };
        });
    }

    var matches = topCountries.concat(cityMatches).concat(stateMatches);
    if (!matches.length) {
      ctx.results.innerHTML = '<div class="px-4 py-3 text-xs text-slate-400">No matching locations</div>';
      ctx.results.classList.remove("hidden");
      return;
    }
    matches.forEach(function (item) { ctx.results.appendChild(renderMatch(ctx, item)); });
    ctx.results.classList.remove("hidden");
  }

  function clearChip(ctx, keepInput) {
    ctx.setCur(null);
    ctx.selected.classList.add("hidden");
    ctx.selected.innerHTML = "";
    if (!keepInput) ctx.input.value = "";
    try { ctx.onClear(); } catch (e) {}
  }

  function renderChip(ctx, loc) {
    ctx.selected.innerHTML = "";
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "w-3 h-3 text-emerald-600");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.innerHTML = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>';
    var span = document.createElement("span");
    span.textContent = loc.label;
    if (_isUnsupported(loc.country_code)) {
      span.style.color = "#b45309";
      span.textContent += " (limited)";
    }
    var btn = document.createElement("button");
    btn.setAttribute("class", "ml-1 text-emerald-600/60 hover:text-emerald-800");
    btn.innerHTML = '<svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>';
    btn.addEventListener("click", function () { clearChip(ctx, false); });
    ctx.selected.appendChild(svg);
    ctx.selected.appendChild(span);
    ctx.selected.appendChild(btn);
    ctx.selected.classList.remove("hidden");
  }

  function selectLocation(ctx, loc) {
    ctx.setCur(loc);
    ctx.input.value = loc.label;
    ctx.results.classList.add("hidden");
    renderChip(ctx, loc);
    _unsupportedNote(ctx, loc);
    try { ctx.onSelect(); } catch (e) {}
  }

  function resolve(text) {
    if (!text) return null;
    var lower = text.toLowerCase();
    var best = null;
    for (var i = 0; i < allStates.length; i++) {
      var s = allStates[i];
      var sl = s.state.toLowerCase();
      if (sl === lower) return s;
      if (!best && lower.includes(sl)) best = s;
    }
    if (best) return best;
    for (var j = 0; j < allCities.length; j++) {
      var c = allCities[j];
      if (c.city.toLowerCase() === lower) {
        return { city: c.city, state: c.state, country: c.country, country_code: c.country_code };
      }
    }
for (var code in countriesMap) {
    if (countriesMap[code].toLowerCase() === lower || code === lower) {
      return { state: "", country: countriesMap[code], country_code: code };
    }
  }
  if (lower.length >= 2) {
    var codeMatches = [];
    for (var code2 in countriesMap) {
      if (countriesMap[code2].toLowerCase().startsWith(lower)) codeMatches.push(code2);
    }
    if (codeMatches.length === 1) {
      return { state: "", country: countriesMap[codeMatches[0]], country_code: codeMatches[0] };
    }
  }
  return null;
}

  function setValue(ctx, label, structured) {
    var loc = null;
    if (structured) {
      loc = { city: structured.city || "", state: structured.state || "", country: structured.country || "",
              country_code: structured.country_code || "", label: label };
    } else {
      var parts = (label || "").split(",").map(function (s) { return s.trim(); }).filter(Boolean);
      loc = resolve(parts.length ? parts[parts.length - 1] : label) || null;
      if (loc) loc.label = label;
    }
    ctx.setCur(loc);
    ctx.input.value = label;
    ctx.results.classList.add("hidden");
    renderChip(ctx, loc);
  }

  function init(opts) {
    var input = document.getElementById(opts.inputId);
    var results = document.getElementById(opts.resultsId);
    var selected = document.getElementById(opts.selectedId);
    var ctx = {
      input: input,
      results: results,
      selected: selected,
      lastQuery: "",
      cur: null,
      searchTimeout: null,
      onSelect: opts.onSelect || function () {},
      onClear: opts.onClear || function () {},
      onChange: opts.onChange || function () {},
      getCur: function () { return ctx.cur; },
      setCur: function (v) { ctx.cur = v; },
    };

    input.addEventListener("input", function () {
      var q = input.value.trim();
      if (ctx.cur) {
        ctx.cur = null;
        selected.classList.add("hidden");
      }
      try { ctx.onChange(); } catch (e) {}
      if (q.length < 2) { results.classList.add("hidden"); return; }
      clearTimeout(ctx.searchTimeout);
      ctx.searchTimeout = setTimeout(function () { searchState(ctx, q); }, 200);
    });
    input.addEventListener("blur", function () {
      setTimeout(function () { results.classList.add("hidden"); }, 200);
    });
    input.addEventListener("focus", function () {
      if (results.children.length) results.classList.remove("hidden");
    });

    ensureStates();
    return {
      getSelected: function () { return ctx.cur; },
      resolve: function (text) { return resolve(text); },
      getData: function () { return { countries: countriesMap, states: allStates, cities: allCities }; },
      whenReady: whenReady,
      setValue: function (label, structured) { setValue(ctx, label, structured); },
      clear: function () { clearChip(ctx, false); },
    };
  }

  window.LocationPicker = window.LocationPicker || { init: init, whenReady: whenReady };
})();