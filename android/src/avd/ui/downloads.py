"""All Video Downloader (Android) — Downloads screen.

Live job cards fed by the desktop engine's DownloadManager through the
in-process Engine facade: progress, speed, ETA, pause/resume/cancel/retry and
Android share/open intents for finished files.
"""
from __future__ import annotations

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivymd.uix.progressbar import MDProgressBar
from kivymd.uix.screen import MDScreen

from ..i18n import (duration_human, eta_human, fa, fa_num, human_bytes,
                    speed_human, t)
from ..platform import runtime
from . import theme
from .common import Card, IconChip, fa_label, latin_label, snackbar

STATUS = {
    "queued": ("queued", "warning"),
    "downloading": ("downloading", "info"),
    "paused": ("paused", "warning"),
    "done": ("done", "success"),
    "error": ("error", "danger"),
    "cancelled": ("cancelled", "text_3"),
}


class DownloadsScreen(MDScreen):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.app = app
        self.engine = app.engine
        self._cards: dict[str, dict] = {}
        self._build()
        Clock.schedule_interval(self._refresh, 0.7)

    @property
    def pal(self) -> dict:
        return self.app.pal

    def _build(self):
        root = ScrollView(do_scroll_x=False, bar_width=0)
        self.body = BoxLayout(orientation="vertical", spacing=dp(12),
                              padding=[dp(16), dp(16), dp(16), dp(32)],
                              size_hint_y=None)
        self.body.bind(minimum_height=self.body.setter("height"))
        root.add_widget(self.body)
        self.add_widget(root)

        header = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(48))
        header.add_widget(fa_label(t("tab_downloads"), bold=True,
                                   color=self.pal["text"], size=20))
        header.add_widget(Widget())
        self.clear_btn = IconChip("delete-sweep", lambda *_: self._clear_finished(),
                                  bg=self.pal["surface_2"])
        header.add_widget(self.clear_btn)
        self.body.add_widget(header)

        self.list_box = BoxLayout(orientation="vertical", spacing=dp(10), size_hint_y=None)
        self.list_box.bind(minimum_height=self.list_box.setter("height"))
        self.body.add_widget(self.list_box)

        self.empty = Card(self.pal)
        self.empty.add_widget(Widget(size_hint_y=None, height=dp(30)))
        self.empty.add_widget(fa_label("📥", halign="center", size=34))
        self.empty.add_widget(fa_label(t("empty_downloads"), halign="center",
                                       color=self.pal["text_2"], size=14))
        self.empty.add_widget(Widget(size_hint_y=None, height=dp(30)))
        self._show_empty(True)

    def recolor(self):
        self.clear_widgets()  # _build() adds a fresh ScrollView root
        self._cards.clear()
        self._build()

    def _show_empty(self, empty: bool):
        if empty and self.empty not in self.body.children:
            self.body.add_widget(self.empty)
        elif not empty and self.empty in self.body.children:
            self.body.remove_widget(self.empty)

    # ------------------------------------------------------------------ polling
    def _refresh(self, _dt=None):
        fut = self.engine.submit(self.engine.list_jobs)
        fut.add_done_callback(self._got_jobs)

    def _got_jobs(self, fut):
        try:
            jobs = fut.result()
        except Exception:  # noqa: BLE001
            return
        Clock.schedule_once(lambda dt: self._reconcile(jobs))

    def _reconcile(self, jobs: list[dict]):
        seen = set()
        for job in jobs:
            seen.add(job["id"])
            if job["id"] in self._cards:
                self._update_card(job)
            else:
                self._cards[job["id"]] = self._build_card(job)
                self.list_box.add_widget(self._cards[job["id"]]["card"])
        for gone in [jid for jid in self._cards if jid not in seen]:
            self.list_box.remove_widget(self._cards[gone]["card"])
            self._cards.pop(gone)
        self._show_empty(not jobs)

    # ------------------------------------------------------------------ cards
    def _build_card(self, job: dict) -> dict:
        card = Card(self.pal, padding=14)

        title = fa_label(job.get("title") or job.get("filename") or job["url"][:60],
                         bold=True, color=self.pal["text"], size=13.5)
        title.shorten = True
        title.shorten_from = "right"
        card.add_widget(title)

        meta = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(24))
        status_lbl = fa_label("", color=self.pal["info"], size=12)
        progress_lbl = latin_label("", color=self.pal["text_3"], size=11, halign="left")
        meta.add_widget(status_lbl)
        meta.add_widget(progress_lbl)
        card.add_widget(meta)

        bar = MDProgressBar(value=0, color=theme.rgba(self.app.accent_hex),
                            back_color=theme.rgba(self.pal["surface_2"]),
                            size_hint_y=None, height=dp(8))
        bar.radius = dp(4)
        card.add_widget(bar)

        sub = fa_label("", color=self.pal["text_3"], size=11)
        card.add_widget(sub)

        actions = BoxLayout(orientation="horizontal", spacing=dp(8),
                            size_hint_y=None, height=dp(46), padding=[0, dp(4), 0, 0])
        pause = IconChip("pause", lambda *_: self._pause(job["id"]), bg=self.pal["surface_2"])
        retry = IconChip("refresh", lambda *_: self._retry(job["id"]), bg=self.pal["surface_2"])
        cancel = IconChip("close", lambda *_: self._cancel(job["id"]), bg=self.pal["danger"])
        remove = IconChip("trash-can-outline", lambda *_: self._remove(job["id"]),
                          bg=self.pal["surface_2"])
        share = IconChip("share-variant", lambda *_: self._share(job), bg=self.pal["success"])
        openf = IconChip("folder-open", lambda *_: self._open(job), bg=self.pal["surface_2"])
        for w in (pause, retry, cancel, remove, share, openf):
            actions.add_widget(w)
        card.add_widget(actions)

        refs = {"card": card, "title": title, "status": status_lbl,
                "progress": progress_lbl, "bar": bar, "sub": sub,
                "pause": pause, "retry": retry, "cancel": cancel,
                "remove": remove, "share": share, "open": openf}
        self._update_card(job, refs)
        return refs

    def _update_card(self, job: dict, refs: dict | None = None):
        r = refs or self._cards.get(job["id"])
        if not r:
            return
        pal = self.pal
        status_key, color_key = STATUS.get(job["status"], ("queued", "text_3"))
        r["status"].text = t(status_key)
        r["status"].text_color = theme.rgba(pal[color_key])

        pct = float(job.get("progress_pct") or 0)
        r["bar"].value = max(0, min(100, pct))
        r["bar"].color = theme.rgba(pal["success"] if job["status"] == "done"
                                    else self.app.accent_hex)

        if job.get("unit") == "time":
            r["progress"].text = f"{fa_num(duration_human(job.get('done')))} / " \
                                 f"{fa_num(duration_human(job.get('total')))}"
            sub_bits = [f"{fa_num(round(pct))}٪"]
        else:
            total = human_bytes(job.get("total"))
            done = human_bytes(job.get("done"))
            r["progress"].text = f"{done} / {total}"
            sub_bits = [f"{fa_num(round(pct))}٪"]
        sp = speed_human(job.get("speed"))
        if sp:
            sub_bits.append(sp)
        eta = eta_human(job.get("eta"))
        if eta:
            sub_bits.append(eta)
        if job.get("status") == "error" and job.get("error"):
            sub_bits.append(fa("خطا: " + job["error"][:80]))
        r["sub"].text = "  ·  ".join(sub_bits)

        # action visibility per state
        for w in (r["pause"], r["retry"], r["cancel"], r["remove"], r["share"], r["open"]):
            w.opacity = 0
            w.disabled = True
        st = job["status"]
        if st in ("downloading", "queued"):
            self._show(r["pause"], True, "pause", lambda *_: self._pause(job["id"]))
            self._show(r["cancel"], True)
        elif st == "paused":
            self._show(r["pause"], True, "play", lambda *_: self._resume(job["id"]))
            self._show(r["cancel"], True)
        elif st in ("error", "cancelled"):
            self._show(r["retry"], True)
            self._show(r["remove"], True)
        elif st == "done":
            self._show(r["share"], True)
            self._show(r["open"], True)
            self._show(r["remove"], True)

    def _show(self, widget: IconChip, yes: bool, icon: str | None = None, cb=None):
        widget.opacity = 1 if yes else 0
        widget.disabled = not yes
        if icon and yes:
            widget._icon.icon = icon
        if cb and yes:
            widget._cb = cb

    # ------------------------------------------------------------------ controls
    def _pause(self, jid: str):
        self.engine.submit(self.engine.pause, jid)

    def _resume(self, jid: str):
        self.engine.submit(self.engine.resume, jid)

    def _cancel(self, jid: str):
        self.engine.submit(self.engine.cancel, jid)

    def _retry(self, jid: str):
        self.engine.submit(self.engine.retry, jid)

    def _remove(self, jid: str):
        self.engine.submit(self.engine.remove, jid)

    def _clear_finished(self):
        def done(fut):
            try:
                n = fut.result()
                Clock.schedule_once(lambda dt: snackbar(
                    f"{fa_num(n)} مورد پاک شد", self.pal, self.pal["info"]))
            except Exception:  # noqa: BLE001
                pass
        self.engine.submit(self.engine.clear_finished).add_done_callback(done)

    def _share(self, job: dict):
        path = job.get("filepath") or ""
        if not path or not runtime.share_file(path, runtime.mime_for(path)):
            snackbar("فایل برای اشتراک‌گذاری پیدا نشد", self.pal, self.pal["warning"])

    def _open(self, job: dict):
        path = job.get("filepath") or ""
        if not path or not runtime.open_file(path, runtime.mime_for(path)):
            snackbar("باز کردن فایل ممکن نشد", self.pal, self.pal["warning"])
