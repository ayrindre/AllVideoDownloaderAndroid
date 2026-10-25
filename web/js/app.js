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
