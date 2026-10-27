"""All Video Downloader (Android) — Persian UI helpers.

Kivy's text renderer does not shape Arabic-script text or do bidi ordering,
so every Persian string passes through :func:`fa` (arabic-reshaper +
python-bidi, both pure-Python) before reaching a widget. Latin/technical
strings (URLs, format ids) stay untouched.
"""
from __future__ import annotations

from functools import lru_cache

import arabic_reshaper
from bidi.algorithm import get_display


def _make_reshaper():
    """arabic-reshaper changed its public API between 2.x (``Reshaper``) and
    3.x (``ArabicReshaper``); support both so packaging never breaks."""
    cls = getattr(arabic_reshaper, "ArabicReshaper", None) or \
        getattr(arabic_reshaper, "Reshaper", None)
    if cls is None:
        return arabic_reshaper.reshape  # bare function fallback
    try:
        instance = cls(configuration={"delete_harakat": False,
                                      "support_ligatures": True})
    except TypeError:
        instance = cls()
    return instance.reshape


_reshape = _make_reshaper()

_FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_FA_MONTHS = {  # not needed yet, kept for future date labels
    "January": "ژانویه", "February": "فوریه", "March": "مارس",
    "April": "آوریل", "May": "مه", "June": "ژوئن",
    "July": "ژوئیه", "August": "اوت", "September": "سپتامبر",
    "October": "اکتبر", "November": "نوامبر", "December": "دسامبر",
}


@lru_cache(maxsize=2048)
def fa(text: str | int | float | None) -> str:
    """Shape + bidi-order a Persian (or mixed) string for Kivy labels."""
    if text is None:
        return ""
    s = str(text)
    if not s:
        return ""
    try:
        return get_display(_reshape(s))
    except Exception:  # noqa: BLE001 — never let text shaping crash a screen
        return s


def fa_num(value: int | float | str) -> str:
    """Convert Latin digits to Persian digits (kept in logical order — call
    :func:`fa` afterwards when the string is part of a Persian sentence)."""
    s = str(value)
    table = str.maketrans("0123456789", _FA_DIGITS)
    return s.translate(table)


# ---------------------------------------------------------------------------
# Unit formatters — Persian wording, Latin unit symbols
# ---------------------------------------------------------------------------
def human_bytes(num: int | float | None) -> str:
    if not num:
        return fa("۰ بایت")
    num = float(num)
    for unit in ("بایت", "کیلوبایت", "مگابایت", "گیگابایت", "ترابایت"):
        if abs(num) < 1024.0 or unit == "ترابایت":
            if unit == "بایت":
                return fa(f"{fa_num(int(num))} {unit}")
            return fa(f"{fa_num(round(num, 1))} {unit}")
        num /= 1024.0
    return fa("۰ بایت")


def speed_human(bytes_per_sec: float | None) -> str:
    if not bytes_per_sec or bytes_per_sec <= 0:
        return ""
    return human_bytes(bytes_per_sec) + fa("/ثانیه")


def duration_human(seconds: int | float | None) -> str:
    if not seconds or seconds <= 0:
        return ""
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        out = f"{h}:{m:02d}:{s:02d}"
    else:
        out = f"{m:02d}:{s:02d}"
    return fa(fa_num(out))


def eta_human(seconds: float | None) -> str:
    if not seconds or seconds <= 0:
        return ""
    seconds = int(seconds)
    if seconds >= 3600:
        h, rem = divmod(seconds, 3600)
        m = rem // 60
        return fa(f"مانده {fa_num(h)}:{fa_num(f'{m:02d}')} ساعت")
    if seconds >= 60:
        m, s = divmod(seconds, 60)
        return fa(f"مانده {fa_num(m)}:{fa_num(f'{s:02d}')}")
    return fa(f"مانده {fa_num(seconds)} ثانیه")


# ---------------------------------------------------------------------------
# UI vocabulary — one place, Persian-first
# ---------------------------------------------------------------------------
STR = {
    "app_title": "دانلودر همه ویدیوها",
    "app_subtitle": "هر لینکی که ویدیو دارد — با کیفیتی که انتخاب می‌کنی",
    "tab_home": "خانه",
    "tab_downloads": "دانلودها",
    "tab_settings": "تنظیمات",
    "url_hint": "لینک ویدیو، صفحه یا فایل را بچسبانید…",
    "paste": "چسباندن",
    "clear": "پاک کردن",
    "analyze": "بررسی لینک",
    "analyzing": "در حال بررسی…",
    "download": "دانلود",
    "download_quality": "دانلود {quality}",
    "copy_link": "کپی لینک",
    "open_page": "باز کردن صفحه",
    "deep_scan": "اسکن عمیق صفحه",
    "retry": "تلاش دوباره",
    "qualities": "کیفیت‌ها",
    "streams_found": "{n} استریم پیدا شد",
    "files_found": "{n} فایل پیدا شد",
    "playlists_more": "بقیه این پلی‌لیست · {n} مورد",
    "also_found": "چیزهای دیگری که در صفحه پیدا شد · {n} مورد",
    "empty_downloads": "هنوز دانلودی نداری — یک لینک را در خانه بررسی کن",
    "clear_finished": "پاک کردن تمام‌شده‌ها",
    "queued": "در صف",
    "downloading": "در حال دانلود",
    "paused": "متوقف شده",
    "done": "تمام شد",
    "error": "خطا",
    "cancelled": "لغو شد",
    "pause": "توقف",
    "resume": "ادامه",
    "cancel": "لغو",
    "remove": "حذف",
    "retry_job": "تلاش دوباره",
    "share": "اشتراک‌گذاری",
    "open": "باز کردن",
    "saved_to": "ذخیره شد در: {path}",
    "added_to_queue": "به دانلودها اضافه شد",
    "link_copied": "لینک کپی شد",
    "magnet_title": "لینک مگنت — فقط قابل کپی",
    "magnet_body": "لینک‌های مگنت با کلاینت تورنت باز می‌شوند؛ این برنامه دانلود P2P انجام نمی‌دهد.",
    "copy_magnet": "کپی مگنت",
    "ffmpeg_ok": "FFmpeg آماده است",
    "ffmpeg_missing": "FFmpeg در دسترس نیست — ضبط HLS/DASH محدود می‌شود",
    "section_downloads": "دانلودها",
    "section_video": "ویدیو و ضبط",
    "section_appearance": "ظاهر برنامه",
    "section_system": "سیستم",
    "max_concurrent": "دانلود هم‌زمان",
    "proxy": "پروکسی (http/socks5)",
    "proxy_hint": "مثال: socks5://127.0.0.1:1080 — خالی = بدون پروکسی",
    "default_quality": "کیفیت پیش‌فرض",
    "container": "فرمت خروجی",
    "cookies": "فایل cookies.txt",
    "cookies_hint": "فایل را در پوشه برنامه بگذارید تا خودکار شناسایی شود",
    "cookies_active": "{n} کوکی فعال است",
    "cookies_none": "بدون کوکی — حالت ناشناس",
    "theme_dark": "تیره",
    "theme_light": "روشن",
    "accent": "رنگ تأکید",
    "download_folder": "پوشه ذخیره‌سازی",
    "yt_dlp_version": "موتور yt-dlp",
    "sites_count": "دستور پخت سایت‌ها",
    "tls_status": "جعل اثرانگشت TLS",
    "tls_on": "فعال",
    "tls_off": "غیرفعال (اختیاری)",
    "abi": "معماری دستگاه",
    "about": "درباره برنامه",
    "about_body": "نسخه اندروید موتور All Video Downloader — همان موتور تحلیل لینک نسخه دسکتاپ، "
                  "با رابط کاربری مخصوص موبایل و FFmpeg همراه برنامه.",
    "quality_best": "بهترین کیفیت",
    "notice_recovered": "بعد از بلاک شدن استخراج‌کننده، از روی خود صفحه بازیابی شد",
    "notice_upgraded": "استخراج‌کننده کیفیت پایین‌تر می‌داد؛ کیفیت بالاتر از پخش‌کننده صفحه گرفته شد",
    "notice_paywall": "محدودیت دسترسی:",
    "work_in_background_hint": "تا پایان دانلود صفحه را نبندید؛ دانلود در همین برنامه ادامه دارد.",
}


def t(key: str, **kwargs) -> str:
    """Persian label, shaped and ready for a widget."""
    raw = STR.get(key, key)
    if kwargs:
        raw = raw.format(**kwargs)
    return fa(raw)
