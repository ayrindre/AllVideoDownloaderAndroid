/* All Video Downloader · views/instagram.js — Instagram checker (gallery-dl)
 *
 * Paste a profile URL or @handle → gallery-dl walks posts / reels / stories /
 * highlights / tagged and this view lists every media file it found. Select
 * what you want, hit Download, and the files stream through the normal
 * Download Manager (pause/resume/progress included).
 */
(function () {
  const { $, el, toast } = window.UI;
  const S = window.Store;

  const FALLBACK_TARGETS = [
    { key: "posts", label: "Posts", about: "everything on the grid", icon: "image" },
    { key: "reels", label: "Reels", about: "short vertical videos", icon: "film" },
    { key: "stories", label: "Stories", about: "live 24h", icon: "clock" },
    { key: "highlights", label: "Highlights", about: "saved story collections", icon: "book" },
    { key: "tagged", label: "Tagged", about: "posts the account is tagged in", icon: "search" },
  ];
  const LIMITS = [10, 20, 30, 60, 120, 0];

  let targets = FALLBACK_TARGETS;
  let engine = { available: false, version: "", install_hint: "" };
  let include = new Set();
  let limit = 30;
  let scan = null;          // last scan snapshot
  let pollTimer = null;
  let pollToken = 0;
  let selected = new Set();
  let cardNodes = new Map();  // item id → DOM node (selection updates in place)
  let filter = "all";         // all | video | image
  let cookieSig = "";         // last cookie-source state shown in the scan bar

  /* ── init ──────────────────────────────────────────────────────────────── */
  async function init() {
    $("#ig-icon").innerHTML = ICONS.svg("instagram");
    $("#ig-scan .btn-ico").innerHTML = ICONS.svg("scan");
    $("#ig-options").innerHTML = "";

    try {
      engine = await window.API.galleryEngine();
      if (engine.targets?.length) targets = engine.targets;
    } catch { /* keep fallbacks */ }

    const saved = String(S.settings?.instagram_include || "posts,reels")
      .split(",").map((s) => s.trim()).filter(Boolean);
    include = new Set(saved.length ? saved : ["posts", "reels"]);
    limit = Number(S.settings?.instagram_limit ?? 30) || 30;

    renderEngineBadge();
    renderOptions();
    renderIdle();
    restoreLastScan();

    $("#ig-scan").addEventListener("click", startScan);
    $("#ig-paste").addEventListener("click", async () => {
      try { $("#ig-url").value = (await navigator.clipboard.readText()).trim(); $("#ig-url").focus(); }
      catch { toast("Clipboard read needs permission — paste with Ctrl+V.", "warn"); }
    });
    $("#ig-url").addEventListener("keydown", (e) => { if (e.key === "Enter") startScan(); });
  }

  /* after a reload the tab should not look empty if a scan already exists */
  async function restoreLastScan() {
    try {
      const { scans } = await window.API.galleryScans();
      const last = scans?.[0];
      if (!last || scan) return;        // a fresh scan already started — never clobber it
      scan = last;
      selected = new Set();
      render(last);
      if (["queued", "scanning"].includes(last.status)) poll(last.id);
      else btnReset(true);
    } catch { /* first run / API older than this tab */ }
  }

  function renderEngineBadge() {
    const box = $("#ig-engine-badge");
    box.innerHTML = "";
    if (engine.available) {
      box.append(el("span", { class: "cap ok", title: "gallery-dl is the profile walker behind this tab" },
        el("span", { class: "dot" }), `gallery-dl ${engine.version || ""}`.trim()));
    } else {
      box.append(el("button", {
        class: "btn btn-danger-ghost btn-sm",
        title: engine.install_hint || "",
        onclick: () => window.UI.copyText(engine.install_hint || "pip install gallery-dl").then(() => toast("Install command copied — run it, then restart the app.", "info")),
      }, "gallery-dl missing — copy install command"));
    }
  }

  function renderOptions() {
    const row = $("#ig-options");
    row.innerHTML = "";
    row.append(el("span", { class: "qlabel" }, "Scan"));
    for (const t of targets) {
      const on = include.has(t.key);
      const chip = el("button", { class: `chip${on ? " on" : ""}`, type: "button", title: t.about || "",
        style: { "--chip-c": "#e1306c", height: "32px", padding: "0 12px" } },
        el("span", { html: ICONS.svg(t.icon || "image") }), t.label);
      chip.addEventListener("click", () => {
        if (include.has(t.key)) { if (include.size > 1) include.delete(t.key); }
        else include.add(t.key);
        chip.classList.toggle("on", include.has(t.key));
        savePrefs();
      });
      row.append(chip);
    }
    row.append(el("span", { class: "qlabel", style: { marginLeft: "10px" } }, "Newest"));
    const sel = el("select", { class: "input ig-limit", title: "How many posts per tab to walk" });
    for (const n of LIMITS) {
      sel.append(el("option", { value: String(n), ...(n === limit ? { selected: "" } : {}) },
        n ? `${n} posts` : "everything"));
    }
    sel.addEventListener("change", () => { limit = Number(sel.value); savePrefs(); });
    row.append(sel);
    row.append(el("button", {
      class: "btn btn-ghost btn-sm ig-session-btn", type: "button", onclick: openSessionModal,
      title: "Paste an Instagram login (sessionid) — the fix when the browser's cookie DB is locked",
    }, el("span", { class: "btn-ico", html: ICONS.svg("shield") }), "Session"));
    row.append(sessionChip());
  }

  /* Instagram shows almost nothing to a logged-out client, so the state of the
   * cookie source belongs on screen — not only in the error that follows. */
  function sessionChip() {
    const c = S.meta?.system?.cookies || {};
    const hasMeta = c && Object.keys(c).length > 0;
    /* the server value is authoritative: a failed source is '' for mode, and
       falling back to the saved setting here is what painted "chrome session"
       green while every scan was actually running logged out */
    const mode = hasMeta ? (c.mode || "") : (S.settings?.cookies_file ? "file" : (S.settings?.ytdlp_browser_cookies ? "browser" : ""));
    const failed = !!c.browser_failed;
    /* active_browser is what the engines will really use: when the chosen one is
       unreadable it is either a readable fallback or nothing at all */
    const active = c.active_browser || "";
    const label = failed ? (active ? `${active} (fallback)` : "cookies unreadable")
      : mode === "file" ? `${String(c.file || "").split(/[\\/]/).pop() || "cookies.txt"}`
      : mode === "browser" ? `${active || c.browser || S.settings?.ytdlp_browser_cookies || "browser"} session`
      : "logged out";
    const cls = failed ? (active ? "warn" : "err") : mode ? "ok" : "muted";
    const title = failed ? "The browser's cookie database could not be read — click to check."
      : mode ? "Cookie source used for scans"
      : "No cookie source: Instagram hides most profiles, stories and 18+ content from logged-out requests. Click to check.";
    return el("button", { class: `ig-session ${cls}`, type: "button", title, onclick: checkCookies },
      el("i", { class: "dot" }), label);
  }

  const savePrefs = window.UI.debounce((() => {
    const patch = { instagram_include: [...include].join(","), instagram_limit: limit };
    window.API.saveSettings(patch).then((merged) => { S.settings = merged; }).catch(() => {});
  }), 400);

  /* ── scan ──────────────────────────────────────────────────────────────── */
  async function startScan() {
    const url = $("#ig-url").value.trim();
    if (!url) { $("#ig-url").focus(); return; }
    if (!engine.available) {
      toast("gallery-dl is not installed — copy the install command from the badge above.", "err", { ttl: 7000 });
      return;
    }
    const btn = $("#ig-scan");
    btn.disabled = true;
    btn.querySelector("span:last-child").textContent = "Checking…";
    selected = new Set();
    scan = null;
    stopPolling();
    renderScanning(url);

    try {
      const { scan: started } = await window.API.galleryScan({ url, include: [...include], limit });
      scan = started;
      render(scan);
      poll(started.id);
    } catch (err) {
      btn.disabled = false;
      btn.querySelector("span:last-child").textContent = "Check profile";
      renderError(err.message);
    }
  }

  function poll(id) {
    const token = ++pollToken;
    stopPolling();
    const tick = async () => {
      if (token !== pollToken) return;
      try {
        const { scan: snap } = await window.API.galleryScanStatus(id);
        scan = snap;
        render(snap);
        const running = ["queued", "scanning"].includes(snap.status);
        btnReset(!running);
        if (running) pollTimer = setTimeout(tick, 1300);
      } catch (err) {
        if (token === pollToken) renderError(err.message);
      }
    };
    tick();
  }

  function stopPolling() { if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; } }

  function btnReset(idle) {
    const btn = $("#ig-scan");
    btn.disabled = !idle;
    btn.querySelector("span:last-child").textContent = idle ? "Check profile" : "Checking…";
  }

  /* ── renderers ─────────────────────────────────────────────────────────── */
  function stage() { const s = $("#ig-stage"); s.innerHTML = ""; return s; }

  function renderIdle() {
    const s = stage();
    s.append(el("div", { class: "ig-idle card" },
      el("div", { class: "ig-idle-ico", html: ICONS.svg("instagram") }),
      el("h3", {}, "Who are we checking?"),
      el("p", {}, "Paste a profile link (or ", el("code", {}, "@handle"), ") and the checker walks the account with ",
        el("b", {}, "gallery-dl"), ": posts, reels, stories, highlights and tagged media — every file it finds becomes a selectable card."),
      el("p", { class: "ig-hint" }, engine.available
        ? "Instagram shows profiles to logged-out visitors only partially. For private accounts, stories and 18+ content, set Settings → Video & capture → Browser cookies source to your browser (and fully close that browser first)."
        : "gallery-dl is not installed yet — open Settings → System or run: pip install gallery-dl")));
  }

  function renderScanning(url) {
    const s = stage();
    s.append(el("div", { class: "card ig-progress" },
      el("div", { class: "ig-prog-head" },
        el("span", { class: "spinner" }),
        el("div", {},
          el("b", {}, "Walking the profile…"),
          el("p", {}, `Starting gallery-dl for ${url}`))),
      el("div", { class: "ig-hint" }, "Instagram rate-limits page fetches (a few seconds each), so a full scan can take a minute. Results appear as each tab finishes.")));
  }

  /* A scan that worked, but not the way the user asked (e.g. it ran logged out
   * because the browser's cookie DB was unreadable) — say so, with the fix. */
  function warnCard(warnings) {
    return el("div", { class: "ig-warn" },
      el("span", { html: ICONS.svg("warning") }),
      el("div", {},
        ...warnings.slice(0, 2).map((w) => el("div", {}, w)),
        el("div", { class: "ig-warn-actions" },
          el("button", { class: "btn btn-primary btn-sm", onclick: openSessionModal }, "Use my session"),
          el("button", { class: "btn btn-ghost btn-sm", onclick: checkCookies }, "Check cookies"),
          el("button", { class: "btn btn-ghost btn-sm", onclick: applyBestCookies }, "Fix cookies"),
          el("button", { class: "btn btn-ghost btn-sm", onclick: () => window.App.showView("view-settings") }, "Open settings"))));
  }

  async function checkCookies() {
    try {
      const r = await window.API.cookiesProbe();
      const opts = { icon: r.ok ? "check" : "warning", ttl: r.ok ? 5000 : 16000 };
      if (r.suggest) {
        opts.actionLabel = `Use ${r.suggest}`;         // one click, no file juggling
        opts.onAction = () => applyBestCookies();
      }
      toast(r.message, r.ok ? "ok" : "warn", opts);
      await refreshCookieState();
    } catch (e) {
      toast(String(e?.message || e), "err");
    }
  }

  /* The reliable path on Windows: Chrome's cookie DB cannot be read, so let the
   * user paste the one cookie that matters and turn it into a cookies.txt. */
  function openSessionModal() {
    const area = el("textarea", {
      class: "input ig-session-input", rows: "4", spellcheck: "false",
      placeholder: "sessionid=5xxxxxxx%3Axxxx%3Axx…    (or the whole cookies.txt, or a `cookie:` line)",
    });
    const steps = el("div", { class: "ig-session-help" },
      el("p", {}, "1. Open ", el("b", {}, "instagram.com"), " in your browser and sign in."),
      el("p", {}, "2. Press ", el("b", {}, "F12"), " → Application (Chrome/Edge) or Storage (Firefox) → ",
        el("b", {}, "Cookies"), " → https://www.instagram.com, then copy the value of ",
        el("code", {}, "sessionid"), " — or right-click any instagram.com request → ",
        el("b", {}, "Copy as cURL"), " and paste the whole cookie part."),
      el("p", {}, "3. Paste it below. It is stored locally in ",
        el("code", {}, "~/.avd/instagram-cookies.txt"), " and used by the checker instead of ",
        "the browser database that Chrome keeps locked."));

    const close = window.UI.modal({
      title: "Instagram session",
      body: el("div", { class: "ig-session-form" }, steps, area,
        el("p", { class: "ig-hint" }, "Nothing is uploaded — the cookie goes to Instagram, ",
          "the same place your browser sends it.")),
      actions: [
        { label: "Cancel" },
        {
          label: "Save & scan", primary: true, close: false,
          onClick: async () => {
            try {
              const r = await window.API.cookiesSession(area.value.trim());
              toast(r.message, r.ok ? "ok" : "warn",
                { icon: r.ok ? "check" : "warning", ttl: r.ok ? 6000 : 12000 });
              await refreshCookieState();
              if (!r.ok) return;
              close();
              // no link typed yet → just put the caret where the work starts
              if ($("#ig-url").value.trim()) startScan();
              else $("#ig-url").focus();
            } catch (e) {
              toast(String(e?.message || e), "err");
            }
          },
        },
      ],
    });
    setTimeout(() => area.focus(), 60);
  }

  async function applyBestCookies() {
    try {
      const r = await window.API.cookiesUseBest();
      toast(r.message, r.ok ? "ok" : "warn", { icon: r.ok ? "check" : "warning", ttl: r.ok ? 6000 : 12000 });
      if (r.ok) { S.settings = { ...(S.settings || {}), ytdlp_browser_cookies: r.browser }; }
      await refreshCookieState();
    } catch (e) {
      toast(String(e?.message || e), "err");
    }
  }

  async function refreshCookieState() {
    try {
      const meta = await window.API.meta();
      S.meta = meta;
      renderOptions();
    } catch { /* the toast already told the story */ }
  }

  function render(snap) {
    if (!snap) return;
    /* the scan tells us what the cookie source did — keep the pill honest */
    if (snap.cookies) {
      const sig = `${snap.cookies.mode}|${snap.cookies.browser_failed}|${snap.cookies.file}`;
      if (sig !== cookieSig) {
        cookieSig = sig;
        S.meta = { ...(S.meta || {}), system: { ...(S.meta?.system || {}), cookies: snap.cookies } };
        renderOptions();
      }
    }
    const s = stage();
    const running = ["queued", "scanning"].includes(snap.status);
    const items = snap.items || [];

    /* header card: who, progress, per-tab status, selection actions */
    const head = el("div", { class: "card ig-head" });
    const title = el("div", { class: "ig-title" },
      el("div", { class: "ig-ava", html: ICONS.svg("instagram") }),
      el("div", { style: { minWidth: 0 } },
        el("h2", {}, snap.username ? `@${snap.username}` : (snap.source?.username ? `@${snap.source.username}` : "Instagram")),
        el("p", {}, snap.fullname || (snap.source?.kind === "post" ? "single post" : "profile scan"),
          " · ", el("span", { class: "ig-muted" }, `${snap.counts?.total || 0} media · ${snap.counts?.videos || 0} video · ${snap.counts?.posts || 0} posts`))));

    const actions = el("div", { class: "ig-head-actions" });
    if (running) {
      actions.append(el("button", { class: "btn btn-ghost btn-sm", onclick: cancelScan }, "Cancel scan"));
    } else {
      actions.append(el("button", { class: "btn btn-ghost btn-sm", onclick: () => selectAll("video") }, "Select all videos"));
      actions.append(el("button", { class: "btn btn-ghost btn-sm", onclick: () => selectAll("all") }, "Select all"));
      actions.append(el("button", { class: "btn btn-ghost btn-sm", onclick: () => selectAll("clear") }, "Clear"));
    }
    head.append(el("div", { class: "ig-head-row" }, title, actions));

    /* per-tab progress */
    const tabs = el("div", { class: "ig-tabs" });
    for (const t of snap.targets || []) {
      const state = t.status;
      const cls = state === "done" ? "ok" : state === "error" ? "err" : state === "empty" ? "muted" : "run";
      tabs.append(el("span", { class: `ig-tab ${cls}`, title: t.error || "" },
        el("i", { class: "dot" }), t.label,
        el("b", {}, state === "scanning" ? "…" : String(t.count ?? 0))));
    }
    head.append(tabs);

    if (snap.errors?.length) {
      head.append(el("div", { class: "notice warn" },
        el("span", { html: ICONS.svg("warning") }),
        el("div", {}, ...snap.errors.slice(0, 3).map((e) => el("div", {}, e)))));
    }
    if (snap.warnings?.length) head.append(warnCard(snap.warnings));
    s.append(head);

    if (!items.length) {
      if (!running) {
        s.append(el("div", { class: "card ig-empty" },
          el("b", {}, "No media came back."),
          el("p", {}, "Instagram hides most of a profile from logged-out visitors, and private accounts return nothing at all. ",
            "Set Settings → Video & capture → ", el("b", {}, "Browser cookies source"), " to the browser you are logged into Instagram with, close that browser completely, then scan again.",
            " If Chrome keeps answering “Could not copy Chrome cookie database”, export a cookies.txt instead (Settings → ", el("b", {}, "Cookies file"), ") — that source always reads."),
          el("div", { class: "ig-warn-actions", style: { marginTop: "4px" } },
            el("button", { class: "btn btn-primary btn-sm", onclick: openSessionModal }, "Use my Instagram session"),
            el("button", { class: "btn btn-ghost btn-sm", onclick: checkCookies }, "Check my cookies"),
            el("button", { class: "btn btn-ghost btn-sm", onclick: () => window.App.showView("view-settings") }, "Open settings"))));
      }
      return;
    }

    /* filter + download bar */
    const bar = el("div", { class: "ig-bar" });
    const seg = el("div", { class: "ig-seg" });
    for (const [key, label] of [["all", "All"], ["video", "Videos"], ["image", "Photos"]]) {
      const b = el("button", { class: `ig-seg-btn${filter === key ? " on" : ""}`, onclick: () => { filter = key; render(snap); } }, label);
      seg.append(b);
    }
    bar.append(seg);
    bar.append(el("div", { style: { flex: 1 } }));
    bar.append(el("span", { class: "ig-muted", id: "ig-sel-count" }, `${selected.size} selected`));
    bar.append(el("button", {
      class: "btn btn-primary btn-sm",
      id: "ig-download-btn",
      onclick: downloadSelected,
      ...(selected.size ? {} : { disabled: "" }),
    }, el("span", { class: "btn-ico", html: ICONS.svg("download") }),
      el("span", { id: "ig-download-label" }, `Download selected${selected.size ? ` (${selected.size})` : ""}`)));
    s.append(bar);

    /* media grid */
    const shown = items.filter((i) => filter === "all" || i.kind === filter);
    const grid = el("div", { class: "ig-grid" });
    cardNodes.clear();
    shown.slice(0, 300).forEach((it, idx) => {
      const node = card(it, idx);
      cardNodes.set(it.id, node);
      grid.append(node);
    });
    s.append(grid);
    if (shown.length > 300) s.append(el("p", { class: "ig-muted", style: { marginTop: "10px" } },
      `Showing the first 300 of ${shown.length} — download them, then scan a smaller post limit for the rest.`));
  }

  function card(it, idx) {
    const on = selected.has(it.id);
    const node = el("figure", {
      class: `ig-card${on ? " on" : ""}`,
      style: { "--i": String(idx % 40) },
      title: it.caption || it.filename,
      onclick: (e) => { if (e.target.closest("button")) return; toggle(it.id); },
    });
    const thumb = el("div", { class: "ig-thumb" });
    if (it.thumbnail) {
      const img = el("img", { alt: "", loading: "lazy" });
      img.onerror = () => { img.remove(); thumb.classList.add("noimg"); };
      img.src = it.thumbnail;
      thumb.append(img);
    } else {
      thumb.classList.add("noimg");
    }
    thumb.append(el("span", { class: "ig-badge" }, it.kind === "video" ? "VIDEO" : it.kind === "audio" ? "AUDIO" : "PHOTO"));
    thumb.append(el("span", { class: "ig-target" }, it.target || it.type || ""));
    node.append(thumb);

    const meta = el("figcaption", { class: "ig-cap" },
      el("span", { class: "ig-cap-text" }, it.caption || it.post || it.filename),
      el("span", { class: "ig-cap-sub" },
        it.date ? new Date(it.date * 1000).toLocaleDateString() : "",
        it.date ? " · " : "",
        it.ext?.toUpperCase() || ""));
    node.append(meta);

    node.append(el("span", { class: "ig-check", html: ICONS.svg("check") }));
    const links = el("div", { class: "ig-links" },
      it.post_url ? el("button", { class: "ig-mini", title: "Open the original post",
        onclick: () => window.open(it.post_url, "_blank", "noopener") }, "post") : null,
      el("button", { class: "ig-mini", title: "Download just this file",
        onclick: async () => { await download([it]); } }, "get"));
    node.append(links);
    return node;
  }

  /* selection is a class toggle + counter update — re-rendering the grid on
     every click would restart every thumbnail request */
  function toggle(id) {
    if (selected.has(id)) selected.delete(id); else selected.add(id);
    cardNodes.get(id)?.classList.toggle("on", selected.has(id));
    syncSelection();
  }

  function syncSelection() {
    const count = $("#ig-sel-count");
    const label = $("#ig-download-label");
    const btn = $("#ig-download-btn");
    const n = selected.size;
    if (count) count.textContent = `${n} selected`;
    if (label) label.textContent = `Download selected${n ? ` (${n})` : ""}`;
    if (btn) btn.disabled = !n;
  }

  function selectAll(what) {
    const items = scan?.items || [];
    if (what === "clear") selected.clear();
    else items.forEach((i) => { if (what === "all" || i.kind === what) selected.add(i.id); });
    cardNodes.forEach((node, id) => node.classList.toggle("on", selected.has(id)));
    syncSelection();
  }

  async function cancelScan() {
    if (!scan) return;
    try { await window.API.galleryScanCancel(scan.id); toast("Scan cancelled.", "info"); }
    catch (err) { toast(err.message, "err"); }
  }

  async function downloadSelected() {
    const items = (scan?.items || []).filter((i) => selected.has(i.id));
    if (!items.length) return;
    await download(items);
    selected.clear();
    cardNodes.forEach((node) => node.classList.remove("on"));
    syncSelection();
  }

  async function download(items) {
    try {
      const res = await window.API.galleryDownload(items.map((i) => ({
        url: i.url, filename: i.filename, kind: i.kind, post: i.post,
      })));
      toast(`${res.queued} file${res.queued === 1 ? "" : "s"} queued — watch them in the Download Manager.`,
        "ok", { icon: "dl", actionLabel: "View", onAction: () => S.emit("nav", "view-downloads") });
    } catch (err) { toast(err.message, "err"); }
  }

  function renderError(msg) {
    const s = stage();
    s.append(el("div", { class: "card" },
      el("div", { class: "notice err", html: `${ICONS.svg("warning")}<div>${escapeHtml(msg)}</div>` }),
      el("p", { class: "ig-muted", style: { marginTop: "12px" } },
        "Tips: Instagram needs a logged-in session for most profiles (Settings → Browser cookies source), ",
        "a private account can never be listed, and a very large account is better handled with a smaller post limit.")));
    btnReset(true);
  }

  function escapeHtml(str) {
    const d = document.createElement("div");
    d.textContent = str ?? "";
    return d.innerHTML;
  }

  window.InstagramView = { init };
})();
