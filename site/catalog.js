/* OpenScores catalog page: every discovered open source AI repo, categorized. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var PAGE = 200;
  var all = [], catalog = null;
  var state = { q: "", category: "", language: "", sort: "stars", lists: false, adjacent: false, shown: PAGE };

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function fmtInt(n) { return n == null ? "—" : Number(n).toLocaleString("en-US"); }
  function fmtCompact(n) { n = Number(n || 0); if (n >= 1e6) return (n / 1e6).toFixed(1) + "M"; if (n >= 1e3) return (n / 1e3).toFixed(n >= 1e4 ? 0 : 1) + "k"; return String(n); }
  function ago(iso) {
    if (!iso) return "—";
    var days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
    if (days < 1) return "today"; if (days < 30) return days + "d ago"; if (days < 365) return Math.floor(days / 30) + "mo ago"; return (days / 365).toFixed(1) + "y ago";
  }
  function tile(label, value, sub) { return '<div class="tile"><div class="label">' + label + '</div><div class="value">' + value + '</div><div class="sub">' + sub + "</div></div>"; }

  function visible() {
    var q = state.q.trim().toLowerCase();
    return all.filter(function (p) {
      if (!include(p)) return false;
      if (state.category && p.c !== state.category) return false;
      if (state.language && p.l !== state.language) return false;
      if (!q) return true;
      return (p.n + " " + (p.d || "") + " " + (p.t || []).join(" ")).toLowerCase().indexOf(q) !== -1;
    }).sort(function (a, b) {
      if (state.sort === "name") return a.n.toLowerCase().localeCompare(b.n.toLowerCase());
      if (state.sort === "pushed") return (b.p || "").localeCompare(a.p || "");
      if (state.sort === "created") return (b.cr || "").localeCompare(a.cr || "");
      if (state.sort === "forks") return (b.f || 0) - (a.f || 0);
      return (b.s || 0) - (a.s || 0);
    });
  }

  function include(p) {
    if (p.list) return state.lists;
    if (p.sig < 2) return state.adjacent;
    return true;
  }

  function renderCats() {
    var counts = {}, total = 0;
    all.forEach(function (p) { if (!include(p)) return; counts[p.c] = (counts[p.c] || 0) + 1; total++; });
    var names = Object.keys(counts).sort(function (a, b) { return counts[b] - counts[a]; });
    var html = '<button type="button" class="cat-btn' + (state.category ? "" : " active") + '" data-cat=""><span>All categories</span><b>' + fmtInt(total) + "</b></button>";
    names.forEach(function (n) {
      html += '<button type="button" class="cat-btn' + (state.category === n ? " active" : "") + '" data-cat="' + esc(n) + '"><span>' + esc(n) + "</span><b>" + fmtInt(counts[n]) + "</b></button>";
    });
    $("cats").innerHTML = html;
  }

  function renderRows() {
    var list = visible();
    $("count").textContent = fmtInt(list.length) + " projects";
    $("empty").hidden = list.length > 0;
    var slice = list.slice(0, state.shown);
    $("rows").innerHTML = slice.map(function (p, i) {
      var parts = p.n.split("/");
      var chips = (p.t || []).slice(0, 5).map(function (t) { return '<span class="chip">' + esc(t) + "</span>"; }).join("");
      var flag = p.list ? ' <span class="chip">list</span>' : (p.sig < 2 ? ' <span class="chip" title="Weak AI signal: tagged with a generic topic only">adjacent</span>' : "");
      return "<tr>" +
        '<td class="rank">' + (i + 1) + "</td>" +
        '<td class="proj"><div class="name"><a href="https://github.com/' + esc(p.n) + '" target="_blank" rel="noopener"><span class="owner">' + esc(parts[0]) + " / </span>" + esc(parts[1]) + "</a>" + flag + "</div>" +
        '<div class="desc" title="' + esc(p.d) + '">' + esc(p.d) + "</div>" + chips + "</td>" +
        '<td class="cat">' + esc(p.c) + "</td>" +
        '<td class="num" title="' + fmtInt(p.s) + '">' + fmtCompact(p.s) + "</td>" +
        '<td class="num">' + fmtCompact(p.f) + "</td>" +
        "<td>" + esc(p.l || "—") + "</td>" +
        '<td class="cat">' + esc(p.lic || "none") + "</td>" +
        '<td class="cat" title="' + esc(p.p) + '">' + ago(p.p) + "</td></tr>";
    }).join("");
    $("more").hidden = list.length <= state.shown;
    $("more").textContent = "Show more (" + fmtInt(Math.min(PAGE, list.length - state.shown)) + " of " + fmtInt(list.length - state.shown) + " remaining)";
  }

  function render() { renderCats(); renderRows(); }

  function wire() {
    $("q").addEventListener("input", function (e) { state.q = e.target.value; state.shown = PAGE; renderRows(); });
    $("language").addEventListener("change", function (e) { state.language = e.target.value; state.shown = PAGE; renderRows(); });
    $("sort").addEventListener("change", function (e) { state.sort = e.target.value; renderRows(); });
    $("lists").addEventListener("change", function (e) { state.lists = e.target.checked; state.shown = PAGE; render(); });
    $("adjacent").addEventListener("change", function (e) { state.adjacent = e.target.checked; state.shown = PAGE; render(); });
    $("cats").addEventListener("click", function (e) {
      var b = e.target.closest(".cat-btn"); if (!b) return;
      state.category = b.getAttribute("data-cat"); state.shown = PAGE; render();
      window.history.replaceState(null, "", state.category ? "#" + encodeURIComponent(state.category) : location.pathname);
    });
    $("more").addEventListener("click", function () { state.shown += PAGE; renderRows(); });
    $("theme").addEventListener("click", function () {
      var root = document.documentElement;
      var dark = root.getAttribute("data-theme") === "dark" || (!root.getAttribute("data-theme") && window.matchMedia("(prefers-color-scheme: dark)").matches);
      root.setAttribute("data-theme", dark ? "light" : "dark");
      try { localStorage.setItem("theme", dark ? "light" : "dark"); } catch (err) { /* ignore */ }
    });
  }

  function init() {
    try { var t = localStorage.getItem("theme"); if (t) document.documentElement.setAttribute("data-theme", t); } catch (err) { /* ignore */ }
    wire();
    fetch("data/catalog-web.json", { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); }).then(function (data) {
      catalog = data; all = data.projects || [];
      var langs = {}; all.forEach(function (p) { if (p.l) langs[p.l] = (langs[p.l] || 0) + 1; });
      Object.keys(langs).sort(function (a, b) { return langs[b] - langs[a]; }).forEach(function (l) {
        var o = document.createElement("option"); o.value = l; o.textContent = l + " (" + langs[l] + ")"; $("language").appendChild(o);
      });
      var software = all.filter(function (p) { return !p.list && p.sig >= 2; });
      var adjacent = all.filter(function (p) { return !p.list && p.sig < 2; }).length;
      var stars = software.reduce(function (a, p) { return a + (p.s || 0); }, 0);
      var recent = software.filter(function (p) { return p.p && (Date.now() - new Date(p.p).getTime()) < 30 * 86400000; }).length;
      var cats = Object.keys(data.category_counts || {}).length - 1;
      $("tiles").innerHTML = tile("AI projects", fmtInt(software.length), "≥ " + fmtInt(data.min_stars) + " stars, not archived, not forks") +
        tile("AI-adjacent", fmtInt(adjacent), "tagged with a generic topic only") +
        tile("Curated lists", fmtInt(all.filter(function (p) { return p.list; }).length), "awesome-lists, courses, paper collections") +
        tile("Combined stars", fmtCompact(stars), "across " + fmtInt(cats) + " categories") +
        tile("Active last 30 days", fmtInt(recent), Math.round(100 * recent / Math.max(1, software.length)) + "% of AI projects") +
        tile("Topics searched", fmtInt(data.topics_searched), fmtInt(data.requests) + " GitHub search requests");
      if (data.partial) { $("banner").hidden = false; $("banner").textContent = "This catalog is a partial checkpoint: the sweep is still running."; }
      var hash = decodeURIComponent(location.hash.slice(1));
      if (hash && data.category_counts && data.category_counts[hash] != null) state.category = hash;
      $("foot").textContent = "Catalog generated " + new Date(data.generated_at).toLocaleString() + " · " + fmtInt(data.project_count) + " repositories · OpenScores v" + data.version + " · full data: data/catalog.json";
      render();
    }).catch(function (err) {
      $("banner").hidden = false;
      $("banner").textContent = "Could not load data/catalog-web.json (" + err.message + "). Build it with: python -m whitescore.catalog";
    });
  }
  init();
})();
