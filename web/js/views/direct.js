/* WebFinder · views/direct.js — Smart Direct Link module: analyze anything, act accordingly */
(function () {
  const { $, el, toast, fmtBytes, fmtDuration } = window.UI;
  const S = window.Store;

  const QUICK = [
    { label: "YouTube", url: "https://www.youtube.com/watch?v=dQw4w9WgXcQ" },
    { label: "HLS stream", url: "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8" },
    { label: "Direct MP4", url: "https://filesamples.com/samples/video/movie_1080p.mp4" },
    { label: "Linux ISO", url: "https://cdimage.ubuntu.com/lubuntu/releases/24.04/release/lubuntu-24.04.2-desktop-amd64.iso" },
  ];

  let current = null;   // last analysis payload

  function init() {
    $("#pb-icon").innerHTML = ICONS.svg("link");
    $("#btn-analyze .btn-ico").innerHTML = ICONS.svg("scan");
    const ql = $("#quick-links");
    ql.append(el("span", { class: "qlabel" }, "Try"));
    for (const q of QUICK) {
      ql.append(el("button", { class: "qchip", type: "button", onclick: () => { $("#direct-url").value = q.url; analyze(); } }, q.label));
    }
    $("#btn-analyze").addEventListener("click", analyze);
    $("#pb-paste").addEventListener("click", async () => {
      try { $("#direct-url").value = (await navigator.clipboard.readText()).trim(); $("#direct-url").focus(); }
      catch { toast("Clipboard read needs permission — paste with Ctrl+V.", "warn"); }
    });
    $("#direct-url").addEventListener("keydown", (e) => { if (e.key === "Enter") analyze(); });

    const stage = $("#analyze-stage");
    stage.innerHTML = '<div class="analyze-idle" id="analyze-idle"></div>';
    const idle = $("#analyze-idle");
    idle.append(el("div", { class: "ai-inner" },
      el("div", { class: "radar" }, el("div", { class: "ring" }), el("div", { class: "ring" }), el("div", { class: "ring" }),
        el("div", { class: "sweep" }), el("div", { class: "core", html: ICONS.svg("link") })),
      el("p", { style: { marginTop: "22px", fontSize: "13.5px", lineHeight: 1.6 } },
        "Waiting for a URL. Media-platform links get the ", el("b", {}, "yt-dlp"), " treatment, ",
        el("code", {}, ".m3u8"), "/", el("code", {}, ".mpd"), " streams get captured with ", el("b", {}, "FFmpeg"),
        ", and files stream straight into the Download Manager.")));
  }

  async function analyze() {
    const url = $("#direct-url").value.trim();
    if (!url) { $("#direct-url").focus(); return; }
    const btn = $("#btn-analyze");
    btn.disabled = true;
    btn.querySelector("span:last-child").innerHTML = `<span class="spinner"></span>`;
    const stage = $("#analyze-stage");
    stage.innerHTML = "";
    stage.append(el("div", { class: "analyze-idle" },
      el("div", {}, el("div", { class: "radar" }, el("div", { class: "ring" }), el("div", { class: "ring" }), el("div", { class: "ring" }),
        el("div", { class: "sweep" }), el("div", { class: "core", html: ICONS.svg("scan") })),
        el("p", { style: { marginTop: 18, fontSize: "13px", color: "var(--text-3)" } },
          "Probing extractors, manifests and content-type…"))));
    try {
      current = await window.API.analyze(url);
      render(current);
    } catch (err) {
      renderError(err.message);
    } finally {
      btn.disabled = false;
      btn.querySelector("span:last-child").textContent = "Analyze";
    }
  }

  /* ── renderers per result kind ─────────────────────────────────────────── */
  function cardShell(kindLabel, color) {
    const stage = $("#analyze-stage");
    stage.innerHTML = "";
    const card = el("div", { class: "card analyze-card" });
    card.style.setProperty("--ft-c", color);
    const head = el("div", { style: { display: "flex", alignItems: "center", gap: 10, marginBottom: "16px", flexWrap: "wrap" } },
      el("span", { class: "rc-type", style: { "--ft-c": color } }, kindLabel),
      el("div", { style: { flex: 1 } }),
      el("button", { class: "icon-btn", title: "Dismiss", html: ICONS.svg("x"), onclick: () => { init(); } }));
    card.append(head);
    stage.append(card);
    return card;
  }

  function render(d) {
    if (d.kind === "media") return renderMedia(d);
    if (d.kind === "hls") return renderHls(d);
    if (d.kind === "direct") return renderDirect(d);
    if (d.kind === "magnet") return renderMagnet(d);
    return renderPage(d);
  }

  function renderMedia(d) {
    const card = cardShell(`MEDIA · ${d.extractor || "yt-dlp"}`, "#a855f7");
    const sel = { height: pickDefaultQuality(d.formats), format: null };
    sel.format = d.formats.find((f) => f.height === sel.height) || d.formats[0];

    const grid = el("div", { class: "ac-grid" });
    const thumb = el("div", { class: "ac-thumb" });
    if (d.thumbnail) { const img = el("img", { alt: "" }); img.onerror = () => img.remove(); img.src = d.thumbnail; thumb.append(img); }
    else thumb.style.background = "linear-gradient(140deg, #241a3d, #0f172a)";
    if (d.duration) thumb.append(el("span", { class: "dur" }, fmtDuration(d.duration)));

    const info = el("div", {});
    info.append(el("h2", { class: "ac-title" }, d.title));
    info.append(el("div", { class: "ac-meta" },
      d.uploader ? el("span", { html: `${ICONS.svg("globe")} ${escapeHtml(d.uploader)}` }) : null,
      d.view_count ? el("span", { html: `${ICONS.svg("zap")} ${d.view_count.toLocaleString()} views` }) : null,
      el("span", { html: `${ICONS.svg("db")} ${d.formats_total} streams found` })));

    if (!d.ffmpeg && !d.demo) {
      info.append(el("div", { class: "notice warn", style: { marginBottom: "12px" },
        html: `${ICONS.svg("warning")}<div>FFmpeg is not installed — highest qualities that need merging will be replaced by the best single-file stream. Install with <code>winget install Gyan.FFmpeg</code> for full power.</div>` }));
    }

    info.append(el("div", { class: "ac-block-label" }, "Resolution"));
    const qrow = el("div", { class: "chip-set", style: { justifyContent: "flex-start" } });
    let dlBtn = null;
    for (const f of d.formats) {
      const active = f === sel.format;
      const chip = el("button", { class: `chip${active ? " on" : ""}`, type: "button", style: { "--chip-c": f.height >= 2160 ? "#f472b6" : f.height ? "#a855f7" : "#38bdf8", height: "34px", padding: "0 13px" } },
        el("span", { html: ICONS.svg(f.height ? "film" : "audio") }),
        f.label + (f.fps ? ` ${Math.round(f.fps)}fps` : ""),
        f.size ? el("span", { style: { opacity: .55, fontSize: "11px" } }, ` ~${fmtBytes(f.size)}`) : null);
      chip.addEventListener("click", () => {
        sel.height = f.height; sel.format = f;
        [...qrow.children].forEach((c) => c.classList.remove("on"));
        chip.classList.add("on");
        if (dlBtn) dlBtn.querySelector("span:last-child").textContent = `Download ${f.label}`;
      });
      qrow.append(chip);
    }
    info.append(qrow);

    const actions = el("div", { class: "ac-actions" },
      dlBtn = el("button", { class: "btn btn-primary", onclick: (e) => enqueue(e, d, sel.format) },
        el("span", { class: "btn-ico", html: ICONS.svg("download") }), el("span", {}, `Download ${sel.format?.label || ""}`.trim())),
      el("button", { class: "btn btn-ghost", onclick: () => { window.UI.copyText(d.url); toast("Media page URL copied.", "ok", { icon: "copy" }); } },
        el("span", { class: "btn-ico", html: ICONS.svg("copy") }), el("span", {}, "Copy source link")),
      el("a", { class: "btn btn-ghost", href: d.webpage || d.url, target: "_blank", rel: "noopener" },
        el("span", { class: "btn-ico", html: ICONS.svg("external") }), el("span", {}, "Open page")));
    info.append(actions);
    grid.append(thumb, info);
    card.append(grid);
  }

  function pickDefaultQuality(formats) {
    const want = String(window.Store.settings.default_quality || "1080");
    if (want === "best") return formats[0]?.height;
    const hit = formats.find((f) => String(f.height) === want);
    if (hit) return hit.height;
    return (formats.find((f) => f.height) || formats[0] || {}).height;
  }

  function renderHls(d) {
    const card = cardShell("STREAM · HLS/DASH", "#38bdf8");
    const body = el("div", {});
    body.append(el("h2", { class: "ac-title", style: { marginBottom: 6 } }, d.title));
    const kv = el("div", {});
    kv.append(el("div", { class: "kv" }, el("span", { class: "k" }, "Manifest"), el("span", { class: "v" }, d.url.slice(0, 90))));
    if (d.duration) kv.append(el("div", { class: "kv" }, el("span", { class: "k" }, "Duration"), el("span", { class: "v" }, fmtDuration(d.duration))));
    if (d.bit_rate) kv.append(el("div", { class: "kv" }, el("span", { class: "k" }, "Bitrate"), el("span", { class: "v" }, `${(d.bit_rate / 1000).toFixed(0)} kbps`)));
    if (d.streams?.length) kv.append(el("div", { class: "kv" }, el("span", { class: "k" }, "Tracks"),
      el("span", { class: "v" }, d.streams.map((s) => `${s.type}:${s.codec}${s.height ? ` ${s.height}p` : ""}`).join(" · "))));
    body.append(kv);
    if (!d.ffmpeg) {
      body.append(el("div", { class: "notice warn", style: { marginTop: 14 },
        html: `${ICONS.svg("warning")}<div><b>FFmpeg required.</b> Install it (<code>winget install Gyan.FFmpeg</code>) and point WebFinder at it in Settings → FFmpeg path. Capture will be simulated in this demo environment otherwise.</div>` }));
    } else {
      body.append(el("div", { class: "notice info", style: { marginTop: 14 },
        html: `${ICONS.svg("info")}<div>The stream will be captured losslessly with <code>-c copy</code> into a <b>.${window.Store.settings.default_container || "mp4"}</b> container — no re-encode, CPU stays cool.</div>` }));
    }
    body.append(el("div", { class: "ac-actions" },
      el("button", { class: "btn btn-primary", onclick: (e) => enqueue(e, d, { label: "stream" }) },
        el("span", { class: "btn-ico", html: ICONS.svg("film") }), el("span", {}, "Capture & convert")),
      el("button", { class: "btn btn-ghost", onclick: () => { window.UI.copyText(d.url); toast("m3u8 link copied — works with VLC, IDM & yt-dlp too.", "ok", { icon: "copy" }); } },
        el("span", { class: "btn-ico", html: ICONS.svg("copy") }), el("span", {}, "Copy stream URL"))));
    card.append(body);
  }

  function renderDirect(d) {
    const card = cardShell(`FILE · ${d.file_type || "binary"}`, "#34d399");
    const body = el("div", {});
    body.append(el("h2", { class: "ac-title", style: { marginBottom: 10 } }, d.title));
    const kv = el("div", {});
    kv.append(el("div", { class: "kv" }, el("span", { class: "k" }, "Size"), el("span", { class: "v" }, d.size ? fmtBytes(d.size) : "unknown (chunked)")));
    kv.append(el("div", { class: "kv" }, el("span", { class: "k" }, "Content-type"), el("span", { class: "v" }, d.content_type || "—")));
    kv.append(el("div", { class: "kv" }, el("span", { class: "k" }, "Resume"), el("span", { class: "v" }, d.accepts_ranges ? "supported (HTTP 206)" : "unknown")));
    body.append(kv);
    body.append(el("div", { class: "ac-actions" },
      el("button", { class: "btn btn-primary", onclick: (e) => enqueue(e, d, { label: "file" }) },
        el("span", { class: "btn-ico", html: ICONS.svg("download") }), el("span", {}, "Download")),
      el("button", { class: "btn btn-ghost", onclick: async () => { window.UI.copyText(d.url); toast("Direct link copied — paste into IDM, aria2 or your browser.", "ok", { icon: "copy" }); } },
        el("span", { class: "btn-ico", html: ICONS.svg("copy") }), el("span", {}, "Copy download link")),
      el("a", { class: "btn btn-ghost", href: d.url, target: "_blank", rel: "noopener" },
        el("span", { class: "btn-ico", html: ICONS.svg("external") }), el("span", {}, "Open"))));
    card.append(body);
  }

  function renderMagnet(d) {
    const card = cardShell("MAGNET", "#f97316");
    card.append(el("h2", { class: "ac-title", style: { marginBottom: 8 } }, d.title));
    card.append(el("p", { style: { fontSize: 13, color: "var(--text-2)", lineHeight: 1.6 } },
      "Magnet links resolve through your torrent client — WebFinder can’t stream them directly, but you can copy the link or hand it off."));
    card.append(el("div", { class: "ac-actions" },
      el("button", { class: "btn btn-primary", onclick: () => { window.UI.copyText(d.url); toast("Magnet copied.", "ok", { icon: "copy" }); } },
        el("span", { class: "btn-ico", html: ICONS.svg("copy") }), el("span", {}, "Copy magnet")),
      el("button", { class: "btn btn-ghost", onclick: () => openMagnet(d.url) },
        el("span", { class: "btn-ico", html: ICONS.svg("external") }), el("span", {}, "Open in torrent client"))));
  }

  function renderPage(d) {
    const card = cardShell("PAGE · no direct file", "#8b8b96");
    card.append(el("h2", { class: "ac-title", style: { marginBottom: 8 } }, d.url));
    card.append(el("p", { style: { fontSize: 13, color: "var(--text-2)", lineHeight: 1.7 } },
      "That URL is a regular web page. " + (d.candidates?.length
        ? `The deep-link scanner found <b>${d.candidates.length}</b> downloadable file${d.candidates.length === 1 ? "" : "s"} inside it:`
        : "No direct file links were found inside it — the real file is probably loaded by JavaScript.")));
    if (d.candidates?.length) {
      const list = el("div", { class: "rc-candidates", style: { borderStyle: "solid", marginTop: 12 } });
      for (const c of d.candidates) {
        list.append(el("div", { class: "cand" },
          el("span", { class: "cand-name", title: c.url }, c.filename),
          el("button", { class: "icon-btn", title: "Copy link", html: ICONS.svg("copy"), onclick: () => { window.UI.copyText(c.url); toast("Link copied.", "ok", { icon: "copy" }); } }),
          el("button", { class: "icon-btn", title: "Download", html: ICONS.svg("download"), onclick: async () => {
            try { await window.API.startDownload({ url: c.url, filename: c.filename }); toast("Added to downloads.", "ok", { icon: "dl" }); } catch (e) { toast(e.message, "err"); }
          } })));
      }
      card.append(list);
    }
  }

  function renderError(msg) {
    const card = cardShell("UNREACHABLE", "#fb7185");
    card.append(el("div", { class: "notice err", style: { marginBottom: 12 }, html: `${ICONS.svg("warning")}<div>${escapeHtml(msg)}</div>` }));
    card.append(el("p", { style: { fontSize: 12.5, color: "var(--text-3)", lineHeight: 1.6 } },
      "Tips: some hosts block datacenter IPs, TLS handshakes fail behind corporate proxies, and offline sandboxes can’t reach the internet at all. In this preview environment Demo mode (Settings) simulates the full pipeline instead."));
  }

  /* ── actions ─────────────────────────────────────────────────────────────── */
  async function enqueue(btnEvent, d, fmt) {
    const btn = btnEvent.currentTarget;
    const original = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner"></span>`;
    try {
      const body = { url: d.url, title: d.title || "" };
      if (d.kind === "media") body.kind = "ytdlp";
      if (d.kind === "hls") body.kind = "hls";
      if (d.kind === "media" && fmt) body.meta = { format: fmt.format, quality: fmt.label };
      await window.API.startDownload(body);
      toast("Transfer started — watch it in the Download Manager.", "ok", { icon: "dl", actionLabel: "View", onAction: () => S.emit("nav", "view-downloads") });
    } catch (err) {
      toast(err.message, "err");
    } finally {
      btn.disabled = false; btn.innerHTML = original;
    }
  }

  function openMagnet(url) {
    try { window.location = url; toast("Handed the magnet to your OS — open your torrent client if nothing happened.", "info"); }
    catch { /* noop */ }
  }

  function escapeHtml(s) { const d = document.createElement("div"); d.textContent = s ?? ""; return d.innerHTML; }

  window.DirectView = { init, analyze };
})();
