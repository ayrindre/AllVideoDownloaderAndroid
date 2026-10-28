"""All Video Downloader (Android) — Settings screen."""
from __future__ import annotations

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivymd.uix.screen import MDScreen
from kivymd.uix.selectioncontrol import MDSwitch
from kivymd.uix.slider import MDSlider
from kivymd.uix.textfield import MDTextField

from ..i18n import fa_num, t
from . import theme
from .common import Card, Chip, SectionLabel, fa_label, latin_label, snackbar, spacer

QUALITIES = [("best", "بهترین"), ("2160", "4K"), ("1440", "2K"),
             ("1080", "1080p"), ("720", "720p"), ("480", "480p")]
CONTAINERS = ["mp4", "mkv", "mov"]
ACCENTS = [("violet", "#8B5CF6"), ("azure", "#38BDF8"),
           ("magenta", "#EC4899"), ("mint", "#34D399")]


class SettingsScreen(MDScreen):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.app = app
        self.engine = app.engine
        self._chips: dict[str, list[Chip]] = {}
        self._build()

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
        self.body.add_widget(fa_label(t("tab_settings"), bold=True,
                                      color=self.pal["text"], size=20))

        s = self.app.settings_snapshot()
        self._download_card(s)
        self._video_card(s)
        self._appearance_card(s)
        self._system_card()
        self._about_card()

    def recolor(self):
        self.clear_widgets()  # _build() adds a fresh ScrollView root
        self._chips.clear()
        self._build()

    # ------------------------------------------------------------------ cards
    def _download_card(self, s: dict):
        card = Card(self.pal)
        card.add_widget(SectionLabel(t("section_downloads"), self.pal))

        card.add_widget(fa_label(t("download_folder"), bold=True,
                                 color=self.pal["text_2"], size=12.5))
        path = latin_label(s.get("download_dir", ""), color=self.pal["text_3"], size=11)
        path.shorten = True
        path.shorten_from = "left"
        card.add_widget(path)
        card.add_widget(spacer(6))

        self.concurrent_val = fa_label(t("max_concurrent") + ": " +
                                       fa_num(s.get("max_concurrent", 2)),
                                       color=self.pal["text_2"], size=13)
        card.add_widget(self.concurrent_val)
        self.slider = MDSlider(min=1, max=4, step=1, value=int(s.get("max_concurrent", 2)),
                               color=theme.rgba(self.app.accent_hex),
                               hint_bg_color=theme.rgba(self.app.accent_hex),
                               hint_text_color=[1, 1, 1, 1])
        self.slider.bind(value=self._on_slider)
        card.add_widget(self.slider)

        card.add_widget(fa_label(t("proxy"), bold=True, color=self.pal["text_2"], size=12.5))
        self.proxy_field = MDTextField(
            mode="rectangle", text=s.get("proxy", ""),
            hint_text=t("proxy_hint"),
            font_name=theme.font_name(), font_size=dp(12),
            line_color_normal=theme.rgba(self.pal["outline"]),
            line_color_focus=theme.rgba(self.app.accent_hex),
            fill_color_normal=theme.rgba(self.pal["surface_2"]),
            fill_color_focus=theme.rgba(self.pal["surface_2"]),
            text_color_normal=theme.rgba(self.pal["text"]),
            text_color_focus=theme.rgba(self.pal["text"]),
            hint_text_color_normal=theme.rgba(self.pal["text_3"]),
            size_hint_y=None, height=dp(52))
        self.proxy_field.bind(focus=self._on_proxy_focus)
        card.add_widget(self.proxy_field)
        self.body.add_widget(card)

    def _video_card(self, s: dict):
        card = Card(self.pal)
        card.add_widget(SectionLabel(t("section_video"), self.pal))

        card.add_widget(fa_label(t("default_quality"), bold=True,
                                 color=self.pal["text_2"], size=12.5))
        card.add_widget(self._chip_row(
            "quality", [(k, v) for k, v in QUALITIES],
            str(s.get("default_quality", "1080")),
            lambda key: self._patch({"default_quality": key})))
        card.add_widget(spacer(8))

        card.add_widget(fa_label(t("container"), bold=True,
                                 color=self.pal["text_2"], size=12.5))
        card.add_widget(self._chip_row(
            "container", [(c, c.upper()) for c in CONTAINERS],
            s.get("default_container", "mp4"),
            lambda key: self._patch({"default_container": key})))
        card.add_widget(spacer(8))

        card.add_widget(fa_label(t("cookies"), bold=True,
                                 color=self.pal["text_2"], size=12.5))
        self.cookie_lbl = fa_label("", color=self.pal["text_3"], size=11.5)
        card.add_widget(self.cookie_lbl)
        card.add_widget(fa_label(t("cookies_hint"), color=self.pal["text_3"], size=10.5))
        self.body.add_widget(card)
        self._refresh_cookies()

    def _appearance_card(self, s: dict):
        card = Card(self.pal)
        card.add_widget(SectionLabel(t("section_appearance"), self.pal))

        row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(48),
                        spacing=dp(12))
        row.add_widget(fa_label(t("theme_dark"), color=self.pal["text_2"], size=13))
        row.add_widget(Widget())
        self.theme_switch = MDSwitch(
            active=s.get("theme_style", "Dark") == "Dark",
            icon_active="moon-waning", icon_inactive="white-balance-sunny",
            track_color_active=theme.rgba(self.app.accent_hex))
        self.theme_switch.bind(active=self._on_theme_switch)
        row.add_widget(self.theme_switch)
        card.add_widget(row)

        card.add_widget(fa_label(t("accent"), bold=True,
                                 color=self.pal["text_2"], size=12.5))
        card.add_widget(self._chip_row(
            "accent", ACCENTS, s.get("accent", "violet"),
            lambda key: self._on_accent(key)))
        self.body.add_widget(card)

    def _system_card(self):
        card = Card(self.pal)
        card.add_widget(SectionLabel(t("section_system"), self.pal))
        self.status_lbl = latin_label("…", color=self.pal["text_2"], size=11.5,
                                      halign="left")
        self.status_lbl.font_name = theme.font_name()
        card.add_widget(self.status_lbl)
        self.body.add_widget(card)
        fut = self.engine.submit(self.engine.system_status)
        fut.add_done_callback(lambda f: Clock.schedule_once(lambda dt: self._status(f)))

    def _about_card(self):
        card = Card(self.pal)
        card.add_widget(SectionLabel(t("about"), self.pal))
        card.add_widget(fa_label(t("about_body"), color=self.pal["text_2"], size=12))
        card.add_widget(fa_label(t("work_in_background_hint"),
                                 color=self.pal["warning"], size=11))
        self.body.add_widget(card)

    # ------------------------------------------------------------------ chips
    def _chip_row(self, group: str, items: list[tuple[str, str]], active: str,
                  on_choose) -> BoxLayout:
        scroll = ScrollView(do_scroll_y=False, size_hint_y=None, height=dp(46), bar_width=0)
        row = BoxLayout(orientation="horizontal", spacing=dp(8), size_hint_y=None,
                        height=dp(42), size_hint_x=None)
        row.bind(minimum_width=row.setter("width"))
        chips = []
        for key, label in items:
            chip = Chip(label, selected=(key == active), accent=self.app.accent_hex,
                        on_select=lambda *_, k=key: self._choose(group, k, on_choose))
            chip.attach_palette(self.pal)
            chip.key = key
            chips.append(chip)
            row.add_widget(chip)
        self._chips[group] = chips
        scroll.add_widget(row)
        return scroll

    def _choose(self, group: str, key: str, on_choose):
        for c in self._chips.get(group, []):
            c.set_selected(getattr(c, "key", None) == key)
        on_choose(key)

    # ------------------------------------------------------------------ handlers
    def _on_slider(self, slider, value):
        val = int(value)
        self.concurrent_val.text = t("max_concurrent") + ": " + fa_num(val)

    def on_touch_up(self, touch):
        consumed = super().on_touch_up(touch)
        if hasattr(self, "slider") and self.slider.collide_point(*touch.pos):
            self._patch({"max_concurrent": int(self.slider.value)})
        return consumed

    def _on_proxy_focus(self, field, focus):
        if not focus:
            self._patch({"proxy": field.text.strip()})

    def _on_theme_switch(self, switch, active):
        style = "Dark" if active else "Light"
        self._patch({"theme_style": style})
        self.app.apply_theme(style, self.app.accent)
        self.app.recolor_all()

    def _on_accent(self, key: str):
        self._patch({"accent": key})
        self.app.apply_theme(self.app.style_name, key)
        self.app.recolor_all()

    def _patch(self, patch: dict):
        def done(fut):
            try:
                fut.result()
            except Exception as e:  # noqa: BLE001 — keep the message, the except
                msg = str(e)[:100]  # variable itself is cleared by Python afterwards
                Clock.schedule_once(lambda dt: snackbar(
                    "ذخیره تنظیمات شکست خورد: " + msg, self.pal, self.pal["danger"]))
        self.engine.submit(self.engine.update_settings, patch).add_done_callback(done)

    # ------------------------------------------------------------------ data
    def _refresh_cookies(self):
        def done(fut):
            try:
                status = fut.result()["cookies"]
            except Exception:  # noqa: BLE001
                status = {}
            Clock.schedule_once(lambda dt: self._render_cookies(status))
        self.engine.submit(self.engine.system_status).add_done_callback(done)

    def _render_cookies(self, status: dict):
        if not hasattr(self, "cookie_lbl"):
            return
        if status.get("file_ok"):
            self.cookie_lbl.text = t("cookies_active", n=fa_num("✓"))
            self.cookie_lbl.text_color = theme.rgba(self.pal["success"])
        else:
            self.cookie_lbl.text = t("cookies_none")
            self.cookie_lbl.text_color = theme.rgba(self.pal["text_3"])

    def _status(self, fut):
        try:
            st = fut.result()
        except Exception as exc:  # noqa: BLE001
            self.status_lbl.text = f"error: {exc}"
            return
        ff = st["ffmpeg"]
        ff_line = (t("ffmpeg_ok") + f" ({fa_num(st['abi'])})") if ff.get("available") \
            else t("ffmpeg_missing")
        lines = [
            f"All Video Downloader · v{st['app_version']} Android",
            f"yt-dlp: {st['yt_dlp']}  ({st['yt_dlp_engine']})",
            f"FFmpeg: {ff_line}",
            t("sites_count") + f": {fa_num(st['sites'])}  /  embed hosts: {fa_num(st['embed_hosts'])}",
            t("tls_status") + ": " + (t("tls_on") if st["tls_impersonation"] else t("tls_off")),
        ]
        self.status_lbl.text = "\n".join(lines)
        self.status_lbl.font_name = theme.font_name()
