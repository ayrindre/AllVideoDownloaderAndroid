"""All Video Downloader (Android) — KivyMD application shell."""
from __future__ import annotations

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivymd.app import MDApp
from kivymd.uix.bottomnavigation import (MDBottomNavigation,
                                          MDBottomNavigationItem)

from ..config import settings
from ..engine import engine
from ..i18n import fa, t
from ..platform import runtime
from . import theme
from .downloads import DownloadsScreen
from .home import HomeScreen
from .settings_screen import SettingsScreen


class GradientHeader(BoxLayout):
    """Brand header: violet→blue gradient with the app name and subtitle."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.orientation = "vertical"
        self.padding = [dp(20), dp(22), dp(20), dp(20)]
        self.spacing = dp(4)
        self.size_hint_y = None
        self.height = dp(118)
        from kivymd.uix.label import MDLabel

        self.title = MDLabel(text=fa(t("app_title")), font_name=theme.font_name(),
                             font_size=dp(22), bold=True, halign="right",
                             adaptive_height=True, text_color=[1, 1, 1, 1])
        self.subtitle = MDLabel(text=fa(t("app_subtitle")), font_name=theme.font_name(),
                                font_size=dp(12.5), halign="right",
                                adaptive_height=True, text_color=[1, 1, 1, 0.85])
        self.add_widget(self.title)
        self.add_widget(self.subtitle)
        self.bind(pos=self._paint, size=self._paint)

    def _paint(self, *args):
        self.canvas.before.clear()
        theme.paint_gradient(self, radius=26)


class AVDDownloaderApp(MDApp):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.engine = engine
        self.style_name = settings.get("theme_style", "Dark")
        self.accent = settings.get("accent", "violet")
        self.pal: dict = {}
        self.screens: dict = {}

    @property
    def accent_hex(self) -> str:
        return theme.ACCENTS[self.accent]["hex"]

    def build(self):
        self.engine.start()
        self.apply_theme(self.style_name, self.accent)
        Window.clearcolor = theme.rgba(self.pal["bg"])

        nav = MDBottomNavigation()
        nav.panel_color = theme.rgba(self.pal["surface"])
        nav.text_color_active = theme.rgba(self.accent_hex)
        nav.text_color_normal = theme.rgba(self.pal["text_3"])

        home_item = MDBottomNavigationItem(
            name="home", text=fa(t("tab_home")), icon="home-variant")
        downloads_item = MDBottomNavigationItem(
            name="downloads", text=fa(t("tab_downloads")), icon="download")
        settings_item = MDBottomNavigationItem(
            name="settings", text=fa(t("tab_settings")), icon="cog-outline")

        self.screens["home"] = HomeScreen(self)
        self.screens["downloads"] = DownloadsScreen(self)
        self.screens["settings"] = SettingsScreen(self)

        # gradient brand header sits on top of the home tab
        home_wrap = BoxLayout(orientation="vertical")
        home_wrap.add_widget(GradientHeader())
        home_wrap.add_widget(self.screens["home"])
        home_item.add_widget(home_wrap)

        downloads_item.add_widget(self.screens["downloads"])
        settings_item.add_widget(self.screens["settings"])

        for item in (home_item, downloads_item, settings_item):
            nav.add_widget(item)
        self.nav = nav
        return nav

    def on_start(self):
        # app launched from the system share sheet?
        url = runtime.incoming_share_url()
        if url:
            home = self.screens["home"]
            home.url_field.text = url
            Clock.schedule_once(lambda dt: home._analyze(), 1.2)

    # ------------------------------------------------------------------ theme
    def apply_theme(self, style: str, accent: str):
        self.style_name = style
        self.accent = accent if accent in theme.ACCENTS else "violet"
        self.pal = theme.apply_theme(self, style, self.accent)
        Window.clearcolor = theme.rgba(self.pal["bg"])

    def recolor_all(self):
        Window.clearcolor = theme.rgba(self.pal["bg"])
        for screen in self.screens.values():
            try:
                screen.recolor()
            except Exception:  # noqa: BLE001
                pass
        if hasattr(self, "nav"):
            self.nav.panel_color = theme.rgba(self.pal["surface"])
            self.nav.text_color_active = theme.rgba(self.accent_hex)
            self.nav.text_color_normal = theme.rgba(self.pal["text_3"])

    def switch_tab(self, name: str):
        if hasattr(self, "nav"):
            self.nav.switch_tab(name)

    def settings_snapshot(self) -> dict:
        return settings.snapshot()

    def on_stop(self):
        try:
            settings.save()
        except Exception:  # noqa: BLE001
            pass
