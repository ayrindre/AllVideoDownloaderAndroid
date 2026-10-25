/* WebFinder · views/search.js — hero search, dork chips, multi-engine fan-out, results grid */
(function () {
  const { $, $$, el, toast, fmtBytes, fmtDuration, faviconUrl, debounce } = window.UI;
  const S = window.Store;

  const state = { loading: false, filter: "all", lastData: null };

  /* ── boot -------------------------------------------------------------- */
  function init() {
    $("#sb-search-icon").innerHTML = ICONS.svg("search");
    $("#sb-go .sb-go-icon").innerHTML = ICONS.svg("arrowRight");
    $("#q-clear").innerHTML = ICONS.svg("x");
    $("#back-hero").innerHTML = ICONS.svg("chevronL");
    $("#back-hero").title = "Edit query (expand the command bar)";
    $("#re-run").innerHTML = ICONS.svg("refresh");

    renderTypeChips();
    renderEngines();
    wireForm();
    wireSafePill();
    wireFiltersPop();
    const resolve = $("#opt-resolve");
    resolve.checked = !!S.settings.resolve_pages;
    resolve.addEventListener("change", () => {
      window.API.saveSettings({ resolve_pages: resolve.checked });
      S.settings = { ...S.settings, resolve_pages: resolve.checked };
    });
    S.on("settings.changed", (st) => { resolve.checked = !!st.resolve_pages; });
  }

  const maybeRerun = debounce(() => {
    if (S.lastQuery && !state.loading && !$("#results-wrap").classList.contains("hidden")) run();
  }, 420);

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
        maybeRerun();
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
        maybeRerun();
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
    video: "filetype:mp4/mkv/webm", image: "filetype:jpg/png/webp", torrent: "filetype:torrent/magnet",
    software: "filetype:exe/msi", archive: "filetype:zip/rar/7z",
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
      if (e.key === "Escape" && $("#search-hero").classList.contains("compact")) backToHero();
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
    const hero = $("#search-hero");
    hero.classList.remove("compact");
    $("#viewport").scrollTo({ top: 0, behavior: "smooth" });
    setTimeout(() => $("#q").focus(), 120);
  }

  /* A bare URL typed into search is almost never a search — hand it to the
     Smart Direct Link module, which actually knows how to resolve it. */
  function looksLikeUrl(q) {
    if (/^(https?|ftp|magnet|ed2k):\/\//i.test(q)) return true;
    return !/\s/.test(q) && /^(www\.)?[\w-]+(\.[\w-]+)+([/:?#].*)?$/.test(q) && /\.[a-z]{2,}([/:?#]|$)/i.test(q);
  }

  /* ── search run ---------------------------------------------------------- */
  async function run() {
    const q = $("#q").value.trim();
    if (!q) { $("#q").focus(); shake($("#q").closest(".search-bar")); return; }
    if (state.loading) return;
    if (looksLikeUrl(q)) {
      S.emit("nav", "view-direct");
      $("#direct-url").value = q;
      window.DirectView.analyze();
      toast("That's a link, not a query — analyzed it in Smart Direct Link instead.", "info");
      return;
    }
    state.loading = true;
    S.lastQuery = q;
    $("#search-hero").classList.add("compact");
    const wrap = $("#results-wrap");
    wrap.classList.remove("hidden");
    $("#rh-title").textContent = q;
    $("#rh-meta").textContent = "querying engines…";
    $("#engine-strip").innerHTML = "";
    renderSkeletons();
    try {
      const data = await window.API.search(q, [...S.selectedTypes], chosenEngines(), S.searchFilters);
      state.lastData = data;
      S.results = data.results || [];
      renderEngineStrip(data);
      renderResults();
      requestAnimationFrame(() => $("#results-wrap").scrollIntoView({ behavior: "smooth", block: "start" }));
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

  const VERTICAL_LABELS = { web_dorks: "Gated dorks", apibay: "ThePirateBay", nyaa: "Nyaa",
    "1337x": "1337x", gutenberg: "Gutenberg", internetarchive: "Internet Archive",
    youtube: "YouTube", torlock: "Torlock", openlibrary: "Open Library",
    standardebooks: "Standard Ebooks", github: "GitHub", fdroid: "F-Droid",
    ccmixter: "ccMixter", deepscan: "Deep scan" };
  function renderEngineStrip(data) {
    const strip = $("#engine-strip");
    strip.innerHTML = "";
    (data.engines || []).forEach((e, i) => {
      const meta = S.meta.engines[e.engine] || {};
      strip.append(el("span", { class: `esrc${e.ok ? "" : " bad"}`, style: { "--i": i, "--eng-c": meta.color }, title: e.error || "ok" },
        el("span", { class: "dot" }),
        el("b", {}, meta.label || VERTICAL_LABELS[e.engine] || e.engine),
        e.ok ? `${e.count} hits` : "blocked"));
    });
    const n = (data.results || []).length;
    const mode = { images: "image index", videos: "video index", torrents: "torrent indexes",
                   ebooks: "book library", archives: "file-gated web", software: "software index",
                   audios: "audio library" }[data.mode] || "web";
    $("#rh-meta").textContent = `${n} result${n === 1 ? "" : "s"} · ${data.elapsed_ms} ms · ${mode}${data.demo ? " · demo data" : ""}`;
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
    const data = state.lastData;
    const vertical = ["images", "videos", "torrents", "ebooks", "archives", "software", "audios"].includes(data?.mode);
    $("#result-filter").classList.toggle("hidden", vertical);
    grid.classList.toggle("grid-media", !!vertical);
    let list = data?.results || [];
    if (state.filter === "direct") list = list.filter((r) => r.is_direct);
    if (vertical) { renderMediaGrid(list, data.mode); return; }
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

  /* ── media grid (image & video verticals) ────────────────────────────── */
  function renderMediaGrid(list, mode) {
    const grid = $("#results-grid");
    if (!list.length) {
      const data = state.lastData || {};
      const errs = (data.engines || []).filter((e) => !e.ok);
      grid.classList.remove("grid-media");
      const box = $("#results-empty");
      box.classList.remove("hidden");
      box.innerHTML = "";
      const HEAD = { images: ["image", "Bing, DuckDuckGo and Google media indexes"], videos: ["video", "YouTube search, Bing, DuckDuckGo and gated video-file dorks"],
                     torrents: ["torrent", "The Pirate Bay (apibay), Nyaa, 1337x and Torlock"], ebooks: ["book", "Gutenberg, Internet Archive, Open Library and Standard Ebooks"],
                     archives: ["archive", "dorked engines with a hard file-relevance gate"],
                     software: ["download", "GitHub Releases, F-Droid APKs and gated portable-file dorks"],
                     audios: ["audio", "Internet Archive audio, ccMixter and gated audio-file dorks"] };
      const hd = HEAD[mode] || HEAD.images;
      box.append(el("div", { class: "re-ico", html: ICONS.svg(hd[0]) }),
        el("h3", {}, `The ${mode.replace(/s$/, "")} indexes came back empty`),
        el("p", {}, `WebFinder queries ${hd[1]} in parallel. This search is never padded with irrelevant web pages — here is what each index said:`));
      const why = el("div", { style: { margin: "18px auto 0", maxWidth: "560px", textAlign: "left", display: "grid", gap: 7 } });
      (data.engines || []).forEach((e) => {
        why.append(el("div", { class: "notice " + (e.ok ? "info" : "warn"), style: { marginBottom: 0 } },
          el("span", { class: "dot", style: { width: 8, height: 8, borderRadius: "50%", background: e.ok ? "var(--ok)" : "var(--warn)", flex: "none", marginTop: 5 } }),
          el("div", {}, el("b", {}, e.engine), e.ok ? ` — ${e.count} results` : ` — ${e.error || "blocked"}`)));
      });
      box.append(why);
      if (errs.length) {
        box.append(el("p", { style: { marginTop: 16, fontSize: 12 } },
          "Common causes: your network/ISP blocking a Google or DuckDuckGo endpoint, rate limiting after fast searches, or a captcha wall. Fixes: wait a minute and retry · set Settings → Scrape proxy · keep only the engines that respond."));
        box.append(el("button", { class: "btn btn-primary", style: { marginTop: 12 },
          onclick: () => run(), html: `${ICONS.svg("refresh")}<span>Retry now</span>` }));
      }
      return;
    }
    $("#results-empty").classList.add("hidden");
    list.forEach((r, i) => grid.append(mediaCard(r, mode, i)));
  }

  function mediaCard(r, mode, i) {
    const isVideo = mode === "videos", isTorrent = mode === "torrents";
    const mkImg = (src) => {
      const im = el("img", { class: "mc-thumb", alt: "", loading: "lazy", src });
      im.onerror = () => im.replaceWith(fileTile(r, mode));
      return im;
    };
    const tile = r.thumb ? mkImg(r.thumb)
      : (mode === "images" && /\.(jpe?g|png|webp|gif|avif)(\?|#|$)/i.test(r.url)) ? mkImg(r.url)
      : fileTile(r, mode);
    const badge = isVideo
      ? (r.duration ? fmtDurationLocal(r.duration) : (r.height ? `${r.height}p` : "clip"))
      : isTorrent
        ? [r.seeders != null ? `${r.seeders} seeds` : "", r.size_bytes ? fmtBytes(r.size_bytes) : ""].filter(Boolean).join(" · ")
        : mode === "ebooks"
          ? [r.year, r.size_bytes ? fmtBytes(r.size_bytes) : ""].filter(Boolean).join(" · ")
          : (r.width && r.height ? `${r.width}×${r.height}` : (r.size_bytes ? fmtBytes(r.size_bytes) : ""));
    const card = el("figure", { class: `mcard${isTorrent ? " mcard-torrent" : ""}`, tabindex: 0, style: { "--i": Math.min(i, 20) } },
      tile,
      badge ? el("span", { class: "mc-badge" }, badge) : null,
      el("div", { class: "mc-actions" },
        (r.page || isVideo) ? el("button", { class: "fab", title: isVideo ? "Play source" : "Open source page", html: ICONS.svg(isVideo ? "play" : "external") }) : null,
        el("button", { class: "fab fab-copy", title: isTorrent ? "Copy magnet link" : "Copy direct link" }, el("span", { html: ICONS.svg("copy") })),
        (isTorrent && !r.torrent_url) ? null
          : el("button", { class: "fab fab-dl", title: isTorrent ? "Save .torrent file" : "Download in WebFinder" }, el("span", { html: ICONS.svg("download") }))),
      el("figcaption", {},
        el("div", { class: "mc-title" }, r.title || ""),
        el("div", { class: "mc-src" },
          el("span", {}, r.domain || ""),
          r.publisher ? el("span", { class: "mc-pub" }, r.publisher) : null,
          el("span", { class: "mc-eng" }, r.engine || ""))));

    const openBtn = card.querySelector(".mc-actions .fab:not(.fab-copy):not(.fab-dl)");
    if (openBtn) openBtn.addEventListener("click", () => window.open(r.page || r.url, "_blank", "noopener"));
    card.querySelector(".fab-copy").addEventListener("click", async (e) => {
      const btn = e.currentTarget;   // MUST capture pre-await: currentTarget nulls out after dispatch
      await window.UI.copyText(r.url);
      btn.classList.add("copied"); setTimeout(() => { if (btn.isConnected) btn.classList.remove("copied"); }, 900);
      toast(isTorrent ? "Magnet copied — paste into your torrent client." : "Direct link copied — paste into IDM.", "ok", { icon: "copy" });
    });
    const dlBtn = card.querySelector(".fab-dl");
    if (dlBtn) dlBtn.addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      btn.innerHTML = `<span class="spinner"></span>`;
      try {
        const url = isTorrent ? r.torrent_url : r.url;
        const ft = { videos: "video", torrents: "torrent", ebooks: "ebook", archives: "archive", software: "app", audios: "audio" }[mode] || "image";
        await window.API.startDownload({ url, title: r.title || "", file_type: ft });
        toast(isTorrent ? ".torrent file queued." : "Added to the download queue.", "ok", { icon: "dl", actionLabel: "View", onAction: () => S.emit("nav", "view-downloads") });
      } catch (err) { toast(err.message, "err"); }
      finally { btn.innerHTML = `<span>${ICONS.svg("download")}</span>`; }
    });
    card.addEventListener("dblclick", () => window.open(r.url, "_blank", "noopener"));
    return card;
  }
  function fileTile(r, mode) {
    const ext = (String(r.url || "").match(/\.([a-z0-9]{2,5})(?:[?#]|$)/i) || [])[1]
      || { torrents: "TORRENT", ebooks: "BOOK", archives: "ARCH" }[mode] || "FILE";
    const iconKey = { torrents: "torrent", ebooks: "book", archives: "archive" }[mode] || "download";
    return el("div", { class: "mc-file", title: String(ext).toUpperCase() },
      el("span", { class: "mc-file-ico", html: ICONS.svg(iconKey) }),
      el("b", {}, String(ext).toUpperCase().slice(0, 5)));
  }

  function fmtDurationLocal(sec) {
    sec = Math.round(sec || 0);
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    return (h ? `${h}:` : "") + String(m).padStart(h ? 2 : 1, "0") + ":" + String(s).padStart(2, "0");
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
      const btn = e.currentTarget;   // capture before await (spec: currentTarget → null after dispatch)
      const ok = await window.UI.copyText(best);
      btn.classList.add("copied");
      setTimeout(() => { if (btn.isConnected) btn.classList.remove("copied"); }, 900);
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

  /* ── SafeSearch quick toggle (persisted; default OFF) ────────────────── */
  function wireSafePill() {
    const pill = $("#safe-pill");
    const paintPill = () => {
      const on = !!S.settings.safe_search;
      pill.classList.toggle("on", !on);
      pill.innerHTML = `<span class="dot" style="--eng-c:${on ? "var(--warn)" : "var(--ok)"}"></span>SafeSearch: <b>${on ? "ON" : "OFF"}</b>`;
      pill.title = on ? "SafeSearch filters adult results out — click to see everything" : "Showing unfiltered results — click to re-enable SafeSearch";
    };
    pill.addEventListener("click", async () => {
      try {
        S.settings = await window.API.saveSettings({ safe_search: !S.settings.safe_search });
        paintPill();
        if (S.lastQuery && !state.loading) run();
      } catch (e) { toast(e.message, "err"); }
    });
    paintPill();
  }

  /* ── per-type advanced filters ───────────────────────────────────────── */
  const FILTER_DEFS = {
    images: { label: "Images", fields: [
      { key: "size", label: "Min size", opts: [["", "Any"], ["large", "≥ 800"], ["hd", "HD 1280+"], ["uhd", "4K+"] ] },
      { key: "aspect", label: "Aspect", opts: [["", "Any"], ["square", "Square"], ["wide", "Landscape"], ["tall", "Portrait"]] },
      { key: "color", label: "Color", opts: [["", "Any"], ["red", "Red"], ["orange", "Orange"], ["yellow", "Yellow"], ["green", "Green"], ["teal", "Teal"], ["blue", "Blue"], ["purple", "Purple"], ["pink", "Pink"], ["brown", "Brown"], ["black", "Black"], ["white", "White"], ["gray", "Gray"], ["transparent", "Transparent"]] },
      { key: "type", label: "Kind", opts: [["", "Any"], ["photo", "Photo"], ["clipart", "Clipart"], ["line", "Line art"], ["animated", "GIF"], ["greyscale", "B&amp;W"]] },
    ] },
    videos: { label: "Videos", fields: [
      { key: "duration", label: "Length", opts: [["", "Any"], ["short", "Under 4 min"], ["medium", "4–20 min"], ["long", "Over 20 min"]] },
      { key: "min_res", label: "Min height", opts: [["", "Any"], ["480", "480p+"], ["720", "720p+"], ["1080", "1080p+"]] },
    ] },
    torrents: { label: "Torrents", fields: [
      { key: "min_seeds", label: "Min seeders", opts: [["", "Any"], ["5", "5+"], ["20", "20+"], ["50", "50+"]] },
    ] },
    ebooks: { label: "E-Books", fields: [
      { key: "format", label: "Format", opts: [["", "Any"], ["epub", "EPUB"], ["pdf", "PDF"], ["djvu", "DjVu"]] },
    ] },
  };

  let popEl = null;
  function activeFilterCount() {
    return Object.values(S.searchFilters).reduce((n, g) => n + Object.values(g || {}).filter(Boolean).length, 0);
  }
  function wireFiltersPop() {
    const btn = $("#filters-btn");
    btn.innerHTML = `${ICONS.svg("shield")} Filters<span class="fb-count hidden"></span>`;
    const badge = () => {
      const n = activeFilterCount();
      const b = btn.querySelector(".fb-count");
      b.textContent = n; b.classList.toggle("hidden", !n);
    };
    btn.addEventListener("click", (e) => { e.stopPropagation(); popEl ? closePop() : openPop(badge); });
    badge();
    window.__wfFiltersBadge = badge;
  }
  function closePop() { popEl?.remove(); popEl = null; document.removeEventListener("pointerdown", outside); }
  function outside(e) { if (popEl && !popEl.contains(e.target) && !e.target.closest("#filters-btn")) closePop(); }
  function openPop(badge) {
    closePop();
    popEl = el("div", { class: "popover" });
    for (const [group, def] of Object.entries(FILTER_DEFS)) {
      popEl.append(el("div", { class: "pop-group" },
        el("h4", {}, def.label),
        ...def.fields.map((fd) => {
          const row = el("div", { class: "frow" });
          const val = S.searchFilters[group]?.[fd.key] || "";
          const opts = el("div", { class: "pillrow" });
          for (const [v, lab] of fd.opts) {
            const b = el("button", { class: `fopt${String(val) === String(v) ? " on" : ""}`, type: "button" });
            b.innerHTML = lab;
            b.addEventListener("click", () => {
              S.searchFilters[group] = S.searchFilters[group] || {};
              if (v === "") delete S.searchFilters[group][fd.key]; else S.searchFilters[group][fd.key] = v;
              [...opts.children].forEach((x) => x.classList.remove("on")); b.classList.add("on");
              badge();
              if (S.lastQuery && !state.loading) run();
            });
            opts.append(b);
          }
          row.append(el("span", { class: "f-label" }, fd.label), opts);
          return row;
        })));
    }
    popEl.append(el("div", { class: "pop-foot" },
      el("span", {}, "Image color/kind ride Bing's index; size, seeds & format are enforced locally."),
      el("button", { class: "btn btn-ghost btn-sm", onclick: () => {
        S.searchFilters = { images: {}, videos: {}, torrents: {}, ebooks: {} };
        closePop(); badge();
        if (S.lastQuery && !state.loading) run();
      } }, "Reset")));
    document.body.append(popEl);
    const r = $("#filters-btn").getBoundingClientRect();
    popEl.style.top = `${r.bottom + 8}px`;
    popEl.style.left = `${Math.max(12, Math.min(r.left - 180, innerWidth - r.width))}px`;
    requestAnimationFrame(() => document.addEventListener("pointerdown", outside));
  }

  window.SearchView = { init, run };
})();
