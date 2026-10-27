"""All Video Downloader (Android) — Home screen.

Paste any video link → analyze → quality card → one download button.
Mobile rewrite of the desktop ``views/direct.js`` flow, in Persian.
"""
from __future__ import annotations

from kivy.clock import Clock
from kivy.graphics import Color, Ellipse
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivymd.uix.screen import MDScreen
from kivymd.uix.spinner import MDSpinner
from kivymd.uix.textfield import MDTextField

from ..i18n import duration_human, fa, human_bytes, t
from ..platform import runtime
from . import theme
from .common import (Card, Chip, IconChip, RoundedButton, SectionLabel,
                     Thumbnail, fa_label, latin_label, snackbar, spacer,
                     strip_html)

QUICK_LINKS = [
    ("YouTube", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
    ("HLS", "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8"),
    ("MP4", "https://filesamples.com/samples/video/movie_1080p.mp4"),
]


class Radar(Widget):
    """Concentric-ring idle illustration drawn on the canvas."""

    def __init__(self, pal: dict, **kw):
        super().__init__(**kw)
        self.size_hint_y = None
        self.height = dp(150)
        self._pal = pal
        self.bind(pos=self._draw, size=self._draw)

    def _draw(self, *args):
        self.canvas.clear()
        cx, cy = self.center_x, self.center_y
        accent = theme.rgba("#8B5CF6")
        with self.canvas:
            for r, a in ((68, 0.08), (50, 0.14), (32, 0.22)):
                Color(accent[0], accent[1], accent[2], a)
                Ellipse(pos=[cx - dp(r), cy - dp(r)], size=[dp(r * 2), dp(r * 2)])
            Color(*accent)
            Ellipse(pos=[cx - dp(22), cy - dp(22)], size=[dp(44), dp(44)])


class HomeScreen(MDScreen):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.app = app
        self.engine = app.engine
        self.current: dict | None = None
        self.selected_format: dict | None = None
        self._build()
        self._show_idle()

    # ------------------------------------------------------------------ build
    @property
    def pal(self) -> dict:
        return self.app.pal

    def _build(self):
        root = ScrollView(do_scroll_x=False, bar_width=0)
        self.body = BoxLayout(orientation="vertical", spacing=dp(14),
                              padding=[dp(16), dp(16), dp(16), dp(32)],
                              size_hint_y=None)
        self.body.bind(minimum_height=self.body.setter("height"))
        root.add_widget(self.body)
        self.add_widget(root)

        # ── URL input card ──────────────────────────────────────────────
        url_card = Card(self.pal, padding=16)
        title = fa_label("لینک ویدیو را بچسبانید", bold=True, color=self.pal["text"], size=16)
        url_card.add_widget(title)

        self.url_field = MDTextField(
            mode="rectangle",
            hint_text=t("url_hint"),
            font_name=theme.font_name(),
            font_size=dp(14),
            line_color_normal=theme.rgba(self.pal["outline"]),
            line_color_focus=theme.rgba(self.app.accent_hex),
            fill_color_normal=theme.rgba(self.pal["surface_2"]),
            fill_color_focus=theme.rgba(self.pal["surface_2"]),
            text_color_normal=theme.rgba(self.pal["text"]),
            text_color_focus=theme.rgba(self.pal["text"]),
            hint_text_color_normal=theme.rgba(self.pal["text_3"]),
            hint_text_color_focus=theme.rgba(self.app.accent_hex),
            size_hint_y=None,
            height=dp(56),
        )
        url_card.add_widget(self.url_field)

        row = BoxLayout(orientation="horizontal", spacing=dp(10), size_hint_y=None, height=dp(46))
        self.paste_btn = RoundedButton(t("paste"), on_press_cb=self._paste,
                                       bg_color=self.pal["surface_2"],
                                       text_color=self.pal["text"], radius=14, font_size=13)
        self.clear_btn = RoundedButton(t("clear"), on_press_cb=lambda *_: self._clear(),
                                       bg_color=self.pal["surface_2"],
                                       text_color=self.pal["text_2"], radius=14, font_size=13)
        row.add_widget(self.paste_btn)
        row.add_widget(self.clear_btn)
        url_card.add_widget(row)

        self.analyze_btn = RoundedButton(t("analyze"), on_press_cb=self._analyze,
                                         bg_color=self.app.accent_hex, radius=16)
        url_card.add_widget(self.analyze_btn)
        self.body.add_widget(url_card)

        # ── quick links ─────────────────────────────────────────────────
        quick = BoxLayout(orientation="horizontal", spacing=dp(8), size_hint_y=None,
                          height=dp(38), padding=[dp(2), 0, dp(2), 0])
        for label, url in QUICK_LINKS:
            ch = Chip(label, small=True, accent=self.app.accent_hex,
                      on_select=lambda *_, u=url: self._use_quick(u))
            ch.attach_palette(self.pal)
            quick.add_widget(ch)
        quick.add_widget(Widget())
        self.body.add_widget(quick)

        # ── result / idle stage ─────────────────────────────────────────
        self.stage = BoxLayout(orientation="vertical", size_hint_y=None)
        self.stage.bind(minimum_height=self.stage.setter("height"))
        self.body.add_widget(self.stage)

    def recolor(self):
        """Rebuild after a theme/accent change."""
        self.clear_widgets()  # _build() adds a fresh ScrollView root
        self._build()
        if self.current:
            self._render(self.current)
        else:
            self._show_idle()

    # ------------------------------------------------------------------ helpers
    def _use_quick(self, url: str):
        self.url_field.text = url
        self._analyze()

    def _clear(self):
        self.url_field.text = ""
        self.current = None
        self._show_idle()

    def _paste(self, *_):
        text = runtime.clipboard_get()
        if text:
            self.url_field.text = text.strip()
        else:
            snackbar("حافظه کلیپ‌بورد خالی است", self.pal, self.pal["warning"])

    def _set_busy(self, busy: bool, label: str = ""):
        self.analyze_btn.disabled = busy
        self.analyze_btn.set_text(t("analyzing") if busy else t("analyze"))
        self.analyze_btn.opacity = 0.75 if busy else 1.0

    # ------------------------------------------------------------------ analyze
    def _analyze(self, *_):
        url = self.url_field.text.strip()
        if not url:
            snackbar("اول یک لینک وارد کنید", self.pal, self.pal["warning"])
            return
        self._set_busy(True)
        self._show_loading()
        fut = self.engine.submit(self.engine.analyze, url)
        fut.add_done_callback(lambda f: Clock.schedule_once(lambda dt: self._analyzed(f)))

    def _analyzed(self, fut):
        self._set_busy(False)
        try:
            data = fut.result()
        except Exception as exc:  # noqa: BLE001
            self.current = None
            self._render_error(str(exc))
            return
        self.current = data
        self._render(data)

    # ------------------------------------------------------------------ stage renders
    def _clear_stage(self):
        self.stage.clear_widgets()

    def _show_idle(self):
        self._clear_stage()
        card = Card(self.pal)
        card.add_widget(Radar(self.pal))
        card.add_widget(fa_label("هر لینکی که ویدیو دارد را اینجا بچسبانید",
                                 bold=True, color=self.pal["text"], size=16,
                                 halign="center"))
        card.add_widget(fa_label(
            "یوتیوب و بیش از ۱۹۰۰ سایت · فایل مستقیم · مانیفست HLS/DASH · صفحه‌های وب "
            "با اسکن عمیق و استخراج پیکربندی پخش‌کننده. کیفیت‌ها با شناسه واقعی فرمت انتخاب می‌شوند.",
            color=self.pal["text_2"], size=13, halign="center"))
        try:
            n = len(__import__("avd.core.sites", fromlist=["RECIPES"]).RECIPES)
            card.add_widget(fa_label(f"{n} دستور پخت سایت آماده است",
                                     color=self.pal["text_3"], size=12, halign="center"))
        except Exception:  # noqa: BLE001
            pass
        self.stage.add_widget(card)

    def _show_loading(self):
        self._clear_stage()
        card = Card(self.pal)
        box = BoxLayout(orientation="vertical", spacing=dp(18), padding=[0, dp(26), 0, dp(26)])
        spin = MDSpinner(size=[dp(46), dp(46)], pos_hint={"center_x": 0.5},
                         active=True, color=theme.rgba(self.app.accent_hex))
        box.add_widget(spin)
        box.add_widget(fa_label("در حال بررسی استخراج‌کننده‌ها، مانیفست‌ها و نوع محتوا…",
                                color=self.pal["text_2"], size=13, halign="center"))
        card.add_widget(box)
        self.stage.add_widget(card)

    def _render_error(self, msg: str):
        self._clear_stage()
        card = Card(self.pal)
        card.add_widget(fa_label("خطا در دریافت اطلاعات", bold=True,
                                 color=self.pal["danger"], size=16))
        card.add_widget(fa_label(strip_html(msg), color=self.pal["text_2"], size=13))
        row = BoxLayout(orientation="horizontal", spacing=dp(10), size_hint_y=None, height=dp(50))
        row.add_widget(RoundedButton(t("retry"), on_press_cb=lambda *_: self._analyze(),
                                     bg_color=self.app.accent_hex))
        self.stage.add_widget(card)
        self.stage.add_widget(spacer(8))
        self.stage.add_widget(row)

    # ------------------------------------------------------------------ main router
    def _render(self, d: dict):
        kind = d.get("kind")
        self._clear_stage()
        if kind == "media":
            self.stage.add_widget(self._media_card(d))
        elif kind == "webmedia":
            self.stage.add_widget(self._webmedia_card(d))
        elif kind == "hls":
            self.stage.add_widget(self._hls_card(d))
        elif kind == "direct":
            self.stage.add_widget(self._direct_card(d))
        elif kind == "magnet":
            self.stage.add_widget(self._magnet_card(d))
        elif kind == "media_error":
            self.stage.add_widget(self._error_card(d))
            self._add_candidate_rows(d.get("candidates") or [], referer=d.get("url", ""))
        else:
            self.stage.add_widget(self._page_card(d))
            self._add_candidate_rows(d.get("candidates") or [], referer=d.get("url", ""))
        self._add_notices(d)
        self._add_more_block(d)

    def _add_notices(self, d: dict):
        notes = []
        if d.get("recovered_after_block"):
            notes.append((self.pal["success"], t("notice_recovered") + " — " + strip_html(d["recovered_after_block"])))
        if d.get("upgraded_from_extractor"):
            notes.append((self.pal["success"], t("notice_upgraded") + " — " + strip_html(d["upgraded_from_extractor"])))
        if d.get("access_note"):
            notes.append((self.pal["warning"], t("notice_paywall") + " " + strip_html(d["access_note"])))
        for color, text in notes:
            card = Card(self.pal, padding=12)
            card.add_widget(fa_label(text, color=color, size=12))
            self.stage.add_widget(spacer(8))
            self.stage.add_widget(card)

    # ------------------------------------------------------------------ card builders
    def _header(self, d: dict, badge: str, badge_color: str, title: str, thumb: str = "",
                duration: int = 0) -> Card:
        card = Card(self.pal)
        if thumb:
            tbox = BoxLayout(size_hint_y=None, height=dp(190))
            tbox.add_widget(Thumbnail(thumb, self.pal))
            if duration:
                dur = latin_label(duration_human(duration), color="#FFFFFF", size=12)
                dur.halign = "right"
                dur.padding = [0, 0, dp(10), dp(8)]
                tbox.add_widget(dur)
            card.add_widget(tbox)
        badge_row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(30))
        badge_row.add_widget(fa_label(badge, bold=True, color=badge_color, size=12))
        badge_row.add_widget(Widget())
        card.add_widget(badge_row)
        card.add_widget(fa_label(title, bold=True, color=self.pal["text"], size=16))
        return card

    def _quality_chips(self, formats: list[dict]) -> BoxLayout:
        SectionLabel_holder = BoxLayout(orientation="vertical", size_hint_y=None)
        SectionLabel_holder.add_widget(SectionLabel(t("qualities"), self.pal))
        SectionLabel_holder.add_widget(spacer(6))
        scroll = ScrollView(do_scroll_y=False, size_hint_y=None, height=dp(48), bar_width=0)
        row = BoxLayout(orientation="horizontal", spacing=dp(8), size_hint_y=None,
                        height=dp(44), size_hint_x=None)
        row.bind(minimum_width=row.setter("width"))
        chips: list[Chip] = []

        def choose(chip: Chip, fmt: dict):
            self.selected_format = fmt
            for c in chips:
                c.set_selected(c is chip)

        for i, fmt in enumerate(formats):
            label = fmt.get("label") or "?"
            chip = Chip(label, selected=(i == 0), accent=self.app.accent_hex,
                        on_select=lambda c, f=fmt: choose(c, f))
            chip.attach_palette(self.pal)
            chips.append(chip)
            row.add_widget(chip)
        self.selected_format = formats[0] if formats else None
        scroll.add_widget(row)
        SectionLabel_holder.add_widget(scroll)
        return SectionLabel_holder

    def _action_row(self, on_download, copy_text: str, open_url: str = "") -> BoxLayout:
        row = BoxLayout(orientation="horizontal", spacing=dp(10), size_hint_y=None, height=dp(52))
        row.add_widget(RoundedButton(t("download"), on_press_cb=on_download,
                                     bg_color=self.app.accent_hex))
        row.add_widget(IconChip("content-copy", lambda *_: self._copy(copy_text),
                                bg=self.pal["surface_2"]))
        if open_url:
            row.add_widget(IconChip("open-in-new", lambda *_: self._open_url(open_url),
                                    bg=self.pal["surface_2"]))
        return row

    def _media_card(self, d: dict) -> Card:
        card = self._header(d, f"MEDIA · {d.get('extractor', 'yt-dlp')}", self.pal["info"],
                            d.get("title", d.get("url", "")), d.get("thumbnail", ""),
                            d.get("duration", 0))
        meta = []
        if d.get("uploader"):
            meta.append(d["uploader"][:60])
        if d.get("view_count"):
            meta.append(f"{d['view_count']:,} بازدید")
        meta.append(t("streams_found", n=d.get("formats_total", len(d.get("formats", [])))))
        card.add_widget(fa_label("  ·  ".join(meta), color=self.pal["text_3"], size=12))
        if not d.get("ffmpeg", True):
            card.add_widget(fa_label("FFmpeg همراه برنامه پیدا نشد؛ کیفیت‌های needing-merge ممکن است "
                                     "به بهترین فایل تکی محدود شوند.",
                                     color=self.pal["warning"], size=12))
        card.add_widget(self._quality_chips(d.get("formats", [])))
        card.add_widget(self._action_row(
            lambda *_: self._download_media(d),
            d.get("webpage") or d.get("url", ""), d.get("webpage", d.get("url", ""))))
        return card

    def _webmedia_card(self, d: dict) -> Card:
        card = self._header(d, f"PLAYER · {d.get('site') or d.get('player') or 'embedded'}",
                            self.pal["info"], d.get("title") or d.get("url", ""),
                            d.get("thumbnail", ""))
        card.add_widget(fa_label("فایل‌ها مستقیماً از پیکربندی پخش‌کننده همان صفحه خوانده شده‌اند؛ "
                                 "صفحه میزبان به‌عنوان Referer ارسال می‌شود.",
                                 color=self.pal["text_2"], size=12))
        card.add_widget(self._quality_chips(d.get("formats", [])))
        card.add_widget(self._action_row(
            lambda *_: self._download_webmedia(d),
            d.get("url", ""), d.get("url", "")))
        return card

    def _hls_card(self, d: dict) -> Card:
        card = self._header(d, "STREAM · HLS/DASH" + (f" · {d['site']}" if d.get("site") else ""),
                            self.pal["info"], d.get("title", d.get("url", "")))
        if d.get("duration"):
            card.add_widget(fa_label("مدت: " + duration_human(d["duration"]),
                                     color=self.pal["text_2"], size=12))
        formats = d.get("formats", [])
        if len(formats) > 1:
            card.add_widget(self._quality_chips(formats))
        else:
            self.selected_format = formats[0] if formats else {"label": "stream"}
        if not d.get("ffmpeg", True) and len(formats) <= 1:
            card.add_widget(fa_label("برای ضبط این استریم به FFmpeg نیاز است که normally همراه APK نصب است.",
                                     color=self.pal["warning"], size=12))
        card.add_widget(self._action_row(
            lambda *_: self._download_hls(d), d.get("url", "")))
        return card

    def _direct_card(self, d: dict) -> Card:
        card = self._header(d, f"FILE · {d.get('file_type', 'binary')}", self.pal["success"],
                            d.get("title", d.get("url", "")))
        size = human_bytes(d.get("size")) if d.get("size") else fa("نامشخص (چانکی)")
        card.add_widget(fa_label("حجم: " + size, color=self.pal["text_2"], size=13))
        card.add_widget(latin_label(d.get("content_type", "—"), color=self.pal["text_3"], size=11))
        card.add_widget(self._action_row(
            lambda *_: self._download_direct(d), d.get("url", ""), d.get("url", "")))
        return card

    def _magnet_card(self, d: dict) -> Card:
        card = self._header(d, "MAGNET", self.pal["warning"], d.get("title", "Magnet"))
        card.add_widget(fa_label(t("magnet_body"), color=self.pal["text_2"], size=13))
        row = BoxLayout(orientation="horizontal", spacing=dp(10), size_hint_y=None, height=dp(52))
        row.add_widget(RoundedButton(t("copy_magnet"),
                                     on_press_cb=lambda *_: self._copy(d.get("url", "")),
                                     bg_color=self.app.accent_hex))
        card.add_widget(row)
        return card

    def _error_card(self, d: dict) -> Card:
        card = self._header(d, f"MEDIA · {d.get('extractor', '?')} — BLOCKED",
                            self.pal["danger"],
                            d.get("title") or "استخراج توسط سایت رد شد")
        card.add_widget(fa_label(strip_html(d.get("error", "")), color=self.pal["danger"], size=12))
        for hint in (d.get("hints") or [])[:4]:
            card.add_widget(fa_label("• " + strip_html(hint), color=self.pal["text_2"], size=11.5))
        row = BoxLayout(orientation="horizontal", spacing=dp(10), size_hint_y=None, height=dp(52))
        row.add_widget(RoundedButton(t("retry"), on_press_cb=lambda *_: self._analyze(),
                                     bg_color=self.app.accent_hex))
        row.add_widget(RoundedButton(t("deep_scan"),
                                     on_press_cb=lambda *_: self._deep_scan(d.get("url", "")),
                                     bg_color=self.pal["surface_2"],
                                     text_color=self.pal["text"]))
        card.add_widget(row)
        return card

    def _page_card(self, d: dict) -> Card:
        card = self._header(d, "PAGE", self.pal["text_3"],
                            d.get("title") or d.get("url", ""))
        if d.get("site"):
            card.add_widget(fa_label(d["site"], color=self.pal["text_3"], size=12))
        card.add_widget(fa_label("این صفحه ویدیو را داخل یک پخش‌کننده اسکریپتی اجرا می‌کند؛ "
                                 "می‌توانید صفحه را اسکن عمیق کنید.",
                                 color=self.pal["text_2"], size=12.5))
        card.add_widget(RoundedButton(t("deep_scan"),
                                      on_press_cb=lambda *_: self._deep_scan(d.get("url", "")),
                                      bg_color=self.pal["surface_2"],
                                      text_color=self.pal["text"]))
        return card

    # ------------------------------------------------------------------ candidate / playlist rows
    def _add_more_block(self, d: dict):
        rows: list[dict] = []
        for e in (d.get("playlist") or {}).get("entries", []) or []:
            if e.get("url"):
                rows.append({"title": e.get("title") or e["url"], "url": e["url"],
                             "sub": duration_human(e.get("duration"))})
        for c in d.get("also_found") or []:
            if c.get("url"):
                rows.append({"title": c.get("filename") or c["url"], "url": c["url"],
                             "sub": human_bytes(c.get("size_bytes")) if c.get("size_bytes") else ""})
        if not rows:
            return
        ref = d.get("referer") or d.get("found_on_page") or ""
        label = (t("playlists_more", n=len(rows)) if d.get("playlist") else
                 t("also_found", n=len(rows)))
        holder = Card(self.pal)
        holder.add_widget(SectionLabel(label, self.pal))
        for it in rows[:15]:
            holder.add_widget(self._candidate_row(it["title"], it["url"], ref, sub=it.get("sub", "")))
        self.stage.add_widget(spacer(10))
        self.stage.add_widget(holder)

    def _add_candidate_rows(self, candidates: list[dict], referer: str):
        if not candidates:
            return
        holder = Card(self.pal)
        holder.add_widget(SectionLabel(f"رسانه‌های پیدا شده در صفحه · {min(len(candidates), 15)}", self.pal))
        for c in candidates[:15]:
            url = c.get("url", "")
            if not url:
                continue
            sub = human_bytes(c.get("size_bytes")) if c.get("size_bytes") else ""
            holder.add_widget(self._candidate_row(c.get("filename") or url, url, referer, sub=sub))
        self.stage.add_widget(spacer(10))
        self.stage.add_widget(holder)

    def _candidate_row(self, title: str, url: str, referer: str, sub: str = "") -> BoxLayout:
        row = BoxLayout(orientation="horizontal", spacing=dp(8), size_hint_y=None,
                        height=dp(52), padding=[0, dp(4), 0, dp(4)])
        text_box = BoxLayout(orientation="vertical")
        lbl = fa_label(title[:90], color=self.pal["text"], size=12.5)
        lbl.shorten = True
        lbl.shorten_from = "right"
        text_box.add_widget(lbl)
        if sub:
            text_box.add_widget(fa_label(sub, color=self.pal["text_3"], size=10.5))
        row.add_widget(text_box)
        row.add_widget(IconChip("magnify", lambda *_: self._reanalyze(url),
                                bg=self.pal["surface_2"]))
        row.add_widget(IconChip("download",
                                lambda *_, u=url, r=referer: self._quick_download(u, r),
                                bg=self.pal["surface_2"]))
        row.add_widget(IconChip("content-copy", lambda *_: self._copy(url),
                                bg=self.pal["surface_2"]))
        return row

    def _reanalyze(self, url: str):
        self.url_field.text = url
        self._analyze()

    def _deep_scan(self, url: str):
        if not url:
            return
        snackbar("اسکن عمیق شروع شد…", self.pal, self.pal["info"])
        fut = self.engine.submit(self.engine.scan_page, url)

        def done(f):
            try:
                data = f.result()
                cands = data.get("candidates", [])
                Clock.schedule_once(lambda dt: self._after_deep_scan(url, cands))
            except Exception as e:  # noqa: BLE001 — stringify now: Python clears
                msg = str(e)[:160]   # the exception var after the except block
                Clock.schedule_once(lambda dt: snackbar("اسکن شکست خورد: " + msg,
                                                        self.pal, self.pal["danger"]))

        fut.add_done_callback(done)

    def _after_deep_scan(self, url: str, candidates: list[dict]):
        if not candidates:
            snackbar("هیچ لینک رسانه‌ای ساده‌ای پیدا نشد", self.pal, self.pal["warning"])
            return
        self.current = {"kind": "page", "url": url, "title": url, "candidates": candidates}
        self._render(self.current)

    # ------------------------------------------------------------------ downloads
    def _guard(self, fut, ok_msg: str):
        try:
            fut.result()
            Clock.schedule_once(lambda dt: snackbar(ok_msg, self.pal, self.pal["success"]))
            Clock.schedule_once(lambda dt: self.app.switch_tab("downloads"), 0.6)
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            Clock.schedule_once(lambda dt: snackbar("خطا: " + msg[:160], self.pal,
                                                    self.pal["danger"]))

    def _download_media(self, *_):
        d, fmt = self.current, self.selected_format
        if not d or not fmt:
            return
        referer = d.get("referer") or d.get("found_on_page") or ""
        fut = self.engine.submit(self.engine.enqueue_from_card,
                                 d["url"], d.get("title", ""), dict(fmt),
                                 referer)
        fut.add_done_callback(lambda f: self._guard(f, t("added_to_queue")))

    def _download_webmedia(self, *_):
        d, fmt = self.current, self.selected_format
        if not d or not fmt:
            return
        referer = d.get("referer") or d.get("found_on_page") or d.get("url", "")
        if fmt.get("format") == "url" and fmt.get("url"):
            ext = (fmt.get("ext") or "mp4").lstrip(".")
            filename = f"{(d.get('title') or 'video')[:120]}.{ext}"
            fut = self.engine.submit(
                self.engine.enqueue_direct, fmt["url"], d.get("title", ""), filename,
                {"referer": referer})
        else:
            fut = self.engine.submit(self.engine.enqueue_from_card,
                                     d["url"], d.get("title", ""), dict(fmt), referer)
        fut.add_done_callback(lambda f: self._guard(f, t("added_to_queue")))

    def _download_hls(self, *_):
        d, fmt = self.current, self.selected_format
        if not d:
            return
        referer = d.get("referer") or d.get("found_on_page") or ""
        fut = self.engine.submit(self.engine.enqueue_from_card,
                                 d["url"], d.get("title", ""),
                                 dict(fmt) if fmt else None, referer)
        fut.add_done_callback(lambda f: self._guard(f, t("added_to_queue")))

    def _download_direct(self, *_):
        d = self.current
        if not d:
            return
        fut = self.engine.submit(
            self.engine.enqueue_direct, d["url"], d.get("title", ""),
            d.get("filename", ""), {"referer": d.get("referer", "")})
        fut.add_done_callback(lambda f: self._guard(f, t("added_to_queue")))

    def _quick_download(self, url: str, referer: str):
        fut = self.engine.submit(self.engine.enqueue_direct, url, url, "",
                                 {"referer": referer} if referer else {})
        fut.add_done_callback(lambda f: self._guard(f, t("added_to_queue")))

    # ------------------------------------------------------------------ system
    def _copy(self, text: str):
        if not text:
            return
        runtime.clipboard_set(text)
        snackbar(t("link_copied"), self.pal, self.pal["success"])

    def _open_url(self, url: str):
        if not runtime.IS_ANDROID:
            snackbar("روی دستگاه اندروید در مرورگر باز می‌شود", self.pal)
            return
        autoclass = runtime._jnius()
        try:
            Intent = autoclass("android.content.Intent")
            Uri = autoclass("android.net.Uri")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            PythonActivity.mActivity.startActivity(intent)
        except Exception:  # noqa: BLE001
            snackbar("باز کردن صفحه ممکن نشد", self.pal, self.pal["danger"])
