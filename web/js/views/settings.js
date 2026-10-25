/* All Video Downloader · views/settings.js — everything persisted server-side to settings.json */
(function () {
  const { $, $$, el, toast, debounce } = window.UI;
  const S = window.Store;
  const save = debounce(async (patch) => {
    try {
      const merged = await window.API.saveSettings(patch);
      S.settings = merged;
      S.emit("settings.changed", merged);
      flashSaved();
    } catch (e) { toast(`Couldn't save: ${e.message}`, "err"); }
  }, 350);

  let flashTimer = null;
  function flashSaved() {
    const dot = $("#save-flash");
    if (!dot) return;
    dot.classList.remove("hidden");
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => dot.classList.add("hidden"), 1200);
  }

  function init() {
    const grid = $("#settings-grid");
    grid.innerHTML = "";
    $("#cfg-path").textContent = S.meta?.config_file || "~/.avd/settings.json";

    grid.append(secDownloads(), secMedia(), secInstagram(), secAppearance(), secSystem());
  }

  function card(title, sub, iconName, ...fields) {
    return el("section", { class: "card set-card" },
      el("h3", { html: `${ICONS.svg(iconName)}<span>${title}</span><span id="save-flash" class="pulse-dot hidden" style="margin-left:auto"></span>` }),
      sub ? el("p", { class: "sc-sub" }, sub) : null,
      ...fields);
  }

  /* ── downloads ──────────────────────────────────────────────────────────── */
  function secDownloads() {
    const st = S.settings;
    const dirInput = el("input", { class: "input", value: st.download_dir, onchange: (e) => save({ download_dir: e.target.value }) });
    const maxRange = el("input", { type: "range", min: 1, max: 8, value: st.max_concurrent,
      style: { "--v": `${((st.max_concurrent - 1) / 7) * 100}%` } });
    const maxVal = el("span", { class: "range-val" }, `${st.max_concurrent} parallel`);
    maxRange.addEventListener("input", () => {
      maxRange.style.setProperty("--v", `${((maxRange.value - 1) / 7) * 100}%`);
      maxVal.textContent = `${maxRange.value} parallel`;
      save({ max_concurrent: +maxRange.value });
    });
    return card("Downloads", "Where files land and how hard All Video Downloader pulls.", "download",
      el("div", { class: "field" },
        el("label", { class: "f-label" }, "Download folder"),
        el("div", { class: "input-row" }, dirInput,
          el("button", { class: "btn btn-ghost btn-sm", onclick: async () => {
            const picked = await window.API.bridge.pickFolder?.();
            if (picked) { dirInput.value = picked; save({ download_dir: picked }); }
            else toast("Folder picker is available in the desktop shell. Edit the path directly in browser mode.", "info");
          }, html: ICONS.svg("folder") }))),
      el("div", { class: "field" },
        el("label", { class: "f-label" }, "Concurrency"),
        el("div", { class: "range-line" }, maxRange, maxVal)),
      el("div", { class: "field" },
        el("label", { class: "f-label" }, "Network proxy (optional)"),
        el("input", { class: "input", placeholder: "http://127.0.0.1:7890 · socks5://user:pass@host:port", value: st.proxy || "", onchange: (e) => save({ proxy: e.target.value.trim() }) }),
        el("p", { style: { fontSize: "11.5px", color: "var(--text-3)", marginTop: 7, lineHeight: 1.5 } },
          "Routes downloads, stream capture and yt-dlp through the proxy — useful when a CDN geoblocks you.")),
      setRow("Simulate on network failure", "If the remote host is unreachable, finish the job in simulation so nothing looks broken.",
        switchOpt("simulate_on_network_error", st.simulate_on_network_error)));
  }

  /* ── media ──────────────────────────────────────────────────────────────── */
  function secMedia() {
    const st = S.settings;
    const ff = S.meta.system.ffmpeg;
    const caps = el("div", { style: { display: "flex", gap: 8, flexWrap: "wrap", margin: "4px 0 14px" } },
      el("span", { class: `cap ${ff.available ? "ok" : "bad"}`, html: `<span class="dot"></span>FFmpeg ${ff.available ? "detected" : "not found"}` }),
      el("span", { class: `cap ${S.meta.system.yt_dlp ? "ok" : "bad"}`, html: `<span class="dot"></span>yt-dlp ${S.meta.system.yt_dlp || "not installed"}` }),
      el("span", { class: `cap ${S.meta.system.gallery_dl?.available ? "ok" : "bad"}`,
        html: `<span class="dot"></span>gallery-dl ${S.meta.system.gallery_dl?.version || "not installed"}` }));
    const containerSel = selectOpt(["mp4", "mkv", "webm", "mov"], { mp4: "MP4 (best compatibility)", mkv: "MKV (max flexibility)", webm: "WebM", mov: "MOV" }, st.default_container, (v) => save({ default_container: v }));
    const qualitySel = selectOpt(["best", "2160", "1440", "1080", "720", "480"],
      { best: "Best available", 2160: "2160p (4K)", 1440: "1440p", 1080: "1080p (FHD)", 720: "720p", 480: "480p" },
      String(st.default_quality), (v) => save({ default_quality: v }));
    const ffPath = el("input", { class: "input", placeholder: "e.g. C:\\Tools\\ffmpeg\\bin", value: st.ffmpeg_path || "", onchange: (e) => save({ ffmpeg_path: e.target.value }) });
    return card("Video & capture", "How links are extracted, merged and remuxed.", "film",
      caps,
      el("div", { class: "field" }, el("label", { class: "f-label" }, "Preferred container"), containerSel),
      el("div", { class: "field" }, el("label", { class: "f-label" }, "Default quality"), qualitySel),
      el("div", { class: "field" },
        el("label", { class: "f-label" }, "Browser cookies source (yt-dlp & gallery-dl)"),
        selectOpt(["", "chrome", "edge", "brave", "chromium", "firefox", "vivaldi"],
          { "": "None (anonymous)", chrome: "Chrome", edge: "Edge", brave: "Brave", chromium: "Chromium", firefox: "Firefox", vivaldi: "Vivaldi" },
          st.ytdlp_browser_cookies || "", (v) => save({ ytdlp_browser_cookies: v })),
        el("p", { style: { fontSize: "11.5px", color: "var(--text-3)", marginTop: 7, lineHeight: 1.5 } },
          "When YouTube answers \u201cSign in to confirm you're not a bot\u201d, All Video Downloader reads your session cookies from that browser (locally, never uploaded) so extraction and downloads work on age/region-gated content. Windows: close Chrome fully after enabling, or it holds the cookie DB. Chrome 127+ on Windows encrypts it (App-Bound) — if downloads keep dying with “Could not copy Chrome cookie database”, firefox is the reliable source, or leave it empty: the app now retries every extraction and download without cookies automatically. The same choice is handed to gallery-dl, which is what makes the Instagram checker see logged-in profiles, stories and 18+ content.")),
      el("div", { class: "field" },
        el("label", { class: "f-label" }, "Cookies file (optional, cookies.txt)"),
        el("div", { class: "input-row" },
          el("input", { class: "input", placeholder: "C:\\Users\\you\\cookies.txt",
            value: st.cookies_file || "", onchange: (e) => save({ cookies_file: e.target.value.trim() }) }),
          el("button", { class: "btn btn-ghost btn-sm", onclick: checkCookies }, "Check cookies")),
        el("p", { style: { fontSize: "11.5px", color: "var(--text-3)", marginTop: 7, lineHeight: 1.5 } },
          "A Netscape-format cookies.txt is the one source that always works: Chrome keeps its own ",
          "database locked while running and App-Bound-encrypts it on Windows (yt-dlp issue 7271), so ",
          "“Could not copy Chrome cookie database” is a setup problem, not a site problem. Export the file ",
          "with a “Get cookies.txt LOCALLY” style extension (log in first), point this field at it, and both ",
          "yt-dlp and gallery-dl use it — Instagram stories/highlights and gated videos start working. ",
          "It wins over the browser source above.")),
      el("div", { class: "field" },
        el("label", { class: "f-label" }, "FFmpeg folder (optional)"),
        el("div", { class: "input-row" }, ffPath,
          el("button", { class: "btn btn-ghost btn-sm", onclick: async () => {
            const merged = await window.API.saveSettings({ ffmpeg_path: ffPath.value });
            S.settings = merged;
            const meta = await window.API.meta();
            S.meta = meta; init();
            toast(meta.system.ffmpeg.available ? "FFmpeg detected — streams will capture losslessly." : "Still no FFmpeg at that path.", meta.system.ffmpeg.available ? "ok" : "warn");
          } }, "Re-check")),
        el("p", { style: { fontSize: "11.5px", color: "var(--text-3)", marginTop: 7, lineHeight: 1.5 } },
          "Windows: ", el("code", {}, "winget install Gyan.FFmpeg"), " then restart All Video Downloader. Needed for .m3u8/.mpd capture and for merging separate audio+video streams.")));
  }

  /* ── instagram checker ──────────────────────────────────────────────────── */
  function secInstagram() {
    const st = S.settings;
    const gal = S.meta.system.gallery_dl || {};
    const targets = [["posts", "Posts"], ["reels", "Reels"], ["stories", "Stories"],
      ["highlights", "Highlights"], ["tagged", "Tagged"]];
    const chosen = new Set(String(st.instagram_include || "posts,reels").split(",").map((x) => x.trim()));
    const chips = el("div", { class: "chip-set", style: { justifyContent: "flex-start" } });
    const persist = () => save({ instagram_include: [...chosen].join(",") });
    for (const [key, label] of targets) {
      const chip = el("button", { class: `chip${chosen.has(key) ? " on" : ""}`, type: "button",
        style: { "--chip-c": "#e1306c", height: "32px", padding: "0 12px" } }, label);
      chip.addEventListener("click", () => {
        if (chosen.has(key)) { if (chosen.size > 1) chosen.delete(key); }
        else chosen.add(key);
        chip.classList.toggle("on", chosen.has(key));
        persist();
      });
      chips.append(chip);
    }
    const limitSel = selectOpt([10, 20, 30, 60, 120, 0],
      { 10: "10 newest posts", 20: "20 newest", 30: "30 newest", 60: "60 newest", 120: "120 newest", 0: "Everything (slow)" },
      Number(st.instagram_limit ?? 30), (v) => save({ instagram_limit: Number(v) }));
    return card("Instagram checker", "Which profile tabs the gallery-dl walk covers by default.", "instagram",
      el("div", { style: { display: "flex", gap: 8, flexWrap: "wrap", margin: "4px 0 14px" } },
        el("span", { class: `cap ${gal.available ? "ok" : "bad"}`,
          html: `<span class="dot"></span>gallery-dl ${gal.version || "not installed"}` })),
      !gal.available ? el("div", { class: "notice warn", style: { marginBottom: 12 } },
        el("span", { html: ICONS.svg("warning") }),
        el("div", {}, "The checker needs gallery-dl: ", el("code", {}, gal.install_hint || "pip install gallery-dl"),
          " — then restart All Video Downloader.")) : null,
      el("div", { class: "field" }, el("label", { class: "f-label" }, "Tabs to walk"), chips),
      el("div", { class: "field" }, el("label", { class: "f-label" }, "Post depth per tab"), limitSel),
      el("div", { class: "field" },
        el("label", { class: "f-label" }, "Request delay (optional)"),
        el("input", { class: "input", placeholder: "empty = gallery-dl default (6–12 s, safest)", value: st.instagram_delay || "",
          onchange: (e) => save({ instagram_delay: e.target.value.trim() }) }),
        el("p", { style: { fontSize: "11.5px", color: "var(--text-3)", marginTop: 7, lineHeight: 1.5 } },
          "Instagram throttles page fetches and logs out clients that hammer it. Lower the delay only if you accept that risk; stories and highlights always need the logged-in cookie source above.")));
  }

  /* ── appearance ─────────────────────────────────────────────────────────── */
  function secAppearance() {
    const st = S.settings;
    const ACCENTS = {
      violet: ["#a855f7", "#4f7cff"], azure: ["#38bdf8", "#4f7cff"],
      magenta: ["#f472b6", "#a855f7"], mint: ["#34d399", "#38bdf8"],
    };
    const sw = el("div", { class: "swatches" });
    for (const [name, [c1, c2]] of Object.entries(ACCENTS)) {
      const b = el("button", { class: `swatch${st.accent === name ? " on" : ""}`, title: name,
        style: { background: `linear-gradient(120deg, ${c1}, ${c2})`, "--sw-c": c1 } });
      b.addEventListener("click", () => {
        $$(".swatch", sw).forEach((x) => x.classList.remove("on"));
        b.classList.add("on");
        document.documentElement.dataset.accent = name;
        save({ accent: name });
      });
      sw.append(b);
    }
    return card("Appearance", "Dark is the only honest theme for a downloader at 2 a.m.", "sparkle",
      el("div", { class: "field" }, el("label", { class: "f-label" }, "Accent glow"), sw),
      setRow("Ambient effects", "Drifting light orbs + film grain behind the glass.", switchOpt("ambient_effects", st.ambient_effects)));
  }

  /* ── system ─────────────────────────────────────────────────────────────── */
  function secSystem() {
    const st = S.settings;
    const m = S.meta;
    const upd = el("button", { class: "btn btn-ghost btn-sm", onclick: async (e) => {
      const b = e.currentTarget; const orig = b.innerHTML;
      b.disabled = true; b.innerHTML = `<span class="spinner"></span> pip update…`;
      try {
        const r = await window.API.selfupdate();
        if (r.ok) { toast(`yt-dlp → ${r.version}. Restart the app to load it.`, "ok"); }
        else toast(`pip failed: ${(r.detail || "").slice(-160)}`, "err", { ttl: 9000 });
      } catch (err) { toast(err.message, "err"); }
      finally { b.disabled = false; b.innerHTML = orig; }
    } }, "Update now");
    return card("System", "Runtime health.", "cpu",
      el("div", { class: "set-row" },
        el("div", { class: "sr-txt" },
          el("b", {}, `yt-dlp extractor · ${m.system.yt_dlp || "not installed"}`
            + (m.system.yt_dlp_engine?.use_cli ? "  ·  🖥 your system CLI (active)" : "")),
          el("span", {}, m.system.yt_dlp_engine?.use_cli
            ? "The app found a NEWER yt-dlp on your PATH and is driving that binary directly — terminal parity by construction. Update it there (or click Update now to also refresh the app's private copy)."
            : "YouTube changes its API weekly. If your terminal's yt-dlp works but the app does not, the app's bundled copy is stale — hit Update now (or install a fresh yt-dlp on PATH and restart: the app prefers it automatically).")),
        upd),
      el("div", { style: { marginTop: 8 } },
        el("div", { class: "kv" }, el("span", { class: "k" }, "App"), el("span", { class: "v" }, `${m.app} ${m.version}`)),
        el("div", { class: "kv" }, el("span", { class: "k" }, "Shell"), el("span", { class: "v" }, m.system.desktop ? "pywebview · frameless · WebView2" : "browser dev mode")),
        el("div", { class: "kv" }, el("span", { class: "k" }, "Backend"), el("span", { class: "v" }, `Python ${m.python} · FastAPI`)),
        el("div", { class: "kv" }, el("span", { class: "k" }, "Platform"), el("span", { class: "v" }, m.platform)),
        el("div", { class: "kv" }, el("span", { class: "k" }, "Site recipes"),
          el("span", { class: "v" }, `${m.system.sites?.recipes || 0} sites · player-config engine`)),
        el("div", { class: "kv" }, el("span", { class: "k" }, "gallery-dl"),
          el("span", { class: "v" }, m.system.gallery_dl?.available
            ? `${m.system.gallery_dl.version}${m.system.gallery_dl.exe ? " · " + m.system.gallery_dl.exe : " (module)"}`
            : "not installed — the Instagram checker is disabled")),
        el("div", { class: "kv" }, el("span", { class: "k" }, "TLS impersonation"),
          el("span", { class: "v" }, m.system.tls_impersonation
            ? "on · curl_cffi (browser fingerprint for bot walls)"
            : "off · pip install curl_cffi to beat Cloudflare 403s")),
        el("div", { class: "kv" }, el("span", { class: "k" }, "Settings file"), el("span", { class: "v" }, el("code", {}, m.config_file)))));
  }

  /* ── shared widgets ─────────────────────────────────────────────────────── */
  function setRow(title, sub, control) {
    return el("div", { class: "set-row" },
      el("div", { class: "sr-txt" }, el("b", { html: title }), el("span", {}, sub)), control);
  }
  function switchOpt(key, checked, onChange) {
    const input = el("input", { type: "checkbox" });
    input.checked = !!checked;
    input.addEventListener("change", () => {
      onChange ? onChange(input.checked) : save({ [key]: input.checked });
    });
    return el("label", { class: "switch-line" }, input, el("span", { class: "switch" }));
  }
  /* Reads the configured cookie source locally (no network) and reports exactly
   * what breaks — "Could not copy Chrome cookie database" finally has a button. */
  async function checkCookies() {
    toast("Reading the cookie source…", "info", { icon: "clock", ttl: 2500 });
    try {
      const r = await window.API.cookiesProbe();
      const opts = { icon: r.ok ? "check" : "warning", ttl: r.ok ? 5000 : 16000 };
      if (r.suggest) {
        opts.actionLabel = `Use ${r.suggest}`;
        opts.onAction = () => useBestCookies();
      }
      toast(r.message, r.ok ? "ok" : "warn", opts);
      S.meta = await window.API.meta();
    } catch (e) {
      toast(String(e?.message || e), "err");
    }
  }

  /* One click instead of "go export a cookies.txt": pick the browser on this
     machine whose cookie database actually reads (usually Firefox). */
  async function useBestCookies() {
    try {
      const r = await window.API.cookiesUseBest();
      toast(r.message, r.ok ? "ok" : "warn", { icon: r.ok ? "check" : "warning", ttl: r.ok ? 6000 : 12000 });
      if (r.ok) {
        const merged = await window.API.saveSettings({ ytdlp_browser_cookies: r.browser });
        S.settings = merged;
        S.emit("settings.changed", merged);
        init();
      }
      S.meta = await window.API.meta();
    } catch (e) {
      toast(String(e?.message || e), "err");
    }
  }

  function selectOpt(values, labels, selected, onChange) {
    const s = el("select", { class: "input" });
    for (const v of values) s.append(el("option", { value: v, ...(String(v) === String(selected) ? { selected: "" } : {}) }, labels?.[v] ?? v));
    s.addEventListener("change", () => onChange(s.value));
    return s;
  }

  window.SettingsView = { init };
})();
