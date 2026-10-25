/* WebFinder · app.js — bootstrap, window chrome, navigation shell */
(function () {
  const { $, $$, el, toast } = window.UI;
  const S = window.Store;

  const NAV = [
    { view: "view-search", label: "Search", icon: "search", key: "1" },
    { view: "view-direct", label: "Smart Direct Link", icon: "link", key: "2" },
    { view: "view-downloads", label: "Downloads", icon: "download", key: "3", badge: true },
    { view: "view-settings", label: "Settings", icon: "settings", key: "4" },
  ];

  /* ── boot ─────────────────────────────────────────────────────────────── */
  async function boot() {
    $("#brand-logo").innerHTML = ICONS.svg("search")
      .replace('stroke-width="1.9"', 'stroke-width="2.4" style="width:20px;height:20px;color:#fff"');
    buildTitlebar();
    buildSidebar();
    wireWindow();

    try {
      const [meta, settings] = await Promise.all([window.API.meta(), window.API.getSettings()]);
      S.meta = meta; S.settings = settings;
      window.__WEBFINDER_DESKTOP__ = !!meta.system.desktop;
      applySettings();
      S.selectedEngines = new Set(Object.entries(settings.engines || {}).filter(([, on]) => on).map(([k]) => k));
      netStatus(true);
      S.emit("ready");
      window.API.ws.connect();
    } catch (e) {
      netStatus(false);
      toast("Backend unreachable — is `python run.py` running?", "err", { ttl: 8000 });
      setTimeout(boot, 2500);
      return;
    }

    window.SearchView.init();
    window.DirectView.init();
    window.DownloadsView.init();
    window.SettingsView.init();

    S.on("settings.changed", applySettings);
    S.on("nav", (v) => showView(v));
    requestAnimationFrame(() => document.body.classList.remove("preload"));

    // auto-switch net indicator with WS heartbeats
    S.on("ws", () => {});
    addEventListener("offline", () => netStatus(false));
    addEventListener("online", () => netStatus(true));
  }

  function applySettings() {
    const st = S.settings;
    document.documentElement.dataset.accent = st.accent || "violet";
    document.documentElement.classList.toggle("no-ambient", !st.ambient_effects);
    $("#demo-badge").classList.toggle("hidden", !st.demo_mode);
    $("#cfg-path").textContent = S.meta?.config_file || "";
  }

  /* ── titlebar (custom window frame) ───────────────────────────────────── */
  function buildTitlebar() {
    $("#btn-min").innerHTML = ICONS.svg("minus");
    $("#btn-max").innerHTML = ICONS.svg("square");
    $("#btn-close").innerHTML = ICONS.svg("x");
    const bridge = window.API.bridge;
    $("#btn-min").onclick = () => runDesktop(bridge.minimize);
    const setMaxIcon = (maxed) => { $("#btn-max").innerHTML = ICONS.svg(maxed ? "restore" : "square"); $("#btn-max").dataset.maxed = maxed ? "1" : ""; };
    $("#btn-max").onclick = async (e) => {
      const btn = e.currentTarget;   // capture pre-await: currentTarget clears after dispatch
      const next = await runDesktop(bridge.toggleMaximize);
      setMaxIcon(typeof next === "boolean" ? next : !btn.dataset.maxed);
      btn.animate([{ transform: "scale(.8)" }, { transform: "scale(1)" }], { duration: 180, easing: "cubic-bezier(.34,1.56,.64,1)" });
    };
    // double-click on the (draggable) titlebar = maximize/restore, like native windows
    document.querySelector(".titlebar").addEventListener("dblclick", async (e) => {
      if (!bridge.isDesktop || e.target.closest(".no-drag")) return;
      const next = await runDesktop(bridge.toggleMaximize);
      setMaxIcon(typeof next === "boolean" ? next : !$("#btn-max").dataset.maxed);
    });
    $("#btn-close").onclick = () => {
      if (!bridge.isDesktop) { toast("Browser mode — closing the tab instead. Use `python run.py` for the native window.", "info"); return; }
      runDesktop(bridge.close);
    };
    $("#app-version").textContent = `v${S.meta?.version || "1.0"}`;
    document.title = "WebFinder";
  }
  async function runDesktop(fn) { try { return await fn?.(); } catch { /* browser mode */ } }

  function wireWindow() {
    // in the sandbox/browser preview there is no frameless chrome to emulate drag
    let dragging = false, sx = 0;
    document.querySelector(".titlebar").addEventListener("pointerdown", (e) => {
      if (!window.API.bridge.isDesktop) return;
      if (e.target.closest(".no-drag")) return;
      dragging = true; sx = e.clientX;
    });
  }

  /* ── sidebar ────────────────────────────────────────────────────────────── */
  function buildSidebar() {
    const nav = $("#side-nav");
    nav.innerHTML = "";
    NAV.forEach((item, i) => {
      const b = el("button", { class: "nav-item" + (i === 0 ? " active" : ""), "data-view": item.view, title: `${item.label}  ·  Ctrl+${item.key}` },
        el("span", { html: ICONS.svg(item.icon) }),
        el("span", { class: "nav-label" }, item.label),
        item.badge ? el("span", { class: "nav-count hidden", id: "nav-dl-count" }) : null);
      b.addEventListener("click", () => showView(item.view));
      b.addEventListener("mouseenter", () => slideIndicator(b));
      b.addEventListener("mouseleave", () => {
        const a = nav.querySelector(".nav-item.active"); if (a) slideIndicator(a);
      });
      nav.append(b);
    });
    nav.addEventListener("pointerleave", () => {
      const a = nav.querySelector(".nav-item.active"); if (a) slideIndicator(a);
    });
    $("#btn-about").innerHTML = `${ICONS.svg("info")}<span>About</span>`;
    $("#btn-about").addEventListener("click", showAbout);
    $("#btn-collapse").innerHTML = ICONS.svg("panelLeft");
    $("#btn-collapse").addEventListener("click", () => {
      document.body.classList.toggle("rail-min");
      const collapsed = document.body.classList.contains("rail-min");
      localStorage.setItem("wf-rail-min", collapsed ? "1" : "");
    });
    if (localStorage.getItem("wf-rail-min")) document.body.classList.add("rail-min");
    addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && "1234".includes(e.key)) {
        e.preventDefault();
        showView(NAV[+e.key - 1].view);
      }
    });
    setTimeout(() => { const a = nav.querySelector(".active"); if (a) slideIndicator(a); }, 30);
  }

  /* ── About sheet (graphical, with author card) ──────────────────────────── */
  function showAbout() {
    const chip = (t) => el("span", { class: "about-chip" }, t);
    const feat = (icon, title, text) => el("div", { class: "about-feat" },
      el("span", { class: "af-ico", html: ICONS.svg(icon) }),
      el("div", {}, el("b", {}, title), el("p", {}, text)));
    const openExt = (u) => {
      try { const w = window.open(u, "_blank", "noopener"); if (!w) throw new Error("blocked"); }
      catch { window.UI.copyText(u); toast("Link copied to the clipboard.", "info"); }
    };
    const body = el("div", {},
      el("div", { class: "about-hero" },
        el("div", { class: "ah-ico", html: ICONS.svg("search") }),
        el("div", {},
          el("h2", {}, "WebFinder", el("i", {}, "v1.0")),
          el("p", {}, "Dork-aware meta search for REAL files — images, videos, torrents, e-books, archives and software — with a built-in parallel download manager."))),
      el("div", { class: "about-feats" },
        feat("zap", "True media verticals", "One chip queries YouTube, Bing Images, apibay, Nyaa, Gutenberg, Open Library… — never padded with web-page filler."),
        feat("search", "Google-dork aware", "filetype:, intitle:index of, site: and friends run across five engines, merged and deduped."),
        feat("download", "IDM-ready links", "Every card exposes the direct file URL for one-click copy; the manager adds Range resume, pause, retry and speed stats."),
        feat("shield", "Honest failures", "A blocked index shows its actual error instead of lying with irrelevant results — with the fixes that work."),
        feat("cpu", "Native desktop shell", "pywebview window: drag, maximize/restore, native folder picker, auto-installed FFmpeg. Or run browser.bat."),
        feat("sparkle", "Smart download plans", "HLS/DASH remux through FFmpeg; platform videos honor the exact quality you picked via yt-dlp.")),
      el("div", { class: "about-chips" },
        chip("pywebview"), chip("FastAPI"), chip("yt-dlp"), chip("curl-cffi"), chip("FFmpeg"), chip("httpx"), chip("WebView2")),
      el("div", { class: "about-author" },
        el("div", { class: "aa-ava" }, "BE"),
        el("div", { style: { flex: "1" } },
          el("b", {}, "Behnam Ehsani"),
          el("p", {}, "Design · code · relentless edge-case hunting")),
        el("button", { class: "btn btn-ghost btn-sm", onclick: () => openExt("mailto:inbox.ehsani@gmail.com") }, "Email"),
        el("button", { class: "btn btn-ghost btn-sm", onclick: () => openExt("https://github.com/wrappedman") }, "GitHub")));
    window.UI.modal({ title: "About WebFinder", body, actions: [{ label: "Close", primary: true }] });
  }

  function slideIndicator(target) {
    const nav = $("#side-nav");
    nav.style.setProperty("--nav-y", `${target.offsetTop}px`);
  }

  function showView(viewId) {
    const views = $$(".view");
    const current = views.find((v) => v.classList.contains("active"));
    if (current?.id === viewId) return;
    if (current) current.classList.remove("active");
    const next = document.getElementById(viewId);
    next.style.animation = "";          // re-arm the view-in transition every visit
    next.classList.add("active");
    $$(".nav-item").forEach((n) => n.classList.toggle("active", n.dataset.view === viewId));
    const active = document.querySelector(".nav-item.active");
    if (active) slideIndicator(active);
    document.getElementById("viewport").scrollTop = 0;
  }

  /* ── global badges / status ─────────────────────────────────────────────── */
  function syncRail() {
    const badge = $("#nav-dl-count");
    if (!badge) return;
    const n = S.activeCount;
    badge.textContent = n;
    badge.classList.toggle("hidden", !n);
  }
  S.on("job.update", syncRail);
  S.on("jobs.hydrated", syncRail);

  function netStatus(online) {
    const n = $("#net-status");
    n.classList.toggle("online", online);
    n.classList.toggle("offline", !online);
    n.querySelector(".net-label").textContent = online ? "connected" : "offline";
  }

  window.App = { boot, showView, syncRail };
  document.readyState === "loading" ? addEventListener("DOMContentLoaded", boot) : boot();
})();
