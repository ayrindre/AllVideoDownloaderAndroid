/* WebFinder · views/search.js — hero search, dork chips, multi-engine fan-out, results grid */
(function () {
  const { $, $$, el, toast, fmtBytes, faviconUrl, debounce, modal } = window.UI;
  const S = window.Store;

  const state = { loading: false, filter: "all", lastData: null };

  /* ── boot -------------------------------------------------------------- */
  function init() {
    $("#sb-search-icon").innerHTML = ICONS.svg("search");
    $("#sb-go .sb-go-icon").innerHTML = ICONS.svg("arrowRight");
    $("#q-clear").innerHTML = ICONS.svg("x");
    $("#back-hero").innerHTML = ICONS.svg("chevronL");
    $("#re-run").innerHTML = ICONS.svg("refresh");

    renderTypeChips();
    renderEngines();
    wireForm();
    const resolve = $("#opt-resolve");
    resolve.checked = !!S.settings.resolve_pages;
    resolve.addEventListener("change", () => {
      window.API.saveSettings({ resolve_pages: resolve.checked });
      S.settings = { ...S.settings, resolve_pages: resolve.checked };
    });
    S.on("settings.changed", (st) => { resolve.checked = !!st.resolve_pages; });
  }

  function renderTypeChips() {
    const wrap = $("#type-chips");
    wrap.innerHTML = "";
    for (const [key, spec] of Object.entries(S.meta.file_types)) {
      const input = el("input", { type: "checkbox" });
      const chip = el("label", { class: "chip", style: { "--chip-c": spec.color }, title: `Append ${key} dorks to the query` },
        input, el("span", { html: ICONS.svg(spec.icon) }), spec.label);
      input.addEventListener("change", () => {
        chip.classList.toggle("on", input.checked);
        input.checked ? S.selectedTypes.add(key) : S.selectedTypes.delete(key);
        previewQuery();
      });
      wrap.append(chip);
    }
    previewQuery();
  }

  function renderEngines() {
    const wrap = $("#engine-set");
    wrap.innerHTML = "";
    wrap.append(el("span", { class: "qlabel" }, "Engines"));
    for (const [key, m] of Object.entries(S.meta.engines)) {
      const active = S.selectedEngines.has(key);
      const pill = el("button", { class: `epill${active ? " on" : ""}`, type: "button", style: { "--eng-c": m.color }, title: `${m.label} — reliability: ${m.reliability}` },
        el("span", { class: "dot" }), m.label);
      pill.addEventListener("click", () => {
        if (S.selectedEngines.has(key)) { S.selectedEngines.delete(key); pill.classList.remove("on"); }
        else { S.selectedEngines.add(key); pill.classList.add("on"); }
      });
      wrap.append(pill);
    }
    // never let the user search with zero engines (UI safety net)
    if (!S.selectedEngines.size) wrap.append(el("span", { style: { fontSize: "11px", color: "var(--warn)", alignSelf: "center" } }, "at least one engine required"));
  }

  function chosenEngines() {
    return S.selectedEngines.size ? [...S.selectedEngines] : null;
  }

  function previewQuery() {
    const box = $("#query-preview");
    const q = $("#q").value.trim();
    const types = [...S.selectedTypes];
    if (!q && !types.length) { box.classList.add("hidden"); return; }
    // mirror backend dork composition for a live preview
    const dorks = types.map((t) => FILETYPE_DORKS[t]).filter(Boolean);
    box.classList.remove("hidden");
    box.innerHTML = `Query preview: <b>${escapeHtml(q || "…")}</b>${dorks.length ? ` ${dorks.map((d) => `<b>${escapeHtml(d)}</b>`).join(" OR ")}` : ""}`;
  }
  const FILETYPE_DORKS = {
    video: "filetype:mp4/mkv/webm", image: "filetype:jpg/png/webp", torrent: "filetype:torrent",
    magnet: "inurl:magnet btih", software: "filetype:exe/msi", archive: "filetype:zip/rar/7z",
    audio: "filetype:mp3/flac", ebook: "filetype:pdf/epub",
  };

  function wireForm() {
    const form = $("#search-form"), input = $("#q");
    input.addEventListener("input", debounce(() => {
      $("#q-clear").classList.toggle("hidden", !input.value);
      previewQuery();
    }, 90));
    $("#q-clear").addEventListener("click", () => { input.value = ""; input.focus(); previewQuery(); });
    form.addEventListener("submit", (e) => { e.preventDefault(); run(); });
    $("#back-hero").addEventListener("click", backToHero);
    $("#re-run").addEventListener("click", () => run());
    $("#result-filter").addEventListener("click", (e) => {
      const b = e.target.closest(".seg"); if (!b) return;
      $$("#result-filter .seg").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      state.filter = b.dataset.f;
      paintSeg(); renderResults();
    });
    addEventListener("keydown", (e) => {
      if (e.key === "/" && document.activeElement !== input && !e.ctrlKey && !e.metaKey) { e.preventDefault(); input.focus(); }
      if (e.key === "Escape" && !$("#results-wrap").classList.contains("hidden") && state.loading) backToHero();
    });
    paintSeg();
  }

  function paintSeg() {
    const wrap = $("#result-filter");
    const active = wrap.querySelector(".seg.active");
    if (!active) return;
    wrap.style.setProperty("--sx", `${active.offsetLeft - 3}px`);
    wrap.style.setProperty("--sw", `${active.offsetWidth}px`);
  }

  function backToHero() {
    $("#results-wrap").classList.add("hidden");
    $("#search-hero").classList.remove("hidden");
    $("#search-hero").style.opacity = "";
    setTimeout(() => $("#q").focus(), 60);
  }

  /* ── search run ---------------------------------------------------------- */
  async function run() {
    const q = $("#q").value.trim();
    if (!q) { $("#q").focus(); shake($("#q").closest(".search-bar")); return; }
    if (state.loading) return;
    state.loading = true;
    S.lastQuery = q;
    $("#search-hero").classList.add("lifting");
    setTimeout(() => $("#search-hero").classList.add("hidden"), 240);
    const wrap = $("#results-wrap");
    wrap.classList.remove("hidden");
    $("#rh-title").textContent = q;
    $("#rh-meta").textContent = "querying engines…";
    $("#engine-strip").innerHTML = "";
    renderSkeletons();
    try {
      const data = await window.API.search(q, [...S.selectedTypes], chosenEngines());
      state.lastData = data;
      S.results = data.results || [];
      renderEngineStrip(data);
      renderResults();
    } catch (err) {
      $("#results-grid").innerHTML = "";
      showEmpty("search-x", "Search failed", `${err.message}. Check the engine mix in Settings — some engines wall off datacenter IPs; try Bing + DuckDuckGo, or flip on Demo mode to preview the UI offline.`);
    } finally {
      state.loading = false;
    }
  }

  function shake(node) {
    node.animate([{ transform: "translateX(0)" }, { transform: "translateX(-7px)" }, { transform: "translateX(6px)" },
      { transform: "translateX(-4px)" }, { transform: "translateX(0)" }], { duration: 280, easing: "ease-out" });
  }

  function renderEngineStrip(data) {
    const strip = $("#engine-strip");
    strip.innerHTML = "";
    (data.engines || []).forEach((e, i) => {
      const meta = S.meta.engines[e.engine] || {};
      strip.append(el("span", { class: `esrc${e.ok ? "" : " bad"}`, style: { "--i": i, "--eng-c": meta.color }, title: e.error || "" },
        el("span", { class: "dot" }),
        el("b", {}, meta.label || e.engine),
        e.ok ? `${e.count} hits` : "blocked"));
    });
    const n = (data.results || []).length;
    $("#rh-meta").textContent = `${n} result${n === 1 ? "" : "s"} · ${data.elapsed_ms} ms${data.demo ? " · demo data" : ""}`;
  }

  /* ── rendering ------------------------------------------------------------- */
  function renderSkeletons() {
    const grid = $("#results-grid");
    grid.innerHTML = "";
    $("#results-empty").classList.add("hidden");
    for (let i = 0; i < 8; i++) {
      grid.append(el("article", { class: "card result-card skeleton", style: { "--i": i } },
        el("div", { class: "rc-top" },
          el("span", { class: "sk-ico" }),
          el("div", { style: { flex: 1, display: "grid", gap: "7px" } },
            el("div", { class: "sk-line w90" }), el("div", { class: "sk-line w40" })),
          el("div", { class: "sk-line", style: { width: 52, height: 20 } })),
        el("div", { class: "sk-line w90" }), el("div", { class: "sk-line w70" }),
        el("div", { style: { display: "flex", justifyContent: "flex-end", gap: 7, marginTop: 4 } },
          el("div", { class: "sk-line", style: { width: 30, height: 30 } }),
          el("div", { class: "sk-line", style: { width: 30, height: 30 } }),
          el("div", { class: "sk-line", style: { width: 30, height: 30 } })),
      ));
    }
  }

  function renderResults() {
    const grid = $("#results-grid");
    grid.innerHTML = "";
    let list = state.lastData?.results || [];
    if (state.filter === "direct") list = list.filter((r) => r.is_direct);
    if (!list.length) {
      showEmpty(state.filter === "direct" ? "scan" : "search-x",
        state.filter === "direct" ? "No direct files in this batch" : "Nothing came back",
        state.filter === "direct"
          ? "All hits were regular web pages. Switch to “All” or try the Smart Direct Link module on the most promising page."
          : "Engines may be rate-limiting this IP. Toggle more engines, disable a blocked one, or widen your file-type chips.");
      return;
    }
    $("#results-empty").classList.add("hidden");
    const tpl = $("#tpl-result-card");
    list.forEach((r, i) => {
      const card = tpl.content.firstElementChild.cloneNode(true);
      card.style.setProperty("--i", Math.min(i, 14));
      const ftColor = (S.meta.file_types[r.file_type] || {}).color || "#8b8b96";
      const ftLabel = (S.meta.file_types[r.file_type] || {}).label || (r.file_type === "link" ? "Web page" : r.file_type);
      card.querySelector(".rc-title").textContent = r.title || r.url;
      card.querySelector(".rc-title").title = r.url;
      card.querySelector(".rc-domain").textContent = r.domain || "";
      card.querySelector(".rc-snippet").textContent = r.snippet || "No snippet returned by the engine.";
      const typeBadge = card.querySelector(".rc-type");
      typeBadge.textContent = ftLabel;
      typeBadge.style.setProperty("--ft-c", ftColor);
      const engMeta = S.meta.engines[r.engine] || {};
      const tags = card.querySelector(".rc-tags");
      tags.append(el("span", { class: "tag tag-engine", style: { "--eng-c": engMeta.color }, html: `<span class="dot" style="width:6px;height:6px;border-radius:50%;background:currentColor;display:inline-block"></span>${escapeHtml(engMeta.label || r.engine)}` }));
      if (r.size_bytes) tags.append(el("span", { class: "tag tag-size", html: `${ICONS.svg("db")}${fmtBytes(r.size_bytes)}` }));
      if (r.is_direct) tags.append(el("span", { class: "tag", html: `${ICONS.svg("bolt")}direct`, title: "Looks like a direct file link" }));

      // favicon with graceful fallback to a letter avatar
      const img = card.querySelector(".rc-favicon img");
      const letterFallback = () => {
        const box = card.querySelector(".rc-favicon");
        box.innerHTML = `<span class="fx-letter" style="color:${ftColor}">${(r.domain || "?")[0] || "?"}</span>`;
      };
      img.onerror = letterFallback;
      img.src = faviconUrl(r.domain || "");

      wireCard(card, r, letterFallback);
      grid.append(card);
    });
  }

  function wireCard(card, r, letterFallback) {
    const title = card.querySelector(".rc-title");
    title.addEventListener("click", () => openUrl(r.url));

    const [btnSrc, btnCopy, btnDl] = ["fab-src", "fab-copy", "fab-dl"].map((c) => card.querySelector(`.${c} span`));
    ICONS.set(btnSrc, "external"); ICONS.set(btnCopy, "copy"); ICONS.set(btnDl, "download");

    card.querySelector(".fab-src").addEventListener("click", () => openUrl(r.url));

    // the copy-link button always copies the *best* download URL we know of
    card.querySelector(".fab-copy").addEventListener("click", async (e) => {
      const best = r.media_candidates?.[0]?.url || r.url;
      const ok = await window.UI.copyText(best);
      e.currentTarget.classList.add("copied");
      setTimeout(() => e.currentTarget.classList.remove("copied"), 900);
      toast(ok ? (r.media_candidates?.length ? "Direct file link copied — paste into IDM or your browser." : "Download link copied to clipboard.") : "Clipboard blocked by the browser.",
        ok ? "ok" : "err");
    });

    card.querySelector(".fab-dl").addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      btn.innerHTML = `<span class="spinner"></span>`;
      try {
        await window.API.startDownload({ url: r.url, title: r.title || "" });
        toast(`Added to queue — ${r.title || r.url}`, "ok", { icon: "dl", actionLabel: "View", onAction: () => S.emit("nav", "view-downloads") });
      } catch (err) {
        toast(err.message, "err");
      } finally {
        btn.innerHTML = `<span>${ICONS.svg("download")}</span>`;
      }
    });

    // hidden direct links discovered by the deep-link scan
    if (r.media_candidates?.length) {
      const box = card.querySelector(".rc-candidates");
      box.classList.remove("hidden");
      box.append(el("div", { class: "cand-head", html: `${ICONS.svg("scan")}Direct links found on page (${r.media_candidates.length})` }));
      for (const c of r.media_candidates) {
        box.append(el("div", { class: "cand" },
          el("span", { class: "cand-name", title: c.url }, c.filename),
          el("button", { class: "icon-btn", title: "Copy link", html: ICONS.svg("copy"), onclick: async () => {
            await window.UI.copyText(c.url); toast("Direct link copied.", "ok", { icon: "copy" });
          } }),
          el("button", { class: "icon-btn", title: "Download", html: ICONS.svg("download"), onclick: async () => {
            try { await window.API.startDownload({ url: c.url, filename: c.filename, title: c.filename }); toast(`Downloading ${c.filename}`, "ok", { icon: "dl" }); }
            catch (err) { toast(err.message, "err"); }
          } })));
      }
    }
  }

  function openUrl(url) {
    try { window.open(url, "_blank", "noopener"); }
    catch { toast("Popup blocked — copy the link instead.", "warn"); }
  }

  function showEmpty(icon, title, msg) {
    const box = $("#results-empty");
    box.classList.remove("hidden");
    box.innerHTML = "";
    box.append(
      el("div", { class: "re-ico", html: ICONS.svg(icon === "search-x" ? "search" : icon) }),
      el("h3", {}, title), el("p", {}, msg));
  }

  function escapeHtml(s) { const d = document.createElement("div"); d.textContent = s ?? ""; return d.innerHTML; }

  window.SearchView = { init, run };
})();
