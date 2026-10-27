/* OpenScores leaderboard front-end. Plain JS, no dependencies. */
(function () {
  "use strict";

  var SCORE_KEYS = ["overall", "maturity", "health", "popularity", "risk", "sustainability"];
  var LABELS = {
    overall: "Overall", maturity: "Maturity", health: "Health", popularity: "Popularity",
    risk: "Risk", sustainability: "Sustainability"
  };
  var COMPONENT_LABELS = {
    maturity: { age: "Project age", releases: "Release discipline", documentation: "Documentation", governance: "Governance files", ci_tests: "CI & tests", maintainers: "Maintainer base", versioning: "Versioning", compatibility: "Backward compatibility" },
    health: { commit_activity: "Commit activity", issue_response: "Issue responsiveness", pr_response: "PR responsiveness", issue_closure: "Issue closure rate", pr_merge: "PR merge rate", backlog: "Backlog pressure", contributor_diversity: "Contributor diversity", release_freshness: "Release freshness", ci_reliability: "CI reliability" },
    popularity: { stars: "Stars", star_growth: "Star growth (90d)", forks: "Forks", fork_growth: "Fork growth (90d)", watchers: "Watchers", contributors: "Contributor reach", external_engagement: "External engagement" },
    risk: { bus_factor: "Bus factor", concentration: "Maintainer concentration", commit_staleness: "Commit staleness", release_staleness: "Release staleness", security: "No security policy", stale_issues: "Stale issue ratio", ownership: "Individual ownership", archived: "Archived" },
    sustainability: { maintainers: "Active maintainers", maintainer_diversity: "Maintainer diversity", retention: "Contributor retention", sponsorship: "Sponsorship / funding", org_backing: "Organization backing", governance: "Governance", release_consistency: "Release consistency", workload: "Maintainer workload" }
  };
  var METRIC_ROWS = [
    ["stars", "Stars"], ["stars_90d", "New stars (90d)"], ["forks", "Forks"], ["forks_90d", "New forks (90d)"],
    ["watchers", "Watchers"], ["contributors_total", "Contributors (all time)"],
    ["active_contributors_90d", "Active contributors (90d)"], ["active_maintainers_180d", "Active maintainers (180d)"],
    ["bus_factor", "Bus factor"], ["top_contributor_share", "Top contributor share", "pct"],
    ["commits_90d", "Commits (90d)"], ["days_since_commit", "Days since last commit", "days"],
    ["releases_12m", "Releases (12m)"], ["days_since_release", "Days since last release", "days"],
    ["issues_opened_90d", "Issues opened (90d)"], ["issues_closed_90d", "Issues closed (90d)"], ["open_issues", "Open issues"],
    ["stale_open_issues", "Stale open issues (180d)"], ["prs_opened_90d", "PRs opened (90d)"], ["prs_merged_90d", "PRs merged (90d)"],
    ["median_issue_response_hours", "Median issue first response", "hours"], ["median_pr_response_hours", "Median PR first response", "hours"],
    ["ci_success_rate", "CI success rate (90d)", "pct"], ["external_engagement_90d", "External issues + PRs (90d)"],
    ["contributor_retention", "Contributor retention", "pct"], ["breaking_changes_12m", "Breaking-change signals (12m)"],
    ["age_months", "Age (months)", "int"]
  ];
  var FLAGS = [
    ["has_license", "License"], ["has_contributing", "Contributing guide"], ["has_code_of_conduct", "Code of conduct"],
    ["has_security_policy", "Security policy"], ["has_issue_templates", "Issue templates"], ["has_ci", "CI configured"],
    ["has_tests", "Tests"], ["has_changelog", "Changelog"], ["uses_semver", "SemVer tags"], ["has_install_docs", "Install docs"],
    ["has_examples", "Examples"], ["has_api_docs", "API / docs site"], ["has_troubleshooting", "Troubleshooting / FAQ"],
    ["has_sponsorship", "Sponsorship"], ["owner_is_org", "Org-owned"], ["is_archived", "Archived"]
  ];

  var board = null, history = null, projects = [];
  var state = { q: "", category: "", language: "", sort: "overall", dir: "desc", selected: null };
  var $ = function (id) { return document.getElementById(id); };

  // ---------------------------------------------------------------- utils
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function fmtInt(n) { if (n == null) return "—"; return Number(n).toLocaleString("en-US"); }
  function fmtCompact(n) {
    if (n == null) return "—";
    n = Number(n);
    if (n >= 1e6) return (n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(n >= 1e4 ? 0 : 1) + "k";
    return String(Math.round(n));
  }
  function fmtMetric(v, kind) {
    if (v == null) return "—";
    if (kind === "pct") return Math.round(v * 100) + "%";
    if (kind === "days") return v < 1 ? "<1" : Math.round(v).toLocaleString("en-US");
    if (kind === "hours") return v < 48 ? Math.round(v) + " h" : Math.round(v / 24) + " d";
    if (kind === "int") return Math.round(v).toLocaleString("en-US");
    return typeof v === "number" ? fmtInt(Math.round(v)) : String(v);
  }
  function fmtDate(iso) {
    if (!iso) return "—";
    var d = new Date(iso);
    return d.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }
  function scoreCell(p, key) {
    var v = p.scores[key];
    var risk = key === "risk";
    var delta = "";
    if (key === "overall" && p.delta_7d && typeof p.delta_7d.overall === "number") {
      var d = p.delta_7d.overall;
      var cls = d > 0.05 ? "up" : d < -0.05 ? "down" : "flat";
      var glyph = d > 0.05 ? "▲" : d < -0.05 ? "▼" : "•";
      delta = '<span class="d"><span class="delta ' + cls + '" style="margin:0" title="Change over 7 days">' + glyph + " " + Math.abs(d).toFixed(1) + " · 7d</span></span>";
    }
    return '<div class="score ' + key + '"><span class="v">' + v.toFixed(0) + '</span>' +
      '<div class="meter' + (risk ? " risk" : "") + '" role="img" aria-label="' + LABELS[key] + " " + v + ' out of 100"><i style="width:' + Math.max(0, Math.min(100, v)) + '%"></i></div>' + delta + '</div>';
  }
  function starsCell(p) {
    var delta = "";
    if (p.delta_7d && typeof p.delta_7d.stars === "number" && p.delta_7d.stars !== 0) {
      var d = p.delta_7d.stars;
      delta = '<span class="delta ' + (d > 0 ? "up" : "down") + '" title="Stars gained over 7 days">' + (d > 0 ? "▲" : "▼") + " " + fmtCompact(Math.abs(d)) + "</span>";
    }
    return '<span title="' + fmtInt(p.metrics.stars) + ' stars">' + fmtCompact(p.metrics.stars) + "</span>" + delta;
  }

  // ---------------------------------------------------------------- render
  function renderTiles() {
    var n = projects.length;
    var avg = function (k) { return n ? projects.reduce(function (a, p) { return a + p.scores[k]; }, 0) / n : 0; };
    var totalStars = projects.reduce(function (a, p) { return a + (p.metrics.stars || 0); }, 0);
    var movers = projects.filter(function (p) { return p.delta_7d && p.delta_7d.overall > 0; }).length;
    var top = projects.slice().sort(function (a, b) { return b.scores.overall - a.scores.overall; })[0];
    $("tiles").innerHTML = [
      tile("Projects tracked", fmtInt(n), "open source AI on GitHub"),
      tile("Combined stars", fmtCompact(totalStars), "across all tracked projects"),
      tile("Average health", avg("health").toFixed(1), "0–100, last " + board.window_days + " days"),
      tile("Average maturity", avg("maturity").toFixed(1), "0–100"),
      tile("Improved this week", fmtInt(movers), history ? "overall score up vs 7 days ago" : "needs ≥ 7 days of history"),
      tile("Top project", top ? esc(top.name) : "—", top ? "Overall " + top.scores.overall.toFixed(1) : "")
    ].join("");
  }
  function tile(label, value, sub) {
    return '<div class="tile"><div class="label">' + label + '</div><div class="value">' + value + '</div><div class="sub">' + sub + "</div></div>";
  }

  function visibleProjects() {
    var q = state.q.trim().toLowerCase();
    var list = projects.filter(function (p) {
      if (state.category && p.category !== state.category) return false;
      if (state.language && p.language !== state.language) return false;
      if (!q) return true;
      var hay = (p.full_name + " " + (p.description || "") + " " + (p.topics || []).join(" ") + " " + (p.language || "")).toLowerCase();
      return hay.indexOf(q) !== -1;
    });
    var key = state.sort, dir = state.dir === "asc" ? 1 : -1;
    list.sort(function (a, b) {
      var va = sortValue(a, key), vb = sortValue(b, key);
      if (typeof va === "string") return va.localeCompare(vb) * dir;
      if (va === vb) return a.rank - b.rank;
      return (va > vb ? 1 : -1) * dir;
    });
    return list;
  }
  function sortValue(p, key) {
    if (key === "rank") return p.rank;
    if (key === "name") return p.name.toLowerCase();
    if (key === "category") return p.category;
    if (key === "stars") return p.metrics.stars || 0;
    if (key === "delta") return p.delta_7d ? p.delta_7d.overall : -Infinity;
    return p.scores[key];
  }

  function renderTable() {
    var list = visibleProjects();
    $("count").textContent = list.length + " of " + projects.length + " projects";
    $("empty").hidden = list.length > 0;
    var html = list.map(function (p) {
      var chips = (p.topics || []).slice(0, 4).map(function (t) { return '<span class="chip">' + esc(t) + "</span>"; }).join("");
      return '<tr tabindex="0" data-id="' + esc(p.full_name) + '">' +
        '<td class="rank">' + p.rank + "</td>" +
        '<td class="proj"><div class="name"><span class="owner">' + esc(p.owner) + " / </span>" + esc(p.name) + "</div>" +
        '<div class="desc" title="' + esc(p.description) + '">' + esc(p.description) + "</div>" + chips + "</td>" +
        '<td class="cat">' + esc(p.category) + "</td>" +
        '<td class="num">' + starsCell(p) + "</td>" +
        "<td>" + scoreCell(p, "overall") + "</td>" +
        "<td>" + scoreCell(p, "maturity") + "</td>" +
        "<td>" + scoreCell(p, "health") + "</td>" +
        "<td>" + scoreCell(p, "popularity") + "</td>" +
        "<td>" + scoreCell(p, "risk") + "</td>" +
        "<td>" + scoreCell(p, "sustainability") + "</td>" +
        "</tr>";
    }).join("");
    $("rows").innerHTML = html;
    var ths = document.querySelectorAll("thead th");
    for (var i = 0; i < ths.length; i++) {
      var th = ths[i];
      var active = th.getAttribute("data-sort") === state.sort || (state.sort === "delta" && th.getAttribute("data-sort") === "overall");
      th.setAttribute("aria-sort", active ? (state.dir === "asc" ? "ascending" : "descending") : "none");
      var label = th.textContent.replace(/[▲▼]\s*$/, "").trim();
      th.innerHTML = esc(label) + (active ? ' <span class="arrow">' + (state.dir === "asc" ? "▲" : "▼") + "</span>" : "");
    }
  }

  // ---------------------------------------------------------------- drawer
  function sparkline(series, key) {
    if (!series || series.length < 2) return '<div class="spark-cap">Trend appears once the collector has run on more than one day.</div>';
    var w = 320, h = 64, pad = 4;
    var vals = series.map(function (pt) { return pt[key]; });
    var min = Math.min.apply(null, vals), max = Math.max.apply(null, vals);
    if (max - min < 4) { var mid = (max + min) / 2; min = mid - 2; max = mid + 2; }
    var x = function (i) { return pad + (i / (series.length - 1)) * (w - 2 * pad); };
    var y = function (v) { return h - pad - ((v - min) / (max - min)) * (h - 2 * pad); };
    var pts = vals.map(function (v, i) { return x(i).toFixed(1) + "," + y(v).toFixed(1); });
    var last = series[series.length - 1], first = series[0];
    return '<svg class="spark" viewBox="0 0 ' + w + " " + h + '" preserveAspectRatio="none" role="img" aria-label="' + LABELS[key] + " from " + first[key] + " on " + first.d + " to " + last[key] + " on " + last.d + '">' +
      '<line class="axis" x1="0" y1="' + (h - pad) + '" x2="' + w + '" y2="' + (h - pad) + '"/>' +
      '<polygon class="area" points="' + x(0).toFixed(1) + "," + (h - pad) + " " + pts.join(" ") + " " + x(vals.length - 1).toFixed(1) + "," + (h - pad) + '"/>' +
      '<polyline class="line" points="' + pts.join(" ") + '"/>' +
      '<circle class="dot" r="3.5" cx="' + x(vals.length - 1).toFixed(1) + '" cy="' + y(last[key]).toFixed(1) + '"/>' +
      "</svg><div class=\"spark-cap\">" + series.length + " daily points · " + first.d + " → " + last.d + "</div>";
  }

  function componentSection(p, key) {
    var comps = p.scores.components[key], weights = board.weights[key], labels = COMPONENT_LABELS[key];
    var risk = key === "risk";
    var rows = Object.keys(weights).map(function (k) {
      var v = comps[k];
      return '<div class="row"><span class="k">' + esc(labels[k] || k) + '</span>' +
        '<div class="meter' + (risk ? " risk" : "") + '"><i style="width:' + Math.max(0, Math.min(100, v)) + '%"></i></div>' +
        '<span class="w">×' + weights[k].toFixed(2) + '</span><span class="v">' + v.toFixed(0) + "</span></div>";
    }).join("");
    return '<details class="section"' + (key === "maturity" ? " open" : "") + '><summary><span>' + LABELS[key] + " components</span>" +
      '<span class="sum">' + p.scores[key].toFixed(1) + " · " + esc(p.bands[key]) + "</span></summary><div class=\"comp\">" + rows + "</div></details>";
  }

  function openProject(id, push) {
    var p = null;
    for (var i = 0; i < projects.length; i++) if (projects[i].full_name === id) { p = projects[i]; break; }
    if (!p) return;
    state.selected = id;
    var m = p.metrics;
    var cards = ["maturity", "health", "popularity", "risk", "sustainability"].map(function (k) {
      return '<div class="card"><div class="label">' + LABELS[k] + '</div><div class="value">' + p.scores[k].toFixed(0) + '</div><div class="band">' + esc(p.bands[k]) + "</div></div>";
    }).join("");
    var series = history ? history[p.full_name] : null;
    var flags = FLAGS.map(function (f) { return '<span class="chip" title="' + f[1] + '">' + (m[f[0]] ? "✓ " : "✗ ") + f[1] + "</span>"; }).join("");
    var metricRows = METRIC_ROWS.map(function (r) {
      var note = "";
      if (r[0] === "stars_90d" && m.stars_90d_estimated) note = ' <span class="flag">est.</span>';
      if (r[0] === "forks_90d" && m.forks_90d_estimated) note = ' <span class="flag">est.</span>';
      return "<tr><td>" + r[1] + "</td><td>" + fmtMetric(m[r[0]], r[2]) + note + "</td></tr>";
    }).join("");
    $("drawer").innerHTML =
      '<div class="drawer-head"><div><h2>' + esc(p.name) + " <small>" + esc(p.owner) + "</small></h2>" +
      '<div class="desc">' + esc(p.description || "") + "</div></div>" +
      '<button class="icon-btn" id="close" type="button" aria-label="Close">✕</button></div>' +
      '<div class="meta"><span>#' + p.rank + " overall</span><span>" + esc(p.category) + "</span>" +
      (p.language ? "<span>" + esc(p.language) + "</span>" : "") + (p.license ? "<span>" + esc(p.license) + "</span>" : "") +
      '<a href="' + esc(p.url) + '" target="_blank" rel="noopener">GitHub ↗</a>' +
      (p.homepage ? '<a href="' + esc(p.homepage) + '" target="_blank" rel="noopener">Website ↗</a>' : "") + "</div>" +
      '<div class="cards"><div class="card overall"><div><div class="label">Overall White Score</div><div class="value">' + p.scores.overall.toFixed(1) + "</div>" +
      '<div class="band">Mean of maturity, health and popularity</div></div><div>' + sparkline(series, "o") + "</div></div>" + cards + "</div>" +
      componentSection(p, "maturity") + componentSection(p, "health") + componentSection(p, "popularity") +
      componentSection(p, "risk") + componentSection(p, "sustainability") +
      '<details class="section"><summary><span>Raw metrics</span><span class="sum">collected ' + fmtDate(m.collected_at) + '</span></summary><div class="comp">' +
      '<div style="margin:6px 0 10px">' + flags + "</div><table class=\"metrics\">" + metricRows + "</table>" +
      (m.commit_sample_truncated ? '<p class="flag">Commit-based people metrics use the most recent ' + m.commit_sample_size + " commits of the 180-day window.</p>" : "") +
      "</div></details>" +
      '<p class="flag" style="margin-top:14px">Topics: ' + esc((p.topics || []).join(", ") || "none") + "</p>";
    document.body.classList.add("open");
    $("drawer").setAttribute("aria-hidden", "false");
    $("close").onclick = closeDrawer;
    $("drawer").scrollTop = 0;
    if (push !== false) history_push(id);
  }
  function closeDrawer() {
    document.body.classList.remove("open");
    $("drawer").setAttribute("aria-hidden", "true");
    state.selected = null;
    if (location.hash) window.history.replaceState(null, "", location.pathname + location.search);
  }
  function history_push(id) {
    window.history.replaceState(null, "", "#" + encodeURIComponent(id));
  }

  // ---------------------------------------------------------------- wiring
  function wire() {
    $("q").addEventListener("input", function (e) { state.q = e.target.value; renderTable(); });
    $("category").addEventListener("change", function (e) { state.category = e.target.value; renderTable(); });
    $("language").addEventListener("change", function (e) { state.language = e.target.value; renderTable(); });
    $("sort").addEventListener("change", function (e) {
      state.sort = e.target.value; state.dir = state.sort === "risk" || state.sort === "name" || state.sort === "category" ? "asc" : "desc"; renderTable();
    });
    document.querySelector("thead").addEventListener("click", function (e) {
      var th = e.target.closest("th"); if (!th) return;
      var key = th.getAttribute("data-sort");
      if (state.sort === key) state.dir = state.dir === "asc" ? "desc" : "asc";
      else { state.sort = key; state.dir = (key === "rank" || key === "name" || key === "category" || key === "risk") ? "asc" : "desc"; }
      $("sort").value = SCORE_KEYS.indexOf(key) !== -1 || key === "stars" ? key : "overall";
      renderTable();
    });
    $("rows").addEventListener("click", function (e) { var tr = e.target.closest("tr"); if (tr) openProject(tr.getAttribute("data-id")); });
    $("rows").addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { var tr = e.target.closest("tr"); if (tr) { e.preventDefault(); openProject(tr.getAttribute("data-id")); } }
    });
    $("scrim").addEventListener("click", closeDrawer);
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeDrawer(); });
    window.addEventListener("hashchange", function () {
      var id = decodeURIComponent(location.hash.slice(1));
      if (id && id !== state.selected) openProject(id, false);
      else if (!id && state.selected) closeDrawer();
    });
    $("theme").addEventListener("click", function () {
      var root = document.documentElement;
      var dark = root.getAttribute("data-theme") === "dark" || (!root.getAttribute("data-theme") && window.matchMedia("(prefers-color-scheme: dark)").matches);
      root.setAttribute("data-theme", dark ? "light" : "dark");
      try { localStorage.setItem("theme", dark ? "light" : "dark"); } catch (err) { /* ignore */ }
    });
  }

  function fillSelect(id, values) {
    var sel = $(id);
    values.forEach(function (v) { var o = document.createElement("option"); o.value = v; o.textContent = v; sel.appendChild(o); });
  }

  function init() {
    try { var t = localStorage.getItem("theme"); if (t) document.documentElement.setAttribute("data-theme", t); } catch (err) { /* ignore */ }
    wire();
    fetch("data/leaderboard.json", { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); }).then(function (data) {
      board = data;
      projects = data.projects || [];
      if (data.sample) {
        $("banner").hidden = false;
        $("banner").textContent = "Sample data: these scores were generated from synthetic metrics for development. Run the collector with a GitHub token to populate real scores.";
      }
      fillSelect("category", data.categories || []);
      var langs = {}; projects.forEach(function (p) { if (p.language) langs[p.language] = 1; });
      fillSelect("language", Object.keys(langs).sort());
      $("foot").innerHTML = "Last refreshed " + fmtDate(data.generated_at) + " · " + fmtInt(data.project_count) + " projects · collector v" + esc(data.version) +
        (data.failures && data.failures.length ? " · " + data.failures.length + " repositories could not be collected" : "") +
        ' · <a href="methodology.html">How scores are computed</a>';
      renderTiles();
      renderTable();
      return fetch("data/history.json", { cache: "no-cache" }).then(function (r) { return r.ok ? r.json() : {}; }).catch(function () { return {}; });
    }).then(function (h) {
      history = h || {};
      renderTiles();
      var id = decodeURIComponent(location.hash.slice(1));
      if (id) openProject(id, false);
    }).catch(function (err) {
      $("banner").hidden = false;
      $("banner").textContent = "Could not load data/leaderboard.json (" + err.message + "). Run the collector first: python -m whitescore";
    });
  }
  init();
})();
