/* WebFinder · views/settings.js — everything persisted server-side to settings.json */
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
    $("#cfg-path").textContent = S.meta?.config_file || "~/.webfinder/settings.json";

    grid.append(secDownloads(), secSearch(), secMedia(), secAppearance(), secSystem());
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
    return card("Downloads", "Where files land and how hard WebFinder pulls.", "download",
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
      setRow("Simulate on network failure", "If the remote host is unreachable, finish the job in simulation so nothing looks broken.",
        switchOpt("simulate_on_network_error", st.simulate_on_network_error)));
  }

  /* ── search ─────────────────────────────────────────────────────────────── */
  function secSearch() {
    const st = S.settings;
    const engWrap = el("div", { class: "eng-grid" });
    for (const [key, m] of Object.entries(S.meta.engines)) {
      engWrap.append(setRow(
        `<span style="display:inline-flex;align-items:center;gap:7px"><span class="dot" style="width:8px;height:8px;border-radius:50%;background:${m.color};display:inline-block"></span>${m.label}</span>`,
        `Reliability: ${m.reliability}`,
        switchOpt(`engines.${key}`, st.engines?.[key], (v) => save({ engines: { [key]: v } }))));
    }
    const limitSel = selectOpt(["20", "40", "60", "100"], { "20": "20", "40": "40", "60": "60", "100": "100" }, String(st.result_limit), (v) => save({ result_limit: +v }));
    return card("Search", "Engines get the raw query plus dork operators for the file types you toggle.", "search",
      engWrap,
      el("div", { class: "field", style: { marginTop: 12 } }, el("label", { class: "f-label" }, "Results per search"), limitSel),
      el("div", { class: "field" },
        el("label", { class: "f-label" }, "Scrape proxy (optional)"),
        el("input", { class: "input", placeholder: "http://127.0.0.1:7890 · socks5://user:pass@host:port", value: st.proxy || "", onchange: (e) => save({ proxy: e.target.value.trim() }) })),
        el("p", { style: { fontSize: "11.5px", color: "var(--text-3)", marginTop: 7, lineHeight: 1.5 } },
        "Useful when Yandex/Google captcha-wall your residential or datacenter IP."),
      setRow("Deep-link scan", "Crawl top result pages to reveal hidden direct file links (extra requests, slower but golden for Copy-Link).",
        switchOpt("resolve_pages", st.resolve_pages)));
  }

  /* ── media ──────────────────────────────────────────────────────────────── */
  function secMedia() {
    const st = S.settings;
    const ff = S.meta.system.ffmpeg;
    const caps = el("div", { style: { display: "flex", gap: 8, flexWrap: "wrap", margin: "4px 0 14px" } },
      el("span", { class: `cap ${ff.available ? "ok" : "bad"}`, html: `<span class="dot"></span>FFmpeg ${ff.available ? "detected" : "not found"}` }),
      el("span", { class: `cap ${S.meta.system.yt_dlp ? "ok" : "bad"}`, html: `<span class="dot"></span>yt-dlp ${S.meta.system.yt_dlp || "not installed"}` }));
    const containerSel = selectOpt(["mp4", "mkv", "webm", "mov"], { mp4: "MP4 (best compatibility)", mkv: "MKV (max flexibility)", webm: "WebM", mov: "MOV" }, st.default_container, (v) => save({ default_container: v }));
    const qualitySel = selectOpt(["best", "2160", "1440", "1080", "720", "480"],
      { best: "Best available", 2160: "2160p (4K)", 1440: "1440p", 1080: "1080p (FHD)", 720: "720p", 480: "480p" },
      String(st.default_quality), (v) => save({ default_quality: v }));
    const ffPath = el("input", { class: "input", placeholder: "e.g. C:\\Tools\\ffmpeg\\bin", value: st.ffmpeg_path || "", onchange: (e) => save({ ffmpeg_path: e.target.value }) });
    return card("Media & conversion", "Used by the Smart Direct Link module and stream capture.", "film",
      caps,
      el("div", { class: "field" }, el("label", { class: "f-label" }, "Preferred container"), containerSel),
      el("div", { class: "field" }, el("label", { class: "f-label" }, "Default quality"), qualitySel),
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
          "Windows: ", el("code", {}, "winget install Gyan.FFmpeg"), " then restart WebFinder. Needed for .m3u8/.mpd capture and for merging separate audio+video streams.")));
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
    return card("System", "Runtime health & demo data.", "cpu",
      setRow("Demo mode", "Synthetic search results & simulated transfers — the full UI pipeline without touching the network.",
        switchOpt("demo_mode", st.demo_mode)),
      el("div", { style: { marginTop: 8 } },
        el("div", { class: "kv" }, el("span", { class: "k" }, "App"), el("span", { class: "v" }, `${m.app} ${m.version}`)),
        el("div", { class: "kv" }, el("span", { class: "k" }, "Shell"), el("span", { class: "v" }, m.system.desktop ? "pywebview · frameless · WebView2" : "browser dev mode")),
        el("div", { class: "kv" }, el("span", { class: "k" }, "Backend"), el("span", { class: "v" }, `Python ${m.python} · FastAPI`)),
        el("div", { class: "kv" }, el("span", { class: "k" }, "Platform"), el("span", { class: "v" }, m.platform)),
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
  function selectOpt(values, labels, selected, onChange) {
    const s = el("select", { class: "input" });
    for (const v of values) s.append(el("option", { value: v, ...(String(v) === String(selected) ? { selected: "" } : {}) }, labels?.[v] ?? v));
    s.addEventListener("change", () => onChange(s.value));
    return s;
  }

  window.SettingsView = { init };
})();
