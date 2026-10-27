# All Video Downloader — Android (نسخه موبایل)

بازنویسی کامل نسخه ویندوزی برنامه برای موبایل، با همان موتور تحلیل لینک و یک
رابط کاربری جدید مخصوص اندروید (KivyMD، فارسی، راست‌چین).

```
android/
├─ buildozer.spec                 پیکربندی بیلد اندروید (p4a 2026.05، arm64-v8a)
├─ intent_filters.xml             دریافت لینک از منوی Share سایر اپ‌ها
├─ src/
│  ├─ main.py                     نقطه ورود برنامه
│  ├─ icon.png / presplash.png    آیکون و اسپلش برند (تولیدشده با tools/make_brand.py)
│  ├─ assets/
│  │  ├─ fonts/Vazirmatn-*.ttf     فونت فارسی متن‌باز (وزیرمتن)
│  │  └─ bin/arm64-v8a/           ffmpeg و ffprobe مخصوص اندروید — جایگزین فایل‌های .exe ویندوزی
│  └─ avd/
│     ├─ config.py                تنظیمات (ذخیره در حافظه داخلی برنامه)
│     ├─ engine.py                سرویس موتور: حلقه asyncio در نخ جدا + پل همگام برای UI
│     ├─ i18n.py                  متن فارسی، اتصال حروف (reshaper+bidi)، واحدها و اعداد فارسی
│     ├─ platform/runtime.py      لایه اندروید: مسیرها، کلیپ‌بورد، Intent، MediaStore، بوت‌استرپ FFmpeg
│     ├─ core/                    همان موتور نسخه دسکتاپ (بدون تغییر رفتاری):
│     │                           media · downloader · embed · sites · adapters · net ·
│     │                           cookies · ytcli · ffmpeg_tools · filekind
│     └─ ui/                      رابط کاربری جدید موبایل: app · home · downloads · settings · theme
├─ tests/                         تست‌های آفلاین موتور + تست سرویس با سرور HTTP محلی + تست دودکش UI
└─ tools/
   ├─ fetch_ffmpeg.sh             دانلود باینری FFmpeg اندروید (SHA پین‌شده، اعتبارسنجی ELF)
   └─ make_brand.py               تولید آیکون/اسپلش با Pillow
```

## معادل موبایل فایل‌های ویندوزی

| نسخه ویندوز | معادل اندروید |
|---|---|
| دانلود خودکار ffmpeg.exe از روی اینترنت (`ffmpeg_setup.py`) | باینری‌های `ffmpeg`/`ffprobe` آرم۶۴ داخل APK (`assets/bin/arm64-v8a`) که اولین اجرا به حافظه داخلی کپی و قابل‌اجرا می‌شوند — بدون دانلود هنگام نصب |
| `~/.avd/settings.json` | فایل تنظیمات در حافظه داخلی اختصاصی برنامه |
| پوشه دانلود ویندوز | `Android/data/ir.avd.allvideodownloader/files/Movies/All Video Downloader` (بدون مجوز دسترسی به حافظه) |
| باز کردن فایل در Explorer | اشتراک/پخش از طریق MediaStore و Intent اندروید (فایل در گالری/فایل‌منیجر هم دیده می‌شود) |
| مرورگر ویندوزی برای کوکی | فایل `cookies.txt` که کاربر در پوشه خارجی برنامه می‌گذارد |
| پنجره pywebview | اپ بومی KivyMD با ناوبری پایین متریال |

## قابلیت‌ها

- همان موتور universal لینک: یوتیوب و ~۱۹۰۰ سایت yt-dlp، فایل مستقیم، مانیفست
  HLS/DASH با نردبان کیفیت واقعی، اسکن عمیق صفحه و استخراج پیکربندی پخش‌کننده،
  ۳۸۴ دستور پخت سایت داخلی.
- سه تب: **خانه** (بررسی لینک و انتخاب کیفیت)، **دانلودها** (پیشرفت زنده، سرعت،
  زمان باقی‌مانده، توقف/ادامه/لغو/تلاش دوباره، اشتراک فایل)، **تنظیمات** (کیفیت
  پیش‌فرض، فرمت، پروکسی، تم تیره/روشن، رنگ تأکید، وضعیت موتور).
- دریافت لینک از منوی Share مرورگر/یوتیوب.
- رابط کاملاً فارسی و راست‌چین با فونت وزیرمتن و اعداد فارسی.
- FFmpeg آرم۶۴ (نسخه ۹، LGPL، فقط وابسته به کتابخانه‌های سیستمی اندروید).

## بیلد

بیلد کامل روی GitHub Actions اجرا می‌شود (فایل `.github/workflows/android-build.yml`)
چون محیط توسعه این پروژه به JDK/SDK دسترسی ندارد. روی یک ماشین مجهز:

```bash
cd android
pip install buildozer python-for-android==2026.5.9 "Cython>=3.0,<3.2"
buildozer android debug      # خروجی: android/bin/AllVideoDownloader-3.0.0-arm64-v8a-debug.apk
```

به‌روزرسانی باینری FFmpeg:

```bash
android/tools/fetch_ffmpeg.sh   # SHAها داخل اسکریپت پین شده‌اند
```

## تست‌ها

```bash
pip install httpx yt-dlp arabic-reshaper python-bidi pillow
cd android
for t in test_video_core test_coverage test_cookies test_engine_service; do
  PYTHONPATH=src python tests/$t.py
done
```

- `test_video_core` / `test_coverage` / `test_cookies` — همان تست‌های فیکسچری نسخه
  دسکتاپ، روی موتور مشترک.
- `test_engine_service` — اجرای کامل سرویس با یک سرور HTTP محلی: دانلود واقعی،
  نردبان m3u8، اسکن صفحه، تنظیمات و مگنت.
- `smoke_ui` — ساخت تمام صفحه‌های Kivy در محیط headless (روی CI با GL واقعی هم
  توسط خود بیلد اعتبارسنجی می‌شود).

## محدودیت‌های نسخه اول

- معماری فقط `arm64-v8a` (بیش از ۹۸٪ دستگاه‌های فعلی).
- حداقل اندروید ۱۰ (API 29) — به‌خاطر MediaStore و باینری FFmpeg.
- کوکی مرورگرهای دسکتاپ پشتیبانی نمی‌شود؛ فقط `cookies.txt`.
- `curl_cffi` (جعل اثرانگشت TLS) در این نسخه همراه نیست؛ موتور بدون آن هم کار
  می‌کند و در صورت بلاک، مسیر اسکن عمیق صفحه فعال است.
